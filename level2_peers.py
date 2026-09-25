"""Post-close cross-sectional comparisons; no historical industry membership inferred."""
import csv
import math
from pathlib import Path


def market_caps(path, day):
    """Read same-day total market value in Tushare's 10k CNY unit."""
    if path is None:
        return {}, {'status': 'NOT_CONFIGURED', 'source': None, 'day': day, 'coverage': 0}
    source = Path(path) / f'{day}_daily_basic.csv'
    evidence = {'status': 'MISSING_FILE', 'source': str(source), 'day': day, 'coverage': 0}
    if not source.is_file():
        return {}, evidence
    values = {}
    try:
        with source.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if not {'ts_code', 'trade_date', 'total_mv'}.issubset(reader.fieldnames or []):
                evidence['status'] = 'INVALID_SCHEMA'
                return {}, evidence
            for row in reader:
                if row['trade_date'] != day:
                    evidence['status'] = 'INVALID_DATE'
                    return {}, evidence
                code = row['ts_code']
                if code in values:
                    evidence['status'] = 'DUPLICATE_CODE'
                    return {}, evidence
                try:
                    value = float(row['total_mv'])
                except (TypeError, ValueError):
                    value = None
                values[code] = value if value is not None and math.isfinite(value) and value > 0 else None
    except (OSError, UnicodeError, csv.Error):
        evidence['status'] = 'READ_ERROR'
        return {}, evidence
    evidence.update(status='AVAILABLE', coverage=sum(v is not None for v in values.values()))
    return values, evidence


def rank_peers(states, market_values, market_evidence):
    """Equal-count cap/amount groups; midrank percentiles only with >=20 valid flows."""
    evidence = {**market_evidence, 'scope': '收盘后同日横截面；市值单位万元；成交额来自当前 Level-2 日级聚合',
                'metric': '主动净额比组内百分位；同值取中位秩；不代表行业中性或预测效果'}
    for state in states.values():
        state.update(totalMv=None, sizeGroup=None, sizeGroupCount=None, sizePeerCount=None,
                     sizeFlowPercentile=None, liquidityGroup=None, liquidityGroupCount=None,
                     liquidityPeerCount=None, liquidityFlowPercentile=None)

    def assign(key, prefix):
        eligible = [(code, key(code, state)) for code, state in states.items()]
        eligible = [(code, value) for code, value in eligible if isinstance(value, (int, float))
                    and math.isfinite(value) and value > 0]
        eligible.sort(key=lambda pair: (pair[1], pair[0]))
        groups = min(10, max(1, len(eligible) // 20))
        buckets = [[] for _ in range(groups)]
        for index, (code, _) in enumerate(eligible):
            group = min(groups - 1, index * groups // len(eligible))
            buckets[group].append(code)
            states[code][prefix + 'Group'] = group + 1
            states[code][prefix + 'GroupCount'] = groups
        for codes in buckets:
            ranked = sorted([(code, states[code]['level']) for code in codes
                             if isinstance(states[code].get('level'), (int, float))
                             and math.isfinite(states[code]['level'])], key=lambda pair: (pair[1], pair[0]))
            for code in codes:
                states[code][prefix + 'PeerCount'] = len(ranked)
            if len(ranked) < 20:
                continue
            start = 0
            while start < len(ranked):
                end = start + 1
                while end < len(ranked) and ranked[end][1] == ranked[start][1]:
                    end += 1
                percentile = 100 * ((start + end - 1) / 2 + .5) / len(ranked)
                for code, _ in ranked[start:end]:
                    states[code][prefix + 'FlowPercentile'] = percentile
                start = end
        return len(eligible)

    for code, value in market_values.items():
        if code in states:
            states[code]['totalMv'] = value
    evidence['sizeCoverage'] = assign(lambda code, state: state['totalMv'], 'size')
    evidence['liquidityCoverage'] = assign(lambda code, state: state.get('amount'), 'liquidity')
    evidence['stockCount'] = len(states)
    return evidence
