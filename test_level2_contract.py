import tempfile
import unittest
from pathlib import Path
import duckdb
from level2_contract import calendar,window,native_ticks,COMPLETE_NET,KNOWN_NET,UNKNOWN_AMOUNT,parent_query
from level2_quality import audit_raw_rows,inspect_day,render_quality

class ContractTests(unittest.TestCase):
    def test_calendar_gap_and_duplicates_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'trade_cal.csv'
            p.write_text('exchange,cal_date,is_open\nSSE,20260918,1\nSSE,20260920,0\n')
            with self.assertRaisesRegex(ValueError,'缺口'):calendar(p)
            p.write_text('exchange,cal_date,is_open\nSSE,20260918,1\nSSE,20260918,0\n')
            with self.assertRaisesRegex(ValueError,'重复'):calendar(p)
            p.write_text('exchange,cal_date,is_open\nSSE,20260918,1\nSSE,20260919,0\nSSE,20260920,0\nSSE,20260921,1\n')
            self.assertEqual(window('20260921',2,p),['20260918','20260921'])

    def test_quality_and_unknown_contract(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);day='20260922';c=duckdb.connect()
            df=pd.DataFrame([
              ['000001.SZ',day,'93000000','1','100000','10','B','0','9'],
              ['000001.SZ',day,'93000001','1','100000','10','B','0','9'],
              ['000001.SZ',day,'126000000','2','100000','10','?','3','4'],
              ['000001.SZ',day,'93000003','3','100000','999','C','3','4'],
              ['000001.SZ','20260921','93000000','4','100000','999','B','3','4'],
            ],columns=['万得代码','自然日','时间','成交编号','成交价格','成交数量','BS标志','叫买序号','叫卖序号'])
            c.register('df',df);c.execute('COPY df TO ? (FORMAT PARQUET)',[str(root/f'deal_{day}.parquet')])
            sn=pd.DataFrame([['000002.SZ',day,'153000000','10'],
                             ['000002.SZ',day,'93000000','11'],
                             ['000002.SZ',day,'93000000','12'],
                             ['000002.SZ',day,'93100000','13'],
                             ['000002.SZ',day,'93030000','14'],
                             ['000002.SZ',day,'96000000','0'],
                             ['000002.SZ',day,'96000000','0']],columns=['万得代码','自然日','时间','成交价'])
            c.register('sn',sn);c.execute('COPY sn TO ? (FORMAT PARQUET)',[str(root/f'snapshot_{day}.parquet')])
            od=pd.DataFrame([['000001.SZ',day,'0','0','9','B'],['000001.SZ',day,'93000000','0','9','S']],
                columns=['万得代码','自然日','时间','委托编号','交易所委托号','委托代码'])
            c.register('od',od);c.execute('COPY od TO ? (FORMAT PARQUET)',[str(root/f'order_raw_{day}.parquet')])
            c.execute('CREATE VIEW ticks AS '+native_ticks(root/f'deal_{day}.parquet',day))
            net,known,unknown=c.execute(f'SELECT {COMPLETE_NET},{KNOWN_NET},{UNKNOWN_AMOUNT} FROM ticks').fetchone()
            self.assertIsNone(net);self.assertEqual((known,unknown),(200,100))
            parents=c.execute(parent_query()).fetchall()
            self.assertEqual(parents,[('000001.SZ','关联键未知',200,2)])
            q=inspect_day(c,root,day,lambda _:None)
            self.assertEqual(q['tables']['deal']['badDate'],1)
            self.assertEqual(q['tables']['deal']['invalidClock'],1)
            self.assertEqual(q['tables']['order_raw']['zeroClock'],1)
            self.assertEqual(q['tables']['snapshot']['afterClose'],1)
            self.assertEqual(q['tables']['snapshot']['invalidClock'],2)
            self.assertEqual(q['snapshotTimestampDuplicates'],
                             {'eligibleRows':4,'groups':1,'affectedStocks':1,'affectedRows':2,'excessRows':1})
            self.assertEqual(q['snapshotExactDuplicates'],
                             {'eligibleRows':7,'candidateKeyGroups':2,'candidateRows':4,
                              'groups':1,'affectedRows':2,'excessRows':1})
            self.assertEqual(q['snapshotPhysicalTimeRegressions'],
                             {'eligibleRows':4,'comparablePairs':3,'regressions':1,'affectedStocks':1})
            self.assertEqual(q['dealExactDuplicates']['groups'],0)
            self.assertEqual(q['orderRawExactDuplicates']['groups'],0)
            self.assertEqual(q['dealPhysicalTimeRegressions']['regressions'],0)
            self.assertEqual(q['orderRawPhysicalTimeRegressions']['regressions'],0)
            self.assertEqual(q['coverage']['intersection'],0)
            self.assertEqual(q['candidateDuplicateKey']['groups'],1)
            self.assertIn('数据质量',render_quality(q));c.close()

    def test_full_raw_equality_and_file_clock_order_do_not_confuse_ties_or_invalid_times(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'deal_20260922.parquet';c=duckdb.connect();day='20260922'
            df=pd.DataFrame([
                ['000001.SZ',day,'93000000','A'],
                ['000001.SZ',day,'93000000','A'],
                ['000001.SZ',day,'93100000','B'],
                ['000001.SZ',day,'93050000','C'],
                ['000001.SZ',day,'96000000','D'],
                ['000001.SZ','20260921','93000000','A'],
                ['000002.SZ',day,'93000000','X'],
                ['000002.SZ',day,'93000000','X'],
            ],columns=['万得代码','自然日','时间','其他原始字段'])
            c.register('raw',df);c.execute('COPY raw TO ? (FORMAT PARQUET)',[str(path)])
            exact,physical=audit_raw_rows(c,path,day,{'000001.SZ','000002.SZ'},lambda _:None,batch_size=1)
            self.assertEqual(exact,{'eligibleRows':None,'groups':2,'affectedRows':4,'excessRows':2,'affectedStocks':2})
            self.assertEqual(physical,{'eligibleRows':6,'comparablePairs':4,'regressions':1,'affectedStocks':1})
            c.close()

    def test_parent_key_preserves_security_and_day(self):
        c=duckdb.connect()
        c.execute("CREATE TABLE ticks(trade_day VARCHAR,code VARCHAR,side VARCHAR,pid BIGINT,price DOUBLE,qty DOUBLE)")
        c.execute("INSERT INTO ticks VALUES ('20260921','000001.SZ','B',1,1,30000),('20260922','000001.SZ','B',1,1,30000),('20260922','000002.SZ','B',1,1,30000)")
        rows=c.execute(parent_query()).fetchall()
        self.assertTrue(all(r[1]=='<5万' for r in rows));self.assertEqual(sum(r[3] for r in rows),3);c.close()

if __name__=='__main__':unittest.main()
