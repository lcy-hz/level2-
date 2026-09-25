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
        self.assertEqual(view['trajectory'][1]['buyShare'],100)
        self.assertEqual(view['counts'],{'improve':1,'worsen':1,'flat':0,'unknown':1,'toBuy':1,'toSell':0})
        self.assertEqual([s['code'] for s in view['stocks']],['A','B','C'])

    def test_unknown_one_day_micro_change_and_empty(self):
        self.assertIsNone(derive({'window':2,'states':{'C':{'history':[row('1',50,None),row('2',50,5)]}}})['trajectory'][0]['ratio'])
        self.assertFalse(derive({'window':1,'states':{'A':{'history':[row('2',100,1)]}}})['applicable'])
        tiny=derive({'window':2,'states':{'A':{'history':[row('1',100,1),row('2',100,1.0000001)]}}})
        self.assertEqual(tiny['stocks'][0]['change'],'improve')
        self.assertEqual(derive({'window':2,'states':{}})['common'],0)

    def test_matches_legacy_presentation_model_on_contract_fixture(self):
        result={'day':'20260922','window':2,'states':{
            'A':{'history':[row('20260921',100,-10),row('20260922',100,10)]},
            'B':{'history':[row('20260921',900,20),row('20260922',900,10)]},
            'C':{'history':[row('20260921',50,None),row('20260922',50,5)]}}}
        script="const m=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(m.derive(JSON.parse(s)))));"
        output=subprocess.run(['node','-e',script,str(Path(__file__).with_name('level2_state_view.js'))],
                              input=json.dumps(result),text=True,capture_output=True,check=True,timeout=10)
        old=json.loads(output.stdout);new=derive(result)
        self.assertEqual(new['counts'],old['counts'])
        self.assertEqual(new['common'],old['common'])
        self.assertEqual([row['code'] for row in new['stocks']],[row['code'] for row in old['stocks']])
        for a,b in zip(new['trajectory'],old['trajectory']):
            self.assertEqual(a['amountCoverage'],b['amountCoverage'])
            self.assertAlmostEqual(a['ratio'],b['ratio'])


if __name__=='__main__':unittest.main()
