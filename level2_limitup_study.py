"""Descriptive limit-up cohort study; no executable entry or trading claim."""
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from level2_contract import PAT
from level2_events import usable
from level2_validation import _price, _return, entry_gate, leave_one_day_out_excess


CONFIG = Path(__file__).with_name('level2_limitup_sources.json')
SOURCE_STATUSES = {'NATIVE', 'LEGACY_CALIBRATED_ROW_GUARD'}
MARKET_DIRECTIONS = ('IMPROVING', 'WEAKENING')
STOCK_DIRECTIONS = ('IMPROVING', 'WEAKENING')
BOARDS = ('MAIN', 'GEM', 'STAR')


def board_of(code):
    """Exchange-code market segment, not a claim about daily price-limit rules."""
    if re.fullmatch(PAT, code or '') is None:
        raise ValueError(f'非沪深A股代码：{code}')
    if code.startswith(('300', '301', '302')):
        return 'GEM'
    if code.startswith(('688', '689')):
        return 'STAR'
    return 'MAIN'


def limit_root():
    """Optional dedicated source path; default follows the configured stock sync tree."""
    from level2_paths import PATHS
    if CONFIG.is_file():
        value = json.loads(CONFIG.read_text())
        if not isinstance(value, dict) or set(value) != {'limit_list_d_root'}:
            raise ValueError('涨停来源配置只允许 limit_list_d_root')
        root = value['limit_list_d_root']
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError('limit_list_d_root 必须是绝对目录路径')
        return Path(root).resolve()
    return (PATHS['stk_factor_pro'].parents[2] / 'limitup' / 'limit_list_d' / 'by_date').resolve()


def limit_path(root, day):
    return Path(root) / f'{day}_limit_list_d.csv'


