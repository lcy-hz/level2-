import unittest
from statistics import median

from level2_quote_path import quote_path, ten_level_imbalance, ten_level_metrics, microprice_premium_bp


class QuotePathTests(unittest.TestCase):
    def test_segment_midpoint_change_and_recovery(self):
        rows=[('20260922','92900000','10000','10100'),
              ('20260922','93000000','10000','10100'),
              ('20260922','93003000','9800','9900'),
              ('20260922','95957000','10000','10100')]
        result=quote_path(rows,'20260922')
        self.assertEqual(result['status'],'AVAILABLE')
        first=result['segments'][0]
        self.assertEqual((first['observed'],first['valid']),(3,3))
        self.assertEqual((first['firstTime'],first['lastTime']),(93000000,95957000))
        self.assertAlmostEqual(first['firstMid'],1.005)
        self.assertAlmostEqual(first['midChangePct'],0)
        self.assertAlmostEqual(first['minMid'],.985)
        self.assertAlmostEqual(first['recoveryPct'],100*(1.005/.985-1))
        self.assertIsNone(result['segments'][1]['midChangePct'])

    def test_invalid_quote_excluded_without_turning_into_zero(self):
        result=quote_path([('20260922','93000000','10000','10100'),
                           ('20260922','93003000','0','10100')], '20260922')
        self.assertEqual(result['status'],'NO_COMPARABLE_QUOTES')
        self.assertEqual((result['segments'][0]['observed'],result['segments'][0]['valid']),(2,1))
        self.assertIsNone(result['segments'][0]['midChangePct'])

    def test_top_of_book_metrics_are_observations_not_order_additions(self):
        rows=[('20260922','93000000','10000','10100','100','200'),
              ('20260922','93003000','10000','10100','150','100'),
              ('20260922','93006000','9900','10000','300','100'),
              ('20260922','93009000','9900','10000','200','100'),
              ('20260922','93012000','9900','10000',None,'100')]
        result=quote_path(rows,'20260922')['segments'][0]
        self.assertEqual((result['valid'],result['depthValid']),(5,4))
        self.assertEqual((result['sameBidComparable'],result['sameBidDisplayedRise']),(2,1))
        self.assertAlmostEqual(result['medianSpreadBps'],20000*100/19900)
        self.assertAlmostEqual(result['medianTopImbalancePct'],(20 + 100/3)/2)
        self.assertAlmostEqual(result['medianMicropricePremiumBps'], median([
            microprice_premium_bp(10000,10100,100,200),
            microprice_premium_bp(10000,10100,150,100),
            microprice_premium_bp(9900,10000,300,100),
            microprice_premium_bp(9900,10000,200,100)]))

    def test_missing_depth_breaks_same_price_comparison(self):
        rows=[('20260922','93000000','10000','10100','100','100'),
              ('20260922','93003000','10000','10100',None,'100'),
              ('20260922','93006000','10000','10100','200','100')]
        segment=quote_path(rows,'20260922')['segments'][0]
        self.assertEqual(segment['depthValid'],2)
        self.assertEqual(segment['sameBidComparable'],0)
        self.assertEqual(segment['sameBidDisplayedRise'],0)
        self.assertEqual(segment['medianTopImbalancePct'],(0+100/3)/2)

    def test_ten_level_requires_complete_ordered_ladder(self):
        row = ('20260922', '93000000', '10000', '10100', '100', '200',
               *[str(10000 - 100*i) for i in range(1, 10)],
               *[str(10100 + 100*i) for i in range(1, 10)],
               *['10'] * 9, *['20'] * 9)
        self.assertEqual(len(row), 42)
        self.assertAlmostEqual(ten_level_imbalance(row), -100/3)
        segment = quote_path([row], '20260922')['segments'][0]
        self.assertEqual(segment['tenLevelValid'], 1)
        self.assertAlmostEqual(segment['medianTenLevelImbalancePct'], -100/3)
        self.assertAlmostEqual(segment['medianWeightedTenImbalancePct'], -100/3)
        self.assertIsNone(ten_level_imbalance(row[:6]))
        invalid_price = list(row); invalid_price[7] = invalid_price[6]
        self.assertIsNone(ten_level_imbalance(invalid_price))
        missing_qty = list(row); missing_qty[25] = None
        self.assertIsNone(ten_level_imbalance(missing_qty))

    def test_distance_weighted_depth_distinguishes_near_and_far_and_rejects_bad_ladder(self):
        row = ('20260922', '93000000', '10000', '10100', '100', '10',
               *[str(10000 - 100*i) for i in range(1, 10)],
               *[str(10100 + 100*i) for i in range(1, 10)],
               *['10'] * 9, *['100'] * 9)
        metrics = ten_level_metrics(row)
        self.assertIsNotNone(metrics)
        self.assertLess(metrics['imbalancePct'], 0)
        self.assertGreater(metrics['weightedImbalancePct'], metrics['imbalancePct'])
        self.assertAlmostEqual(microprice_premium_bp(10000,10100,100,10),
                               10000*100*90/(20100*110))
        self.assertIsNone(microprice_premium_bp(10000,10100,0,0))
        self.assertIsNone(microprice_premium_bp(10100,10000,100,10))
        locked = list(row); locked[3] = '10000'
        self.assertIsNotNone(ten_level_metrics(locked))
        self.assertAlmostEqual(microprice_premium_bp(10000,10000,100,10),0)
        broken = list(row); broken[24] = '-1'
        self.assertIsNone(ten_level_metrics(broken))

    def test_duplicate_regular_time_or_bad_date_disables_path(self):
        rows=[('20260922','93000000','10000','10100'),
              ('20260922','93000000','10000','10100')]
        self.assertEqual(quote_path(rows,'20260922')['status'],'DUPLICATE_TIME')
        self.assertEqual(quote_path([('20260921','93000000','10000','10100')],'20260922')['status'],'INVALID_DATE')
        # Duplicate auction observations do not contaminate the regular session.
        rows=[('20260922','92500000','10000','10100')]*2 + [('20260922','93000000','10000','10100')]
        self.assertEqual(quote_path(rows,'20260922')['status'],'NO_COMPARABLE_QUOTES')


if __name__=='__main__':unittest.main()
