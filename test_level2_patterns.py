import unittest
from unittest.mock import patch
from threading import Lock
import time
import pandas as pd
from level2_patterns import read_factor_files
from level2_patterns import recognize,normalize_qfq,CATALOG

def bar(o,c,h=None,l=None,v=100):return [o,max(o,c)+.2 if h is None else h,min(o,c)-.2 if l is None else l,c,v,1000]
class PatternTests(unittest.TestCase):
    def test_parallel_reads_deterministic_and_date_bound(self):
        lock=Lock();active=0;peak=0;progress=[]
        def fake_read(path,**kwargs):
            nonlocal active,peak
            code=path.name[:9].replace('_','.')
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.02)
            with lock:active-=1
            return pd.DataFrame({'ts_code':[code,code],'trade_date':['20260922','20260923']})
        codes=['000002.SZ','000001.SZ','000003.SZ']
        with patch('level2_patterns.Path.exists',return_value=True),patch('level2_patterns.pd.read_csv',side_effect=fake_read):
            frames,missing=read_factor_files(codes,['20260922'],'/unused',lambda *v:progress.append(v),workers=2)
        self.assertEqual(peak,2);self.assertEqual(missing,[])
        self.assertEqual([f.iloc[0].ts_code for f in frames],sorted(codes))
        self.assertTrue(all(list(f.trade_date)==['20260922'] for f in frames))
        self.assertEqual(progress[-1],(3,3,2))
    def test_parallel_read_error_not_silenced(self):
        with patch('level2_patterns.Path.exists',return_value=True),patch('level2_patterns.pd.read_csv',side_effect=ValueError('bad CSV')):
            with self.assertRaisesRegex(ValueError,'bad CSV'):read_factor_files(['000001.SZ'],['20260922'],'/unused')
    def days(self,n):return [str(i) for i in range(n)]
    def soldiers(self):return [bar(x,x-.1) for x in [15,14,13,12,11]]+[bar(10,11,11.1,9.9),bar(10.5,12,12.1,10.4),bar(11.5,13,13.1,11.4)]
    def test_soldiers_and_gap(self):
        b=self.soldiers();events=recognize(b,self.days(len(b)));self.assertIn('soldiers',[x['pattern'] for x in events]);b[-2]=None;self.assertNotIn('soldiers',[x['pattern'] for x in recognize(b,self.days(len(b)))])
    def test_three_positive_not_sufficient(self):
        b=[bar(10+i,11+i) for i in range(8)];self.assertNotIn('soldiers',[x['pattern'] for x in recognize(b,self.days(8))])
    def test_confirmation_not_backdated_and_future(self):
        b=self.soldiers();before=recognize(b,self.days(8));after=recognize(b+[bar(13,13.5)],self.days(9));e=next(x for x in before if x['pattern']=='soldiers');z=next(x for x in after if x['eventId']==e['eventId']);self.assertEqual(e['confirmed'],7);self.assertEqual(e['detected'],z['detected'])
    def test_invalidation(self):
        b=self.soldiers()+[bar(13,8)];e=next(x for x in recognize(b,self.days(9)) if x['pattern']=='soldiers');self.assertEqual(e['invalidated'],8)
    def test_qfq_scale(self):
        r=dict(open=10,high=12,low=9,close=11,adj_factor=2,open_qfq=5,high_qfq=6,low_qfq=4.5,close_qfq=5.5,vol=100,amount=200,ma_qfq_5=5,macd_qfq=.5,rsi_qfq_6=60)
        b,i=normalize_qfq(r,4);self.assertEqual(b[:4],[5,6,4.5,5.5]);self.assertEqual(i['ma_qfq_5'],5);self.assertEqual(i['rsi_qfq_6'],60)
        b,i=normalize_qfq(r,2);self.assertEqual(b[3],5.5);self.assertEqual(i['macd_qfq'],.5)
        r.pop('adj_factor');b,i=normalize_qfq(r);self.assertEqual(b[3],5.5)
        r['high_qfq']=1;self.assertIsNone(normalize_qfq(r,2)[0])
    def test_no_raw_fallback(self):
        self.assertIsNone(normalize_qfq(dict(open=10,close=10,high=11,low=9,adj_factor=1),1)[0])
    def test_catalog_and_empty(self):
        self.assertEqual(len(CATALOG),22);self.assertEqual(recognize([None]*90,self.days(90)),[])
    def test_scale_invariant(self):
        b=self.soldiers();scaled=[[x*2 for x in a[:4]]+a[4:] for a in b];self.assertEqual([x['pattern'] for x in recognize(b,self.days(8))],[x['pattern'] for x in recognize(scaled,self.days(8))])
if __name__=='__main__':unittest.main()
