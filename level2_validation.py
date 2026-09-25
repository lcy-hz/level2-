"""Descriptive, close-to-close follow-up study for daily Level-2 flow events.

This is not an executable strategy: the trigger is known only after its close.
"""
import argparse
import json
import math
import statistics
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from level2_events import kind, usable


def _price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _return(start, end):
    if not (_price(start) and _price(end)):
        return None
    return 100 * (end / start - 1)


def study(flows, prices, days, start, end, asof, split, horizons=(1, 3, 5)):
    """Use adjacent calendar sessions and frozen signal-day facts only.

    `split` is the final training date. Training events whose longest outcome
    overlaps the split are embargoed, even when evaluating a shorter horizon.
    """
    days = list(days)
    if days != sorted(set(days)) or any(d not in days for d in (start, end, asof, split)):
        raise ValueError('研究日期必须属于无重复、已排序的交易日历')
    if not start <= end <= asof or not start <= split < end:
        raise ValueError('要求起点≤终点≤数据截止日，且起点≤训练截止日<事件终点')
    if not horizons or any(type(h) is not int or h < 1 for h in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError('预测期限须为不重复的正整数交易日')
    max_horizon = max(horizons)
    index = {day: i for i, day in enumerate(days)}
    split_idx, asof_idx = index[split], index[asof]
    if index[start] == 0:
        raise ValueError('起点前须有一交易日用于形成事件')

    observations, missing_sources = [], []
    signal_days = days[index[start]:index[end] + 1]
    for day in signal_days:
        i = index[day]
        prior = days[i - 1]
        previous, current = flows.get(prior), flows.get(day)
        if previous is None or current is None:
            missing_sources.append({'day': day, 'missing': [d for d in (prior, day) if d not in flows]})
            continue
        pool = {code for code in previous.keys() & current.keys()
                if usable(previous[code]) and usable(current[code])}
        events = [(code, kind(previous[code], current[code])) for code in sorted(pool)]
        events = [(code, rule) for code, rule in events if rule]
        cohort = ('TRAIN' if i + max_horizon <= split_idx else
                  'EMBARGO' if i <= split_idx else 'OUT_OF_SAMPLE')
        for horizon in horizons:
            target = days[i + horizon] if i + horizon < len(days) else None
            maturity = target is not None and i + horizon <= asof_idx
            current_prices = prices.get(day, {})
            target_prices = prices.get(target, {}) if maturity else {}
            # Same-day, same-horizon eligible-universe baseline; not a matched control.
            benchmark_returns = [_return(current_prices.get(code), target_prices.get(code)) for code in pool] if maturity else []
            benchmark_returns = [value for value in benchmark_returns if value is not None]
            benchmark = statistics.mean(benchmark_returns) if benchmark_returns else None
            for code, rule in events:
                outcome = _return(current_prices.get(code), target_prices.get(code)) if maturity else None
                status = 'PENDING' if not maturity else 'MISSING_PRICE' if outcome is None else 'OBSERVED'
                observations.append({'day': day, 'code': code, 'rule': rule, 'cohort': cohort,
                                     'horizon': horizon, 'targetDay': target, 'status': status,
                                     'returnPct': outcome, 'benchmarkPct': benchmark,
                                     'excessPct': outcome - benchmark if outcome is not None and benchmark is not None else None,
                                     'benchmarkN': len(benchmark_returns)})

    grouped = defaultdict(list)
    for item in observations:
        grouped[(item['cohort'], item['rule'], item['horizon'])].append(item)
    summary = []
    for (cohort, rule, horizon), items in sorted(grouped.items()):
        observed = [item for item in items if item['status'] == 'OBSERVED']
        daily = defaultdict(list)
        for item in observed:
            if item['excessPct'] is not None:
                daily[item['day']].append(item['excessPct'])
        values = [item['returnPct'] for item in observed]
        excess = [item['excessPct'] for item in observed if item['excessPct'] is not None]
        summary.append({'cohort': cohort, 'rule': rule, 'horizon': horizon,
                        'events': len(items), 'observed': len(observed),
                        'pending': sum(item['status'] == 'PENDING' for item in items),
                        'missingPrice': sum(item['status'] == 'MISSING_PRICE' for item in items),
                        'signalDays': len({item['day'] for item in observed}),
                        'benchmarkPoolMeanN': statistics.mean(item['benchmarkN'] for item in observed) if observed else None,
                        'meanReturnPct': statistics.mean(values) if values else None,
                        'medianReturnPct': statistics.median(values) if values else None,
                        'positiveShare': sum(value > 0 for value in values) / len(values) if values else None,
                        'meanExcessPct': statistics.mean(excess) if excess else None,
                        'equalDayMeanExcessPct': statistics.mean(statistics.mean(v) for v in daily.values()) if daily else None})
    return {'method': 'DAILY_EVENT_CLOSE_TO_CLOSE_DESCRIPTIVE_1',
            'start': start, 'end': end, 'asof': asof, 'split': split,
            'horizons': list(horizons), 'embargoSessions': max_horizon,
            'signalDaysRequested': len(signal_days), 'signalDaysMissingFlow': missing_sources,
            'summary': summary, 'observations': observations,
            'limitations': ['事件仅在收盘日级数据就绪后可识别，收盘至收盘收益不是可成交策略收益',
                            'close×adj_factor 的历史当时可得性未验证；复权因子修订可改变回看结果',
                            '无入场成交、涨跌停排队、停牌退出、手续费、滑点或容量模型',
                            '基准为同日有效方向且有价格的股票等权均值，不是行业或风格匹配对照',
                            '重叠事件和同日股票相关；按信号日等权的超额均值仅供描述，不作显著性证明']}


def _local_plan(start, end, asof, split, horizons):
    from level2_contract import calendar
    from level2_state import settings
    cfg = settings()
    days, _ = calendar(cfg['trade_calendar'])
    if any(d not in days for d in (start, end, asof, split)) or days.index(start) == 0:
        raise ValueError('研究日期或起点前一交易日不在已核验交易日历内')
    if not start <= split < end <= asof:
        raise ValueError('日期顺序须为起点≤训练截止日<事件终点≤数据截止日')
    if not horizons or any(type(h) is not int or h < 1 for h in horizons):
        raise ValueError('预测期限须为正整数交易日')
    through = days[min(days.index(asof), days.index(end) + max(horizons))]
    selected = days[days.index(start) - 1:days.index(through) + 1]
    flow_days = [d for d in selected if d <= end]
    return cfg, days, flow_days, selected

def study_identity(start, end, asof, split, horizons=(1, 3, 5)):
    """Cheap source check for a saved research receipt; no raw Level-2 scan."""
    from level2_state import StateService, stamp, sha, BASE, CONFIG
    from level2_paths import PATHS, CONFIG as PATH_CONFIG
    cfg, _, flow_days, price_days = _local_plan(start, end, asof, split, horizons)
    state = StateService(SimpleNamespace(base=BASE, root=PATHS['level2']))
    try:
        files = [cfg['trade_calendar'], CONFIG, PATH_CONFIG, Path(__file__), BASE/'level2_state.py', BASE/'level2_events.py']
        missing = []
        for day in flow_days:
            source = state.source(day)
            if source:
                files.extend((source, source.parent/'_conversion_audit'/day/'manifest.json',
                              source.parent/'_conversion_audit'/day/'COMMITTED'))
            else:
                missing.append([day, 'missing_deal'])
        files.extend(PATHS['stk_factor_pro']/f'{day}_stk_factor_pro.csv' for day in price_days)
        return sha([stamp(path) for path in files] + missing)
    finally:
        state.pool.shutdown(wait=False)


def local_study(start, end, asof, split, horizons=(1, 3, 5)):
    """Read source-gated daily aggregates; never mix cached facts from changed files."""
    from level2_state import StateService, BASE
    from level2_paths import PATHS
    _, days, flow_days, price_days = _local_plan(start, end, asof, split, horizons)
    state = StateService(SimpleNamespace(base=BASE, root=PATHS['level2']))

    before = study_identity(start, end, asof, split, horizons)
    try:
        flows, sources = {}, []
        for day in flow_days:
            rows, source = state.facts(day)
            if source['status'] not in ('MISSING', 'UNCOMMITTED', 'UNKNOWN_SCHEMA'):
                flows[day] = rows
            sources.append(source)
        prices = {day: state.prices(day) for day in price_days}
        result = study(flows, prices, days, start, end, asof, split, horizons)
        if before != study_identity(start, end, asof, split, horizons):
            raise ValueError('研究期间输入来源变化，结果未发布')
        result['sourceIdentity'] = before
        result['flowSources'] = sources
        result['priceCoverage'] = {day: len(prices[day]) for day in price_days}
        return result
    finally:
        state.pool.shutdown(wait=False)


class ValidationService:
    """One bounded local study at a time; snapshots freeze only verified summaries."""
    def __init__(self, base=None, calculator=local_study, identity=study_identity):
        self.base = Path(base) if base is not None else Path(__file__).resolve().parent
        self.receipts = self.base / '.level2_validation_receipts'
        self.calculator, self.identity = calculator, identity
        self.jobs, self.lock = {}, Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)

    @staticmethod
    def request(data):
        if not isinstance(data, dict) or set(data) != {'start', 'end', 'asof', 'split', 'horizons'}:
            raise ValueError('研究参数需包含起点、事件终点、数据截止、训练截止和预测期限')
        dates = [data[key] for key in ('start', 'end', 'asof', 'split')]
        if any(not isinstance(day, str) or len(day) != 8 or not day.isdigit() for day in dates):
            raise ValueError('日期须为 YYYYMMDD')
        horizons = data['horizons']
        if (not isinstance(horizons, list) or not 1 <= len(horizons) <= 6 or
                any(type(h) is not int or not 1 <= h <= 20 for h in horizons) or len(set(horizons)) != len(horizons)):
            raise ValueError('预测期限须为1至20的互异交易日整数，最多6个')
        _, days, _, _ = _local_plan(*dates, tuple(horizons))
        if days.index(data['end']) - days.index(data['start']) + 1 > 250:
            raise ValueError('单次研究最多250个事件交易日')
        return (data['start'], data['end'], data['asof'], data['split'], tuple(horizons))

    def start(self, data):
        args = self.request(data)
        with self.lock:
            if any(job['status'] in ('queued', 'running') for job in self.jobs.values()):
                raise ValueError('已有后续收益研究正在计算，请等待完成')
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'status': 'queued', 'message': '等待日级数据聚合', 'args': args}
            self.pool.submit(self._work, job_id, args)
        return {'id': job_id, 'status': 'queued'}

    def _work(self, job_id, args):
        with self.lock:
            self.jobs[job_id] = {'status': 'running', 'message': '正在核对来源并计算后续收益', 'args': args}
        try:
            result = self.calculator(*args)
            result['observationCount'] = len(result.pop('observations'))
            token = uuid.uuid4().hex
            self.receipts.mkdir(exist_ok=True)
            from level2_state import sha
            record = {'result': result, 'dataSha256': sha(result)}
            (self.receipts / f'{token}.json').write_text(json.dumps(record, ensure_ascii=False, allow_nan=False))
            with self.lock:
                self.jobs[job_id] = {'status': 'done', 'message': '描述性研究完成', 'args': args,
                                     'receipt': token, 'result': result}
        except Exception as exc:
            with self.lock:
                self.jobs[job_id] = {'status': 'error', 'message': str(exc), 'args': args}

    def status(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('研究任务编号无效')
        with self.lock:
            job = dict(self.jobs.get(job_id, {'status': 'missing', 'message': '研究任务不存在或服务已重启'}))
        if job['status'] == 'done' and job['result']['sourceIdentity'] != self.identity(*job['args']):
            return {'status': 'stale', 'message': '研究来源已变化，请重新计算'}
        job.pop('args', None)
        return job

    def frozen(self, token):
        if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError('后续收益凭据无效')
        from level2_state import sha
        record = json.loads((self.receipts / f'{token}.json').read_text())
        result = record['result']
        if record.get('dataSha256') != sha(result):
            raise ValueError('后续收益凭据内容校验失败')
        args = (result['start'], result['end'], result['asof'], result['split'], tuple(result['horizons']))
        if result['sourceIdentity'] != self.identity(*args):
            raise ValueError('后续收益研究来源已变化，不能冻结旧结果')
        return result


def main():
    parser = argparse.ArgumentParser(description='日级主动成交事件后续收益描述性研究（非策略回测）')
    for key in ('start', 'end', 'asof', 'split'):
        parser.add_argument('--' + key, required=True, help='YYYYMMDD 交易日')
    parser.add_argument('--horizons', default='1,3,5', help='逗号分隔的未来交易日数')
    parser.add_argument('--details', action='store_true', help='输出逐股事件明细')
    args = parser.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(','))
    result = local_study(args.start, args.end, args.asof, args.split, horizons)
    if not args.details:
        result.pop('observations')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
