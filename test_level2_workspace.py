import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from level2_workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'level2';self.root.mkdir()
        self.calendar=self.base/'trade_cal.csv'
        self.calendar.write_text('exchange,cal_date,is_open\n'+''.join(f'SSE,202609{d:02d},1\n' for d in range(1,8)))
        for d in range(1,8):
            day=f'202609{d:02d}'
            for kind in ['deal','snapshot','order_raw']:(self.root/f'{kind}_{day}.parquet').touch()
            audit=self.root/'_conversion_audit'/day;audit.mkdir(parents=True)
            (audit/'COMMITTED').touch();(audit/'manifest.json').write_text('{"commit_state":"COMMITTED"}')
        self.data={'markets':[{'day':'20260907'}],'cards':[{'code':'000001.SZ','close':12}]}
        self.report=self.base/'report.html'
        self.report.write_text('<head></head><body><script>const D='+json.dumps(self.data)+';</script></body>')
        (self.base/'level2_workspace_ui.html').write_text('<div>snapshot controls</div>')
        self.patcher=patch('level2_detail_server.REPORT',self.report);self.patcher.start()
        self.service=SimpleNamespace(root=self.root,day='20260907',report=self.data,cards={'000001.SZ':self.data['cards'][0]})
        self.w=Workspace(self.service,self.base,self.calendar)

    def tearDown(self):
        self.w.pool.shutdown();self.w.state.pool.shutdown();self.patcher.stop();self.temp.cleanup()

    def test_missing_window_not_substituted(self):
        self.assertTrue(self.w.dates()[0]['canBuild'])
        (self.root/'deal_20260904.parquet').unlink()
        self.assertFalse(self.w.dates()[0]['canBuild'])
        self.assertEqual(self.w.dates()[0]['windowMissing'],['20260904'])
        with self.assertRaises(ValueError):self.w.build('20260907')

    def test_calendar_missing_day_is_not_shortened(self):
        self.calendar.write_text(self.calendar.read_text().replace('SSE,20260904,1\n',''))
        with self.assertRaisesRegex(ValueError,'缺口'):self.w.window('20260907')

    def test_snapshot_cannot_forge_quality(self):
        bad=copy.deepcopy(self.data);bad['quality']={'passed':True}
        with self.assertRaisesRegex(ValueError,'质量'):self.w.save({'day':'20260907','data':bad})

    def test_snapshot_is_frozen(self):
        receipt=self.w.record_chart({'day':'20260907','code':'000001.SZ','source':str(self.base),'labels':[],'bars':[[1,2,3]]},'day')
        result=self.w.save({'day':'20260907','data':copy.deepcopy(self.data),'filters':{'search':'000001'},'charts':{'day/000001.SZ':receipt}})
        before=self.w.frozen_page(result['id'])
        self.report.write_text('changed live report')
        self.assertEqual(before,self.w.frozen_page(result['id']))
        self.assertIn(b'"mode":"snapshot"',before)
        self.assertEqual(result['chartCount'],1)

    def test_report_document_is_gated_and_snapshot_never_reads_live(self):
        with patch.object(self.w,'status',return_value={'status':'ready'}):
            document=self.w.report_document('20260907')
        self.assertEqual(document['report'],self.data)
        self.assertEqual(document['mode'],'live')
        self.assertTrue(document['researchOnly'])
        self.assertEqual(document['provenance']['status'],'UNKNOWN_GENERATION_LINEAGE')
        with patch.object(self.w,'status',return_value={'status':'stale'}):
            with self.assertRaisesRegex(ValueError,'未就绪'):
                self.w.report_document('20260907')
        saved=self.w.save({'day':'20260907','data':copy.deepcopy(self.data)})
        self.report.write_text('changed live report')
        frozen=self.w.snapshot_document(saved['id'])
        self.assertEqual(frozen['report'],self.data)
        self.assertEqual(frozen['mode'],'snapshot')
        self.assertEqual(frozen['stateViews'],{})
        bundle=self.w.snapshot_path(saved['id'])/'bundle.json'
        content=json.loads(bundle.read_text());content['report']['cards'][0]['close']=99
        content['payloadSha256']=__import__('level2_workspace').digest(content['report'])
        bundle.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError,'完整性'):
            self.w.snapshot_document(saved['id'])

    def test_snapshot_freezes_shared_presentation_from_verified_states(self):
        model=Path(__file__).with_name('level2_state_view.js')
        (self.base/model.name).write_text(model.read_text())
        states={'1':{'day':'20260907','window':1,'states':{'000001.SZ':{'history':[{'day':'20260907','amount':100,'net':10,'ratio':10,'unknown':0}]}}}}
        with patch.object(self.w.state,'frozen',return_value=states):
            result=self.w.save({'day':'20260907','data':self.data,'stateWindow':1})
        bundle=json.loads((self.w.snapshot_path(result['id'])/'bundle.json').read_text())
        self.assertEqual(bundle['stateViews']['1']['trajectory'][0]['ratio'],10)
        self.assertIn(b'stateViews',self.w.frozen_page(result['id']))
        self.assertEqual(self.w.snapshot_document(result['id'])['stateViews']['1']['trajectory'][0]['ratio'],10)

    def test_invalid_data_and_identifiers(self):
        bad=copy.deepcopy(self.data);bad['cards'][0]['close']=99
        with self.assertRaises(ValueError):self.w.save({'day':'20260907','data':bad})
        with self.assertRaises(ValueError):self.w.snapshot_path('../report')
        with self.assertRaises(ValueError):self.w.report_path('../report')

    def test_corrupt_snapshot_rejected(self):
        result=self.w.save({'day':'20260907','data':self.data})
        (self.w.snapshot_path(result['id'])/'report.html').write_text('corrupt')
        with self.assertRaises(ValueError):self.w.frozen_page(result['id'])

if __name__=='__main__':unittest.main()