def read_limitups(root, day):
    """Use provider U, never a fixed percentage threshold; audit exclusions."""
    path = limit_path(root, day)
    base = {'day': day, 'source': str(path), 'status': 'MISSING', 'uRows': None,
            'eligibleRows': None, 'outsideA': None, 'stRows': None,
            'missingName': None, 'invalidClose': None}
    if not path.is_file():
        return base, {}
    with path.open(newline='', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not {'trade_date', 'ts_code', 'name', 'close', 'limit'}.issubset(reader.fieldnames):
            raise ValueError(f'涨停列表字段不完整：{path}')
        selected = {}
        counts = {'uRows': 0, 'outsideA': 0, 'stRows': 0, 'missingName': 0,
                  'invalidClose': 0}
        for row in reader:
            if row['trade_date'] != day:
                raise ValueError(f'涨停列表交易日冲突：{path}')
            if row['limit'] != 'U':
                continue
            counts['uRows'] += 1
            code = row['ts_code']
            if not isinstance(code, str) or not re.fullmatch(PAT, code):
                counts['outsideA'] += 1
                continue
            name = (row['name'] or '').strip()
            if not name:
                counts['missingName'] += 1
                continue
            if re.match(r'^(?:S\*?ST|\*?ST)', name.upper()):
                counts['stRows'] += 1
                continue
            try:
                close = float(row['close'])
            except (TypeError, ValueError):
                close = None
            if not _price(close):
                counts['invalidClose'] += 1
                continue
            if code in selected:
                raise ValueError(f'涨停列表股票重复：{day} {code}')
            selected[code] = close
    return {**base, **counts, 'status': 'AVAILABLE', 'eligibleRows': len(selected)}, selected


def market_change(previous, current, limit_codes):
    """Broad-market flow change on a fixed, valid, non-limit-up common set."""
    common = sorted(code for code in (previous.keys() & current.keys()) - set(limit_codes)
                    if usable(previous[code]) and usable(current[code]))
    if not common:
        return {'status': 'NO_COMMON_STOCKS', 'commonStocks': 0,
                'previousRatio': None, 'currentRatio': None, 'deltaPP': None}
    previous_amount = sum(previous[code]['amount'] for code in common)
    current_amount = sum(current[code]['amount'] for code in common)
    if not _price(previous_amount) or not _price(current_amount):
        return {'status': 'INVALID_AMOUNT', 'commonStocks': len(common),
                'previousRatio': None, 'currentRatio': None, 'deltaPP': None}
    prior_ratio = 100 * sum(previous[code]['net'] for code in common) / previous_amount
    current_ratio = 100 * sum(current[code]['net'] for code in common) / current_amount
    delta = current_ratio - prior_ratio
    if not all(math.isfinite(value) for value in (prior_ratio, current_ratio, delta)):
        return {'status': 'INVALID_RATIO', 'commonStocks': len(common),
                'previousRatio': None, 'currentRatio': None, 'deltaPP': None}
    return {'status': 'AVAILABLE', 'commonStocks': len(common),
            'previousRatio': prior_ratio, 'currentRatio': current_ratio, 'deltaPP': delta}


def adjusted_open_reference(bar, adjusted_close):
    """Observed next-session open on the adjusted-close scale, never a fill price."""
    if entry_gate(bar) not in {'ONE_PRICE_SESSION', 'PRICE_REFERENCE_ONLY'} or not _price(adjusted_close):
        return None
    raw_open, _, _, raw_close, _ = bar
    value = raw_open * adjusted_close / raw_close
    return value if _price(value) else None


def limitup_study(flows, sources, limitups, prices, bars, days, start, end, asof, split,
                  horizons=(1, 3, 5)):
    """Fixed-sign 2x2 comparison among provider-U, non-ST沪深A stocks only."""
    days = list(days)
    if days != sorted(set(days)) or any(day not in days for day in (start, end, asof, split)):
        raise ValueError('涨停研究交易日历无效')
    if not start <= split < end <= asof or not horizons or any(type(h) is not int or h < 1 for h in horizons):
        raise ValueError('涨停研究日期或期限无效')
    index = {day: position for position, day in enumerate(days)}
    if index[start] == 0:
        raise ValueError('涨停研究起点前缺前一交易日')
    groups = defaultdict(lambda: {'events': 0, 'observed': 0, 'pending': 0,
                                  'missingPrice': 0, 'returns': [], 'excesses': [], 'boardExcesses': [],
                                  'entryOpenGaps': [], 'postOpenReturns': [],
                                  'pairedSignalReturns': [],
                                  'eventAmounts': [], 'entryGateCounts': defaultdict(int),
                                  'daily': defaultdict(lambda: {'events': 0, 'observed': 0,
                                                                'returns': [], 'excesses': [], 'boardExcesses': []})})
    board_returns = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    coverage = []
    max_horizon = max(horizons)
    for day in days[index[start]:index[end] + 1]:
        position = index[day]
        prior = days[position - 1]
        source_a, source_b = sources.get(prior), sources.get(day)
        list_audit, u_codes = limitups.get(day, ({'day': day, 'status': 'MISSING',
                                                  'source': None, 'uRows': None,
                                                  'eligibleRows': None}, {}))
        audit = {**list_audit, 'previousDay': prior, 'previousSource': source_a,
                 'currentSource': source_b, 'matchedClose': None, 'mismatchedRawClose': None,
                 'missingRawClose': None, 'missingAdjustedClose': None, 'validStockDirection': None,
                 'missingStockDirection': None, 'flatStockDirection': None,
                 'market': None}
        if list_audit['status'] != 'AVAILABLE':
            audit['studyStatus'] = 'MISSING_LIMIT_LIST'
            coverage.append(audit)
            continue
        if not u_codes:
            audit['studyStatus'] = 'NO_ELIGIBLE_U'
            coverage.append(audit)
            continue
        previous, current = flows.get(prior), flows.get(day)
        if previous is None or current is None:
            audit['studyStatus'] = 'MISSING_FLOW'
            coverage.append(audit)
            continue
        if source_a not in SOURCE_STATUSES or source_a != source_b:
            audit['studyStatus'] = 'SOURCE_NOT_COMPARABLE'
            coverage.append(audit)
            continue
        market = market_change(previous, current, u_codes)
        audit['market'] = market
        if market['status'] != 'AVAILABLE' or market['deltaPP'] == 0:
            audit['studyStatus'] = 'MARKET_UNAVAILABLE_OR_FLAT'
            coverage.append(audit)
            continue
        audit.update({'matchedClose': 0, 'mismatchedRawClose': 0,
                      'missingRawClose': 0, 'missingAdjustedClose': 0,
                      'validStockDirection': 0, 'missingStockDirection': 0,
                      'flatStockDirection': 0})
        audit['studyStatus'] = 'COMPARABLE'
        selected = {}
        for code, limit_close in u_codes.items():
            bar = bars.get(day, {}).get(code)
            raw_close = bar[3] if bar and len(bar) >= 4 else None
            if not _price(raw_close):
                audit['missingRawClose'] += 1
                continue
            if abs(raw_close - limit_close) > 0.011:
                audit['mismatchedRawClose'] += 1
                continue
            if not _price(prices.get(day, {}).get(code)):
                audit['missingAdjustedClose'] += 1
                continue
            audit['matchedClose'] += 1
            if code not in previous or code not in current or not usable(previous[code]) or not usable(current[code]):
                audit['missingStockDirection'] += 1
                continue
            delta = current[code]['ratio'] - previous[code]['ratio']
            if delta == 0:
                audit['flatStockDirection'] += 1
                continue
            audit['validStockDirection'] += 1
            selected[code] = 'IMPROVING' if delta > 0 else 'WEAKENING'
        if not audit['matchedClose']:
            audit['studyStatus'] = 'NO_VALID_U_PRICE'
        elif not audit['validStockDirection']:
            audit['studyStatus'] = 'NO_VALID_STOCK_DIRECTION'
        coverage.append(audit)
        market_direction = 'IMPROVING' if market['deltaPP'] > 0 else 'WEAKENING'
        cohort = ('TRAIN' if position + max_horizon <= index[split] else
                  'EMBARGO' if position <= index[split] else 'OUT_OF_SAMPLE')
        valid_u = [code for code, limit_close in u_codes.items()
                   if (bar := bars.get(day, {}).get(code)) and len(bar) >= 4
                   and _price(bar[3]) and abs(bar[3] - limit_close) <= 0.011
                   and _price(prices.get(day, {}).get(code))]
        for horizon in horizons:
            target = days[position + horizon] if position + horizon < len(days) else None
            mature = target is not None and position + horizon <= index[asof]
            target_prices = prices.get(target, {}) if mature else {}
            baseline_returns = [_return(prices[day][code], target_prices.get(code))
                                for code in valid_u] if mature else []
            baseline_returns = [value for value in baseline_returns if value is not None]
            benchmark = statistics.mean(baseline_returns) if baseline_returns else None
            board_baselines = {}
            if mature:
                for board in BOARDS:
                    board_pool = [_return(prices[day][code], target_prices.get(code))
                                  for code in valid_u if board_of(code) == board]
                    board_pool = [value for value in board_pool if value is not None]
                    board_baselines[board] = statistics.mean(board_pool) if board_pool else None
            for code, stock_direction in selected.items():
                group = groups[(cohort, horizon, market_direction, stock_direction)]
                daily = group['daily'][day]
                group['events'] += 1
                daily['events'] += 1
                group['eventAmounts'].append(current[code]['amount'])
                if not mature:
                    group['pending'] += 1
                    continue
                entry_day = days[position + 1]
                entry_bar = bars.get(entry_day, {}).get(code)
                group['entryGateCounts'][entry_gate(entry_bar)] += 1
                entry_open = adjusted_open_reference(entry_bar, prices.get(entry_day, {}).get(code))
                if entry_open is not None:
                    gap = _return(prices[day][code], entry_open)
                    if gap is not None:
                        group['entryOpenGaps'].append(gap)
                outcome = _return(prices[day][code], target_prices.get(code))
                if outcome is None:
                    group['missingPrice'] += 1
                    continue
                # T+1 opening-to-close is a price path, not a same-day A-share exit.
                # Only horizons >= 2 receive a post-open endpoint comparison.
                if horizon >= 2 and entry_open is not None:
                    post_open = _return(entry_open, target_prices.get(code))
                    if post_open is not None:
                        group['postOpenReturns'].append(post_open)
                        group['pairedSignalReturns'].append(outcome)
                group['observed'] += 1
                daily['observed'] += 1
                group['returns'].append(outcome)
                daily['returns'].append(outcome)
                if benchmark is not None:
                    group['excesses'].append(outcome - benchmark)
                    daily['excesses'].append(outcome - benchmark)
                board = board_of(code)
                board_returns[(cohort, horizon, market_direction)][day][board, stock_direction].append(outcome)
                board_benchmark = board_baselines.get(board)
                if board_benchmark is not None:
                    group['boardExcesses'].append(outcome - board_benchmark)
                    daily['boardExcesses'].append(outcome - board_benchmark)
    summary = []
    for cohort in ('TRAIN', 'EMBARGO', 'OUT_OF_SAMPLE'):
        for horizon in horizons:
            for market_direction in MARKET_DIRECTIONS:
                for stock_direction in STOCK_DIRECTIONS:
                    group = groups[(cohort, horizon, market_direction, stock_direction)]
                    daily_rows = [{'day': day, 'events': row['events'], 'observed': row['observed'],
                                   'meanReturnPct': statistics.mean(row['returns']) if row['returns'] else None,
                                   'meanExcessPct': statistics.mean(row['excesses']) if row['excesses'] else None,
                                   'meanBoardExcessPct': (statistics.mean(row['boardExcesses'])
                                                          if row['boardExcesses'] else None)}
                                  for day, row in sorted(group['daily'].items())]
                    comparable = [row['meanExcessPct'] for row in daily_rows
                                  if row['meanExcessPct'] is not None]
                    board_comparable = [row['meanBoardExcessPct'] for row in daily_rows
                                        if row['meanBoardExcessPct'] is not None]
                    summary.append({'cohort': cohort, 'horizon': horizon,
                                    'marketDirection': market_direction,
                                    'stockDirection': stock_direction,
                                    'events': group['events'], 'observed': group['observed'],
                                    'pending': group['pending'], 'missingPrice': group['missingPrice'],
                                    'medianEventAmountYuan': (statistics.median(group['eventAmounts'])
                                                              if group['eventAmounts'] else None),
                                    'entryGateCounts': dict(sorted(group['entryGateCounts'].items())),
                                    'entryOpenObserved': len(group['entryOpenGaps']),
                                    'meanSignalToNextOpenPct': (statistics.mean(group['entryOpenGaps'])
                                                                if group['entryOpenGaps'] else None),
                                    'postOpenObserved': len(group['postOpenReturns']),
                                    'meanSignalToTargetPairedPct': (statistics.mean(group['pairedSignalReturns'])
                                                                    if group['pairedSignalReturns'] else None),
                                    'meanNextOpenToTargetPct': (statistics.mean(group['postOpenReturns'])
                                                                if group['postOpenReturns'] else None),
                                    'triggerDays': len(daily_rows), 'comparableDays': len(comparable),
                                    'meanReturnPct': statistics.mean(group['returns']) if group['returns'] else None,
                                    'meanExcessPct': statistics.mean(group['excesses']) if group['excesses'] else None,
                                    'equalDayMeanExcessPct': statistics.mean(comparable) if comparable else None,
                                    'equalDayMeanBoardExcessPct': (statistics.mean(board_comparable)
                                                                   if board_comparable else None),
                                    'boardBenchmarkDays': len(board_comparable),
                                    'leaveOneDayOutExcess': leave_one_day_out_excess(daily_rows),
                                    'daily': daily_rows})
    contrasts = []
    summary_by_key = {(row['cohort'], row['horizon'], row['marketDirection'], row['stockDirection']): row
                      for row in summary}
    for cohort in ('TRAIN', 'EMBARGO', 'OUT_OF_SAMPLE'):
        for horizon in horizons:
            for market_direction in MARKET_DIRECTIONS:
                stronger = summary_by_key[(cohort, horizon, market_direction, 'IMPROVING')]
                weaker = summary_by_key[(cohort, horizon, market_direction, 'WEAKENING')]
                improve_days = {row['day']: row for row in stronger['daily']
                                if row['meanReturnPct'] is not None}
                weaken_days = {row['day']: row for row in weaker['daily']
                               if row['meanReturnPct'] is not None}
                paired = [{'day': day,
                           'improvingN': improve_days[day]['observed'],
                           'weakeningN': weaken_days[day]['observed'],
                           'spreadPct': improve_days[day]['meanReturnPct'] - weaken_days[day]['meanReturnPct']}
                          for day in sorted(improve_days.keys() & weaken_days.keys())]
                contrasts.append({'cohort': cohort, 'horizon': horizon,
                                  'marketDirection': market_direction,
                                  'pairedDays': len(paired),
                                  'equalDayMeanSpreadPct': (statistics.mean(row['spreadPct'] for row in paired)
                                                            if paired else None),
                                  'leaveOneDayOutSpread': leave_one_day_out_excess(
                                      [{'meanExcessPct': row['spreadPct']} for row in paired]),
                                  'daily': paired})
    board_contrasts = []
    for cohort in ('TRAIN', 'EMBARGO', 'OUT_OF_SAMPLE'):
        for horizon in horizons:
            for market_direction in MARKET_DIRECTIONS:
                daily_board = board_returns[(cohort, horizon, market_direction)]
                board_pairs = []
                for day, buckets in sorted(daily_board.items()):
                    for board in BOARDS:
                        improving = buckets.get((board, 'IMPROVING'), [])
                        weakening = buckets.get((board, 'WEAKENING'), [])
                        if improving and weakening:
                            board_pairs.append({'day': day, 'board': board,
                                                'improvingN': len(improving), 'weakeningN': len(weakening),
                                                'spreadPct': statistics.mean(improving) - statistics.mean(weakening),
                                                'medianStockSpreadPct': (statistics.median(improving)
                                                                         - statistics.median(weakening))})
                for board in ('ALL', *BOARDS):
                    selected_pairs = [row for row in board_pairs if board == 'ALL' or row['board'] == board]
                    by_day = defaultdict(list)
                    median_by_day = defaultdict(list)
                    three_by_day = defaultdict(list)
                    for pair in selected_pairs:
                        by_day[pair['day']].append(pair['spreadPct'])
                        median_by_day[pair['day']].append(pair['medianStockSpreadPct'])
                        if pair['improvingN'] >= 3 and pair['weakeningN'] >= 3:
                            three_by_day[pair['day']].append(pair['spreadPct'])
                    daily = []
                    for day, spreads in sorted(by_day.items()):
                        components = [pair for pair in selected_pairs if pair['day'] == day]
                        daily.append({'day': day, 'pairedBoards': len(spreads),
                                      'improvingN': sum(pair['improvingN'] for pair in components),
                                      'weakeningN': sum(pair['weakeningN'] for pair in components),
                                      'spreadPct': statistics.mean(spreads),
                                      'medianStockSpreadPct': statistics.mean(
                                          pair['medianStockSpreadPct'] for pair in components),
                                      'boardDetails': components if board == 'ALL' else []})
                    spread_values = [row['spreadPct'] for row in daily]
                    for row in daily:
                        other = [value['spreadPct'] for value in daily if value['day'] != row['day']]
                        row['withoutDayMeanPct'] = statistics.mean(other) if other else None
                        row['influencePP'] = (statistics.mean(spread_values) - row['withoutDayMeanPct']
                                              if other else None)
                    median_stock_days = [statistics.mean(spreads) for _, spreads in sorted(median_by_day.items())]
                    three_days = [statistics.mean(spreads) for _, spreads in sorted(three_by_day.items()) if spreads]
                    board_contrasts.append({'cohort': cohort, 'horizon': horizon,
                                            'marketDirection': market_direction, 'board': board,
                                            'pairedBoardDays': len(selected_pairs), 'pairedDays': len(daily),
                                            'improvingN': sum(row['improvingN'] for row in selected_pairs),
                                            'weakeningN': sum(row['weakeningN'] for row in selected_pairs),
                                            'equalDayMeanSpreadPct': (statistics.mean(spread_values)
                                                                      if spread_values else None),
                                            'medianDailySpreadPct': (statistics.median(spread_values)
                                                                      if spread_values else None),
                                            'equalDayMedianStockSpreadPct': (statistics.mean(median_stock_days)
                                                                             if median_stock_days else None),
                                            'minThreeEachSideDays': len(three_days),
                                            'minThreeEachSideSpreadPct': (statistics.mean(three_days)
                                                                           if three_days else None),
                                            'leaveOneDayOutSpread': leave_one_day_out_excess(
                                                [{'meanExcessPct': row['spreadPct']} for row in daily]),
                                            'daily': daily})
    return {'method': 'PROVIDER_U_MARKET_STOCK_FLOW_2X2_DESCRIPTIVE',
            'start': start, 'end': end, 'asof': asof, 'split': split,
            'horizons': list(horizons), 'coverage': coverage, 'summary': summary,
            'pairedContrasts': contrasts, 'boardMatchedContrasts': board_contrasts,
            'definition': 'limit_list_d.limit=U 的非ST沪深A股；市场净额比在排除当日U股后的相邻日共同有效样本上计算',
            'limitations': ['只做正负变化四格，无参数搜索；平值和未知不硬分组',
                            '收盘后的 U、市场与个股方向仅在当日数据就绪后可见，后续收盘收益非买卖点或可成交收益',
                            '市场方向按日共享，市场改善／恶化组的跨日比较混有行情时期因素',
                            '同日U股均值只作同群价格基准；缺价格不补零，剔一范围不是显著性检验',
                            '板块内对照只控制代码板块与事件日期，未控制行业、市值、容量、封单或可成交性',
                            '中位数与每组至少3只只作预先固定的极值敏感性诊断；触发日成交额和次日日线门槛不等于可成交容量或订单成交',
                            '次日开盘仅为有量且OHLC有效日线的复权价格参考；后1日不展示开盘到当日收盘为交易收益，后3/5日也不代表真实成交、费用后收益',
                            '本地涨停列表与复权因子无历史采集时间冻结，严格 PIT 未验证']}
