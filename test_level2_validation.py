import unittest

from level2_validation import study


DAYS = ['20260914', '20260915', '20260916', '20260917', '20260918',
        '20260921', '20260922', '20260923']


def flow(ratio):
    return {'ratio': ratio, 'amount': 100, 'net': ratio, 'unknown': 0}


class ValidationTests(unittest.TestCase):
    def test_event_is_signal_day_only_and_future_is_separate(self):
        flows = {
            '20260914': {'A': flow(-4), 'B': flow(-4)},
            '20260915': {'A': flow(-2), 'B': flow(-4)},
            '20260916': {'A': flow(2), 'B': flow(-5)},
            '20260917': {'A': flow(3), 'B': flow(-5)},
        }
        prices = {
            '20260915': {'A': 100, 'B': 100},
            '20260916': {'A': 110, 'B': 100},
            '20260917': {'A': 121, 'B': 100},
            '20260918': {'A': 130, 'B': 100},
        }
        result = study(flows, prices, DAYS, '20260915', '20260917', '20260918', '20260916', (1, 2))
        a = next(o for o in result['observations'] if o['day'] == '20260915' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual((a['rule'], a['status'], a['cohort']), ('SELL_EASING', 'OBSERVED', 'EMBARGO'))
        self.assertAlmostEqual(a['returnPct'], 10)
        self.assertAlmostEqual(a['benchmarkPct'], 5)  # eligible A/B, not event-only baseline
        self.assertAlmostEqual(a['excessPct'], 5)
        cross = next(o for o in result['observations'] if o['day'] == '20260916' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual(cross['rule'], 'SELL_TO_BUY')
        later = study(flows, {**prices, '20260918': {'A': 999, 'B': 100}}, DAYS,
                      '20260915', '20260917', '20260918', '20260916', (1, 2))
        first_later = next(o for o in later['observations'] if o['day'] == '20260915' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual(a, first_later)

    def test_pending_missing_and_unknown_do_not_become_zero(self):
        flows = {
            '20260914': {'A': flow(-4), 'B': flow(-4), 'C': flow(-4)},
            '20260915': {'A': flow(-2), 'B': flow(-2), 'C': {**flow(-2), 'unknown': 10}},
            '20260916': {'A': flow(-1), 'B': flow(-1)},
        }
        prices = {'20260915': {'A': 100, 'B': 100}, '20260916': {'A': 110}}
        result = study(flows, prices, DAYS, '20260915', '20260916', '20260916', '20260915', (1, 3))
        short = [o for o in result['observations'] if o['day'] == '20260915' and o['horizon'] == 1]
        self.assertEqual({(o['code'], o['status']) for o in short}, {('A', 'OBSERVED'), ('B', 'MISSING_PRICE')})
        self.assertTrue(all(o['status'] == 'PENDING' for o in result['observations'] if o['horizon'] == 3))
        self.assertFalse(any(o['code'] == 'C' for o in result['observations']))
        self.assertNotIn('20260917', result['signalDaysMissingFlow'])
        self.assertTrue(all(s['meanReturnPct'] is None for s in result['summary'] if s['horizon'] == 3))

    def test_missing_trading_session_is_not_bridged(self):
        flows = {'20260914': {'A': flow(-3)}, '20260916': {'A': flow(-1)}}
        result = study(flows, {}, DAYS, '20260915', '20260916', '20260918', '20260915', (1,))
        self.assertEqual(len(result['observations']), 0)
        self.assertEqual([x['day'] for x in result['signalDaysMissingFlow']], ['20260915', '20260916'])

    def test_training_purge_and_oos_are_calendar_based(self):
        flows = {d: {'A': flow(-10 + i)} for i, d in enumerate(DAYS)}
        prices = {d: {'A': 100 + i} for i, d in enumerate(DAYS)}
        result = study(flows, prices, DAYS, '20260915', '20260922', '20260923', '20260918', (1, 2))
        byday = {o['day']: o['cohort'] for o in result['observations']}
        self.assertEqual(byday['20260916'], 'TRAIN')
        self.assertEqual(byday['20260917'], 'EMBARGO')
        self.assertEqual(byday['20260918'], 'EMBARGO')
        self.assertEqual(byday['20260921'], 'OUT_OF_SAMPLE')

    def test_invalid_dates_and_horizons_rejected(self):
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260914', '20260916', '20260918', '20260915')
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260915', '20260916', '20260918', '20260915', (0,))
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260915', '20260916', '20260915', '20260915')

    def test_equal_day_average_is_not_stock_count_weighted(self):
        flows = {
            '20260915': {'A': flow(-4), 'B': flow(-4), 'C': flow(-4)},
            '20260916': {'A': flow(-2), 'B': flow(-2), 'C': flow(-4)},
            '20260917': {'A': flow(-2), 'B': flow(-2), 'C': flow(-2)},
        }
        prices = {
            '20260916': {'A': 100, 'B': 100, 'C': 100},
            '20260917': {'A': 120, 'B': 120, 'C': 100},
            '20260918': {'A': 120, 'B': 120, 'C': 100},
        }
        result = study(flows, prices, DAYS, '20260915', '20260917', '20260918', '20260915', (1,))
        same_rule = next(x for x in result['summary'] if x['rule'] == 'SELL_EASING' and x['cohort'] == 'OUT_OF_SAMPLE')
        self.assertEqual(same_rule['signalDays'], 2)
        self.assertEqual(same_rule['observed'], 3)
        self.assertEqual(same_rule['benchmarkPoolMeanN'], 3)
        self.assertAlmostEqual(same_rule['meanExcessPct'], 40 / 9)
        self.assertAlmostEqual(same_rule['equalDayMeanExcessPct'], 10 / 3)


if __name__ == '__main__':
    unittest.main()
