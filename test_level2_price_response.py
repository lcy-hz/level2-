import unittest

from level2_price_response import price_response


class PriceResponseTests(unittest.TestCase):
    day = '20260922'

    def test_adjacent_quote_intervals_and_lag_are_descriptive(self):
        quotes = [(self.day, t, b, a) for t, b, a in [
            (93000000, 10000, 10100), (93003000, 10100, 10200),
            (93006000, 10000, 10100), (93009000, 10100, 10200),
        ]]
        trades = [(93001000, 1.005, 100, 'B'),
                  (93003000, 1.015, 1000, 'S'),  # exact quote tie excluded
                  (93004000, 1.015, 100, 'S'),
                  (93007000, 1.005, 100, '?')]
        result = price_response(trades, quotes, self.day)
        row = result['segments'][0]
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertEqual((row['adjacentPairs'], row['flowPairs'], row['unknownFlowPairs']), (3, 2, 1))
        self.assertEqual(row['positiveAlignedSharePct'], 100)
        self.assertGreater(row['medianAlignedBps'], 0)
        self.assertGreater(row['meanAlignedBps'], 0)
        self.assertEqual(row['nextPairs'], 2)
        self.assertLess(row['medianNextAlignedBps'], 0)
        self.assertLess(row['meanNextAlignedBps'], 0)

    def test_gaps_missing_quotes_and_zero_flow_are_not_filled(self):
        quotes = [(self.day, 93000000, 10000, 10100),
                  (self.day, 93003000, None, 10100),
                  (self.day, 93006000, 10000, 10100),
                  (self.day, 93030000, 10000, 10100)]
        result = price_response([(93004000, 1, 100, 'B')], quotes, self.day)
        row = result['segments'][0]
        self.assertEqual(result['status'], 'NO_COMPARABLE_PAIRS')
        self.assertEqual((row['invalidQuotePairs'], row['gapPairs'], row['flowPairs']), (2, 1, 0))
        self.assertIsNone(row['medianAlignedBps'])
        flat = price_response([(93001000, 1, 100, 'B'), (93001000, 1, 100, 'S')],
                              quotes[:1] + [(self.day, 93003000, 10000, 10100)], self.day)
        self.assertEqual(flat['segments'][0]['zeroFlowPairs'], 1)

    def test_clock_date_and_duplicate_gate(self):
        quotes = [(self.day, 93000000, 10000, 10100), (self.day, 93003000, 10000, 10100)]
        self.assertEqual(price_response([(93099000, 1, 100, 'B')], quotes, self.day)['status'], 'INVALID_TRADE_CLOCK')
        self.assertEqual(price_response([], quotes + quotes[:1], self.day)['status'], 'DUPLICATE_QUOTE_TIME')
        self.assertEqual(price_response([], [('20260921', *quotes[0][1:])], self.day)['status'], 'INVALID_QUOTE_DATE')

    def test_lunch_and_closing_auction_are_not_paired_with_continuous_quotes(self):
        quotes = [(self.day, 112959000, 10000, 10100),
                  (self.day, 113000000, 10100, 10200),
                  (self.day, 130000000, 10200, 10300),
                  (self.day, 145659000, 10200, 10300),
                  (self.day, 145700000, 10300, 10400)]
        result = price_response([(145658000, 1, 100, 'B'),
                                 (145659500, 1, 100, 'S')], quotes, self.day)
        self.assertEqual(result['segments'][2]['quoteRows'], 2)
        self.assertEqual(result['segments'][3]['quoteRows'], 1)
        self.assertEqual(result['segments'][4]['quoteRows'], 1)
        self.assertEqual(result['segments'][4]['adjacentPairs'], 0)


if __name__ == '__main__':
    unittest.main()
