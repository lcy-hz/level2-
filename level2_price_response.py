"""Descriptive trade-flow/quote co-movement; never a causal impact estimate."""
from bisect import bisect_left, bisect_right
from statistics import median
import math

from level2_quote_path import clock_millis


WINDOWS = (
    ('09:30–10:00', 93000000, 100000000),
    ('10:00–10:30', 100000000, 103000000),
    ('10:30–11:30', 103000000, 113000001),
    ('13:00–14:00', 130000000, 140000000),
    ('14:00–14:57', 140000000, 145700000),
)
MAX_GAP_MS = 10_000


def _midpoint(row):
    try:
        bid, ask = float(row[2]), float(row[3])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (bid, ask)) or bid <= 0 or ask < bid:
        return None
    return (bid + ask) / 20000


def price_response(trades, quotes, day):
    """Use only trades strictly between adjacent valid, timely quote observations.

    trades: (native HHMMSSmmm, yuan price, shares, B/S/unknown side).
    quotes: source rows (day, native time, bid1, ask1, ...), raw prices /10000.
    Exact timestamp ties are excluded because feed ordering is unavailable.
    """
    ticks = []
    for time, price, qty, side in trades:
        moment = clock_millis(time) if isinstance(time, int) else None
        if moment is None:
            return {'status': 'INVALID_TRADE_CLOCK', 'segments': []}
        if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (price, qty)):
            return {'status': 'INVALID_TRADE_PRINT', 'segments': []}
        ticks.append((moment, price * qty, side))
    ticks.sort(key=lambda item: item[0])
    moments = [item[0] for item in ticks]
    signed = [0.0]
    amount = [0.0]
    unknown = [0.0]
    for _, value, side in ticks:
        amount.append(amount[-1] + value)
        signed.append(signed[-1] + (value if side == 'B' else -value if side == 'S' else 0))
        unknown.append(unknown[-1] + (value if side not in ('B', 'S') else 0))

    observations = []
    for row in quotes:
        if str(row[0]) != day:
            return {'status': 'INVALID_QUOTE_DATE', 'segments': []}
        try:
            raw_time = int(row[1])
        except (TypeError, ValueError):
            return {'status': 'INVALID_QUOTE_CLOCK', 'segments': []}
        if not any(start <= raw_time < end for _, start, end in WINDOWS):
            continue
        moment = clock_millis(raw_time)
        if moment is None:
            return {'status': 'INVALID_QUOTE_CLOCK', 'segments': []}
        observations.append((raw_time, moment, _midpoint(row)))
    observations.sort(key=lambda item: item[1])
    if len({item[1] for item in observations}) != len(observations):
        return {'status': 'DUPLICATE_QUOTE_TIME', 'segments': []}

    segments = []
    for label, start, end in WINDOWS:
        rows = [item for item in observations if start <= item[0] < end]
        pairs = []
        gap_pairs = invalid_quote_pairs = unknown_pairs = zero_flow_pairs = 0
        aligned = []
        next_aligned = []
        for previous, current in zip(rows, rows[1:]):
            gap = current[1] - previous[1]
            if gap <= 0 or gap > MAX_GAP_MS:
                gap_pairs += 1
                pairs.append(None)
                continue
            if previous[2] is None or current[2] is None:
                invalid_quote_pairs += 1
                pairs.append(None)
                continue
            left, right = bisect_right(moments, previous[1]), bisect_left(moments, current[1])
            if unknown[right] - unknown[left] > 1e-7:
                unknown_pairs += 1
                pairs.append(None)
                continue
            flow = signed[right] - signed[left]
            traded = amount[right] - amount[left]
            if traded <= 1e-7 or abs(flow) <= max(1e-7, traded * 1e-10):
                zero_flow_pairs += 1
                pairs.append(None)
                continue
            direction = 1 if flow > 0 else -1
            response = direction * 10000 * (current[2] / previous[2] - 1)
            aligned.append(response)
            pairs.append((direction, current[2], current[1]))
        for current, following in zip(pairs, rows[2:]):
            if current is None or following[2] is None:
                continue
            if 0 < following[1] - current[2] <= MAX_GAP_MS:
                next_aligned.append(current[0] * 10000 * (following[2] / current[1] - 1))
        segments.append({'s': label, 'quoteRows': len(rows), 'adjacentPairs': max(0, len(rows) - 1),
                         'gapPairs': gap_pairs, 'invalidQuotePairs': invalid_quote_pairs,
                         'unknownFlowPairs': unknown_pairs, 'zeroFlowPairs': zero_flow_pairs,
                         'flowPairs': len(aligned), 'medianAlignedBps': median(aligned) if aligned else None,
                         'meanAlignedBps': sum(aligned) / len(aligned) if aligned else None,
                         'positiveAlignedSharePct': 100 * sum(value > 0 for value in aligned) / len(aligned) if aligned else None,
                         'zeroMovePairs': sum(abs(value) < 1e-9 for value in aligned),
                         'nextPairs': len(next_aligned),
                         'medianNextAlignedBps': median(next_aligned) if next_aligned else None,
                         'meanNextAlignedBps': sum(next_aligned) / len(next_aligned) if next_aligned else None})
    return {'status': 'AVAILABLE' if any(item['flowPairs'] for item in segments) else 'NO_COMPARABLE_PAIRS',
            'maxGapMs': MAX_GAP_MS, 'segments': segments,
            'method': '相邻有效快照≤10秒；仅取严格落在两次快照之间、方向完整且净额非零的成交，排除端点同刻成交；14:57后不纳入。方向对齐的同区间及后一快照中间价变化仅为相关性描述，非因果价格冲击。'}
