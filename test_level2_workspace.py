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
        self.calendar=self.base/'calendar';self.calendar.mkdir()
        for d in range(1,8):
            day=f'202609{d:02d}'
            (self.calendar/f'{day}_daily.csv').touch()
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
        self.w.pool.shutdown();self.patcher.stop();self.temp.cleanup()

    def test_missing_window_not_substituted(self):
        self.assertTrue(self.w.dates()[0]['canBuild'])
        (self.root/'deal_20260904.parquet').unlink()
        self.assertFalse(self.w.dates()[0]['canBuild'])
        self.assertEqual(self.w.dates()[0]['windowMissing'],['20260904'])
        with self.assertRaises(ValueError):self.w.build('20260907')

    def test_snapshot_is_frozen(self):
        receipt=self.w.record_chart({'day':'20260907','code':'000001.SZ','source':str(self.base),'labels':[],'bars':[[1,2,3]]},'day')
        result=self.w.save({'day':'20260907','data':copy.deepcopy(self.data),'filters':{'search':'000001'},'charts':{'day/000001.SZ':receipt}})
        before=self.w.frozen_page(result['id'])
        self.report.write_text('changed live report')
        self.assertEqual(before,self.w.frozen_page(result['id']))
        self.assertIn(b'"mode":"snapshot"',before)
        self.assertEqual(result['chartCount'],1)

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
