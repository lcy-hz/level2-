import unittest
import json
import subprocess
from pathlib import Path
from level2_state_view import derive


def row(day,amount,ratio):
    return {'day':day,'amount':amount,'ratio':ratio,
            'net':None if ratio is None else amount*ratio/100,
            'unknown':amount if ratio is None else 0}


class StateViewTests(unittest.TestCase):
    def test_weighted_common_cohort_and_transitions(self):
        result={'day':'20260922','window':2,'states':{
            'A':{'history':[row('20260921',100,-10),row('20260922',100,10)]},
            'B':{'history':[row('20260921',900,20),row('20260922',900,10)]},
            'C':{'history':[row('20260921',50,None),row('20260922',50,5)]}}}
        view=derive(result)
        self.assertEqual(view['common'],2)
        self.assertEqual(view['trajectory'][0]['ratio'],17)
        self.assertEqual(view['trajectory'][0]['amountCoverage'],3)
        self.assertEqual(view['trajectory'][0]['directionCoverage'],2)
        self.assertEqual(view['trajectory'][0]['commonAmount'],1000)
        self.assertEqual(view['trajectory'][0]['commonNet'],170)
        self.assertEqual(view['trajectory'][1]['ratioDeltaPP'],-7)
        self.assertEqual(view['trajectory'][1]['buyShareDeltaPP'],50)
        self.assertEqual(view['trajectory'][1]['buyShare'],100)
        self.assertEqual(view['marketState']['ratioSlopePPPerDay'],-7)
        self.assertEqual(view['marketState']['ratioPersistence'],{'side':1,'days':2,'leftCensored':True})
        self.assertEqual(view['marketState']['breadthPersistence'],{'side':1,'days':1,'leftCensored':False})
        self.assertEqual(view['marketState']['ratioImprovement'],{'comparisons':0,'leftCensored':False})
        self.assertEqual(view['counts'],{'improve':1,'worsen':1,'flat':0,'unknown':1,'toBuy':1,'toSell':0})
        self.assertEqual([s['code'] for s in view['stocks']],['A','B','C'])
        self.assertIsNone(view['eventMethod'])

    def test_unknown_one_day_micro_change_and_empty(self):
        self.assertIsNone(derive({'window':2,'states':{'C':{'history':[row('1',50,None),row('2',50,5)]}}})['trajectory'][0]['ratio'])
        one=derive({'window':1,'states':{'A':{'history':[row('2',100,1)]}}})
        self.assertFalse(one['applicable'])
        self.assertIsNone(one['marketState']['ratioDeltaPP'])
        self.assertIsNone(one['marketState']['ratioSlopePPPerDay'])
        self.assertIsNone(one['marketState']['ratioImprovement']['comparisons'])
        tiny=derive({'window':2,'states':{'A':{'history':[row('1',100,1),row('2',100,1.0000001)]}}})
        self.assertEqual(tiny['stocks'][0]['change'],'improve')
        self.assertGreater(tiny['marketState']['ratioDeltaPP'],0)
        empty=derive({'window':2,'states':{}})
        self.assertEqual(empty['common'],0)
        self.assertEqual(empty['marketState']['status'],'INCOMPLETE_WINDOW')
        unknown=derive({'window':2,'states':{'A':{'history':[row('1',50,None),row('2',50,5)]}}})
        self.assertEqual(unknown['marketState']['status'],'NO_COMMON_COHORT')
        self.assertIsNone(unknown['marketState']['latestRatio'])

    def test_matches_legacy_presentation_model_on_contract_fixture(self):
        result={'day':'20260922','window':2,'eventMethod':'日级事件口径',
                'sources':[{'day':'20260921','status':'LEGACY_CALIBRATED_ROW_GUARD','source':'/tmp/a.parquet'},
                           {'day':'20260922','status':'NATIVE','source':'/tmp/b.parquet'}], 'states':{
            'A':{'history':[row('20260921',100,-10),row('20260922',100,10)]},
            'B':{'history':[row('20260921',900,20),row('20260922',900,10)]},
            'C':{'history':[row('20260921',50,None),row('20260922',50,5)]}}}
        script="const m=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(m.derive(JSON.parse(s)))));"
        output=subprocess.run(['node','-e',script,str(Path(__file__).with_name('level2_state_view.js'))],
                              input=json.dumps(result),text=True,capture_output=True,check=True,timeout=10)
        old=json.loads(output.stdout);new=derive(result)
        self.assertEqual(new['counts'],old['counts'])
        self.assertEqual(new['eventMethod'],old['eventMethod'])
        self.assertEqual(new['common'],old['common'])
        self.assertEqual(new['marketState']['ratioPersistence'],old['marketState']['ratioPersistence'])
        self.assertEqual(new['marketState']['breadthPersistence'],old['marketState']['breadthPersistence'])
        self.assertEqual(new['marketState']['ratioImprovement'],old['marketState']['ratioImprovement'])
        for key in ['latestRatio','latestBuyShare','ratioDeltaPP','buyShareDeltaPP','ratioSlopePPPerDay','buyShareSlopePPPerDay']:
            self.assertAlmostEqual(new['marketState'][key],old['marketState'][key])
        self.assertEqual([row['code'] for row in new['stocks']],[row['code'] for row in old['stocks']])
        for a,b in zip(new['trajectory'],old['trajectory']):
            self.assertEqual(a['amountCoverage'],b['amountCoverage'])
            self.assertEqual(a['directionCoverage'],b['directionCoverage'])
            self.assertEqual(a['sourceStatus'],b['sourceStatus'])
            self.assertEqual(a['sourceFile'],b['sourceFile'])
            self.assertEqual(a['commonAmount'],b['commonAmount'])
            self.assertAlmostEqual(a['ratio'],b['ratio'])


if __name__=='__main__':unittest.main()
