import json
import tempfile
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from unittest.mock import patch
import unittest
from level2_kline import build_bundle
from level2_detail_server import Service,make_handler


class FreshChartTests(unittest.TestCase):
    def test_by_code_qfq_without_factor_and_future_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/'000977_SZ_stk_factor_pro.csv'
            file.write_text('ts_code,trade_date,open_qfq,high_qfq,low_qfq,close_qfq,vol,amount\n000977.SZ,20260921,9,11,8,10,100,125\n000977.SZ,20260922,10,12,9,11,200,250\n000977.SZ,20260923,20,22,19,21,999,999\n')
            result=build_bundle({'000977.SZ'},'20260922',root,root,include_volume=True)
            self.assertEqual(result['dates'],['20260921','20260922'])
            self.assertEqual(result['series']['000977.SZ']['bars'][-1],[1,10,12,9,11,200,250000])
            self.assertEqual(result['series']['000977.SZ']['sourceFiles'],[str(file)])

    def test_daily_volume_reread_and_date_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            header='ts_code,trade_date,open_qfq,high_qfq,low_qfq,close_qfq,unused,vol,amount\n'
            file=root/'20260922_stk_factor_pro.csv'
            file.write_text(header+'000977.SZ,20260922,10,12,9,11,2,100,125\n')
            (root/'20260923_stk_factor_pro.csv').write_text(header+'000977.SZ,20260923,20,22,19,21,2,999,999\n')
            def read():
                return build_bundle({'000977.SZ'},'20260922',root,root,include_volume=True)
            a=read()
            self.assertEqual(a['dates'],['20260922'])
            self.assertEqual(a['series']['000977.SZ']['bars'][0][5:],[100,125000])
            file.write_text(header+'000977.SZ,20260922,10,12,9,11,2,200,250\n')
            self.assertEqual(read()['series']['000977.SZ']['bars'][0][5:],[200,250000])

    def test_every_http_request_rereads_both_sources(self):
        service=Service({'markets':[{'day':'20260922'}],'cards':[{'code':'000977.SZ'}]})
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(service,0))
        server.RequestHandlerClass=make_handler(service,server.server_port)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        bundle={'series':{'000977.SZ':{'bars':[]}},'dates':[], 'source':'test','method':'test'}
        try:
            with patch('level2_kline.build_bundle',return_value=bundle) as daily,patch('level2_intraday.calculate_intraday',return_value={'code':'000977.SZ','day':'20260922','bars':[]}) as minute:
                for kind in ['day','minute']:
                    times=[]
                    for _ in range(2):
                        with urlopen(f'http://127.0.0.1:{server.server_port}/api/chart/{kind}/000977.SZ') as response:
                            self.assertEqual(response.headers['Cache-Control'],'no-store')
                            times.append(json.load(response)['result']['readAt'])
                    self.assertNotEqual(times[0],times[1])
                self.assertEqual(daily.call_count,2)
                self.assertEqual(minute.call_count,2)
                self.assertFalse(service.jobs)
        finally:
            server.shutdown();server.server_close();service.pool.shutdown()


if __name__=='__main__': unittest.main()
