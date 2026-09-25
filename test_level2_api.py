"""HTTP contract tests for the read-only report payloads."""
import json
import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from level2_detail_server import make_handler


class ReportApiTests(unittest.TestCase):
    def setUp(self):
        report={'markets':[{'day':'20260922','stocks':1}],
                'cards':[{'code':'000001.SZ','net':None,'unknownAmount':100}]}
        self.service=SimpleNamespace(day='20260922',report=report)
        self.workspace=SimpleNamespace(
            report_document=lambda day: {'mode':'live','day':day,'researchOnly':True,'report':report}
                if day=='20260922' else self._invalid(),
            snapshot_document=lambda ident: {'mode':'snapshot','id':ident,'day':'20260922',
                                                'researchOnly':True,'report':report}
                if ident=='a'*32 else self._invalid(),
            get_service=lambda day: self.service if day=='20260922' else self._invalid(),
            validation=SimpleNamespace(start=lambda request: {'id':'a'*32,'status':'queued'},
                status=lambda job: {'status':'done','receipt':'b'*32,'result':{'start':'20260901','summary':[]}}
                if job=='a'*32 else self._invalid(),
                detail=lambda token,code: {'code':code,'status':'NO_EVENT','observations':[]}
                if token=='b'*32 and code=='000001.SZ' else self._invalid()),
            state=SimpleNamespace(status=lambda day,window: {'status':'done','receipt':'proof',
                'result':{'day':day,'window':window,'states':{'000001.SZ':{'history':[
                    {'day':'20260922','amount':100,'net':10,'ratio':10,'unknown':0}]}},
                    'sources':[],'scope':'日级研究证据'}}))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.service,0,workspace=self.workspace))
        self.port=self.server.server_port
        self.server.RequestHandlerClass=make_handler(self.service,self.port,workspace=self.workspace)
        self.thread=Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    @staticmethod
    def _invalid():
        raise ValueError('报告未就绪或快照无效')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def fetch(self,path):
        with urlopen(f'http://127.0.0.1:{self.port}{path}') as response:
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            return json.load(response)

    def test_live_report_preserves_unknown_and_scope(self):
        result=self.fetch('/api/report/data?date=20260922')
        self.assertEqual(result['day'],'20260922')
        self.assertTrue(result['researchOnly'])
        self.assertIsNone(result['report']['cards'][0]['net'])
        with self.assertRaises(HTTPError) as context:
            self.fetch('/api/report/data?date=20260921')
        self.assertEqual(context.exception.code,400)

    def test_snapshot_is_separate_and_bad_id_is_rejected(self):
        result=self.fetch('/api/snapshot/data?id='+'a'*32)
        self.assertEqual(result['mode'],'snapshot')
        with self.assertRaises(HTTPError) as context:
            self.fetch('/api/snapshot/data?id=missing')
        self.assertEqual(context.exception.code,400)

    def test_continuous_view_is_derived_on_server(self):
        result=self.fetch('/api/state/view?date=20260922&window=1')
        self.assertEqual(result['status'],'done')
        self.assertEqual(result['view']['common'],1)
        self.assertEqual(result['view']['trajectory'][0]['ratio'],10)
        self.assertFalse(result['view']['applicable'])

    def test_validation_job_api_and_origin_gate(self):
        url=f'http://127.0.0.1:{self.port}/api/validation'
        body=json.dumps({'start':'20260901'}).encode()
        request=Request(url,data=body,headers={'Content-Type':'application/json',
            'Origin':f'http://127.0.0.1:{self.port}'},method='POST')
        with urlopen(request) as response:
            self.assertEqual(json.load(response)['id'],'a'*32)
        self.assertEqual(self.fetch('/api/validation/status?id='+'a'*32)['result']['summary'],[])
        self.assertEqual(self.fetch('/api/validation/detail?receipt='+'b'*32+'&code=000001.SZ')['status'],'NO_EVENT')
        bad=Request(url,data=body,headers={'Content-Type':'application/json','Origin':'https://other.invalid'},method='POST')
        with self.assertRaises(HTTPError) as context:urlopen(bad)
        self.assertEqual(context.exception.code,403)


if __name__=='__main__':
    unittest.main()
