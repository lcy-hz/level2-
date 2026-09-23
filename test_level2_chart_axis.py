"""Check the actual JavaScript domain helper used by the candle renderer."""
import json
from pathlib import Path
import re
import subprocess
import unittest


class ChartAxisTests(unittest.TestCase):
    def domain(self, bars, anchor):
        source = Path(__file__).with_name('level2_kline_ui.html').read_text()
        helper = re.search(r'function candlePriceDomain\(.*?\n}', source, re.S)[0]
        js = helper + '\nconsole.log(JSON.stringify(candlePriceDomain(' + json.dumps(bars) + ',' + json.dumps(anchor) + ')));'
        return json.loads(subprocess.check_output(['node', '-e', js], text=True))

    def test_zero_centered_for_rising_falling_and_flat_prices(self):
        for low, high, anchor in [(71.83,73.36,71.85),(66,70,71.85),(71.85,71.85,71.85)]:
            with self.subTest(low=low,high=high):
                lo,hi = self.domain([[0,low,high,low,high]],anchor)
                self.assertAlmostEqual((lo+hi)/2,anchor)
                self.assertAlmostEqual(16+(hi-anchor)/(hi-lo)*190,111)
                self.assertLess(lo,low)
                self.assertGreater(hi,high)

    def test_daily_and_missing_baseline_keep_price_fit(self):
        lo,hi = self.domain([[0,20,23,19,22]],None)
        self.assertAlmostEqual(lo,18.64)
        self.assertAlmostEqual(hi,23.36)


if __name__ == '__main__':
    unittest.main()
