"""Descriptive, close-to-close follow-up study for daily Level-2 flow events.

This is not an executable strategy: the trigger is known only after its close.
"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
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


def local_study(start, end, asof, split, horizons=(1, 3, 5)):
    """Read source-gated daily aggregates; never mix cached facts from changed files."""
    from level2_contract import calendar
    from level2_state import StateService, settings, stamp, sha, BASE, CONFIG
    from level2_paths import PATHS, CONFIG as PATH_CONFIG
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
    price_days = selected
    state = StateService(SimpleNamespace(base=BASE, root=PATHS['level2']))

    def identity():
        files = [cfg['trade_calendar'], CONFIG, PATH_CONFIG, Path(__file__), BASE/'level2_state.py', BASE/'level2_events.py']
        for d in flow_days:
            source = state.source(d)
            if source:
                files.extend((source, source.parent/'_conversion_audit'/d/'manifest.json',
                              source.parent/'_conversion_audit'/d/'COMMITTED'))
        files.extend(PATHS['stk_factor_pro']/f'{d}_stk_factor_pro.csv' for d in price_days)
        return sha([stamp(p) for p in files] + [[d, 'missing_deal'] for d in flow_days if not state.source(d)])

    before = identity()
    try:
        flows, sources = {}, []
        for day in flow_days:
            rows, source = state.facts(day)
            if source['status'] not in ('MISSING', 'UNCOMMITTED', 'UNKNOWN_SCHEMA'):
                flows[day] = rows
            sources.append(source)
        prices = {day: state.prices(day) for day in price_days}
        result = study(flows, prices, days, start, end, asof, split, horizons)
        if before != identity():
            raise ValueError('研究期间输入来源变化，结果未发布')
        result['sourceIdentity'] = before
        result['flowSources'] = sources
        result['priceCoverage'] = {day: len(prices[day]) for day in price_days}
        return result
    finally:
        state.pool.shutdown(wait=False)


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
