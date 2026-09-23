"""Regression tests for report-date qfq normalization and embedded chart data."""
import json
import math
import re
import unittest
from pathlib import Path
import pandas as pd
from level2_kline import FIELDS, SOURCE, normalized_candles


class KlineTests(unittest.TestCase):
    def test_anchor_and_future_cutoff(self):
        rows = [['X', '20260921', 100, 120, 90, 110, 1],
                ['X', '20260922', 55, 60, 50, 58, 2],
                ['X', '20260923', 20, 30, 10, 25, 9]]
        s = normalized_candles(pd.DataFrame(rows, columns=FIELDS), {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(s['anchor'], 2)
        self.assertEqual(s['bars'], [[0, 50, 60, 45, 55], [1, 55, 60, 50, 58]])

    def test_missing_anchor_does_not_fallback(self):
        frame = pd.DataFrame([['X', '20260921', 1, 2, 1, 2, 1]], columns=FIELDS)
        result = normalized_candles(frame, {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(result['bars'], [])
        self.assertIn('复权因子', result['reason'])

    def test_invalid_ohlc_excluded_and_conflicts_rejected(self):
        frame = pd.DataFrame([['X', '20260921', 5, 4, 3, 4, 1], ['X', '20260922', 5, 6, 3, 4, 1]], columns=FIELDS)
        s = normalized_candles(frame, {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(s['rejected'], 1)
        self.assertEqual(len(s['bars']), 1)
        frame.loc[0, 'trade_date'] = '20260922'
        with self.assertRaises(ValueError):
            normalized_candles(frame, {'X'}, ['20260922'], '20260922')

    def test_embedded_data_source_and_dates(self):
        html = Path(__file__).with_name('level2-market-scan_20260922.html').read_text()
        match = re.search(r'<script id="kline-data" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match)
        data = json.loads(match[1])
        self.assertEqual(len(data['series']), 5209)
        self.assertEqual(len(data['dates']), 60)
        self.assertEqual(data['dates'][-1], '20260922')
        self.assertEqual(data['missingFiles'], ['20260916'])
        missing = data['dates'].index('20260916')
        for s in data['series'].values():
            indices = [b[0] for b in s['bars']]
            self.assertEqual(indices, sorted(set(indices)))
            self.assertNotIn(missing, indices)
            for index, o, h, l, c in s['bars']:
                self.assertLess(index, len(data['dates']))
                self.assertTrue(all(math.isfinite(v) and v > 0 for v in [o, h, l, c]))
                self.assertLessEqual(l, min(o, c))
                self.assertGreaterEqual(h, max(o, c))
        s = data['series']['601669.SH']
        first = s['bars'][0]
        date = data['dates'][first[0]]
        raw = pd.read_csv(SOURCE / f'{date}_stk_factor_pro.csv', usecols=FIELDS)
        row = raw[raw.ts_code == '601669.SH'].iloc[0]
        self.assertAlmostEqual(first[4], row['close'] * row.adj_factor / s['anchor'], places=4)
        self.assertNotAlmostEqual(first[4], row['close'], places=2)
        self.assertAlmostEqual(s['bars'][-1][4], 4.61)


if __name__ == '__main__':
    unittest.main()
