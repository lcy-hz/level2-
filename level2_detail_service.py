"""Date-bound report reading and on-demand single-stock calculation jobs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import json
import re

from level2_detail_research import calculate, source_identity
from level2_paths import PATHS

BASE = Path(__file__).resolve().parent
REPORT = BASE / '.level2_reports' / '20260922' / 'report.json'
SOURCE = PATHS['level2']
CACHE = BASE / '.level2_detail_cache'


def read_report(path=REPORT):
    if Path(path).suffix != '.json':raise ValueError('正式报告必须是 JSON')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('markets'),list) or not isinstance(data.get('cards'),list):
        raise ValueError('报告 JSON 结构无效')
    return data


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
