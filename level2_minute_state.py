"""Observed minute-close drawdown for a continuous trading-day window.

Minute bars are snapshot-derived, not an executable tick path. Per-day summaries
are cached by source identity; missing or invalid days never join across gaps.
"""
import csv
import hashlib
import json
import math
from pathlib import Path

import duckdb

from level2_intraday import minute_directory, minute_slots


def _stamp(path):
    path = Path(path)
    if not path.is_file():
        return [str(path), 'missing']
    stat = path.stat()
    return [str(path.resolve()), stat.st_size, stat.st_mtime_ns]


def sources(root, factor_root, day):
    minute = minute_directory(root) / f'{day}.parquet'
    factor = Path(factor_root) / f'{day}_stk_factor_pro.csv'
    audit = root / '_conversion_audit' / day
    manifest = audit / 'manifest.json'
    committed = audit / 'COMMITTED'
    status = 'MISSING_MINUTE' if not minute.is_file() else 'MISSING_FACTOR' if not factor.is_file() else 'UNCOMMITTED'
    if minute.is_file() and factor.is_file() and manifest.is_file() and committed.is_file():
        try:
            if json.loads(manifest.read_text()).get('commit_state') == 'COMMITTED':
                status = 'READY'
        except (OSError, ValueError):
            pass
    identity = hashlib.sha256(json.dumps([_stamp(p) for p in (minute, factor, manifest, committed)] +
                                         [_stamp(Path(__file__)), _stamp(Path(__file__).with_name('level2_intraday.py'))]).encode()).hexdigest()
    return {'day': day, 'status': status, 'minuteFile': str(minute) if minute.is_file() else None,
            'factorFile': str(factor) if factor.is_file() else None, 'identity': identity}


def _factors(path, day, wanted):
    factors = {}
    invalid = set()
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'ts_code', 'trade_date', 'adj_factor'}.issubset(reader.fieldnames or []):
            raise ValueError('复权因子字段缺失')
        for row in reader:
            code = row['ts_code']
            if code not in wanted or row['trade_date'] != day:
                continue
            if code in factors:
                invalid.add(code)
                continue
            try:
                value = float(row['adj_factor'])
            except (TypeError, ValueError):
                value = None
            factors[code] = value if value is not None and math.isfinite(value) and value > 0 else None
    return factors, invalid


