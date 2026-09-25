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


def ten_level_metrics(row):
    """Visible ladder metrics; distance is measured from each best quote.

    The scale is the current spread, or the nearest valid level step for a
    locked book.  A displayed quantity at distance d receives 1/(1+d/scale).
    This is a descriptive weighting, not calibrated executable depth.
    """
    if len(row) != 42:
        return None
    bid_prices = [row[2], *row[6:15]]
    ask_prices = [row[3], *row[15:24]]
    bid_qtys = [row[4], *row[24:33]]
    ask_qtys = [row[5], *row[33:42]]
    try:
        bp = [float(x) for x in bid_prices]
        ap = [float(x) for x in ask_prices]
        bq = [float(x) for x in bid_qtys]
        aq = [float(x) for x in ask_qtys]
    except (TypeError, ValueError):
        return None
    if (not all(math.isfinite(x) and x > 0 for x in bp + ap) or
            not all(math.isfinite(x) and x >= 0 for x in bq + aq) or
            bp[0] > ap[0] or
            any(bp[i] <= bp[i + 1] or ap[i] >= ap[i + 1] for i in range(9))):
        return None
    buy, sell = sum(bq), sum(aq)
    if buy + sell <= 0:
        return None
    scale = ap[0] - bp[0] if ap[0] > bp[0] else min(bp[0] - bp[1], ap[1] - ap[0])
    weighted_buy = sum(q / (1 + (bp[0] - p) / scale) for p, q in zip(bp, bq))
    weighted_sell = sum(q / (1 + (p - ap[0]) / scale) for p, q in zip(ap, aq))
    return {'imbalancePct': 100 * (buy - sell) / (buy + sell),
            'weightedImbalancePct': 100 * (weighted_buy - weighted_sell) / (weighted_buy + weighted_sell)}


def ten_level_imbalance(row):
    """Compatibility accessor for the unweighted visible ten-level imbalance."""
    metrics = ten_level_metrics(row)
    return metrics['imbalancePct'] if metrics else None


def microprice_premium_bp(bid, ask, bid_qty, ask_qty):
    """Top-of-book microprice minus midpoint, in basis points."""
    if (not all(math.isfinite(v) for v in (bid, ask, bid_qty, ask_qty)) or
            bid <= 0 or ask < bid or bid_qty < 0 or ask_qty < 0 or bid_qty + ask_qty <= 0):
        return None
    return 10000 * (ask - bid) * (bid_qty - ask_qty) / ((ask + bid) * (bid_qty + ask_qty))


def quote_path(rows, day):
    """rows: day/time/bid1/ask1/qty1 pair[/9 more levels]; prices scaled by 10000."""
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
            observed.append((time, bid, ask, bid_qty, ask_qty, ten_level_metrics(row)))
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
        ten_imbalances = []
        weighted_imbalances = []
        microprice_premiums = []
        same_bid_count = 0
        bid_rise_count = 0
        previous_depth = None
        for time, bid, ask, bid_qty, ask_qty, ten_metrics in sorted(segment, key=lambda item: item[0]):
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
                microprice_premiums.append(microprice_premium_bp(b, a, buy_qty, sell_qty))
                if ten_metrics is not None:
                    ten_imbalances.append(ten_metrics['imbalancePct'])
                    weighted_imbalances.append(ten_metrics['weightedImbalancePct'])
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
               'medianTenLevelImbalancePct': median(ten_imbalances) if ten_imbalances else None,
               'medianWeightedTenImbalancePct': median(weighted_imbalances) if weighted_imbalances else None,
               'medianMicropricePremiumBps': median(microprice_premiums) if microprice_premiums else None,
               'tenLevelValid': len(ten_imbalances),
               'sameBidComparable': same_bid_count,
               'sameBidDisplayedRise': bid_rise_count}
        if len(valid) >= 2:
            minimum = min(value for _, value in valid)
            row.update(midChangePct=100 * (valid[-1][1] / valid[0][1] - 1),
                       minMid=minimum, recoveryPct=100 * (valid[-1][1] / minimum - 1))
        segments.append(row)
    return {'status': 'AVAILABLE' if any(item['midChangePct'] is not None for item in segments) else 'NO_COMPARABLE_QUOTES',
            'segments': segments, 'badDateRows': 0,
            'method': '仅连续竞价有效买卖档快照；微价格相对中间价偏离按买卖一档价量交叉加权，单位 bp。十档距离权重为1/(1+离最优价距离/尺度)，尺度为买一卖一价差，锁定盘口时取最近档位价差；均为显示量描述，不代表可成交深度。买一同价显示量上升只比较相邻有效快照，不解码新增或撤单，不重建队列，也不归因于主动成交'}
