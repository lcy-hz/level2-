"""On-demand Level-2 stock research calculations, independent of HTTP routing."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

import duckdb
from level2_contract import native_ticks, KNOWN_NET, UNKNOWN_AMOUNT, COMPLETE_NET, parent_query
from level2_quote_path import quote_path
from level2_trade_path import trade_print_drawdown
from level2_price_response import price_response
from level2_paths import PATHS

BASE = Path(__file__).resolve().parent
SOURCE = PATHS['level2']


def source_identity(day, root=SOURCE):
    audit = root / '_conversion_audit' / day
    manifest = audit / 'manifest.json'
    if not (audit / 'COMMITTED').is_file() or not manifest.is_file():
        raise ValueError('源文件尚未正式提交，不能计算')
    content = json.loads(manifest.read_text())
    if content.get('commit_state') != 'COMMITTED':
        raise ValueError('源数据提交状态不是 COMMITTED')
    files = [root / f'deal_{day}.parquet', root / f'snapshot_{day}.parquet', root / f'order_raw_{day}.parquet', manifest, audit / 'COMMITTED']
    identity = [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    identity.append(('calculator', hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    identity.append(('contract',hashlib.sha256((BASE/'level2_contract.py').read_bytes()).hexdigest()))
    identity.append(('quote_path',hashlib.sha256((BASE/'level2_quote_path.py').read_bytes()).hexdigest()))
    identity.append(('trade_path',hashlib.sha256((BASE/'level2_trade_path.py').read_bytes()).hexdigest()))
    identity.append(('price_response',hashlib.sha256((BASE/'level2_price_response.py').read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def order_key_audit(con, path, day, code):
    """Per-stock candidate key intersections, never an order identity decision."""
    fields = ('委托编号', '交易所委托号')
    columns = {row[0] for row in con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(path)]).fetchall()}
    order_rows = con.execute('SELECT COUNT(*) FROM read_parquet(?) WHERE "万得代码"=? AND "自然日"=?',
                             [str(path), code, day]).fetchone()[0]
    eligible = con.execute("SELECT COUNT(*) FROM ticks WHERE side IN ('B','S') AND pid>0").fetchone()[0]
    output = []
    for field in fields:
        base = {'field': field, 'orderRows': order_rows, 'eligibleTrades': eligible,
                'validOrderRows': None, 'candidateKeys': None, 'repeatedKeyGroups': None,
                'multiCodeKeyGroups': None, 'matchedTrades': None, 'sameCodeMatches': None,
                'singleRowSameCodeMatches': None, 'repeatedKeyMatchedTrades': None,
                'singleRowMatchedTrades': None, 'timeComparable': None,
                'timeEarlier': None, 'timeSame': None, 'timeLater': None,
                'timeFieldStatus': 'AVAILABLE' if '时间' in columns else 'MISSING_FIELD'}
        if field not in columns:
            output.append({**base, 'status': 'MISSING_FIELD'})
            continue
        order_time = 'MIN(TRY_CAST("时间" AS BIGINT))' if '时间' in columns else 'NULL::BIGINT'
        con.execute(f'''CREATE OR REPLACE TEMP TABLE order_key_audit AS
            SELECT TRY_CAST("{field}" AS BIGINT) pid, COUNT(*) nrows,
              COUNT(DISTINCT "委托代码") codes,
              MAX(CASE WHEN "委托代码"='B' THEN 1 ELSE 0 END) has_b,
              MAX(CASE WHEN "委托代码"='S' THEN 1 ELSE 0 END) has_s,
              {order_time} order_t
            FROM read_parquet(?) WHERE "万得代码"=? AND "自然日"=?
              AND TRY_CAST("{field}" AS BIGINT)>0 GROUP BY 1''', [str(path), code, day])
        key_count, valid_rows, repeated, multi_code = con.execute('''SELECT COUNT(*),
            COALESCE(SUM(nrows),0),COUNT(*) FILTER(WHERE nrows>1),
            COUNT(*) FILTER(WHERE codes>1) FROM order_key_audit''').fetchone()
        matched, same_code, single_row, repeated_trades = con.execute('''SELECT
            COUNT(*) FILTER(WHERE o.pid IS NOT NULL),
            COUNT(*) FILTER(WHERE (t.side='B' AND o.has_b=1) OR (t.side='S' AND o.has_s=1)),
            COUNT(*) FILTER(WHERE o.nrows=1 AND ((t.side='B' AND o.has_b=1) OR (t.side='S' AND o.has_s=1))),
            COUNT(*) FILTER(WHERE o.nrows>1)
            FROM ticks t LEFT JOIN order_key_audit o USING(pid)
            WHERE t.side IN ('B','S') AND t.pid>0''').fetchone()
        single_matched, time_comparable, earlier, same, later = (None,) * 5
        if '时间' in columns:
            valid_trade = '(t.t>0 AND t.t<240000000 AND (t.t//100000)%100<60 AND (t.t//1000)%100<60)'
            valid_order = '(o.order_t>0 AND o.order_t<240000000 AND (o.order_t//100000)%100<60 AND (o.order_t//1000)%100<60)'
            single_matched, time_comparable, earlier, same, later = con.execute(f'''SELECT
                COUNT(*),
                COUNT(*) FILTER(WHERE {valid_trade} AND {valid_order}),
                COUNT(*) FILTER(WHERE {valid_trade} AND {valid_order} AND o.order_t<t.t),
                COUNT(*) FILTER(WHERE {valid_trade} AND {valid_order} AND o.order_t=t.t),
                COUNT(*) FILTER(WHERE {valid_trade} AND {valid_order} AND o.order_t>t.t)
                FROM ticks t JOIN order_key_audit o USING(pid)
                WHERE t.side IN ('B','S') AND t.pid>0 AND o.nrows=1''').fetchone()
        output.append({**base, 'status': 'AVAILABLE' if key_count else 'NO_VALID_KEYS',
                       'validOrderRows': valid_rows, 'candidateKeys': key_count,
                       'repeatedKeyGroups': repeated, 'multiCodeKeyGroups': multi_code,
                       'matchedTrades': matched, 'sameCodeMatches': same_code,
                       'singleRowSameCodeMatches': single_row,
                       'repeatedKeyMatchedTrades': repeated_trades,
                       'singleRowMatchedTrades': single_matched,
                       'timeComparable': time_comparable, 'timeEarlier': earlier,
                       'timeSame': same, 'timeLater': later})
    con.execute('DROP TABLE IF EXISTS order_key_audit')
    return output


def calculate(code, day, expected, progress, root=SOURCE):
    before = source_identity(day, root)
    con = duckdb.connect()
    con.execute('SET threads=2')
    con.execute("SET memory_limit='2GB'")
    try:
        progress('正在读取该股逐笔成交，计算五时段结构…')
        con.execute('CREATE TEMP TABLE ticks AS '+native_ticks(root/f'deal_{day}.parquet',day,[code]))
        count, bad_day, amount, net,known_net,unknown = con.execute(f'''SELECT COUNT(*), COUNT(*) FILTER(WHERE trade_day IS NULL OR trade_day<>?),
            SUM(price*qty),{COMPLETE_NET},{KNOWN_NET},{UNKNOWN_AMOUNT} FROM ticks''', [day]).fetchone()
        if not count or bad_day:
            raise ValueError('成交为空或交易日期不一致，未发布计算结果')
        for value, field in [(amount, 'amount'), (net, 'net')]:
            if value is None and expected[field] is None:continue
            if value is None or expected[field] is None:raise ValueError('方向质量状态与报告不一致，请更新报告')
            if abs(value - expected[field]) > max(2, abs(expected[field]) * 1e-9):
                raise ValueError(f'{field} 与报告日级结果不一致，请更新报告后重试')
        rows = con.execute(f'''SELECT CASE WHEN t<100000000 THEN '09:30–10:00'
            WHEN t<103000000 THEN '10:00–10:30' WHEN t<=113000000 THEN '10:30–11:30'
            WHEN t<140000000 THEN '13:00–14:00' ELSE '14:00–收盘' END segment,
            SUM(price*qty), {COMPLETE_NET},
            SUM(price*qty)/SUM(qty) FROM ticks
            WHERE (t BETWEEN 93000000 AND 113000000) OR (t BETWEEN 130000000 AND 150000000)
            GROUP BY 1 ORDER BY 1''').fetchall()
        segments = [{'s': s, 'a': round(a), 'n': round(n) if n is not None else None, 'v': round(v, 4)} for s, a, n, v in rows]
        progress('正在汇总主动成交关联委托…')
        rows = con.execute(parent_query()).fetchall()
        order = {'<5万': 0, '5–20万': 1, '20–100万': 2, '≥100万': 3, '关联键未知': 4}
        parents = sorted([{'b': b, 'n': round(n), 'c': c} for _, b, n, c in rows], key=lambda r: order[r['b']])
        if abs(sum(p['n'] for p in parents) - known_net) > len(parents) + 2:
            raise ValueError('关联委托净额对账失败')
        progress('正在核对成交编号与逐笔成交价路径…')
        trade_path = trade_print_drawdown(con, root / f'deal_{day}.parquet', code, day)
        progress('正在读取 order_raw 原始委托类型与方向…')
        rows = con.execute('''SELECT COALESCE(NULLIF(TRIM("委托类型"),''),'空'),
            COALESCE(NULLIF(TRIM("委托代码"),''),'空'),COUNT(*),SUM(TRY_CAST("委托数量" AS DOUBLE)),
            COUNT(*) FILTER(WHERE TRY_CAST("委托数量" AS DOUBLE) IS NULL),
            COUNT(*) FILTER(WHERE "自然日" IS NULL OR "自然日"<>?)
            FROM read_parquet(?) WHERE "万得代码"=? GROUP BY 1,2 ORDER BY 1,2''',
                           [day, str(root / f'order_raw_{day}.parquet'), code]).fetchall()
        if not rows or any(bad or bad_date for _, _, _, _, bad, bad_date in rows):
            raise ValueError('order_raw 为空或日期/数量异常，未发布不完整结果')
        orders = [{'t': t, 's': s, 'r': r, 'q': round(q)} for t, s, r, q, _, _ in rows]
        progress('正在审计该股两种委托编号的候选字段交集…')
        order_link = order_key_audit(con, root / f'order_raw_{day}.parquet', day, code)
        progress('正在核对该股盘口快照的买卖一档中间价路径…')
        quote_fields = ['自然日', '时间', '申买价1', '申卖价1', '申买量1', '申卖量1']
        quote_fields += [f'申买价{i}' for i in range(2, 11)]
        quote_fields += [f'申卖价{i}' for i in range(2, 11)]
        quote_fields += [f'申买量{i}' for i in range(2, 11)]
        quote_fields += [f'申卖量{i}' for i in range(2, 11)]
        snapshot_sql = 'SELECT ' + ','.join(f'"{field}"' for field in quote_fields) + ' FROM read_parquet(?) WHERE "万得代码"=?'
        snapshots = con.execute(snapshot_sql,
            [str(root / f'snapshot_{day}.parquet'), code]).fetchall()
        quotes = quote_path(snapshots, day)
        quotes['source'] = str(root / f'snapshot_{day}.parquet')
        progress('正在比较成交方向与相邻盘口中间价变化…')
        response = price_response(con.execute('SELECT t,price,qty,side FROM ticks').fetchall(), snapshots, day)
        if before != source_identity(day, root):
            raise ValueError('计算期间源文件发生变化，请重新计算')
        return {'code': code, 'day': day, 'sourceIdentity': before,
                'computedAt': datetime.now(timezone.utc).isoformat(),
                'segments': segments, 'parents': parents, 'orders': orders,
                'orderLinkAudit': order_link,
                'quotePath': quotes, 'tradePrintDrawdown': trade_path,
                'priceResponse': response,
                'regularCoverage': round(sum(r[1] for r in con.execute('''SELECT 1,SUM(price*qty) FROM ticks
                   WHERE (t BETWEEN 93000000 AND 113000000) OR (t BETWEEN 130000000 AND 150000000)''').fetchall() if r[1] is not None) / amount * 100, 2),
                'tradeRows': count, 'amount': round(amount), 'net': round(net) if net is not None else None,
                'knownNet':round(known_net),'unknownAmount':round(unknown),'parentIdentityStatus':'UNVERIFIED_NO_CHANNEL',
                'note': '仅报告日局部深查；两种委托编号只做候选字段匹配，委托代码同字母也不证明经济订单身份；缺少频道和订单生命周期语义。未知编号按成交条数计数，未混入大单；order_raw 类型未解码为补撤单。'}
    finally:
        con.close()
