import tempfile
import unittest
from pathlib import Path

from level2_limitup_study import board_of, limitup_study, market_change, read_limitups


DAYS = ['20260914', '20260915', '20260916', '20260917']
A, B, C, X, Y = '000001.SZ', '300001.SZ', '000002.SZ', '600001.SH', '688001.SH'


def flow(ratio):
    return {'ratio': ratio, 'amount': 100, 'net': ratio, 'unknown': 0}


class LimitUpStudyTests(unittest.TestCase):
    def test_code_segment_is_explicit(self):
        self.assertEqual([board_of(code) for code in (A, B, X, Y)],
                         ['MAIN', 'GEM', 'MAIN', 'STAR'])
        with self.assertRaisesRegex(ValueError, '非沪深A股'):
            board_of('920001.BJ')

    def test_provider_u_non_st_a_universe_and_data_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / '20260916_limit_list_d.csv'
            file.write_text('trade_date,ts_code,name,close,limit\n'
                            '20260916,000001.SZ,平安银行,10,U\n'
                            '20260916,000002.SZ,*ST测试,5,U\n'
                            '20260916,920001.BJ,北交测试,20,U\n'
                            '20260916,000003.SZ,普通炸板,9,Z\n'
                            '20260916,000004.SZ,,4,U\n'
                            '20260916,000005.SZ,无效价格,NA,U\n')
            audit, selected = read_limitups(root, '20260916')
            self.assertEqual((audit['status'], audit['uRows'], audit['outsideA'],
                              audit['stRows'], audit['missingName'], audit['invalidClose'],
                              audit['eligibleRows']), ('AVAILABLE', 5, 1, 1, 1, 1, 1))
            self.assertEqual(selected, {'000001.SZ': 10.0})
            self.assertEqual(read_limitups(root, '20260915')[0]['status'], 'MISSING')
            file.write_text('trade_date,ts_code,name,close,limit\n'
                            '20260915,000001.SZ,错日,10,U\n')
            with self.assertRaisesRegex(ValueError, '交易日冲突'):
                read_limitups(root, '20260916')

    def test_market_excludes_limit_up_stocks_and_uses_fixed_common_set(self):
        previous = {A: flow(-10), B: flow(10), X: flow(-20), Y: flow(-20),
                    'ONLY_PREVIOUS': flow(100)}
        current = {A: flow(90), B: flow(90), X: flow(-10), Y: flow(-10),
                   'ONLY_CURRENT': flow(100)}
        market = market_change(previous, current, {A, B})
        self.assertEqual((market['commonStocks'], market['previousRatio'],
                          market['currentRatio'], market['deltaPP']), (2, -20, -10, 10))

    def test_two_by_two_outcomes_use_same_day_u_baseline_without_price_filling(self):
        flows = {
            '20260914': {A: flow(-10), B: flow(10), X: flow(-20), Y: flow(-20)},
            '20260915': {A: flow(-10), B: flow(10), X: flow(-20), Y: flow(-20)},
            '20260916': {A: flow(-5), B: flow(5), X: flow(-10), Y: flow(-10)},
        }
        sources = {day: 'NATIVE' for day in DAYS[:3]}
        limitups = {
            '20260915': ({'day': '20260915', 'status': 'AVAILABLE', 'uRows': 0, 'eligibleRows': 0}, {}),
            '20260916': ({'day': '20260916', 'status': 'AVAILABLE', 'uRows': 2, 'eligibleRows': 2},
                         {A: 10.0, B: 10.0}),
        }
        prices = {'20260916': {A: 10.0, B: 10.0},
                  '20260917': {A: 11.0, B: 9.0}}
        bars = {'20260916': {A: (10, 10, 10, 10, 100),
                             B: (10, 10, 10, 10, 100)}}
        result = limitup_study(flows, sources, limitups, prices, bars, DAYS,
                               '20260915', '20260916', '20260917', '20260915', (1,))
        observed = [row for row in result['summary'] if row['cohort'] == 'OUT_OF_SAMPLE'
                    and row['horizon'] == 1 and row['events']]
        self.assertEqual(len(observed), 2)
        self.assertEqual([(row['marketDirection'], row['stockDirection'], row['events'])
                          for row in observed], [('IMPROVING', 'IMPROVING', 1),
                                                 ('IMPROVING', 'WEAKENING', 1)])
        self.assertAlmostEqual(observed[0]['meanReturnPct'], 10)
        self.assertAlmostEqual(observed[0]['meanExcessPct'], 10)
        self.assertAlmostEqual(observed[1]['meanReturnPct'], -10)
        self.assertAlmostEqual(observed[1]['meanExcessPct'], -10)
        self.assertEqual(result['coverage'][1]['matchedClose'], 2)
        self.assertEqual(observed[0]['leaveOneDayOutExcess']['comparableDays'], 1)
        contrast = next(row for row in result['pairedContrasts']
                        if row['cohort'] == 'OUT_OF_SAMPLE' and row['marketDirection'] == 'IMPROVING')
        self.assertEqual(contrast['pairedDays'], 1)
        self.assertAlmostEqual(contrast['equalDayMeanSpreadPct'], 20)
        self.assertEqual(contrast['daily'][0]['improvingN'], 1)
        self.assertEqual(contrast['daily'][0]['weakeningN'], 1)
        board_contrast = next(row for row in result['boardMatchedContrasts']
                              if row['cohort'] == 'OUT_OF_SAMPLE' and row['horizon'] == 1
                              and row['marketDirection'] == 'IMPROVING' and row['board'] == 'ALL')
        self.assertEqual(board_contrast['pairedDays'], 0)
        self.assertIsNone(board_contrast['equalDayMeanSpreadPct'])
        missing = limitup_study(flows, sources, limitups,
                                {**prices, '20260917': {A: 11.0}}, bars, DAYS,
                                '20260915', '20260916', '20260917', '20260915', (1,))
        missing_row = next(row for row in missing['summary'] if row['cohort'] == 'OUT_OF_SAMPLE'
                           and row['stockDirection'] == 'WEAKENING' and row['marketDirection'] == 'IMPROVING')
        self.assertEqual((missing_row['events'], missing_row['observed'],
                          missing_row['missingPrice'], missing_row['meanReturnPct']), (1, 0, 1, None))
        self.assertEqual(next(row for row in missing['pairedContrasts']
                              if row['cohort'] == 'OUT_OF_SAMPLE'
                              and row['marketDirection'] == 'IMPROVING')['pairedDays'], 0)
        boundary = limitup_study(flows, {**sources, '20260915': 'LEGACY_CALIBRATED_ROW_GUARD'},
                                 limitups, prices, bars, DAYS,
                                 '20260915', '20260916', '20260917', '20260915', (1,))
        self.assertEqual(boundary['coverage'][1]['studyStatus'], 'SOURCE_NOT_COMPARABLE')
        self.assertFalse(any(row['events'] for row in boundary['summary']))

    def test_missing_adjusted_factor_is_not_a_zero_return(self):
        flows = {'20260914': {A: flow(-10), X: flow(-20)},
                 '20260915': {A: flow(-10), X: flow(-20)},
                 '20260916': {A: flow(-5), X: flow(-10)}}
        limitups = {'20260915': ({'day': '20260915', 'status': 'AVAILABLE', 'uRows': 0,
                                  'eligibleRows': 0}, {}),
                    '20260916': ({'day': '20260916', 'status': 'AVAILABLE', 'uRows': 1,
                                  'eligibleRows': 1}, {A: 10.0})}
        result = limitup_study(flows, {day: 'NATIVE' for day in DAYS[:3]}, limitups,
                               {'20260916': {}, '20260917': {A: 11}},
                               {'20260916': {A: (10, 10, 10, 10, 100)}}, DAYS,
                               '20260915', '20260916', '20260917', '20260915', (1,))
        self.assertEqual(result['coverage'][1]['studyStatus'], 'NO_VALID_U_PRICE')
        self.assertEqual(result['coverage'][1]['missingAdjustedClose'], 1)
        self.assertFalse(any(row['events'] for row in result['summary']))

    def test_same_day_same_board_pair_removes_board_composition_effect(self):
        flows = {'20260914': {A: flow(0), B: flow(0), C: flow(0), X: flow(-20)},
                 '20260915': {A: flow(0), B: flow(0), C: flow(0), X: flow(-20)},
                 '20260916': {A: flow(5), B: flow(5), C: flow(-5), X: flow(-10)}}
        limitups = {'20260915': ({'day': '20260915', 'status': 'AVAILABLE',
                                  'uRows': 0, 'eligibleRows': 0}, {}),
                    '20260916': ({'day': '20260916', 'status': 'AVAILABLE',
                                  'uRows': 3, 'eligibleRows': 3}, {A: 10.0, B: 10.0, C: 10.0})}
        prices = {'20260916': {A: 10, B: 10, C: 10},
                  '20260917': {A: 11, B: 20, C: 9}}
        bars = {'20260916': {code: (10, 10, 10, 10, 100) for code in (A, B, C)}}
        result = limitup_study(flows, {day: 'NATIVE' for day in DAYS[:3]}, limitups,
                               prices, bars, DAYS, '20260915', '20260916',
                               '20260917', '20260915', (1,))
        raw = next(row for row in result['pairedContrasts']
                   if row['cohort'] == 'OUT_OF_SAMPLE' and row['marketDirection'] == 'IMPROVING')
        matched = next(row for row in result['boardMatchedContrasts']
                       if row['cohort'] == 'OUT_OF_SAMPLE' and row['marketDirection'] == 'IMPROVING'
                       and row['board'] == 'ALL')
        self.assertAlmostEqual(raw['equalDayMeanSpreadPct'], 65)
        self.assertAlmostEqual(matched['equalDayMeanSpreadPct'], 20)
        self.assertEqual((matched['pairedBoardDays'], matched['pairedDays'],
                          matched['improvingN'], matched['weakeningN']), (1, 1, 1, 1))
        self.assertIsNone(matched['daily'][0]['withoutDayMeanPct'])
        self.assertIsNone(matched['daily'][0]['influencePP'])
        self.assertEqual(matched['minThreeEachSideDays'], 0)
        self.assertIsNone(matched['minThreeEachSideSpreadPct'])
        improving = next(row for row in result['summary']
                         if row['cohort'] == 'OUT_OF_SAMPLE' and row['marketDirection'] == 'IMPROVING'
                         and row['stockDirection'] == 'IMPROVING')
        self.assertAlmostEqual(improving['equalDayMeanBoardExcessPct'], 5)
        self.assertEqual(improving['boardBenchmarkDays'], 1)

    def test_valid_price_without_stock_direction_is_not_comparable(self):
        flows = {'20260914': {X: flow(-20)},
                 '20260915': {X: flow(-20)},
                 '20260916': {X: flow(-10)}}
        limitups = {'20260915': ({'day': '20260915', 'status': 'AVAILABLE',
                                  'uRows': 0, 'eligibleRows': 0}, {}),
                    '20260916': ({'day': '20260916', 'status': 'AVAILABLE',
                                  'uRows': 1, 'eligibleRows': 1}, {A: 10.0})}
        result = limitup_study(flows, {day: 'NATIVE' for day in DAYS[:3]}, limitups,
                               {'20260916': {A: 10}, '20260917': {A: 11}},
                               {'20260916': {A: (10, 10, 10, 10, 100)}}, DAYS,
                               '20260915', '20260916', '20260917', '20260915', (1,))
        self.assertEqual(result['coverage'][1]['studyStatus'], 'NO_VALID_STOCK_DIRECTION')
        self.assertEqual(result['coverage'][1]['matchedClose'], 1)
        self.assertEqual(result['coverage'][1]['missingStockDirection'], 1)
        self.assertFalse(any(row['events'] for row in result['summary']))

    def test_outlier_sensitivity_and_next_session_capacity_proxies(self):
        codes = [f'0000{number:02d}.SZ' for number in range(10, 16)]
        flows = {
            '20260914': {**{code: flow(0) for code in codes}, X: flow(-20)},
            '20260915': {**{code: flow(0) for code in codes}, X: flow(-20)},
            '20260916': {**{code: flow(5 if index < 3 else -5)
                           for index, code in enumerate(codes)}, X: flow(-10)},
        }
        limitups = {'20260915': ({'day': '20260915', 'status': 'AVAILABLE',
                                   'uRows': 0, 'eligibleRows': 0}, {}),
                    '20260916': ({'day': '20260916', 'status': 'AVAILABLE',
                                   'uRows': 6, 'eligibleRows': 6}, {code: 10 for code in codes})}
        prices = {'20260916': {code: 10 for code in codes},
                  '20260917': dict(zip(codes, (10.1, 10.2, 13, 10, 9.9, 9.8)))}
        bars = {'20260916': {code: (10, 10, 10, 10, 100) for code in codes},
                '20260917': {code: (10, 10, 10, 10, 100) if index == 0 else
                             (10, 10.2, 9.8, 10, 0 if index == 1 else 100)
                             for index, code in enumerate(codes)}}
        result = limitup_study(flows, {day: 'NATIVE' for day in DAYS[:3]}, limitups,
                               prices, bars, DAYS, '20260915', '20260916',
                               '20260917', '20260915', (1,))
        contrast = next(row for row in result['boardMatchedContrasts']
                        if row['cohort'] == 'OUT_OF_SAMPLE' and row['horizon'] == 1
                        and row['marketDirection'] == 'IMPROVING' and row['board'] == 'MAIN')
        self.assertAlmostEqual(contrast['equalDayMeanSpreadPct'], 12)
        self.assertAlmostEqual(contrast['equalDayMedianStockSpreadPct'], 3)
        self.assertEqual(contrast['minThreeEachSideDays'], 1)
        self.assertAlmostEqual(contrast['minThreeEachSideSpreadPct'], 12)
        stronger = next(row for row in result['summary'] if row['cohort'] == 'OUT_OF_SAMPLE'
                        and row['horizon'] == 1 and row['marketDirection'] == 'IMPROVING'
                        and row['stockDirection'] == 'IMPROVING')
        self.assertEqual(stronger['medianEventAmountYuan'], 100)
        self.assertEqual(stronger['entryGateCounts'],
                         {'NO_VOLUME': 1, 'ONE_PRICE_SESSION': 1, 'PRICE_REFERENCE_ONLY': 1})

    def test_board_daily_evidence_identifies_influential_day(self):
        codes = [A, C, '000003.SZ', '000004.SZ']
        days = DAYS + ['20260918']
        flows = {
            '20260914': {**{code: flow(0) for code in codes}, X: flow(-20)},
            '20260915': {**{code: flow(0) for code in codes}, X: flow(-20)},
            '20260916': {**{code: flow(5 if index < 2 else -5)
                           for index, code in enumerate(codes)}, X: flow(-10)},
            '20260917': {**{code: flow(10 if index < 2 else -10)
                           for index, code in enumerate(codes)}, X: flow(0)},
        }
        prices = {'20260916': dict.fromkeys(codes, 10),
                  '20260917': dict(zip(codes, (12, 11, 11, 10))),
                  '20260918': dict(zip(codes, (12.12, 11.11, 11, 10)))}
        limitups = {'20260915': ({'day': '20260915', 'status': 'AVAILABLE',
                                  'uRows': 0, 'eligibleRows': 0}, {}),
                    **{day: ({'day': day, 'status': 'AVAILABLE', 'uRows': 4,
                               'eligibleRows': 4}, prices[day]) for day in ('20260916', '20260917')}}
        bars = {day: {code: (close, close, close, close, 100)
                      for code, close in prices[day].items()}
                for day in ('20260916', '20260917', '20260918')}
        result = limitup_study(flows, {day: 'NATIVE' for day in days[:4]},
                               limitups, prices, bars, days, '20260915',
                               '20260917', '20260918', '20260915', (1,))
        matched = next(row for row in result['boardMatchedContrasts']
                       if row['cohort'] == 'OUT_OF_SAMPLE' and row['horizon'] == 1
                       and row['marketDirection'] == 'IMPROVING' and row['board'] == 'ALL')
        self.assertEqual(matched['pairedDays'], 2)
        self.assertAlmostEqual(matched['equalDayMeanSpreadPct'], 5.5)
        self.assertEqual([row['day'] for row in matched['daily']], ['20260916', '20260917'])
        self.assertAlmostEqual(matched['daily'][0]['spreadPct'], 10)
        self.assertAlmostEqual(matched['daily'][0]['withoutDayMeanPct'], 1)
        self.assertAlmostEqual(matched['daily'][0]['influencePP'], 4.5)
        self.assertAlmostEqual(matched['daily'][1]['influencePP'], -4.5)
        self.assertEqual(matched['daily'][0]['boardDetails'][0]['board'], 'MAIN')


if __name__ == '__main__':
    unittest.main()
