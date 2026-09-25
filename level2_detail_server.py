"""Loopback-only, on-demand stock detail calculations for the existing report."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, BoundedSemaphore
from urllib.parse import urlsplit, parse_qs
from urllib.parse import urlencode
import argparse
import hashlib
import json
import re

import duckdb
from level2_contract import native_ticks,KNOWN_NET,UNKNOWN_AMOUNT,COMPLETE_NET,parent_query
from level2_quote_path import quote_path

BASE = Path(__file__).resolve().parent
LEGACY_BOOKMARK = 'level2-market-scan_20260922.html'
JSON_REPORT = BASE / '.level2_reports' / '20260922' / 'report.json'
REPORT = JSON_REPORT
FRONTEND = BASE / 'frontend' / 'dist'
from level2_paths import PATHS
SOURCE = PATHS['level2']
CACHE = BASE / '.level2_detail_cache'


def read_report(path=REPORT):
    if Path(path).suffix != '.json':raise ValueError('正式报告必须是 JSON')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('markets'),list) or not isinstance(data.get('cards'),list):
        raise ValueError('报告 JSON 结构无效')
    return data


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
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


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
        if before != source_identity(day, root):
            raise ValueError('计算期间源文件发生变化，请重新计算')
        return {'code': code, 'day': day, 'sourceIdentity': before,
                'computedAt': datetime.now(timezone.utc).isoformat(),
                'segments': segments, 'parents': parents, 'orders': orders,
                'quotePath': quotes,
                'regularCoverage': round(sum(r[1] for r in con.execute('''SELECT 1,SUM(price*qty) FROM ticks
                   WHERE (t BETWEEN 93000000 AND 113000000) OR (t BETWEEN 130000000 AND 150000000)''').fetchall() if r[1] is not None) / amount * 100, 2),
                'tradeRows': count, 'amount': round(amount), 'net': round(net) if net is not None else None,
                'knownNet':round(known_net),'unknownAmount':round(unknown),'parentIdentityStatus':'UNVERIFIED_NO_CHANNEL',
                'note': '仅报告日局部深查；关联分组缺少频道和经济订单身份验证；未知编号按成交条数计数，未混入大单；order_raw 类型未解码为补撤单。'}
    finally:
        con.close()


class Service:
    def __init__(self, report=None, root=SOURCE, cache=CACHE, calculator=calculate, identity=source_identity):
        self.report = read_report() if report is None else report
        self.day = self.report['markets'][-1]['day']
        self.cards = {c['code']: c for c in self.report['cards']}
        self.root, self.cache, self.calculator = root, cache, calculator
        self.identity = identity
        self.jobs, self.lock = {}, Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)

    def validate(self, code):
        if not isinstance(code, str) or code not in self.cards or not re.fullmatch(r'\d{6}\.(SH|SZ)', code):
            raise ValueError('只能计算当前报告中的股票代码')

    def path(self, code):
        return self.cache / self.day / f'{code}.json'

    def status(self, code):
        self.validate(code)
        with self.lock:
            job = self.jobs.get(code)
            if job and job['status'] in ('queued', 'running', 'error'):
                return dict(job)
        path = self.path(code)
        if path.is_file():
            try:
                result = json.loads(path.read_text())
                if result['sourceIdentity'] == self.identity(self.day, self.root):
                    return {'status': 'done', 'message': '已读取本地计算结果', 'result': result}
            except (OSError, ValueError, KeyError):
                pass
        return {'status': 'idle', 'message': '尚未计算，或缓存已失效'}

    def start(self, code):
        state = self.status(code)
        if state['status'] in ('done', 'queued', 'running'):
            return state
        with self.lock:
            if self.jobs.get(code, {}).get('status') in ('queued', 'running'):
                return dict(self.jobs[code])
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 8:
                raise ValueError('待计算任务已满，请稍后重试')
            self.jobs[code] = {'status': 'queued', 'message': '已排队；逐只计算以限制磁盘和内存占用'}
            self.pool.submit(self.work, code)
        return {'status': 'queued', 'message': '已加入本地计算队列'}

    def work(self, code):
        def progress(message):
            with self.lock:
                self.jobs[code] = {'status': 'running', 'message': message}
        try:
            progress('正在检查源数据提交状态…')
            result = self.calculator(code, self.day, self.cards[code], progress, self.root)
            path = self.path(code)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            tmp.replace(path)
            with self.lock:
                self.jobs[code] = {'status': 'done', 'message': '计算完成'}
        except Exception as exc:
            with self.lock:
                self.jobs[code] = {'status': 'error', 'message': f'计算失败：{exc}'}


def make_handler(service, port, minute_service=None, workspace=None):
    host = f'127.0.0.1:{port}'
    chart_slots = BoundedSemaphore(2)
    class Handler(BaseHTTPRequestHandler):
        def allowed(self, post=False):
            if self.headers.get('Host') != host or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.send_error(403)
                return False
            if post and self.headers.get('Origin') != 'http://' + host:
                self.send_error(403)
                return False
            return True

        def respond(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            query=parse_qs(urlsplit(self.path).query)
            day=query.get('date',[service.day])[0]
            if path == '/' + LEGACY_BOOKMARK:
                # Historical bookmarks keep their selected evidence, but the old
                # HTML renderer is no longer a second user-facing application.
                selection={key:query[key][0] for key in ('snapshot','date') if key in query}
                self.send_response(307)
                self.send_header('Location','/'+('?' + urlencode(selection) if selection else ''))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                return
            if path == '/' or path.startswith('/assets/'):
                target=FRONTEND/'index.html' if path == '/' else FRONTEND/'assets'/path.removeprefix('/assets/')
                if path.startswith('/assets/') and (target.name != path.removeprefix('/assets/') or target.suffix not in ('.js','.css','.svg','.png','.woff2')):
                    self.send_error(404)
                    return
                if not target.is_file():
                    self.send_error(503 if path == '/' else 404, 'Vue 页面尚未构建；请在 frontend 运行 npm run build')
                    return
                body=target.read_bytes()
                content_type={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
                              '.css':'text/css; charset=utf-8','.svg':'image/svg+xml',
                              '.png':'image/png','.woff2':'font/woff2'}[target.suffix]
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if workspace and path=='/api/validation/status':
                try:self.respond(workspace.validation.status(query.get('id',[''])[0]))
                except (ValueError, OSError, KeyError) as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path=='/api/validation/detail':
                try:self.respond(workspace.validation.detail(query.get('receipt',[''])[0],query.get('code',[''])[0]))
                except (ValueError, OSError, KeyError) as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path in ('/api/patterns/meta','/api/patterns/status','/api/patterns/detail'):
                try:
                    p=workspace.patterns
                    result=p.metadata() if path.endswith('/meta') else p.detail(day,query.get('code',[''])[0],query.get('receipt',[''])[0]) if path.endswith('/detail') else p.status(day)
                    self.respond(result)
                except Exception as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path in ('/api/state/meta','/api/state/status'):
                try:
                    result=workspace.state.metadata() if path.endswith('/meta') else workspace.state.status(day,int(query.get('window',['5'])[0]))
                    self.respond(result)
                except Exception as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path=='/api/state/view':
                try:
                    workspace.get_service(day)
                    window=int(query.get('window',['5'])[0])
                    job=workspace.state.status(day,window)
                    if job['status']=='done':
                        from level2_state_view import derive
                        result=job['result']
                        self.respond({'status':'done','day':day,'window':window,'researchOnly':True,
                                      'receipt':job['receipt'],'view':derive(result),
                                      'sources':result['sources'],'scope':result['scope']})
                    else:self.respond({'status':job['status'],'message':job['message'],'day':day,'window':window})
                except (ValueError, OSError, KeyError) as exc:
                    self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path in ('/api/dates','/api/report/status','/api/snapshots'):
                try:
                    result=workspace.dates() if path=='/api/dates' else workspace.status(day) if path=='/api/report/status' else workspace.list_snapshots()
                    self.respond(result)
                except Exception as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            if workspace and path in ('/api/report/data','/api/snapshot/data'):
                try:
                    result=(workspace.report_document(day) if path=='/api/report/data' else
                            workspace.snapshot_document(query.get('id',[''])[0]))
                    self.respond(result)
                except (ValueError, OSError, KeyError) as exc:
                    self.respond({'status':'error','message':str(exc)},400)
                return
            if path.startswith('/api/detail/'):
                try:
                    current=workspace.get_service(day) if workspace else service
                    self.respond(current.status(path.removeprefix('/api/detail/')))
                except ValueError as exc:
                    self.respond({'status': 'error', 'message': str(exc)}, 400)
            elif path.startswith('/api/minute/') and minute_service is not None:
                try:
                    self.respond(minute_service.status(path.removeprefix('/api/minute/')))
                except ValueError as exc:
                    self.respond({'status': 'error', 'message': str(exc)}, 400)
            elif path.startswith('/api/chart/'):
                parts = path.split('/')
                try:
                    if len(parts)!=5 or parts[3] not in ('day','minute'):
                        raise ValueError('图表请求无效')
                    kind,code = parts[3:]
                    current=workspace.get_service(day) if workspace else service
                    current.validate(code)
                except ValueError as exc:
                    self.respond({'status':'error','message':str(exc)},400)
                    return
                if not chart_slots.acquire(blocking=False):
                    self.respond({'status':'error','message':'本地读取繁忙，请移开后重新悬浮'},429)
                    return
                try:
                    if kind=='day':
                        from level2_kline import build_bundle
                        bundle=build_bundle({code},current.day,include_volume=True)
                        result={**bundle['series'][code], 'code':code,'day':current.day,
                                'labels':bundle['dates'],'source':bundle['source'],'method':bundle['method']}
                    else:
                        from level2_intraday import calculate_intraday
                        result=calculate_intraday(code,current.day,current.cards[code],lambda _:None,current.root)
                    result['readAt']=datetime.now(timezone.utc).isoformat()
                    if workspace:result['receipt']=workspace.record_chart(result,kind)
                    self.respond({'status':'done','result':result})
                except Exception as exc:
                    self.respond({'status':'error','message':f'读取失败：{exc}'},500)
                finally:
                    chart_slots.release()
            else:
                self.send_error(404)

        def do_POST(self):
            if not self.allowed(post=True):
                return
            path=urlsplit(self.path).path
            query=parse_qs(urlsplit(self.path).query)
            if workspace and path in ('/api/report/build','/api/snapshots','/api/state','/api/patterns','/api/validation'):
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=32*1024*1024 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('请求格式或长度无效')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):raise ValueError('请求格式无效')
                    self.respond(workspace.build(data.get('day')) if path=='/api/report/build' else workspace.state.start(data.get('day'),data.get('window')) if path=='/api/state' else workspace.patterns.start(data.get('day')) if path=='/api/patterns' else workspace.validation.start(data) if path=='/api/validation' else workspace.save(data),201)
                except Exception as exc:self.respond({'status':'error','message':str(exc)},400)
                return
            try:
                current=workspace.get_service(query.get('date',[service.day])[0]) if workspace else service
            except ValueError as exc:
                self.respond({'status':'error','message':str(exc)},400);return
            selected = current if path == '/api/detail' else minute_service if path == '/api/minute' else None
            if selected is None or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send_error(404)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('请求长度无效')
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError('请求格式无效')
                self.respond(selected.start(request.get('code')), 202)
            except (ValueError, TypeError) as exc:
                self.respond({'status': 'error', 'message': str(exc)}, 400)
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18762)
    args = parser.parse_args()
    service = Service()
    from level2_intraday import calculate_intraday, minute_identity
    minute_service = Service(report=service.report, cache=BASE / '.level2_minute_cache', calculator=calculate_intraday, identity=minute_identity)
    from level2_workspace import Workspace
    workspace=Workspace(service)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(service, args.port, minute_service, workspace))
    print(f'Local Level-2 service: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.pool.shutdown(wait=False, cancel_futures=True)
        minute_service.pool.shutdown(wait=False, cancel_futures=True)
        workspace.pool.shutdown(wait=False, cancel_futures=True)
        workspace.state.pool.shutdown(wait=False, cancel_futures=True)
        if workspace._patterns:workspace._patterns.pool.shutdown(wait=False,cancel_futures=True)
        if workspace._validation:workspace._validation.pool.shutdown(wait=False,cancel_futures=True)
