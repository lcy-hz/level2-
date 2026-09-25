"""Conservative, on-demand drawdown of ordered regular-session trade prints.

This is an observed transaction-price path, not an executable exit path.  We
do not infer an ordering when the native trade sequence is absent or invalid.
"""
import math


def _label(value):
    digits = f'{value:09d}'
    return f'{digits[:2]}:{digits[2:4]}:{digits[4:6]}.{digits[6:]}'


def _valid_time(value):
    if value is None or value < 0 or value > 235959999:
        return False
    digits = f'{value:09d}'
    return int(digits[:2]) < 24 and int(digits[2:4]) < 60 and int(digits[4:6]) < 60


def observe_prints(rows):
    result = {'status': 'NO_REGULAR_PRINTS', 'valuePct': None, 'peakTime': None,
              'troughTime': None, 'printCount': 0, 'ordering': '成交编号升序；时间非降'}
    previous_id = previous_time = peak = peak_time = None
    for trade_id, time, price_raw, quantity in rows:
        if trade_id is None or trade_id <= 0 or (previous_id is not None and trade_id <= previous_id):
            result['status'] = 'INVALID_SEQUENCE'
            result['valuePct'] = result['peakTime'] = result['troughTime'] = None
            return result
        if not _valid_time(time) or (previous_time is not None and time < previous_time):
            result['status'] = 'INVALID_TIME_ORDER'
            result['valuePct'] = result['peakTime'] = result['troughTime'] = None
            return result
        previous_id, previous_time = trade_id, time
        if not (93000000 <= time <= 113000000 or 130000000 <= time <= 150000000):
            continue
        if (price_raw is None or quantity is None or not math.isfinite(price_raw) or
                not math.isfinite(quantity) or price_raw <= 0 or quantity <= 0):
            result['status'] = 'INVALID_PRINT'
            result['valuePct'] = result['peakTime'] = result['troughTime'] = None
            return result
        price = price_raw / 10000
        result['printCount'] += 1
        if peak is None or price > peak:
            peak, peak_time = price, _label(time)
        drawdown = 100 * (price / peak - 1)
        if result['valuePct'] is None or drawdown < result['valuePct']:
            result['valuePct'] = drawdown
            result['peakTime'], result['troughTime'] = peak_time, _label(time)
    if result['printCount']:
        result['status'] = 'OBSERVED'
    return result


def trade_print_drawdown(con, path, code, day):
    columns = {row[0] for row in con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(path)]).fetchall()}
    if '成交编号' not in columns:
        return {'status': 'MISSING_SEQUENCE', 'valuePct': None, 'peakTime': None,
                'troughTime': None, 'printCount': 0, 'ordering': '成交编号缺失'}
    cursor = con.execute('''SELECT TRY_CAST("成交编号" AS BIGINT),
        TRY_CAST("时间" AS BIGINT), TRY_CAST("成交价格" AS DOUBLE),
        TRY_CAST("成交数量" AS DOUBLE)
        FROM read_parquet(?) WHERE "万得代码"=? AND CAST("自然日" AS VARCHAR)=?
          AND COALESCE("BS标志",'')<>'C'
          AND TRY_CAST("成交价格" AS DOUBLE)>0 AND isfinite(TRY_CAST("成交价格" AS DOUBLE))
          AND TRY_CAST("成交数量" AS DOUBLE)>0 AND isfinite(TRY_CAST("成交数量" AS DOUBLE))
        ORDER BY 1 NULLS FIRST''', [str(path), code, day])
    def batches():
        while batch := cursor.fetchmany(50000):
            yield from batch
    return observe_prints(batches())
