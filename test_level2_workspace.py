import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from level2_workspace import Workspace, BASE, digest, report_sources_match, validate_continuous_ui


class WorkspaceTests(unittest.TestCase):
    def test_report_source_gate_ignores_only_state_calculator_code(self):
        base=[{'path':'/data/deal.parquet','bytes':42,'mtimeNs':1},
              {'path':str(BASE/'level2_state.py'),'bytes':100,'mtimeNs':1},
              {'path':'/code/generate_level2_report.py','bytes':80,'mtimeNs':1}]
        saved={'sources':base,'sourceDigest':digest(base)}
        current=[base[0],base[2]]
        self.assertTrue(report_sources_match(saved,current))
        self.assertFalse(report_sources_match(saved,[{**base[0],'mtimeNs':2},base[2]]))
        self.assertFalse(report_sources_match(saved,[base[0],{**base[2],'bytes':81}]))
        self.assertFalse(report_sources_match({**saved,'sourceDigest':'forged'},current))

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
        self.report=self.base/'.level2_reports'/'20260907'/'report.json'
        self.report.parent.mkdir(parents=True)
        self.report.write_text(json.dumps(self.data))
        self.service=SimpleNamespace(root=self.root,day='20260907',report=self.data,cards={'000001.SZ':self.data['cards'][0]})
        self.w=Workspace(self.service,self.base,self.calendar)

    def tearDown(self):
        self.w.pool.shutdown();self.w.state.pool.shutdown();self.temp.cleanup()

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
        continuous_ui={'search':'平安','change':'improve','continuity':'known','coverage':'full',
                       'sort':'delta','direction':'desc','advanced':{'preset':'relief','amountMin':'2'},'page':2}
        result=self.w.save({'day':'20260907','data':copy.deepcopy(self.data),'filters':{'search':'000001'},
                            'continuousUI':continuous_ui,'charts':{'day/000001.SZ':receipt}})
        saved=self.w.snapshot_path(result['id'])
        before=(saved/'bundle.json').read_bytes()
        self.report.write_text('changed live report')
        self.assertEqual(before,(saved/'bundle.json').read_bytes())
        self.assertFalse((saved/'report.html').exists())
        self.assertEqual((saved/'COMMITTED').read_text(),hashlib.sha256(before).hexdigest())
        self.assertEqual(result['chartCount'],1)
        frozen=self.w.snapshot_document(result['id'])
        self.assertEqual(frozen['charts']['day/000001.SZ']['bars'],[[1,2,3]])
        self.assertEqual(frozen['charts'].get('minute/000001.SZ'),None)
        self.assertEqual(frozen['continuousUI'],continuous_ui)

    def test_continuous_controls_reject_invalid_ranges_and_unknown_fields(self):
        self.assertEqual(validate_continuous_ui({}),{})
        for ui in ({'advanced':{'amountMin':'2','amountMax':'1'}},
                   {'advanced':{'buyDays':'0'}},
                   {'advanced':{'levelMin':'Infinity'}},
                   {'advanced':{'unknown':'x'}},
                   {'sort':'not-a-sort'},
                   {'sort':[]},
                   {'page':0}):
            with self.subTest(ui=ui),self.assertRaises(ValueError):
                validate_continuous_ui(ui)

    def test_snapshot_preserves_record_order_instead_of_resorting_legacy_evidence(self):
        second={'code':'000002.SZ','close':8}
        self.data['cards'].insert(0,second)
        self.service.cards={card['code']:card for card in self.data['cards']}
        saved=self.w.save({'day':'20260907','data':copy.deepcopy(self.data)})
        frozen=self.w.snapshot_document(saved['id'])
        self.assertEqual([card['code'] for card in frozen['report']['cards']],['000002.SZ','000001.SZ'])

    def test_snapshot_freezes_only_verified_full_detail(self):
        detail={'code':'000001.SZ','day':'20260907','tradeRows':42,'amount':1000,'net':30,
                'segments':[{'s':'09:30–10:00','a':1000,'n':30,'v':12.0}],
                'parents':[{'b':'<5万','n':30,'c':2}], 'orders':[{'t':'0','s':'B','r':1,'q':100}],
                'quotePath':{'status':'AVAILABLE','source':'/test/snapshot.parquet',
                             'segments':[{'s':'09:30–10:00','midChangePct':.5,'valid':20,'observed':20}]},
                'regularCoverage':100,'note':'测试中的完整深查证据'}
        self.service.status=lambda code:{'status':'done','result':detail}
        data=copy.deepcopy(self.data)
        data['cards'][0].update({key:detail[key] for key in ['segments','parents','orders','regularCoverage']})
        data['cards'][0]['computedDetail']=True
        data['cards'][0]['detailEvidence']=copy.deepcopy(detail)
        saved=self.w.save({'day':'20260907','data':data})
        frozen=self.w.snapshot_document(saved['id'])['report']['cards'][0]['detailEvidence']
        self.assertEqual(frozen['tradeRows'],42)
        self.assertEqual(frozen['quotePath']['segments'][0]['midChangePct'],.5)
        forged=copy.deepcopy(data);forged['cards'][0]['detailEvidence']['tradeRows']=999
        with self.assertRaisesRegex(ValueError,'完整深查证据'):
            self.w.save({'day':'20260907','data':forged})

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
        self.assertEqual(frozen['charts'],{})
        self.assertIsNone(frozen['patterns'])
        self.assertIsNone(frozen['validation'])
        self.assertEqual(frozen['patternUI'],{})
        bundle=self.w.snapshot_path(saved['id'])/'bundle.json'
        content=json.loads(bundle.read_text());content['report']['cards'][0]['close']=99
        content['payloadSha256']=__import__('level2_workspace').digest(content['report'])
        bundle.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError,'完整性'):
            self.w.snapshot_document(saved['id'])

    def test_snapshot_freezes_shared_presentation_from_verified_states(self):
        model=Path(__file__).with_name('level2_state_view.js')
        (self.base/model.name).write_text(model.read_text())
        states={'1':{'day':'20260907','window':1,
                     'benchmark':{'status':'AVAILABLE','code':'000300.SH','name':'沪深300价格指数',
                                  'returnPct':1,'source':'/test/index.csv'},
                     'peers':{'status':'AVAILABLE','source':'/test/daily_basic.csv',
                              'sizeCoverage':1,'liquidityCoverage':1,'stockCount':1},
                     'sources':[{'day':'20260907','status':'NATIVE','source':'/test/deal_20260907.parquet',
                                 'priceStatus':'FILE_PRESENT','priceSource':'/test/20260907_stk_factor_pro.csv'}],
                     'minuteSources':[{'day':'20260907','status':'READY','minuteFile':'/test/20260907.parquet'}],
                     'states':{'000001.SZ':{'maxCloseDrawdown':-5,'drawdownPeakDay':'20260904','drawdownTroughDay':'20260907','relativeReturn':1,
                                            'observedMinuteCloseDrawdown':{'status':'OBSERVED','valuePct':-7,'tradedMinutes':200,'expectedMinutes':240},
                                            'totalMv':1000,'sizeGroup':1,'sizeGroupCount':1,'sizePeerCount':1,
                                            'sizeFlowPercentile':None,'liquidityGroup':1,'liquidityGroupCount':1,
                                            'liquidityPeerCount':1,'liquidityFlowPercentile':None,
                                            'history':[{'day':'20260907','amount':100,'net':10,'ratio':10,'unknown':0,'priceDailyReturn':2}]}}}}
        with patch.object(self.w.state,'frozen',return_value=states):
            result=self.w.save({'day':'20260907','data':self.data,'stateWindow':1})
        bundle=json.loads((self.w.snapshot_path(result['id'])/'bundle.json').read_text())
        self.assertEqual(bundle['stateViews']['1']['trajectory'][0]['ratio'],10)
        self.assertEqual(bundle['stateViews']['1']['marketState']['status'],'AVAILABLE')
        self.assertEqual(bundle['stateViews']['1']['marketState']['latestRatio'],10)
        self.assertIsNone(bundle['stateViews']['1']['marketState']['ratioSlopePPPerDay'])
        self.assertEqual(bundle['stateViews']['1']['trajectory'][0]['sourceFile'],'/test/deal_20260907.parquet')
        self.assertEqual(bundle['stateViews']['1']['priceState']['latestUpShare'],100)
        self.assertEqual(bundle['stateViews']['1']['trajectory'][0]['priceSourceFile'],'/test/20260907_stk_factor_pro.csv')
        self.assertEqual(bundle['stateViews']['1']['stocks'][0]['maxCloseDrawdown'],-5)
        self.assertEqual(bundle['stateViews']['1']['stocks'][0]['observedMinuteCloseDrawdown']['valuePct'],-7)
        self.assertEqual(bundle['stateViews']['1']['minuteObserved'],1)
        self.assertEqual(bundle['stateViews']['1']['minuteSources'][0]['status'],'READY')
        self.assertEqual(bundle['stateViews']['1']['stocks'][0]['relativeReturn'],1)
        self.assertEqual(bundle['stateViews']['1']['benchmark']['returnPct'],1)
        self.assertEqual(bundle['stateViews']['1']['peers']['sizeCoverage'],1)
        self.assertEqual(bundle['stateViews']['1']['stocks'][0]['totalMv'],1000)
        self.assertIn(b'stateViews',(self.w.snapshot_path(result['id'])/'bundle.json').read_bytes())
        self.assertEqual(self.w.snapshot_document(result['id'])['stateViews']['1']['trajectory'][0]['ratio'],10)

    def test_snapshot_exposes_only_saved_pattern_result_and_viewed_details(self):
        pattern={'day':'20260907','identity':'fixture','catalog':[{'id':'breakout'}],
                 'stocks':[{'code':'000001.SZ','events':[]}],'dates':['20260907']}
        detail={'code':'000001.SZ','day':'20260907','dates':['20260907'],'bars':[[1,2,1,2,100,10]]}
        self.w._patterns=SimpleNamespace(receipt=lambda token,day:{'result':pattern,'details':{'000001.SZ':detail}})
        saved=self.w.save({'day':'20260907','data':self.data,'patternReceipt':'a'*32,
                           'patternCharts':['000001.SZ'],'patternUI':{'tab':'patterns','search':'000001'}})
        frozen=self.w.snapshot_document(saved['id'])
        self.assertEqual(frozen['patterns']['result'],pattern)
        self.assertEqual(frozen['patterns']['details']['000001.SZ'],detail)
        self.assertEqual(frozen['patternUI']['tab'],'patterns')

    def test_snapshot_freezes_verified_validation_without_live_backfill(self):
        study={'start':'20260901','end':'20260907','asof':'20260907','split':'20260905',
               'summary':[{'rule':'SELL_EASING','observed':12}], 'sourceIdentity':'fixture'}
        detail={'code':'000001.SZ','observations':[{'day':'20260907','horizon':1,'returnPct':None,'status':'PENDING'}]}
        self.w._validation=SimpleNamespace(frozen=lambda token: study if token=='a'*32 else self._invalid_validation(),
                                           details=lambda token,codes: {'000001.SZ':detail})
        saved=self.w.save({'day':'20260907','data':self.data,'validationReceipt':'a'*32,
                           'validationDetails':['000001.SZ'],'patternUI':{'tab':'validation'}})
        frozen=self.w.snapshot_document(saved['id'])
        self.assertEqual(frozen['validation'],study)
        self.assertEqual(frozen['validationDetails']['000001.SZ'],detail)
        self.assertEqual(frozen['patternUI']['tab'],'validation')
        with self.assertRaises(ValueError):
            self.w.save({'day':'20260907','data':self.data,'validationReceipt':'b'*32})
        with self.assertRaises(ValueError):
            self.w.save({'day':'20260907','data':self.data,'validationDetails':['000001.SZ']})

    @staticmethod
    def _invalid_validation():
        raise ValueError('后续收益凭据无效')

    def test_invalid_data_and_identifiers(self):
        bad=copy.deepcopy(self.data);bad['cards'][0]['close']=99
        with self.assertRaises(ValueError):self.w.save({'day':'20260907','data':bad})
        with self.assertRaises(ValueError):self.w.snapshot_path('../report')
        with self.assertRaises(ValueError):self.w.report_path('../report')

    def test_corrupt_snapshot_rejected(self):
        result=self.w.save({'day':'20260907','data':self.data})
        (self.w.snapshot_path(result['id'])/'bundle.json').write_text('corrupt')
        with self.assertRaises(ValueError):self.w.snapshot_document(result['id'])

    def test_existing_html_snapshot_remains_readable_without_serving_old_page(self):
        identifier='a'*32
        directory=self.w.snapshot_path(identifier);directory.mkdir(parents=True)
        context={'mode':'snapshot','id':identifier,'day':'20260907','charts':{},'stateViews':{}}
        html='<head><script>window.L2_CONTEXT='+json.dumps(context)+'</script></head><body><script>const D='+json.dumps(self.data)+'</script></body>'
        bundle={'id':identifier,'day':'20260907','savedAt':'2026-09-07T00:00:00Z',
                'chartCount':0,'report':self.data,'payloadSha256':digest(self.data),
                'reportProvenance':{},'scope':'旧快照测试'}
        (directory/'report.html').write_text(html)
        (directory/'bundle.json').write_text(json.dumps(bundle))
        (directory/'COMMITTED').write_text(hashlib.sha256(html.encode()).hexdigest())
        result=self.w.snapshot_document(identifier)
        self.assertEqual(result['report'],self.data)
        self.assertEqual(result['integrity']['report'],'verified-against-frozen-html')
        self.assertEqual(result['continuousUI'],{})

if __name__=='__main__':unittest.main()
