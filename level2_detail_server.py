"""Loopback-only HTTP entrypoint for the local Level-2 research application."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlsplit, parse_qs
from urllib.parse import urlencode
import argparse
import json

BASE = Path(__file__).resolve().parent
LEGACY_REPORT_BOOKMARK = 'level2-market-scan_20260922.html'
LEGACY_BOOKMARKS = {LEGACY_REPORT_BOOKMARK, 'level2_state_ui.html'}
FRONTEND = BASE / 'frontend' / 'dist'


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
            day=query.get('date',[service.day if service else ''])[0]
            if path.removeprefix('/') in LEGACY_BOOKMARKS:
                # Historical bookmarks keep their selected evidence, but the old
                # HTML renderer is no longer a second user-facing application.
                selection={key:query[key][0] for key in ('snapshot','date') if key in query}
                if path.removeprefix('/') == LEGACY_REPORT_BOOKMARK and not selection:
                    selection['date'] = '20260922'
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
            elif path.startswith('/api/minute/') and (workspace is not None or minute_service is not None):
                try:
                    current=workspace.get_minute_service(day) if workspace else minute_service
                    self.respond(current.status(path.removeprefix('/api/minute/')))
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
            if path not in ('/api/detail','/api/minute') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send_error(404)
                return
            try:
                day=query.get('date',[service.day if service else ''])[0]
                if path == '/api/detail':
                    selected=workspace.get_service(day) if workspace else service
                else:
                    selected=workspace.get_minute_service(day) if workspace else minute_service
            except ValueError as exc:
                self.respond({'status':'error','message':str(exc)},400);return
            if selected is None:
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
    from level2_workspace import Workspace
    workspace=Workspace()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(None, args.port, workspace=workspace))
    print(f'Local Level-2 service: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        workspace.close()
