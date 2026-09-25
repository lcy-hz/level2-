"""Date-bound report reading and on-demand single-stock calculation jobs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import json
import math
import re

from level2_detail_research import calculate, source_identity
from level2_paths import PATHS

BASE = Path(__file__).resolve().parent
SOURCE = PATHS['level2']
CACHE = BASE / '.level2_detail_cache'


def read_report(path, expected_day=None):
    if Path(path).suffix != '.json':raise ValueError('正式报告必须是 JSON')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(data,dict) or not isinstance(data.get('markets'),list) or not data['markets']
            or not isinstance(data['markets'][-1],dict)
            or not re.fullmatch(r'\d{8}',str(data['markets'][-1].get('day','')))
            or not isinstance(data.get('cards'),list)):
        raise ValueError('报告 JSON 结构无效')
    if expected_day is not None and data['markets'][-1]['day'] != expected_day:
        raise ValueError('报告证据日与文件日期不一致')
    return data


class Service:
    def __init__(self, report, root=SOURCE, cache=CACHE, calculator=calculate, identity=source_identity,
                 verify_report_totals=True):
        self.report = report
        self.day = self.report['markets'][-1]['day']
        self.cards = {c['code']: c for c in self.report['cards']}
        self.root, self.cache, self.calculator = root, cache, calculator
        self.identity = identity
        self.verify_report_totals = verify_report_totals
        self.jobs, self.lock = {}, Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)

    def validate(self, code):
        if not isinstance(code, str) or code not in self.cards or not re.fullmatch(r'\d{6}\.(SH|SZ)', code):
            raise ValueError('只能计算当前报告中的股票代码')

    def path(self, code):
        return self.cache / self.day / f'{code}.json'

    def matches_report(self, code, result):
        if not isinstance(result,dict) or result.get('code') != code or result.get('day') != self.day:
            return False
        if not self.verify_report_totals:
            return True
        expected=self.cards[code]
        for field in ('amount','net'):
            actual, target=result.get(field),expected.get(field)
            if actual is None or target is None:
                if actual is not None or target is not None:return False
            elif (type(actual) not in (int,float) or type(target) not in (int,float)
                  or not math.isfinite(actual) or not math.isfinite(target)
                  or abs(actual-target)>max(2,abs(target)*1e-9)):
                return False
        return True

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
                if (isinstance(result,dict) and result['sourceIdentity'] == self.identity(self.day, self.root)
                        and self.matches_report(code,result)):
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
