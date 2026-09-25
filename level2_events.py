"""Point-in-time, daily active-flow observations; no trading interpretation."""
import math


RULES = {
    'SELL_EASING': ('净额比负值收敛', '连续两日仍为净卖出，后日净额比高于前日', '次日净额比不再改善则失效；转为净买入则结束'),
    'SELL_WORSENING': ('净额比负值扩大', '连续两日仍为净卖出，后日净额比低于前日', '次日净额比不再恶化则失效；转为净买入则结束'),
    'SELL_TO_BUY': ('净卖出转净买入', '前日净额比严格小于零，后日严格大于零', '后续净额比不再为正则失效'),
    'BUY_TO_SELL': ('净买入转净卖出', '前日净额比严格大于零，后日严格小于零', '后续净额比不再为负则失效'),
}


def usable(row):
    if not isinstance(row, dict):
        return False
    values = (row.get('ratio'), row.get('amount'), row.get('net'))
    return (all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values)
            and row['amount'] > 0 and row.get('unknown', 0) == 0)


def kind(previous, current):
    a, b = previous['ratio'], current['ratio']
    if a < 0 < b:
        return 'SELL_TO_BUY'
    if a > 0 > b:
        return 'BUY_TO_SELL'
    if a < b < 0:
        return 'SELL_EASING'
    if b < a < 0:
        return 'SELL_WORSENING'
    return None


def lifecycle(rule, history, index):
    """Only observations after the trigger may update its as-of-current status."""
    status, end_day = 'ACTIVE', None
    previous = history[index]
    for current in history[index + 1:]:
        if not usable(current):
            return 'UNKNOWN', current['day']
        p, c = previous['ratio'], current['ratio']
        if rule == 'SELL_EASING':
            status = 'RESOLVED' if c >= 0 else 'INVALIDATED' if c <= p else 'ACTIVE'
        elif rule == 'SELL_WORSENING':
            status = 'RESOLVED' if c >= 0 else 'INVALIDATED' if c >= p else 'ACTIVE'
        elif rule == 'SELL_TO_BUY':
            status = 'ACTIVE' if c > 0 else 'INVALIDATED'
        else:
            status = 'ACTIVE' if c < 0 else 'INVALIDATED'
        if status != 'ACTIVE':
            end_day = current['day']
            break
        previous = current
    return status, end_day


def observe(history):
    """Use only adjacent observations inside the applied window; no gap crossing."""
    events = []
    for index in range(1, len(history)):
        previous, current = history[index - 1:index + 1]
        if not (usable(previous) and usable(current)):
            continue
        rule = kind(previous, current)
        if not rule:
            continue
        status, end_day = lifecycle(rule, history, index)
        name, trigger, invalidation = RULES[rule]
        events.append({'id': f"{current['day']}:{rule}", 'kind': rule, 'name': name,
                       'triggerDay': current['day'], 'previousDay': previous['day'],
                       'firstRecognizableAt': f"{current['day']} 日级数据就绪后",
                       'rule': trigger, 'invalidation': invalidation,
                       'evidence': {'previousRatio': previous['ratio'], 'currentRatio': current['ratio'],
                                    'deltaPP': current['ratio'] - previous['ratio']},
                       'status': status, 'statusAsOf': history[-1]['day'], 'endDay': end_day,
                       'source': '日级主动成交方向；非盘中守位或补单证据'})
    return events
