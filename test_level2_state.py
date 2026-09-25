import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import duckdb
from level2_state import compute, StateService, calendar

DAYS=['20260916','20260917','20260918','20260921','20260922']
def row(ratio,amount=100):return {'ratio':ratio,'amount':amount,'net':amount*ratio/100,'unknown':0,'adjusted':100}

class StateTests(unittest.TestCase):
    def test_weighted(self):
        s=compute({DAYS[-2]:row(10,100),DAYS[-1]:row(-10,900)},DAYS,DAYS[-1],2)
        self.assertAlmostEqual(s['weighted'],-8)
        self.assertEqual(s['delta'],-20)

    def test_negative_improving(self):
        rows=dict(zip(DAYS[-3:],[row(-8),row(-6),row(-2)]))
        s=compute(rows,DAYS,DAYS[-1],3)
        self.assertEqual((s['streak'],s['improve'],s['sign']),(3,2,-1))
        self.assertTrue(s['leftCensored']);self.assertTrue(s['improveCensored'])
        self.assertEqual([(event['kind'],event['triggerDay']) for event in s['events']],
                         [('SELL_EASING',DAYS[-2]),('SELL_EASING',DAYS[-1])])

    def test_gap_and_unknown(self):
        rows={DAYS[-3]:row(-8),DAYS[-1]:row(-2)}
        s=compute(rows,DAYS,DAYS[-1],3)
        self.assertEqual(s['streak'],1);self.assertEqual(s['improve'],0)
        self.assertIsNone(s['weighted']);self.assertEqual(s['missing'],[DAYS[-2]])
        rows[DAYS[-1]]['unknown']=1
        self.assertIsNone(compute(rows,DAYS,DAYS[-1],3)['level'])

    def test_one_day_and_future(self):
        rows={DAYS[-2]:row(-6),DAYS[-1]:row(-2)}
        a=compute(rows,DAYS,DAYS[-1],1)
        self.assertIsNone(a['slope']);self.assertEqual(a['delta'],4)
        self.assertEqual(a['events'],[])
        rows['20260923']=row(100)
        self.assertEqual(a,compute(rows,DAYS+['20260923'],DAYS[-1],1))

    def test_price_without_flow(self):
        s=compute({DAYS[-2]:{'adjusted':100},DAYS[-1]:{'adjusted':110}},DAYS,DAYS[-1],1)
        self.assertAlmostEqual(s['priceReturn'],10);self.assertIsNone(s['weighted'])
        self.assertIn('缺成交记录',s['history'][0]['reason'])

    def test_snapshot_receipts_reject_changed_source_or_wrong_window(self):
        import json
        with tempfile.TemporaryDirectory() as temp:
            service=StateService(SimpleNamespace(base=Path(temp),root=Path(temp)))
            service.receipts.mkdir()
            token='a'*32
            r={'day':'20260922','window':5,'identity':'current','states':{}}
            (service.receipts/f'{token}.json').write_text(json.dumps(r))
            with patch.object(service,'identity',return_value='current'):
                self.assertEqual(service.frozen({'5':token},'20260922')['5'],r)
                with self.assertRaises(ValueError):service.frozen({'3':token},'20260922')
                with self.assertRaises(ValueError):service.frozen({'5':'../bad'},'20260922')
            with patch.object(service,'identity',return_value='changed'):
                with self.assertRaises(ValueError):service.frozen({'5':token},'20260922')
            service.pool.shutdown()

    def test_window_shortage(self):
        rows={d:row(1) for d in DAYS}
        self.assertEqual(compute(rows,DAYS,DAYS[-1],3)['status'],'AVAILABLE')
        self.assertEqual(compute(rows,DAYS,DAYS[-1],20)['status'],'INCOMPLETE')

    def test_legacy_unknown_and_source_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);primary=base/'primary';legacy=base/'legacy';primary.mkdir();legacy.mkdir()
            p=legacy/'deal_20260922.parquet'
            con=duckdb.connect()
            con.execute('CREATE TABLE d AS SELECT 1 SecuCode,20260922 TradingDay,1000 Price,100 Volume,0 Side')
            con.execute('COPY d TO ? (FORMAT PARQUET)',[str(p)]);con.close()
            service=StateService(SimpleNamespace(base=base,root=primary))
            with patch('level2_state.settings',return_value={'history_roots':[str(legacy)]}):
                rows,source=service.facts('20260922')
                self.assertEqual(rows['000001.SZ']['amount'],1000)
                self.assertIsNone(rows['000001.SZ']['net']);self.assertIsNone(rows['000001.SZ']['ratio'])
                (primary/p.name).touch()
                self.assertEqual(service.source('20260922'),primary/p.name)
            service.pool.shutdown()

    def test_calibrated_legacy_signs_and_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'deal_20260922.parquet'
            con=duckdb.connect()
            con.execute('''CREATE TABLE d(SecuCode INTEGER, TradingDay INTEGER,Price INTEGER,Volume INTEGER,Side INTEGER,BuyID BIGINT,SellID BIGINT)''')
            con.executemany('INSERT INTO d VALUES (?,?,?,?,?,?,?)',[
                (1,20260922,1000,100,0,20,10), # buy1000
                (1,20260922,1000,40,1,10,30), # sell400
                (1,20260922,1000,900,-1,50,0), # cancel excluded
                (2,20260922,1000,100,0,10,20), # reversed direction unknown
                (3,20260922,1000,100,1,0,20), # missing id unknown
                (4,20260922,1000,100,0,20,20), # equal id unknown
                (5,20260922,1000,100,9,20,10), # unknown code
            ])
            con.execute('COPY d TO ? (FORMAT PARQUET)',[str(p)]);con.close()
            service=StateService(SimpleNamespace(base=root,root=root))
            with patch('level2_state.CALIBRATED_LEGACY_ROOT',root),patch('level2_state.settings',return_value={'history_roots':[]}):
                rows,src=service.facts('20260922')
                a=rows['000001.SZ']
                self.assertEqual(a['amount'],1400);self.assertEqual(a['net'],600);self.assertEqual(a['unknown'],0)
                self.assertEqual(src['status'],'LEGACY_CALIBRATED_ROW_GUARD')
                for code in ['000002.SZ','000003.SZ','000004.SZ','000005.SZ']:
                    self.assertEqual(rows[code]['unknown'],1000)
                    self.assertIsNone(compute({'20260922':rows[code]},['20260922'],'20260922',1)['level'])
            # A distinct uncalibrated supplier with identical numeric columns cannot inherit the mapping.
            other=root/'other';other.mkdir();(other/p.name).write_bytes(p.read_bytes())
            other_service=StateService(SimpleNamespace(base=other,root=other))
            with patch('level2_state.settings',return_value={'history_roots':[]}):
                unknown_rows,unknown_source=other_service.facts('20260922')
                self.assertEqual(unknown_source['status'],'LEGACY_DIRECTION_UNKNOWN')
                self.assertIsNone(unknown_rows['000001.SZ']['net'])
            other_service.pool.shutdown()
            service.pool.shutdown()

    def test_skill_helper_calibrated_mapping(self):
        import importlib.util
        import pandas as pd
        helper=Path('/Users/m4pro/.codex/skills/analyze-a-stock-level2/scripts/stock_level2_summary.py')
        if not helper.exists():self.skipTest('local skill not installed')
        spec=importlib.util.spec_from_file_location('calibrated_helper',helper)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        df=pd.DataFrame({'Price':[1000,1000,1000],'Volume':[100,40,900],'Side':[0,1,-1],
                         'BuyID':[20,10,50],'SellID':[10,30,0],'DealTime':[93000000,93000100,93000200]})
        s=mod.summarize_deals(df)
        self.assertEqual(s['active_net_yuan'],600);self.assertEqual(s['small_net_yuan'],600)
        df.loc[0,'BuyID']=0
        self.assertIsNone(mod.summarize_deals(df)['active_net_yuan'])

    def test_calendar_not_weekday_guess(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'calendar.csv'
            p.write_text('exchange,cal_date,is_open\nSSE,20260919,0\nSSE,20260920,0\nSSE,20260921,1\n')
            self.assertEqual(calendar(p)[0],['20260921'])

if __name__=='__main__':unittest.main()
