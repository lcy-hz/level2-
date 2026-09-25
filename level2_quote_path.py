"""Regular-session best-quote path; observations are not reconstructed order queues."""
import math


SEGMENTS = [
    ('09:30–10:00', 93000000, 100000000, False),
    ('10:00–10:30', 100000000, 103000000, False),
    ('10:30–11:30', 103000000, 113000000, True),
    ('13:00–14:00', 130000000, 140000000, False),
    ('14:00–收盘', 140000000, 150000000, True),
]


def in_segment(time, start, end, inclusive):
    return start <= time and (time <= end if inclusive else time < end)


def quote_path(rows, day):
    """rows: (trade_day, raw_time, raw_bid1, raw_ask1), prices scaled by 10000."""
    observed = []
    bad_day = 0
    for trade_day, raw_time, bid, ask in rows:
        if str(trade_day) != day:
            bad_day += 1
            continue
        try:
            time = int(raw_time)
        except (TypeError, ValueError):
            continue
        if any(in_segment(time, start, end, inclusive) for _, start, end, inclusive in SEGMENTS):
            observed.append((time, bid, ask))
    if bad_day:
        return {'status': 'INVALID_DATE', 'segments': [], 'badDateRows': bad_day,
                'method': '买卖一档中间价，不是成交价、可成交收益或盘口队列恢复'}
    if len({time for time, _, _ in observed}) != len(observed):
        return {'status': 'DUPLICATE_TIME', 'segments': [], 'badDateRows': 0,
                'method': '同一股票时间戳重复，未任意选取快照计算中间价'}
    segments = []
    for label, start, end, inclusive in SEGMENTS:
        segment = [(time, bid, ask) for time, bid, ask in observed
                   if in_segment(time, start, end, inclusive)]
        valid = []
        for time, bid, ask in segment:
            try:
                b, a = float(bid), float(ask)
            except (TypeError, ValueError):
                continue
            if math.isfinite(b) and math.isfinite(a) and b > 0 and a >= b:
                valid.append((time, (b + a) / 20000))
        valid.sort(key=lambda item: item[0])
        row = {'s': label, 'observed': len(segment), 'valid': len(valid),
               'firstTime': valid[0][0] if valid else None,
               'lastTime': valid[-1][0] if valid else None,
               'firstMid': valid[0][1] if valid else None,
               'lastMid': valid[-1][1] if valid else None,
               'midChangePct': None, 'minMid': None, 'recoveryPct': None}
        if len(valid) >= 2:
            minimum = min(value for _, value in valid)
            row.update(midChangePct=100 * (valid[-1][1] / valid[0][1] - 1),
                       minMid=minimum, recoveryPct=100 * (valid[-1][1] / minimum - 1))
        segments.append(row)
    return {'status': 'AVAILABLE' if any(item['midChangePct'] is not None for item in segments) else 'NO_COMPARABLE_QUOTES',
            'segments': segments, 'badDateRows': 0,
            'method': '仅连续竞价有效买卖一档中间价；首末有效快照变化与区间最低中间价至末值恢复；不重建队列，不归因于主动成交'}
