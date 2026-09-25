"""Local report-day 1m OHLC hover; volume lots, CNY/share, lunch compressed.
Reuse the existing candle renderer: red hollow up / green filled down.
Missing rows remain gaps; existing imputed rows retained and disclosed.
"""
from pathlib import Path
import hashlib
import json
import math
import csv
import duckdb

from level2_paths import PATHS
DAILY = PATHS['daily']

def minute_directory(root):
    return PATHS['stock_minute'] if root.resolve()==PATHS['level2'] else root.parent/'stock_minute'


def previous_close(code, day):
    source = DAILY / f'{day}_daily.csv'
    if not source.is_file():
        return None, str(source)
    with source.open(newline='') as stream:
        rows = [r for r in csv.DictReader(stream) if r['ts_code'] == code]
    if len(rows) != 1 or rows[0]['trade_date'] != day:
        return None, str(source)
    try:
        value = float(rows[0]['pre_close'])
        return (value if math.isfinite(value) and value>0 else None), str(source)
    except (ValueError, KeyError):
        return None, str(source)


def minute_slots():
    return [f'{m//60:02d}:{m%60:02d}' for m in [*range(571, 691), *range(781, 901)]]


def minute_close_drawdown(bars, labels, pre_close):
    """Observed traded-minute closes from the prior close, not intrabar extrema."""
    traded = [bar for bar in bars if bar[5] > 0]
    result = {'valuePct': None, 'peakTime': None, 'troughTime': None,
              'tradedMinutes': len(traded), 'presentMinutes': len(bars),
              'expectedMinutes': len(labels)}
    if pre_close is None or not math.isfinite(pre_close) or pre_close <= 0:
        result['status'] = 'MISSING_PRE_CLOSE'
        return result
    if not traded:
        result['status'] = 'NO_TRADED_MINUTES'
        return result
    peak, peak_time = pre_close, '昨收'
    result['status'] = 'OBSERVED'
    result['valuePct'] = 0.0
    for bar in traded:
        close = float(bar[4])
        if close > peak:
            peak, peak_time = close, labels[bar[0]]
        drawdown = 100 * (close / peak - 1)
        if drawdown < result['valuePct']:
            result['valuePct'] = drawdown
            result['peakTime'] = peak_time
            result['troughTime'] = labels[bar[0]]
    return result


def minute_identity(day, root):
    source = minute_directory(root) / f'{day}.parquet'
    audit = root / '_conversion_audit' / day
    manifest = audit / 'manifest.json'
    if not (audit / 'COMMITTED').is_file() or json.loads(manifest.read_text()).get('commit_state') != 'COMMITTED':
        raise ValueError('分钟来源尚未提交')
    identity = [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns)
                for p in [source, manifest, audit / 'COMMITTED']]
    identity.append(hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    daily = DAILY / f'{day}_daily.csv'
    identity.append((str(daily), daily.stat().st_size, daily.stat().st_mtime_ns) if daily.exists() else ('daily_missing',str(daily)))
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def calculate_intraday(code, day, expected, progress, root):
    identity = minute_identity(day, root)
    source = minute_directory(root) / f'{day}.parquet'
    progress('正在读取本地 stock_minute 当日分钟数据…')
    con = duckdb.connect()
    try:
        rows = con.execute('''SELECT TradingDay,Time,OpenPrice,HighPrice,LowPrice,
          ClosePrice,Volume,Turnover FROM read_parquet(?) WHERE SecuCode=? ORDER BY Time''',
          [str(source), code.split('.')[0]]).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError('本地分钟文件中没有该股数据')
    labels = minute_slots()
    slots = {int(label.replace(':', '')): i for i,label in enumerate(labels)}
    bars, seen = [], set()
    for trade_day,t,o,h,l,c,v,a in rows:
        if str(trade_day) != day or t not in slots or t in seen:
            raise ValueError('分钟数据日期、时间或唯一性校验失败')
        if not all(x is not None and math.isfinite(x) for x in [o,h,l,c,v,a]) or not (0<l<=min(o,c)<=max(o,c)<=h) or v<0 or a<0:
            raise ValueError('分钟 OHLC 或量额异常，未绘图')
        seen.add(t)
        bars.append([slots[t],o,h,l,c,v,a])
    pre_close, pre_close_source = previous_close(code, day)
    observed_drawdown = minute_close_drawdown(bars, labels, pre_close)
    if minute_identity(day, root) != identity:
        raise ValueError('读取期间分钟文件发生变化，请重试')
    policy = json.loads((root / '_conversion_audit' / day / 'manifest.json').read_text()).get('minute_policy','分钟生成口径未提供')
    return {'code':code,'day':day,'sourceIdentity':identity,'bars':bars,'labels':labels,
            'preClose':pre_close,'preCloseSource':pre_close_source,
            'minuteCloseDrawdown':observed_drawdown,
            'zeroVolumeMinutes':sum(b[5]==0 for b in bars),'source':str(source),
            'method':f'直接读取本地 stock_minute；价格元/股，不复权；Volume 单位手（100股），Turnover 单位元。源文件生成口径：{policy}。横轴为分钟结束时刻；缺失行留空，不额外插值。',
            'quality':'源文件由行情快照生成，OHLC 可能与逐笔汇总不同；无成交分钟可能沿用前收或上一收盘。'}
