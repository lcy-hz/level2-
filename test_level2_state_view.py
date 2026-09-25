import unittest
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

    def test_price_breadth_has_independent_common_cohort(self):
        a=[dict(row('1',100,-10),priceDailyReturn=5),dict(row('2',100,-5),priceDailyReturn=-1)]
        b=[dict(row('1',100,10),priceDailyReturn=0),dict(row('2',100,5),priceDailyReturn=2)]
        c=[dict(row('1',100,None),priceDailyReturn=4),dict(row('2',100,5),priceDailyReturn=None)]
        result={'window':2,'sources':[{'day':'1','priceStatus':'FILE_PRESENT','priceSource':'/test/1.csv'}],
                'states':{'A':{'history':a},'B':{'history':b},'C':{'history':c}}}
        view=derive(result)
        self.assertEqual((view['common'],view['priceCommon']),(2,2))
        self.assertEqual([day['priceCoverage'] for day in view['trajectory']],[3,2])
        self.assertEqual([day['priceUpShare'] for day in view['trajectory']],[50,50])
        self.assertEqual([day['priceDownShare'] for day in view['trajectory']],[0,50])
        self.assertEqual(view['trajectory'][0]['priceFlatShare'],50)
        self.assertEqual(view['trajectory'][0]['priceSourceFile'],'/test/1.csv')
        self.assertEqual(view['priceState']['upShareDeltaPP'],0)
        self.assertEqual(view['priceState']['upShareSlopePPPerDay'],0)
        missing=derive({'window':2,'states':{'A':{'history':[a[0],dict(a[1],priceDailyReturn=None)]}}})
        self.assertEqual(missing['priceState']['status'],'NO_COMMON_PRICE_COHORT')
        self.assertIsNone(missing['trajectory'][1]['priceUpShare'])
        one=derive({'window':1,'states':{'A':{'history':[a[0]]}}})
        self.assertEqual(one['priceState']['status'],'AVAILABLE')
        self.assertIsNone(one['priceState']['upShareDeltaPP'])

    def test_frozen_model_keeps_source_and_missing_evidence(self):
        result={'day':'20260922','window':2,'eventMethod':'日级事件口径',
                'minuteSources':[{'day':'20260921','status':'READY'},{'day':'20260922','status':'READY'}],
                'benchmark':{'status':'AVAILABLE','code':'000300.SH','name':'沪深300价格指数',
                             'returnPct':2,'source':'/tmp/index.csv'},
                'peers':{'status':'AVAILABLE','source':'/tmp/daily_basic.csv','sizeCoverage':2,'liquidityCoverage':3},
                'sources':[{'day':'20260921','status':'LEGACY_CALIBRATED_ROW_GUARD','source':'/tmp/a.parquet','priceStatus':'FILE_PRESENT','priceSource':'/tmp/a.csv'},
                           {'day':'20260922','status':'NATIVE','source':'/tmp/b.parquet','priceStatus':'FILE_PRESENT','priceSource':'/tmp/b.csv'}], 'states':{
            'A':{'observedMinuteCloseDrawdown':{'status':'OBSERVED','valuePct':-3},'history':[dict(row('20260921',100,-10),priceDailyReturn=2),dict(row('20260922',100,10),priceDailyReturn=-1)]},
            'B':{'observedMinuteCloseDrawdown':None,'history':[dict(row('20260921',900,20),priceDailyReturn=-1),dict(row('20260922',900,10),priceDailyReturn=3)]},
            'C':{'history':[dict(row('20260921',50,None),priceDailyReturn=0),dict(row('20260922',50,5),priceDailyReturn=None)]}}}
        view=derive(result)
        self.assertEqual(view['eventMethod'],'日级事件口径')
        self.assertEqual(view['benchmark'],result['benchmark'])
        self.assertEqual(view['peers'],result['peers'])
        self.assertEqual(view['minuteSources'],result['minuteSources'])
        self.assertEqual(view['minuteObserved'],1)
        self.assertEqual((view['common'],view['priceCommon']),(2,2))
        self.assertEqual(view['counts'],{'improve':1,'worsen':1,'flat':0,'unknown':1,'toBuy':1,'toSell':0})
        self.assertEqual([stock['code'] for stock in view['stocks']],['A','B','C'])
        self.assertEqual([day['sourceFile'] for day in view['trajectory']],['/tmp/a.parquet','/tmp/b.parquet'])
        self.assertEqual([day['priceSourceFile'] for day in view['trajectory']],['/tmp/a.csv','/tmp/b.csv'])
        self.assertEqual([day['amountCoverage'] for day in view['trajectory']],[3,3])
        self.assertEqual([day['directionCoverage'] for day in view['trajectory']],[2,3])
        self.assertEqual([day['priceCoverage'] for day in view['trajectory']],[3,2])
        self.assertEqual([day['commonAmount'] for day in view['trajectory']],[1000,1000])
        self.assertEqual([day['ratio'] for day in view['trajectory']],[17,10])
        self.assertEqual(view['marketState']['ratioSlopePPPerDay'],-7)
        self.assertEqual(view['marketState']['ratioPersistence'],{'side':1,'days':2,'leftCensored':True})
        self.assertEqual(view['priceState']['upShareSlopePPPerDay'],0)


if __name__=='__main__':unittest.main()
