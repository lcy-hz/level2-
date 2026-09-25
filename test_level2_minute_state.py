import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from level2_minute_state import combine, read_day, safe_read_day, sources


class WindowMinuteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / 'level2'
        self.factor_root = base / 'factor'
        self.factor_root.mkdir()
        self.cache = base / 'cache'
        self.codes = {'000001.SZ', '000002.SZ'}

    def tearDown(self):
        self.temp.cleanup()

    def day(self, day, rows, factor=1):
        audit = self.root / '_conversion_audit' / day
        audit.mkdir(parents=True)
        (audit / 'COMMITTED').write_text('ok')
        (audit / 'manifest.json').write_text(json.dumps({'commit_state': 'COMMITTED'}))
        minute = self.root.parent / 'stock_minute' / f'{day}.parquet'
        minute.parent.mkdir(exist_ok=True)
        con = duckdb.connect()
        con.execute('CREATE TABLE bars(SecuCode VARCHAR,TradingDay BIGINT,Time BIGINT,ClosePrice DOUBLE,Volume DOUBLE)')
        con.executemany('INSERT INTO bars VALUES (?,?,?,?,?)', rows)
        con.execute('COPY bars TO ? (FORMAT PARQUET)', [str(minute)])
        con.close()
        (self.factor_root / f'{day}_stk_factor_pro.csv').write_text(
            f'ts_code,trade_date,adj_factor\n000001.SZ,{day},{factor}\n000002.SZ,{day},{factor}\n')

    def test_cross_day_peak_trough_and_source_cache(self):
        self.day('20260921', [('000001', 20260921, 931, 11, 2), ('000001', 20260921, 932, 9, 2),
                              ('000002', 20260921, 931, 10, 0)])
        self.day('20260922', [('000001', 20260922, 931, 6, 2), ('000001', 20260922, 932, 4, 2)], factor=2)
        a, src_a = read_day(self.root, self.factor_root, '20260921', self.codes, self.cache)
        b, src_b = read_day(self.root, self.factor_root, '20260922', self.codes, self.cache)
        self.assertEqual(src_a['status'], 'READY')
        self.assertEqual(a['000002.SZ']['status'], 'NO_TRADED_MINUTES')
        self.assertEqual(b['000001.SZ']['minClose'], 8)
        dates = ['20260921', '20260922']
        result = combine(dates, 10, {'20260921': a['000001.SZ'], '20260922': b['000001.SZ']},
                         {src_a['day']: src_a['status'], src_b['day']: src_b['status']})
        self.assertEqual(result['status'], 'OBSERVED')
        self.assertAlmostEqual(result['valuePct'], -100 / 3)
        self.assertEqual((result['peakTime'], result['troughTime']), ('20260922 09:31', '20260922 09:32'))
        self.assertEqual((result['presentMinutes'], result['tradedMinutes'], result['expectedMinutes']), (4, 4, 480))
        cached, _ = read_day(self.root, self.factor_root, '20260922', self.codes, self.cache)
        self.assertEqual(cached, b)
        missing = combine(dates, 10, {'20260921': a['000001.SZ']},
                          {'20260921': 'READY', '20260922': 'MISSING_MINUTE'})
        self.assertEqual(missing['status'], 'INCOMPLETE_MINUTES')
        self.assertIsNone(missing['valuePct'])
        self.assertEqual(missing['missingDays'], ['20260922'])
        self.assertEqual(combine(dates, None, {}, {})['status'], 'MISSING_BASELINE')

    def test_bad_time_duplicate_and_missing_factor_do_not_become_zero(self):
        self.day('20260922', [('000001', 20260922, 931, 11, 2), ('000001', 20260922, 931, 9, 2),
                              ('000002', 20260922, 932, 10, 2)])
        factor = self.factor_root / '20260922_stk_factor_pro.csv'
        factor.write_text('ts_code,trade_date,adj_factor\n000001.SZ,20260922,1\n')
        rows, source = read_day(self.root, self.factor_root, '20260922', self.codes, self.cache)
        self.assertEqual(rows['000001.SZ']['status'], 'INVALID_MINUTE')
        self.assertEqual(rows['000002.SZ']['status'], 'MISSING_FACTOR')
        self.assertIsNone(combine(['20260922'], 10, {'20260922': rows['000001.SZ']},
                                  {'20260922': source['status']})['valuePct'])
        old = source['identity']
        factor.write_text('ts_code,trade_date,adj_factor\n000001.SZ,20260922,2\n000002.SZ,20260922,2\n')
        self.assertNotEqual(old, sources(self.root, self.factor_root, '20260922')['identity'])

    def test_cross_day_drawdown_uses_earlier_peak(self):
        first = {'status': 'OBSERVED', 'minClose': 11, 'maxClose': 12,
                 'minTime': '14:30', 'maxTime': '10:00',
                 'withinPct': -100 / 12, 'withinPeakTime': '10:00',
                 'withinTroughTime': '14:30',
                 'presentMinutes': 240, 'tradedMinutes': 240, 'expectedMinutes': 240}
        second = {'status': 'OBSERVED', 'minClose': 8, 'maxClose': 9,
                  'minTime': '14:30', 'maxTime': '10:00',
                  'withinPct': -100 / 9, 'withinPeakTime': '10:00',
                  'withinTroughTime': '14:30',
                  'presentMinutes': 240, 'tradedMinutes': 240, 'expectedMinutes': 240}
        result = combine(['20260921', '20260922'], 10,
                         {'20260921': first, '20260922': second},
                         {'20260921': 'READY', '20260922': 'READY'})
        self.assertAlmostEqual(result['valuePct'], -100 / 3)
        self.assertEqual((result['peakTime'], result['troughTime']),
                         ('20260921 10:00', '20260922 14:30'))

    def test_invalid_factor_schema_only_degrades_minute_evidence(self):
        self.day('20260922', [('000001', 20260922, 931, 10, 2)])
        (self.factor_root / '20260922_stk_factor_pro.csv').write_text('code,date,factor\n000001.SZ,20260922,1\n')
        rows, source = safe_read_day(self.root, self.factor_root, '20260922', self.codes, self.cache)
        self.assertEqual(rows, {})
        self.assertEqual(source['status'], 'SOURCE_ERROR')
        self.assertIsNone(combine(['20260922'], 10, {'20260922': rows.get('000001.SZ')},
                                  {'20260922': source['status']})['valuePct'])


if __name__ == '__main__':
    unittest.main()