def read_day(root, factor_root, day, wanted, cache):
    """Return per-stock ordered traded-minute summaries, never fill absent bars."""
    source = sources(root, factor_root, day)
    if source['status'] != 'READY':
        return {}, source
    cache = Path(cache)
    target = cache / f'{day}-{source["identity"]}.json'
    if target.is_file():
        data = json.loads(target.read_text())
        if data.get('identity') == source['identity'] and set(data.get('codes', [])) == set(wanted):
            return data['stocks'], source
    factors, bad_factors = _factors(source['factorFile'], day, wanted)
    bare = {code[:6]: code for code in wanted}
    slots = {int(label.replace(':', '')): label for label in minute_slots()}
    stocks = {}
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute('SET threads=2')
    try:
        cursor = con.execute('''SELECT SecuCode, TradingDay, Time, ClosePrice, Volume
            FROM read_parquet(?) ORDER BY SecuCode, Time''', [source['minuteFile']])
        while batch := cursor.fetchmany(50000):
            for raw_code, raw_day, raw_time, raw_close, raw_volume in batch:
                code = bare.get(raw_code)
                if code is None:
                    continue
                item = stocks.setdefault(code, {'status': 'OBSERVED', 'presentMinutes': 0,
                    'tradedMinutes': 0, 'minClose': None, 'maxClose': None,
                    'minTime': None, 'maxTime': None, 'withinPct': 0.0,
                    'withinPeakTime': None, 'withinTroughTime': None, '_lastTime': -1,
                    '_peak': None, '_peakTime': None})
                if item['status'] == 'INVALID_MINUTE':
                    continue
                if (raw_day != int(day) or raw_time not in slots or raw_time <= item['_lastTime'] or
                    raw_volume is None or not math.isfinite(raw_volume) or raw_volume < 0):
                    item['status'] = 'INVALID_MINUTE'
                    continue
                item['_lastTime'] = raw_time
                item['presentMinutes'] += 1
                if raw_volume == 0:
                    continue
                factor = factors.get(code)
                if (code in bad_factors or factor is None or raw_close is None or
                    not math.isfinite(raw_close) or raw_close <= 0):
                    item['status'] = 'INVALID_MINUTE' if factor is not None and code not in bad_factors else 'MISSING_FACTOR'
                    continue
                value = float(raw_close) * factor
                if not math.isfinite(value) or value <= 0:
                    item['status'] = 'INVALID_MINUTE'
                    continue
                label = slots[raw_time]
                item['tradedMinutes'] += 1
                if item['minClose'] is None or value < item['minClose']:
                    item['minClose'], item['minTime'] = value, label
                if item['maxClose'] is None or value > item['maxClose']:
                    item['maxClose'], item['maxTime'] = value, label
                if item['_peak'] is None or value > item['_peak']:
                    item['_peak'], item['_peakTime'] = value, label
                pct = 100 * (value / item['_peak'] - 1)
                if pct < item['withinPct']:
                    item['withinPct'] = pct
                    item['withinPeakTime'], item['withinTroughTime'] = item['_peakTime'], label
    finally:
        con.close()
    for code in wanted:
        item = stocks.setdefault(code, {'status': 'NO_MINUTE_ROWS', 'presentMinutes': 0, 'tradedMinutes': 0})
        if item['status'] == 'OBSERVED' and not item['tradedMinutes']:
            item['status'] = 'NO_TRADED_MINUTES'
        if factors.get(code) is None or code in bad_factors:
            item['status'] = 'MISSING_FACTOR'
        for key in ('_lastTime', '_peak', '_peakTime'):
            item.pop(key, None)
    if sources(root, factor_root, day)['identity'] != source['identity']:
        raise ValueError('分钟或复权来源在计算期间变化')
    cache.mkdir(exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'identity': source['identity'], 'codes': sorted(wanted), 'stocks': stocks},
                                    ensure_ascii=False, allow_nan=False, separators=(',', ':')))
    temporary.replace(target)
    return stocks, source


def safe_read_day(root, factor_root, day, wanted, cache):
    """A bad minute source must not suppress otherwise valid daily flow facts."""
    try:
        return read_day(root, factor_root, day, wanted, cache)
    except (duckdb.Error, OSError, ValueError, TypeError) as exc:
        source = sources(root, factor_root, day)
        source['status'] = 'SOURCE_ERROR'
        source['reason'] = type(exc).__name__
        return {}, source


def combine(dates, baseline, daily, source_statuses):
    """Compose one stock's ordered daily summaries with the pre-window adjusted close."""
    result = {'status': 'OBSERVED', 'valuePct': None, 'peakTime': None, 'troughTime': None,
              'presentMinutes': 0, 'tradedMinutes': 0, 'expectedMinutes': 240 * len(dates),
              'missingDays': []}
    if baseline is None or not math.isfinite(baseline) or baseline <= 0:
        result['status'] = 'MISSING_BASELINE'
        return result
    peak, peak_time = baseline, '窗口前收盘'
    result['valuePct'] = 0.0
    for day in dates:
        row = daily.get(day)
        if source_statuses.get(day) != 'READY' or not row or row.get('status') != 'OBSERVED':
            result['missingDays'].append(day)
            continue
        result['presentMinutes'] += row['presentMinutes']
        result['tradedMinutes'] += row['tradedMinutes']
        cross = 100 * (row['minClose'] / peak - 1)
        if cross < result['valuePct']:
            result['valuePct'] = cross
            result['peakTime'] = peak_time
            result['troughTime'] = f'{day} {row["minTime"]}'
        if row['withinPct'] < result['valuePct']:
            result['valuePct'] = row['withinPct']
            result['peakTime'] = f'{day} {row["withinPeakTime"]}'
            result['troughTime'] = f'{day} {row["withinTroughTime"]}'
        if row['maxClose'] > peak:
            peak, peak_time = row['maxClose'], f'{day} {row["maxTime"]}'
    if result['missingDays']:
        result['status'] = 'INCOMPLETE_MINUTES'
        result['valuePct'] = result['peakTime'] = result['troughTime'] = None
    return result
