"""Regular-session best-quote path; observations are not reconstructed order queues."""
import math
from statistics import median


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
    """rows: day/time/bid1/ask1[/bid_qty1/ask_qty1]; prices scaled by 10000."""
    observed = []
    bad_day = 0
    for row in rows:
        trade_day, raw_time, bid, ask = row[:4]
        bid_qty, ask_qty = row[4:6] if len(row) >= 6 else (None, None)
        if str(trade_day) != day:
            bad_day += 1
            continue
        try:
            time = int(raw_time)
        except (TypeError, ValueError):
            continue
        if any(in_segment(time, start, end, inclusive) for _, start, end, inclusive in SEGMENTS):
            observed.append((time, bid, ask, bid_qty, ask_qty))
    if bad_day:
        return {'status': 'INVALID_DATE', 'segments': [], 'badDateRows': bad_day,
                'method': '买卖一档中间价，不是成交价、可成交收益或盘口队列恢复'}
    if len({row[0] for row in observed}) != len(observed):
        return {'status': 'DUPLICATE_TIME', 'segments': [], 'badDateRows': 0,
                'method': '同一股票时间戳重复，未任意选取快照计算中间价'}
    segments = []
    for label, start, end, inclusive in SEGMENTS:
        segment = [row for row in observed if in_segment(row[0], start, end, inclusive)]
        valid = []
        spreads = []
        imbalances = []
        same_bid_count = 0
        bid_rise_count = 0
        previous_depth = None
        for time, bid, ask, bid_qty, ask_qty in sorted(segment, key=lambda item: item[0]):
            try:
                b, a = float(bid), float(ask)
            except (TypeError, ValueError):
                previous_depth = None
                continue
            if math.isfinite(b) and math.isfinite(a) and b > 0 and a >= b:
                valid.append((time, (b + a) / 20000))
                spreads.append(20000 * (a - b) / (a + b))
                try:
                    buy_qty, sell_qty = float(bid_qty), float(ask_qty)
                except (TypeError, ValueError):
                    previous_depth = None
                    continue
                if (not math.isfinite(buy_qty) or not math.isfinite(sell_qty) or
                        buy_qty < 0 or sell_qty < 0 or buy_qty + sell_qty <= 0):
                    previous_depth = None
                    continue
                imbalances.append(100 * (buy_qty - sell_qty) / (buy_qty + sell_qty))
                if previous_depth is not None and previous_depth[0] == b:
                    same_bid_count += 1
                    bid_rise_count += buy_qty > previous_depth[1]
                previous_depth = (b, buy_qty)
            else:
                previous_depth = None
        valid.sort(key=lambda item: item[0])
        row = {'s': label, 'observed': len(segment), 'valid': len(valid),
               'firstTime': valid[0][0] if valid else None,
               'lastTime': valid[-1][0] if valid else None,
               'firstMid': valid[0][1] if valid else None,
               'lastMid': valid[-1][1] if valid else None,
               'midChangePct': None, 'minMid': None, 'recoveryPct': None,
               'medianSpreadBps': median(spreads) if spreads else None,
               'medianTopImbalancePct': median(imbalances) if imbalances else None,
               'depthValid': len(imbalances),
               'sameBidComparable': same_bid_count,
               'sameBidDisplayedRise': bid_rise_count}
        if len(valid) >= 2:
            minimum = min(value for _, value in valid)
            row.update(midChangePct=100 * (valid[-1][1] / valid[0][1] - 1),
                       minMid=minimum, recoveryPct=100 * (valid[-1][1] / minimum - 1))
        segments.append(row)
    return {'status': 'AVAILABLE' if any(item['midChangePct'] is not None for item in segments) else 'NO_COMPARABLE_QUOTES',
            'segments': segments, 'badDateRows': 0,
            'method': '仅连续竞价有效买卖一档快照；中间价、价差和一档量差分开观察。买一同价显示量上升只比较相邻有效快照，不解码新增或撤单，不重建队列，也不归因于主动成交'}
