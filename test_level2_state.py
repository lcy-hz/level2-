import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import duckdb
from level2_state import compute, benchmark_evidence, StateService, calendar

DAYS=['20260916','20260917','20260918','20260921','20260922']
def row(ratio,amount=100):return {'ratio':ratio,'amount':amount,'net':amount*ratio/100,'unknown':0,'adjusted':100}

class StateTests(unittest.TestCase):
    def test_price_bars_preserve_missing_close_for_entry_gate(self):
        from level2_paths import PATHS
        from level2_validation import entry_gate
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'20260922_stk_factor_pro.csv').write_text(
                'ts_code,trade_date,open,high,low,close,vol,adj_factor\n'
                '000001.SZ,20260922,10,11,9,10,100,2\n'
                '000002.SZ,20260922,10,11,9,,100,2\n')
            service=StateService(SimpleNamespace(base=root,root=root))
            try:
                with patch.dict(PATHS,{'stk_factor_pro':root}):
                    prices,bars=service.price_bars('20260922')
                    self.assertEqual(service.prices('20260922'),prices)
                self.assertEqual(prices,{'000001.SZ':20})
                self.assertEqual(entry_gate(bars['000001.SZ']),'PRICE_REFERENCE_ONLY')
                self.assertEqual(entry_gate(bars['000002.SZ']),'MISSING_PRICE')
            finally:
                service.pool.shutdown()

    def test_weighted(self):
        s=compute({DAYS[-2]:row(10,100),DAYS[-1]:row(-10,900)},DAYS,DAYS[-1],2)
        self.assertAlmostEqual(s['weighted'],-8)
        self.assertEqual(s['delta'],-20)

    def test_relative_turnover_uses_only_complete_prior_window(self):
        observations={DAYS[-3]:row(1,100),DAYS[-2]:row(1,300),DAYS[-1]:row(1,300)}
        measured=compute(observations,DAYS,DAYS[-1],3)
        self.assertEqual(measured['amountPriorMean'],200)
        self.assertAlmostEqual(measured['amountRelativePct'],50)
        self.assertIsNone(compute(observations,DAYS,DAYS[-1],1)['amountRelativePct'])
        self.assertIsNone(compute({DAYS[-3]:row(1,100),DAYS[-1]:row(1,300)},DAYS,DAYS[-1],3)['amountRelativePct'])
        self.assertIsNone(compute({DAYS[-3]:row(1,100),DAYS[-2]:row(1,300)},DAYS,DAYS[-1],3)['amountRelativePct'])
        observations['20260923']=row(1,100000)
        self.assertEqual(measured,compute(observations,DAYS+['20260923'],DAYS[-1],3))

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
        self.assertAlmostEqual(s['history'][0]['priceDailyReturn'],10)
        self.assertIn('缺成交记录',s['history'][0]['reason'])

    def test_price_daily_returns_require_each_preceding_session(self):
        values={DAYS[-4]:row(0),DAYS[-3]:row(0),DAYS[-2]:row(0),DAYS[-1]:row(0)}
        values[DAYS[-4]]['adjusted']=100
        values[DAYS[-3]]['adjusted']=110
        values[DAYS[-2]]['adjusted']=100
        values[DAYS[-1]]['adjusted']=100
        observed=compute(values,DAYS,DAYS[-1],3)
        self.assertEqual([round(r['priceDailyReturn'],5) for r in observed['history']],[10,-9.09091,0])
        self.assertAlmostEqual(observed['maxCloseDrawdown'],-100/11)
        self.assertEqual((observed['drawdownPeakDay'],observed['drawdownTroughDay']),(DAYS[-3],DAYS[-2]))
        del values[DAYS[-2]]['adjusted']
        incomplete=compute(values,DAYS,DAYS[-1],3)
        self.assertEqual([r['priceDailyReturn'] is None for r in incomplete['history']],[False,True,True])
        self.assertIsNone(incomplete['priceReturn'])
        self.assertIsNone(incomplete['maxCloseDrawdown'])

    def test_close_drawdown_uses_baseline_and_never_future(self):
        values={DAYS[-4]:{'adjusted':100},DAYS[-3]:{'adjusted':90},
                DAYS[-2]:{'adjusted':95},DAYS[-1]:{'adjusted':120}}
        state=compute(values,DAYS,DAYS[-1],3)
        self.assertAlmostEqual(state['maxCloseDrawdown'],-10)
        self.assertEqual((state['drawdownPeakDay'],state['drawdownTroughDay']),(DAYS[-4],DAYS[-3]))
        values['20260923']={'adjusted':10}
        self.assertEqual(state,compute(values,DAYS+['20260923'],DAYS[-1],3))
        rising=compute({DAYS[-2]:{'adjusted':100},DAYS[-1]:{'adjusted':110}},DAYS,DAYS[-1],1)
        self.assertEqual(rising['maxCloseDrawdown'],0)
        self.assertIsNone(rising['drawdownPeakDay'])

    def test_benchmark_requires_every_calendar_day_and_ignores_future(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'index.csv'
            config={'code':'000300.SH','name':'沪深300价格指数','path':str(path)}
            self.assertEqual(benchmark_evidence(config,DAYS[-4:],3)['status'],'MISSING_FILE')
            self.assertEqual(benchmark_evidence(None,DAYS[-4:],3)['status'],'NOT_CONFIGURED')
            path.write_text('ts_code,trade_date,close\n000300.SH,20260917,100\n'
                            '000300.SH,20260918,110\n000300.SH,20260922,120\n'
                            '000300.SH,20260923,999\n')
            dates=DAYS[-4:]
            missing=benchmark_evidence(config,dates,3)
            self.assertEqual(missing['status'],'INCOMPLETE_PRICES')
            self.assertEqual(missing['missing'],[DAYS[-2]])
            self.assertIsNone(missing['returnPct'])
            path.write_text(path.read_text()+'000300.SH,20260921,115\n')
            ready=benchmark_evidence(config,dates,3)
            self.assertEqual(ready['status'],'AVAILABLE')
            self.assertAlmostEqual(ready['returnPct'],20)
            self.assertEqual(ready['baselineDay'],DAYS[-4])
            self.assertEqual(benchmark_evidence(config,dates,4)['status'],'INCOMPLETE_WINDOW')
            path.write_text(path.read_text()+'000300.SH,20260921,116\n')
            duplicate=benchmark_evidence(config,dates,3)
            self.assertEqual(duplicate['status'],'DUPLICATE_DATE')
            self.assertEqual(duplicate['missing'],[DAYS[-2]])
            self.assertIsNone(duplicate['returnPct'])

    def test_relative_return_is_difference_in_percentage_points(self):
        rows={DAYS[-2]:{'adjusted':100},DAYS[-1]:{'adjusted':110}}
        state=compute(rows,DAYS,DAYS[-1],1,benchmark_return=2)
        self.assertAlmostEqual(state['relativeReturn'],8)
        self.assertIsNone(compute(rows,DAYS,DAYS[-1],1)['relativeReturn'])
        self.assertIsNone(compute({DAYS[-1]:{'adjusted':110}},DAYS,DAYS[-1],1,benchmark_return=2)['relativeReturn'])

    def test_benchmark_file_is_part_of_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);index=base/'index.csv';index.write_text('close\n100\n')
            service=StateService(SimpleNamespace(base=base,root=base))
            cfg={'trade_calendar':str(base/'calendar.csv'),'history_roots':[],
                 'benchmark':{'code':'000300.SH','name':'沪深300价格指数','path':str(index)}}
            with patch.object(service,'validate',return_value=DAYS),patch('level2_state.settings',return_value=cfg):
                first=service.identity(DAYS[-1],3)
                index.write_text('close\n100\n101\n')
                self.assertNotEqual(first,service.identity(DAYS[-1],3))
            service.pool.shutdown()

    def test_same_day_market_cap_file_is_part_of_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'basic';root.mkdir()
            source=root/'20260922_daily_basic.csv';source.write_text('ts_code,trade_date,total_mv\nA,20260922,100\n')
            service=StateService(SimpleNamespace(base=base,root=base))
            cfg={'trade_calendar':str(base/'calendar.csv'),'history_roots':[],
                 'benchmark':None,'daily_basic_root':str(root)}
            with patch.object(service,'validate',return_value=DAYS),patch('level2_state.settings',return_value=cfg):
                first=service.identity(DAYS[-1],3)
                source.write_text(source.read_text()+'B,20260922,200\n')
                self.assertNotEqual(first,service.identity(DAYS[-1],3))
            service.pool.shutdown()

    def test_minute_file_is_part_of_continuous_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'level2';root.mkdir()
            minute=base/'stock_minute';minute.mkdir()
            source=minute/f'{DAYS[-1]}.parquet';source.write_bytes(b'first')
            service=StateService(SimpleNamespace(base=base,root=root))
            cfg={'trade_calendar':str(base/'calendar.csv'),'history_roots':[],
                 'benchmark':None,'daily_basic_root':None}
            with patch.object(service,'validate',return_value=DAYS),patch('level2_state.settings',return_value=cfg):
                first=service.identity(DAYS[-1],3)
                source.write_bytes(b'changed')
                self.assertNotEqual(first,service.identity(DAYS[-1],3))
            service.pool.shutdown()

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

    def test_saved_state_restores_after_restart_only_for_matching_source(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);receipts=base/'.level2_state_receipts';receipts.mkdir()
            token='a'*32
            result={'day':'20260922','window':3,'identity':'current','states':{}}
            (receipts/f'{token}.json').write_text(json.dumps(result))
            (receipts/'latest_20260922_3.json').write_text(json.dumps({'receipt':token,'identity':'current'}))
            service=StateService(SimpleNamespace(base=base,root=base))
            with patch.object(service,'validate',return_value=DAYS),patch.object(service,'identity',return_value='current'):
                restored=service.status('20260922',3)
                self.assertEqual(restored['status'],'done')
                self.assertEqual(restored['receipt'],token)
                self.assertEqual(restored['result'],result)
            service.pool.shutdown()
            changed=StateService(SimpleNamespace(base=base,root=base))
            with patch.object(changed,'validate',return_value=DAYS),patch.object(changed,'identity',return_value='changed'):
                self.assertEqual(changed.status('20260922',3)['status'],'stale')
            changed.pool.shutdown()

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
