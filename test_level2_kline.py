"""Regression tests for report-date qfq normalization and embedded chart data."""
import json
import math
import unittest
from pathlib import Path
import pandas as pd
from level2_kline import FIELDS, SOURCE, normalized_candles, build_bundle


class KlineTests(unittest.TestCase):
    def test_anchor_and_future_cutoff(self):
        rows = [['X', '20260921', 50, 60, 45, 55],
                ['X', '20260922', 55, 60, 50, 58],
                ['X', '20260923', 20, 30, 10, 25]]
        s = normalized_candles(pd.DataFrame(rows, columns=FIELDS), {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(s['adjustment'], 'source_qfq')
        self.assertEqual(s['bars'], [[0, 50, 60, 45, 55], [1, 55, 60, 50, 58]])

    def test_missing_anchor_does_not_fallback(self):
        frame = pd.DataFrame([['X', '20260921', 1, 2, 1, 2]], columns=FIELDS)
        result = normalized_candles(frame, {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(result['bars'], [[0,1,2,1,2]])

    def test_invalid_ohlc_excluded_and_conflicts_rejected(self):
        frame = pd.DataFrame([['X', '20260921', 5, 4, 3, 4], ['X', '20260922', 5, 6, 3, 4]], columns=FIELDS)
        s = normalized_candles(frame, {'X'}, ['20260921', '20260922'], '20260922')['X']
        self.assertEqual(s['rejected'], 1)
        self.assertEqual(len(s['bars']), 1)
        frame.loc[0, 'trade_date'] = '20260922'
        with self.assertRaises(ValueError):
            normalized_candles(frame, {'X'}, ['20260922'], '20260922')

    def test_report_lazy_chart_contract_and_current_local_data(self):
        data=json.loads((Path(__file__).parent/'.level2_reports'/'20260922'/'report.json').read_text())
        self.assertEqual(data['markets'][-1]['day'],'20260922')
        self.assertIn('601669.SH',{card['code'] for card in data['cards']})
        # The live endpoint builds from current files; do not freeze an obsolete missing-file list.
        data=build_bundle({'601669.SH'},'20260922')
        self.assertEqual(len(data['dates']), 60)
        self.assertEqual(data['dates'][-1], '20260922')
        missing=set()
        self.assertEqual(data['missingFiles'],[])
        for s in data['series'].values():
            indices = [b[0] for b in s['bars']]
            self.assertEqual(indices, sorted(set(indices)))
            self.assertFalse(missing.intersection(indices))
            for index, o, h, l, c in s['bars']:
                self.assertLess(index, len(data['dates']))
                self.assertTrue(all(math.isfinite(v) and v > 0 for v in [o, h, l, c]))
                self.assertLessEqual(l, min(o, c))
                self.assertGreaterEqual(h, max(o, c))
        s = data['series']['601669.SH']
        first = s['bars'][0]
        date = data['dates'][first[0]]
        raw = pd.read_csv(SOURCE / '601669_SH_stk_factor_pro.csv', usecols=FIELDS,dtype={'trade_date':str})
        row = raw[(raw.ts_code == '601669.SH') & (raw.trade_date == date)].iloc[0]
        self.assertAlmostEqual(first[4], row['close_qfq'], places=4)
        self.assertAlmostEqual(s['bars'][-1][4], 4.61)


if __name__ == '__main__':
    unittest.main()
