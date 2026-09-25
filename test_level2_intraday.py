import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import duckdb
from level2_intraday import calculate_intraday, minute_close_drawdown, minute_identity, minute_slots, previous_close


class MinuteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'level2'
        self.day = '20260922'
        audit = self.root / '_conversion_audit' / self.day
        audit.mkdir(parents=True)
        (audit / 'COMMITTED').write_text('ok')
        (audit / 'manifest.json').write_text(json.dumps({'commit_state':'COMMITTED','minute_policy':'test'}))
        self.source = self.root.parent / 'stock_minute' / f'{self.day}.parquet'
        self.source.parent.mkdir()
        self.fixture()

    def fixture(self, bad=False, duplicate=False):
        con = duckdb.connect()
        q = """SELECT * FROM (VALUES ('000977',20260922,931,10.,11.,9.,10.5,12.5,13125.),
          ('000977',20260922,1500,10.5,10.5,10.5,10.5,0.,0.))
          AS t(SecuCode,TradingDay,Time,OpenPrice,HighPrice,LowPrice,ClosePrice,Volume,Turnover)"""
        if bad:
            q = q.replace('20260922','20260921')
        if duplicate:
            q += ' UNION ALL ' + q
        con.execute(f"COPY ({q}) TO '{self.source}' (FORMAT PARQUET)")
        con.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_direct_minute_source_units_and_no_gap_fill(self):
        with patch('level2_intraday.DAILY', Path(self.temp.name) / 'missing_daily'):
            r = calculate_intraday('000977.SZ',self.day,{},lambda _:None,self.root)
        self.assertEqual(len(r['bars']),2)
        self.assertEqual(r['bars'][0],[0,10.,11.,9.,10.5,12.5,13125.])
        self.assertEqual(r['bars'][-1][0],239)
        self.assertEqual(r['zeroVolumeMinutes'],1)
        self.assertEqual(r['minuteCloseDrawdown']['status'],'MISSING_PRE_CLOSE')
        self.assertIsNone(r['minuteCloseDrawdown']['valuePct'])
        self.assertIn('单位手',r['method'])
        self.assertEqual(r['source'],str(self.source))

    def test_calendar_and_lunch(self):
        self.assertEqual(len(minute_slots()),240)
        self.assertEqual(minute_slots()[119:121],['11:30','13:01'])

    def test_invalid_date_and_duplicate_rejected(self):
        for kwargs in [{'bad':True},{'duplicate':True}]:
            self.fixture(**kwargs)
            with self.assertRaises(ValueError):
                calculate_intraday('000977.SZ',self.day,{},lambda _:None,self.root)

    def test_missing_stock_and_cache_change(self):
        with self.assertRaises(ValueError):
            calculate_intraday('000001.SZ',self.day,{},lambda _:None,self.root)
        old = minute_identity(self.day,self.root)
        self.fixture(bad=True)
        self.assertNotEqual(old,minute_identity(self.day,self.root))

    def test_zero_axis_uses_exact_pre_close_and_never_infers(self):
        daily = Path(self.temp.name) / 'daily'
        daily.mkdir()
        with patch('level2_intraday.DAILY', daily):
            self.assertIsNone(previous_close('000977.SZ',self.day)[0])
            p = daily / f'{self.day}_daily.csv'
            p.write_text('ts_code,trade_date,pre_close\n000977.SZ,20260922,71.85\n')
            self.assertEqual(previous_close('000977.SZ',self.day)[0],71.85)
            p.write_text('ts_code,trade_date,pre_close\n000977.SZ,20260921,71.85\n')
            self.assertIsNone(previous_close('000977.SZ',self.day)[0])

    def test_observed_drawdown_uses_only_traded_minute_closes(self):
        labels=minute_slots()
        bars=[[0,10,11,8,10,2,2000], [1,10,13,9,12,3,3600],
              [2,12,12,7,7,0,0], [3,12,12,8,9,4,3600]]
        result=minute_close_drawdown(bars,labels,10)
        self.assertEqual(result['status'],'OBSERVED')
        self.assertAlmostEqual(result['valuePct'],-25)
        self.assertEqual((result['peakTime'],result['troughTime']),('09:32','09:34'))
        self.assertEqual((result['tradedMinutes'],result['presentMinutes'],result['expectedMinutes']),(3,4,240))
        self.assertIsNone(minute_close_drawdown(bars,labels,None)['valuePct'])
        self.assertEqual(minute_close_drawdown([bars[2]],labels,10)['status'],'NO_TRADED_MINUTES')
        self.assertEqual(minute_close_drawdown([bars[2]],labels,10)['valuePct'],None)
        self.assertEqual(minute_close_drawdown([[0,10,11,8,10.5,2,2100]],labels,10)['valuePct'],0)


if __name__ == '__main__':
    unittest.main()
