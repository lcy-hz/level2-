"""Descriptive, close-to-close follow-up study for daily Level-2 flow events.

This is not an executable strategy: the trigger is known only after its close.
"""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import statistics
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from level2_events import kind, usable


def _price(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _return(start, end):
    if not (_price(start) and _price(end)):
        return None
    value = 100 * (end / start - 1)
    return value if math.isfinite(value) else None


def close_path_drawdown(path):
    """Observed adjusted-close path only; missing sessions invalidate the path."""
    if not path:
        return None, None, None
    peak = None
    peak_day = None
    worst = 0.0
    worst_peak = None
    worst_trough = None
    for day, value in path:
        if not _price(value):
            return None, None, None
        if peak is None or value > peak:
            peak, peak_day = value, day
        drawdown = 100 * (value / peak - 1)
        if drawdown < worst:
            worst, worst_peak, worst_trough = drawdown, peak_day, day
    return worst, worst_peak, worst_trough


def entry_gate(bar):
    """Necessary next-session bar checks; never a fill or execution decision."""
    if bar is None:
        return 'MISSING_BAR'
    try:
        open_price, high, low, close, volume = bar
    except (TypeError, ValueError):
        return 'MISSING_BAR'
    if not all(_price(value) for value in (open_price, high, low, close)):
        return 'MISSING_PRICE'
    if high < max(open_price, close) or low > min(open_price, close) or high < low:
        return 'INVALID_OHLC'
    if not isinstance(volume, (int, float)) or not math.isfinite(volume):
        return 'UNKNOWN_VOLUME'
    if volume <= 0:
        return 'NO_VOLUME'
    if open_price == high == low == close:
        return 'ONE_PRICE_SESSION'
    return 'PRICE_REFERENCE_ONLY'


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_timing(day, path):
    """Local last-write evidence only; not first availability or point-in-time proof."""
    if path is None or not Path(path).is_file():
        return {'day': day, 'present': False, 'modifiedAtLocal': None,
                'modifiedAfterTradeDay': None}
    modified = datetime.fromtimestamp(Path(path).stat().st_mtime, ZoneInfo('Asia/Shanghai'))
    return {'day': day, 'present': True, 'modifiedAtLocal': modified.isoformat(timespec='seconds'),
            'modifiedAfterTradeDay': modified.strftime('%Y%m%d') > day}


def input_timing_audit(flow_sources, price_days, price_root):
    """Freeze the local file timeline alongside a result without claiming strict PIT."""
    flow = [file_timing(item['day'], item.get('source')) for item in flow_sources]
    price = [file_timing(day, Path(price_root) / f'{day}_stk_factor_pro.csv') for day in price_days]
    def counts(rows):
        return {'requested': len(rows), 'present': sum(row['present'] for row in rows),
                'modifiedAfterTradeDay': sum(row['modifiedAfterTradeDay'] is True for row in rows),
                'days': rows}
    return {'method': 'LOCAL_LAST_MODIFIED_ONLY_NOT_PIT', 'strictPitVerified': False,
            'flow': counts(flow), 'price': counts(price)}


def leave_one_day_out_excess(daily_rows):
    """Equal-day mean after removing each comparable trigger day in turn."""
    values = [row['meanExcessPct'] for row in daily_rows
              if isinstance(row.get('meanExcessPct'), (int, float))
              and math.isfinite(row['meanExcessPct'])]
    if len(values) < 2:
        return {'comparableDays': len(values), 'minPct': None, 'maxPct': None}
    total = sum(values)
    alternatives = [(total - value) / (len(values) - 1) for value in values]
    return {'comparableDays': len(values), 'minPct': min(alternatives),
            'maxPct': max(alternatives)}


def study(flows, prices, days, start, end, asof, split, horizons=(1, 3, 5),
          collect_observations=True, on_observation=None, bars=None, flow_sources=None):
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

    observations, missing_sources, excluded_sources = [], [], []
    bars = bars or {}
    def daily_group():
        return {'events': 0, 'observed': 0, 'pending': 0, 'missingPrice': 0,
                'returns': [], 'excessSum': 0.0, 'excessN': 0,
                'benchmarkPct': None, 'benchmarkN': None}
    aggregates = defaultdict(lambda: {'events': 0, 'observed': 0, 'pending': 0, 'missingPrice': 0,
                                      'returns': [], 'positive': 0, 'benchmarkSum': 0,
                                      'excessSum': 0, 'excessN': 0, 'daily': defaultdict(daily_group),
                                      'signalDays': set(), 'entryGates': defaultdict(int),
                                      'closeDrawdowns': []})
    observation_count = 0
    signal_days = days[index[start]:index[end] + 1]
    for day in signal_days:
        i = index[day]
        prior = days[i - 1]
        previous, current = flows.get(prior), flows.get(day)
        if previous is None or current is None:
            missing_sources.append({'day': day, 'missing': [d for d in (prior, day) if d not in flows]})
            continue
        if flow_sources is not None:
            previous_source, current_source = flow_sources.get(prior), flow_sources.get(day)
            permitted = {'NATIVE', 'LEGACY_CALIBRATED_ROW_GUARD'}
            if previous_source not in permitted or current_source not in permitted or previous_source != current_source:
                excluded_sources.append({'day': day, 'previousDay': prior,
                                         'previousSource': previous_source, 'currentSource': current_source})
                continue
        pool = {code for code in previous.keys() & current.keys()
                if usable(previous[code]) and usable(current[code])}
        events = [(code, kind(previous[code], current[code])) for code in sorted(pool)]
        events = [(code, rule) for code, rule in events if rule]
        cohort = ('TRAIN' if i + max_horizon <= split_idx else
                  'EMBARGO' if i <= split_idx else 'OUT_OF_SAMPLE')
        entry_day = days[i + 1] if i + 1 < len(days) else None
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
                path = [(path_day, prices.get(path_day, {}).get(code))
                        for path_day in days[i:i + horizon + 1]] if maturity else []
                close_drawdown, drawdown_peak, drawdown_trough = close_path_drawdown(path)
                drawdown_status = ('PENDING' if not maturity else
                                   'OBSERVED' if close_drawdown is not None else 'MISSING_PRICE')
                gate = (entry_gate(bars.get(entry_day, {}).get(code))
                        if entry_day is not None and i + 1 <= asof_idx else 'PENDING')
                item = {'day': day, 'code': code, 'rule': rule, 'cohort': cohort,
                        'horizon': horizon, 'targetDay': target, 'status': status,
                        'entryDay': entry_day, 'entryGate': gate,
                        'closeDrawdownStatus': drawdown_status,
                        'maxCloseDrawdownPct': close_drawdown,
                        'drawdownPeakDay': drawdown_peak, 'drawdownTroughDay': drawdown_trough,
                        'previousRatio': previous[code]['ratio'], 'currentRatio': current[code]['ratio'],
                        'deltaPP': current[code]['ratio'] - previous[code]['ratio'],
                        'triggerClose': current_prices.get(code) if _price(current_prices.get(code)) else None,
                        'targetClose': target_prices.get(code) if maturity and _price(target_prices.get(code)) else None,
                        'returnPct': outcome, 'benchmarkPct': benchmark,
                        'excessPct': outcome - benchmark if outcome is not None and benchmark is not None else None,
                        'benchmarkN': len(benchmark_returns)}
                observation_count += 1
                if collect_observations:
                    observations.append(item)
                if on_observation:
                    on_observation(item)
                group = aggregates[(cohort, rule, horizon)]
                group['events'] += 1
                group['entryGates'][gate] += 1
                daily = group['daily'][day]
                daily['events'] += 1
                daily['benchmarkPct'] = benchmark
                daily['benchmarkN'] = len(benchmark_returns) if maturity else None
                if close_drawdown is not None:
                    group['closeDrawdowns'].append(close_drawdown)
                if status == 'PENDING':
                    group['pending'] += 1
                    daily['pending'] += 1
                elif status == 'MISSING_PRICE':
                    group['missingPrice'] += 1
                    daily['missingPrice'] += 1
                else:
                    group['observed'] += 1
                    daily['observed'] += 1
                    group['returns'].append(outcome)
                    daily['returns'].append(outcome)
                    group['positive'] += outcome > 0
                    group['benchmarkSum'] += len(benchmark_returns)
                    group['signalDays'].add(day)
                    if item['excessPct'] is not None:
                        group['excessSum'] += item['excessPct']
                        group['excessN'] += 1
                        daily['excessSum'] += item['excessPct']
                        daily['excessN'] += 1

    summary = []
    for (cohort, rule, horizon), group in sorted(aggregates.items()):
        values = group['returns']
        n = group['observed']
        daily_rows = [{'day': day, 'events': daily['events'], 'observed': daily['observed'],
                       'pending': daily['pending'], 'missingPrice': daily['missingPrice'],
                       'meanReturnPct': (statistics.mean(daily['returns']) if daily['returns'] else None),
                       'benchmarkPct': daily['benchmarkPct'], 'benchmarkN': daily['benchmarkN'],
                       'meanExcessPct': (daily['excessSum'] / daily['excessN'] if daily['excessN'] else None)}
                      for day, daily in sorted(group['daily'].items())]
        sensitivity = leave_one_day_out_excess(daily_rows)
        summary.append({'cohort': cohort, 'rule': rule, 'horizon': horizon,
                        'events': group['events'], 'observed': n,
                        'pending': group['pending'], 'missingPrice': group['missingPrice'],
                        'signalDays': len(group['signalDays']),
                        'triggerDays': len(daily_rows),
                        'entryGateCounts': dict(sorted(group['entryGates'].items())),
                        'signalDayBreakdown': daily_rows,
                        'leaveOneDayOutExcess': sensitivity,
                        'closeDrawdownObserved': len(group['closeDrawdowns']),
                        'medianMaxCloseDrawdownPct': (statistics.median(group['closeDrawdowns'])
                                                      if group['closeDrawdowns'] else None),
                        'benchmarkPoolMeanN': group['benchmarkSum'] / n if n else None,
                        'meanReturnPct': statistics.mean(values) if values else None,
                        'medianReturnPct': statistics.median(values) if values else None,
                        'positiveShare': group['positive'] / n if n else None,
                        'meanExcessPct': group['excessSum'] / group['excessN'] if group['excessN'] else None,
                        'equalDayMeanExcessPct': (statistics.mean(row['meanExcessPct'] for row in daily_rows
                                                                 if row['meanExcessPct'] is not None)
                                                  if any(row['meanExcessPct'] is not None for row in daily_rows) else None)})
    return {'method': 'DAILY_EVENT_CLOSE_TO_CLOSE_DESCRIPTIVE_2',
            'start': start, 'end': end, 'asof': asof, 'split': split,
            'horizons': list(horizons), 'embargoSessions': max_horizon,
            'signalDaysRequested': len(signal_days), 'signalDaysMissingFlow': missing_sources,
            'signalDaysExcludedSource': excluded_sources,
            'summary': summary, 'observations': observations, 'observationCount': observation_count,
            'limitations': ['事件仅在收盘日级数据就绪后可识别，收盘至收盘收益不是可成交策略收益',
                            'close×adj_factor 的历史当时可得性未验证；复权因子修订可改变回看结果',
                            '次日开盘日线门槛只检查价格、量和单一价位；即使通过也不证明可成交',
                            '最大收盘回撤要求触发日至目标日的每个复权收盘均有效；盘中极值和可成交路径未观察',
                            '无实际订单回报、涨跌停排队、停牌退出、手续费、滑点或容量模型；不展示执行收益',
                            '基准为同日有效方向且有价格的股票等权均值，不是行业或风格匹配对照',
                            '只在相邻交易日均为同一种已核验 Level-2 来源时形成事件；跨来源日和未知来源日单列排除',
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
    from level2_limitup_study import CONFIG as LIMIT_CONFIG, limit_path, limit_root
    cfg, _, flow_days, price_days = _local_plan(start, end, asof, split, horizons)
    state = StateService(SimpleNamespace(base=BASE, root=PATHS['level2']))
    try:
        files = [cfg['trade_calendar'], CONFIG, PATH_CONFIG, LIMIT_CONFIG,
                 Path(__file__), BASE/'level2_state.py', BASE/'level2_events.py', BASE/'level2_limitup_study.py']
        missing = []
        for day in flow_days:
            source = state.source(day)
            if source:
                files.extend((source, source.parent/'_conversion_audit'/day/'manifest.json',
                              source.parent/'_conversion_audit'/day/'COMMITTED'))
            else:
                missing.append([day, 'missing_deal'])
        files.extend(PATHS['stk_factor_pro']/f'{day}_stk_factor_pro.csv' for day in price_days)
        limit_list_root = limit_root()
        files.extend(limit_path(limit_list_root, day) for day in flow_days[1:])
        return sha([stamp(path) for path in files] + missing)
    finally:
        state.pool.shutdown(wait=False)


def local_study(start, end, asof, split, horizons=(1, 3, 5),
                collect_observations=True, on_observation=None):
    """Read source-gated daily aggregates; never mix cached facts from changed files."""
    from level2_state import StateService, BASE
    from level2_paths import PATHS
    from level2_limitup_study import limit_root, limitup_study, read_limitups
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
        prices,bars={},{}
        for day in price_days:
            prices[day],bars[day]=state.price_bars(day)
        root = limit_root()
        limitups = {day: read_limitups(root, day) for day in flow_days[1:]}
        result = study(flows, prices, days, start, end, asof, split, horizons,
                       collect_observations=collect_observations, on_observation=on_observation,
                       bars=bars, flow_sources={item['day']: item['status'] for item in sources})
        result['limitUpStudy'] = limitup_study(flows, {item['day']: item['status'] for item in sources},
                                              limitups, prices, bars, days, start, end, asof, split, horizons)
        limit_timing = [file_timing(day, audit['source']) for day, (audit, _) in limitups.items()]
        result['limitUpStudy']['sourceTiming'] = {
            'requested': len(limit_timing), 'present': sum(row['present'] for row in limit_timing),
            'modifiedAfterTradeDay': sum(row['modifiedAfterTradeDay'] is True for row in limit_timing),
            'days': limit_timing}
        timing_audit = input_timing_audit(sources, price_days, PATHS['stk_factor_pro'])
        if before != study_identity(start, end, asof, split, horizons):
            raise ValueError('研究期间输入来源变化，结果未发布')
        result['sourceIdentity'] = before
        result['flowSources'] = sources
        result['priceCoverage'] = {day: len(prices[day]) for day in price_days}
        result['inputTimingAudit'] = timing_audit
        return result
    finally:
        state.pool.shutdown(wait=False)


class ValidationService:
    """One bounded local study at a time; detail lookups never rescan Level-2."""
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
            token = uuid.uuid4().hex
            self.receipts.mkdir(exist_ok=True)
            database = self.receipts / f'{token}.sqlite'
            temporary = self.receipts / f'{token}.building.sqlite'
            try:
                with closing(sqlite3.connect(temporary)) as connection:
                    with connection:
                        connection.execute('''CREATE TABLE observation (
                            code TEXT, day TEXT, rule TEXT, cohort TEXT, horizon INTEGER, targetDay TEXT,
                            entryDay TEXT, entryGate TEXT,
                            closeDrawdownStatus TEXT, maxCloseDrawdownPct REAL,
                            drawdownPeakDay TEXT, drawdownTroughDay TEXT,
                            status TEXT, previousRatio REAL, currentRatio REAL, deltaPP REAL,
                            triggerClose REAL, targetClose REAL, returnPct REAL, benchmarkPct REAL,
                            excessPct REAL, benchmarkN INTEGER)''')
                        columns = ('code', 'day', 'rule', 'cohort', 'horizon', 'targetDay',
                                   'entryDay', 'entryGate', 'closeDrawdownStatus',
                                   'maxCloseDrawdownPct', 'drawdownPeakDay', 'drawdownTroughDay', 'status',
                                   'previousRatio', 'currentRatio', 'deltaPP', 'triggerClose', 'targetClose',
                                   'returnPct', 'benchmarkPct', 'excessPct', 'benchmarkN')
                        buffer = []
                        inserted = 0
                        insert_sql = 'INSERT INTO observation VALUES (' + ','.join('?' for _ in columns) + ')'
                        def flush():
                            nonlocal inserted
                            if buffer:
                                connection.executemany(insert_sql, buffer)
                                inserted += len(buffer)
                                buffer.clear()
                        def emit(row):
                            buffer.append(tuple(row.get(key) for key in columns))
                            if len(buffer) >= 1000:
                                flush()
                        result = self.calculator(*args, collect_observations=False, on_observation=emit)
                        flush()
                        if result.get('observationCount') != inserted:
                            raise ValueError('逐股证据与汇总数量对账失败')
                        result.pop('observations', None)
                        connection.execute('CREATE INDEX observation_code ON observation(code, day, horizon)')
                temporary.replace(database)
            finally:
                temporary.unlink(missing_ok=True)
            from level2_state import sha
            record = {'result': result, 'dataSha256': sha(result),
                      'observationsSha256': _file_hash(database)}
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
        database = self.receipts / f'{token}.sqlite'
        if record.get('observationsSha256') != _file_hash(database):
            raise ValueError('后续收益逐股证据校验失败')
        args = (result['start'], result['end'], result['asof'], result['split'], tuple(result['horizons']))
        if result['sourceIdentity'] != self.identity(*args):
            raise ValueError('后续收益研究来源已变化，不能冻结旧结果')
        return result

    def details(self, token, codes):
        from level2_contract import PAT
        if (not isinstance(codes, list) or not 1 <= len(codes) <= 50
                or any(not isinstance(code, str) or not re.fullmatch(PAT, code) for code in codes)
                or len(set(codes)) != len(codes)):
            raise ValueError('逐股证据范围无效，最多50只不重复A股')
        result = self.frozen(token)
        database = self.receipts / f'{token}.sqlite'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            query = ('SELECT * FROM observation WHERE code IN (' + ','.join('?' for _ in codes) +
                     ') ORDER BY code, day DESC, horizon ASC')
            rows = [dict(row) for row in connection.execute(query, codes)]
        grouped = defaultdict(list)
        for row in rows:
            grouped[row['code']].append(row)
        return {code: {'code': code, 'start': result['start'], 'end': result['end'], 'asof': result['asof'],
                       'sourceIdentity': result['sourceIdentity'], 'observations': grouped[code],
                       'status': 'AVAILABLE' if grouped[code] else 'NO_EVENT',
                       'scope': '仅所选研究窗口内已识别的日级事件；未来价格不进入触发日证据。'}
                for code in codes}

    def detail(self, token, code):
        return self.details(token, [code])[code]


def main():
    parser = argparse.ArgumentParser(description='日级主动成交事件后续收益描述性研究（非策略回测）')
    for key in ('start', 'end', 'asof', 'split'):
        parser.add_argument('--' + key, required=True, help='YYYYMMDD 交易日')
    parser.add_argument('--horizons', default='1,3,5', help='逗号分隔的未来交易日数')
    parser.add_argument('--details', action='store_true', help='输出逐股事件明细')
    args = parser.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(','))
    result = local_study(args.start, args.end, args.asof, args.split, horizons,
                         collect_observations=args.details)
    if not args.details:
        result.pop('observations')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
