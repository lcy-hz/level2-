import unittest
import tempfile
import json
import os
import statistics
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from level2_validation import study, ValidationService, entry_gate, close_path_drawdown, file_timing, input_timing_audit


DAYS = ['20260914', '20260915', '20260916', '20260917', '20260918',
        '20260921', '20260922', '20260923']


def flow(ratio):
    return {'ratio': ratio, 'amount': 100, 'net': ratio, 'unknown': 0}


class ValidationTests(unittest.TestCase):
    def test_local_file_timing_is_audit_evidence_not_pit_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            flow_file = root / 'deal_20260922.parquet'
            price_file = root / '20260922_stk_factor_pro.csv'
            flow_file.write_bytes(b'flow')
            price_file.write_text('price')
            timezone = ZoneInfo('Asia/Shanghai')
            flow_stamp = datetime(2026, 9, 22, 21, 0, tzinfo=timezone).timestamp()
            price_stamp = datetime(2026, 9, 23, 5, 7, tzinfo=timezone).timestamp()
            os.utime(flow_file, (flow_stamp, flow_stamp))
            os.utime(price_file, (price_stamp, price_stamp))
            audit = input_timing_audit([
                {'day': '20260922', 'source': str(flow_file)},
                {'day': '20260923', 'source': None}], ['20260922', '20260923'], root)
            self.assertEqual((audit['method'], audit['strictPitVerified']),
                             ('LOCAL_LAST_MODIFIED_ONLY_NOT_PIT', False))
            self.assertEqual(audit['flow']['requested'], 2)
            self.assertEqual(audit['flow']['present'], 1)
            self.assertEqual(audit['flow']['modifiedAfterTradeDay'], 0)
            self.assertEqual(audit['price']['modifiedAfterTradeDay'], 1)
            self.assertEqual(audit['price']['days'][0]['modifiedAtLocal'], '2026-09-23T05:07:00+08:00')
            self.assertEqual(file_timing('20260923', None)['modifiedAfterTradeDay'], None)

    def test_close_path_drawdown_requires_every_session_and_keeps_zero(self):
        path = [('20260915', 100), ('20260916', 110), ('20260917', 99)]
        drawdown, peak, trough = close_path_drawdown(path)
        self.assertAlmostEqual(drawdown, -10)
        self.assertEqual((peak, trough), ('20260916', '20260917'))
        self.assertEqual(close_path_drawdown(path[:2]), (0.0, None, None))
        self.assertEqual(close_path_drawdown([path[0], ('20260916', None), path[2]]),
                         (None, None, None))

    def test_drawdown_path_does_not_reclassify_endpoint_return(self):
        flows = {'20260914': {'A': flow(-4)}, '20260915': {'A': flow(-2)}}
        prices = {'20260915': {'A': 100}, '20260916': {},
                  '20260917': {'A': 90}, '20260918': {'A': 105}}
        result = study(flows, prices, DAYS, '20260915', '20260916', '20260918',
                       '20260915', (3,))
        row = result['observations'][0]
        self.assertEqual(row['status'], 'OBSERVED')
        self.assertAlmostEqual(row['returnPct'], 5)
        self.assertEqual((row['closeDrawdownStatus'], row['maxCloseDrawdownPct']),
                         ('MISSING_PRICE', None))
        self.assertEqual(result['summary'][0]['closeDrawdownObserved'], 0)
        prices['20260916'] = {'A': 110}
        complete = study(flows, prices, DAYS, '20260915', '20260916', '20260918',
                         '20260915', (3,))
        self.assertEqual(complete['observations'][0]['closeDrawdownStatus'], 'OBSERVED')
        self.assertAlmostEqual(complete['observations'][0]['maxCloseDrawdownPct'],
                               100 * (90 / 110 - 1))
        self.assertEqual(complete['summary'][0]['closeDrawdownObserved'], 1)
        pending = study(flows, prices, DAYS, '20260915', '20260916', '20260917',
                        '20260915', (3,))['observations'][0]
        self.assertEqual((pending['closeDrawdownStatus'], pending['maxCloseDrawdownPct']),
                         ('PENDING', None))

    def test_next_day_bar_gate_never_claims_fill(self):
        self.assertEqual(entry_gate(None), 'MISSING_BAR')
        self.assertEqual(entry_gate((None, 11, 9, 10, 100)), 'MISSING_PRICE')
        self.assertEqual(entry_gate((10, 9, 8, 10, 100)), 'INVALID_OHLC')
        self.assertEqual(entry_gate((10, 11, 9, 10, None)), 'UNKNOWN_VOLUME')
        self.assertEqual(entry_gate((10, 11, 9, 10, 0)), 'NO_VOLUME')
        self.assertEqual(entry_gate((10, 10, 10, 10, 100)), 'ONE_PRICE_SESSION')
        self.assertEqual(entry_gate((10, 11, 9, 10, 100)), 'PRICE_REFERENCE_ONLY')

    def test_entry_gate_is_distinct_from_close_to_close_outcome(self):
        flows = {'20260914': {'A': flow(-4)}, '20260915': {'A': flow(-2)},
                 '20260916': {'A': flow(-2)}}
        prices = {'20260915': {'A': 100}, '20260916': {'A': 110}}
        bars = {'20260916': {'A': (110, 110, 110, 110, 100)}}
        result = study(flows, prices, DAYS, '20260915', '20260916', '20260916',
                       '20260915', (1,), bars=bars)
        item = result['observations'][0]
        self.assertEqual((item['entryDay'], item['entryGate']), ('20260916', 'ONE_PRICE_SESSION'))
        self.assertEqual(item['status'], 'OBSERVED')
        self.assertAlmostEqual(item['returnPct'], 10)
        self.assertEqual(result['summary'][0]['entryGateCounts'], {'ONE_PRICE_SESSION': 1})
        baseline = study(flows, prices, DAYS, '20260915', '20260916', '20260916',
                         '20260915', (1,))
        for field in ('meanReturnPct', 'meanExcessPct', 'equalDayMeanExcessPct', 'observed'):
            self.assertEqual(result['summary'][0][field], baseline['summary'][0][field])
        pending_flows = {**flows, '20260916': {'A': flow(2)}}
        pending = next(item for item in study(pending_flows, prices, DAYS, '20260915', '20260916',
                                              '20260916', '20260915', (1,), bars=bars)['observations']
                       if item['day'] == '20260916')
        self.assertEqual((pending['entryGate'], pending['status']), ('PENDING', 'PENDING'))

    def test_event_is_signal_day_only_and_future_is_separate(self):
        flows = {
            '20260914': {'A': flow(-4), 'B': flow(-4)},
            '20260915': {'A': flow(-2), 'B': flow(-4)},
            '20260916': {'A': flow(2), 'B': flow(-5)},
            '20260917': {'A': flow(3), 'B': flow(-5)},
        }
        prices = {
            '20260915': {'A': 100, 'B': 100},
            '20260916': {'A': 110, 'B': 100},
            '20260917': {'A': 121, 'B': 100},
            '20260918': {'A': 130, 'B': 100},
        }
        result = study(flows, prices, DAYS, '20260915', '20260917', '20260918', '20260916', (1, 2))
        a = next(o for o in result['observations'] if o['day'] == '20260915' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual((a['rule'], a['status'], a['cohort']), ('SELL_EASING', 'OBSERVED', 'EMBARGO'))
        self.assertAlmostEqual(a['returnPct'], 10)
        self.assertAlmostEqual(a['benchmarkPct'], 5)  # eligible A/B, not event-only baseline
        self.assertAlmostEqual(a['excessPct'], 5)
        cross = next(o for o in result['observations'] if o['day'] == '20260916' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual(cross['rule'], 'SELL_TO_BUY')
        later = study(flows, {**prices, '20260918': {'A': 999, 'B': 100}}, DAYS,
                      '20260915', '20260917', '20260918', '20260916', (1, 2))
        first_later = next(o for o in later['observations'] if o['day'] == '20260915' and o['code'] == 'A' and o['horizon'] == 1)
        self.assertEqual(a, first_later)

    def test_pending_missing_and_unknown_do_not_become_zero(self):
        flows = {
            '20260914': {'A': flow(-4), 'B': flow(-4), 'C': flow(-4)},
            '20260915': {'A': flow(-2), 'B': flow(-2), 'C': {**flow(-2), 'unknown': 10}},
            '20260916': {'A': flow(-1), 'B': flow(-1)},
        }
        prices = {'20260915': {'A': 100, 'B': 100}, '20260916': {'A': 110}}
        result = study(flows, prices, DAYS, '20260915', '20260916', '20260916', '20260915', (1, 3))
        short = [o for o in result['observations'] if o['day'] == '20260915' and o['horizon'] == 1]
        self.assertEqual({(o['code'], o['status']) for o in short}, {('A', 'OBSERVED'), ('B', 'MISSING_PRICE')})
        self.assertTrue(all(o['status'] == 'PENDING' for o in result['observations'] if o['horizon'] == 3))
        self.assertFalse(any(o['code'] == 'C' for o in result['observations']))
        self.assertNotIn('20260917', result['signalDaysMissingFlow'])
        self.assertTrue(all(s['meanReturnPct'] is None for s in result['summary'] if s['horizon'] == 3))

    def test_missing_trading_session_is_not_bridged(self):
        flows = {'20260914': {'A': flow(-3)}, '20260916': {'A': flow(-1)}}
        result = study(flows, {}, DAYS, '20260915', '20260916', '20260918', '20260915', (1,))
        self.assertEqual(len(result['observations']), 0)
        self.assertEqual([x['day'] for x in result['signalDaysMissingFlow']], ['20260915', '20260916'])

    def test_source_boundary_and_unknown_source_do_not_form_events(self):
        flows = {day: {'A': flow(-4 + index)} for index, day in enumerate(DAYS[:5])}
        prices = {day: {'A': 100 + index} for index, day in enumerate(DAYS[:5])}
        sources = {'20260914': 'LEGACY_CALIBRATED_ROW_GUARD',
                   '20260915': 'LEGACY_CALIBRATED_ROW_GUARD',
                   '20260916': 'NATIVE', '20260917': 'NATIVE',
                   '20260918': 'LEGACY_DIRECTION_UNKNOWN'}
        result = study(flows, prices, DAYS, '20260915', '20260918', '20260918',
                       '20260916', (1,), flow_sources=sources)
        self.assertEqual([row['day'] for row in result['observations']],
                         ['20260915', '20260917'])
        self.assertEqual([row['day'] for row in result['signalDaysExcludedSource']],
                         ['20260916', '20260918'])
        self.assertEqual(result['signalDaysExcludedSource'][0],
                         {'day': '20260916', 'previousDay': '20260915',
                          'previousSource': 'LEGACY_CALIBRATED_ROW_GUARD',
                          'currentSource': 'NATIVE'})
        self.assertEqual(result['signalDaysMissingFlow'], [])
        sources.pop('20260917')
        without_source = study(flows, prices, DAYS, '20260915', '20260918', '20260918',
                               '20260916', (1,), flow_sources=sources)
        self.assertNotIn('20260917', [row['day'] for row in without_source['observations']])

    def test_training_purge_and_oos_are_calendar_based(self):
        flows = {d: {'A': flow(-10 + i)} for i, d in enumerate(DAYS)}
        prices = {d: {'A': 100 + i} for i, d in enumerate(DAYS)}
        result = study(flows, prices, DAYS, '20260915', '20260922', '20260923', '20260918', (1, 2))
        byday = {o['day']: o['cohort'] for o in result['observations']}
        self.assertEqual(byday['20260916'], 'TRAIN')
        self.assertEqual(byday['20260917'], 'EMBARGO')
        self.assertEqual(byday['20260918'], 'EMBARGO')
        self.assertEqual(byday['20260921'], 'OUT_OF_SAMPLE')

    def test_invalid_dates_and_horizons_rejected(self):
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260914', '20260916', '20260918', '20260915')
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260915', '20260916', '20260918', '20260915', (0,))
        with self.assertRaises(ValueError):
            study({}, {}, DAYS, '20260915', '20260916', '20260915', '20260915')

    def test_background_receipt_freezes_summary_and_rejects_changed_source(self):
        identity = ['source-a']
        def calculate(start, end, asof, split, horizons, collect_observations=True, on_observation=None):
            observation = {'day': start, 'code': '000001.SZ', 'rule': 'SELL_EASING',
                           'horizon': 1, 'status': 'OBSERVED', 'returnPct': 2.5,
                           'entryDay': '20260916', 'entryGate': 'ONE_PRICE_SESSION',
                           'closeDrawdownStatus': 'OBSERVED', 'maxCloseDrawdownPct': -1.5,
                           'drawdownPeakDay': '20260915', 'drawdownTroughDay': '20260916'}
            if on_observation:on_observation(observation)
            return {'start': start, 'end': end, 'asof': asof, 'split': split,
                    'horizons': list(horizons), 'sourceIdentity': identity[0],
                    'summary': [], 'observations': [observation] if collect_observations else [],
                    'observationCount': 1,
                    'limitations': []}
        with tempfile.TemporaryDirectory() as temp:
            service = ValidationService(Path(temp), calculator=calculate, identity=lambda *args: identity[0])
            with patch.object(service, 'request', return_value=('20260915', '20260917', '20260918', '20260916', (1,))):
                job = service.start({})
            service.pool.shutdown(wait=True)
            ready = service.status(job['id'])
            self.assertEqual((ready['status'], ready['result']['observationCount']), ('done', 1))
            self.assertNotIn('observations', ready['result'])
            self.assertEqual(service.frozen(ready['receipt'])['start'], '20260915')
            detail = service.detail(ready['receipt'], '000001.SZ')
            self.assertEqual((detail['status'], detail['observations'][0]['returnPct']), ('AVAILABLE', 2.5))
            self.assertEqual((detail['observations'][0]['entryDay'], detail['observations'][0]['entryGate']),
                             ('20260916', 'ONE_PRICE_SESSION'))
            self.assertEqual((detail['observations'][0]['maxCloseDrawdownPct'],
                              detail['observations'][0]['drawdownTroughDay']), (-1.5, '20260916'))
            self.assertEqual(service.detail(ready['receipt'], '000002.SZ')['status'], 'NO_EVENT')
            with self.assertRaises(ValueError):
                service.detail(ready['receipt'], '../bad')
            with self.assertRaises(ValueError):
                service.details(ready['receipt'], ['000001.SZ', '000001.SZ'])
            identity[0] = 'source-b'
            self.assertEqual(service.status(job['id'])['status'], 'stale')
            with self.assertRaisesRegex(ValueError, '来源已变化'):
                service.frozen(ready['receipt'])
            with self.assertRaises(ValueError):
                service.frozen('../bad')
            stored = Path(temp)/'.level2_validation_receipts'/f"{ready['receipt']}.json"
            content = json.loads(stored.read_text())
            content['result']['summary'] = [{'forged': True}]
            stored.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, '内容校验失败'):
                service.frozen(ready['receipt'])

    def test_observation_database_tampering_rejected(self):
        def calculate(*args, collect_observations=True, on_observation=None):
            observation = {'code': '000001.SZ', 'day': args[0]}
            if on_observation:on_observation(observation)
            return {'start': args[0], 'end': args[1], 'asof': args[2], 'split': args[3],
                    'horizons': list(args[4]), 'sourceIdentity': 'same',
                    'summary': [], 'observations': [observation] if collect_observations else [],
                    'observationCount': 1}
        with tempfile.TemporaryDirectory() as temp:
            service = ValidationService(Path(temp), calculator=calculate, identity=lambda *args: 'same')
            with patch.object(service, 'request', return_value=('20260915', '20260917', '20260918', '20260916', (1,))):
                job = service.start({})
            service.pool.shutdown(wait=True)
            token = service.status(job['id'])['receipt']
            database = Path(temp)/'.level2_validation_receipts'/f'{token}.sqlite'
            with database.open('ab') as output:
                output.write(b'changed')
            with self.assertRaisesRegex(ValueError, '逐股证据校验失败'):
                service.detail(token, '000001.SZ')

    def test_equal_day_average_is_not_stock_count_weighted(self):
        flows = {
            '20260915': {'A': flow(-4), 'B': flow(-4), 'C': flow(-4)},
            '20260916': {'A': flow(-2), 'B': flow(-2), 'C': flow(-4)},
            '20260917': {'A': flow(-2), 'B': flow(-2), 'C': flow(-2)},
        }
        prices = {
            '20260916': {'A': 100, 'B': 100, 'C': 100},
            '20260917': {'A': 120, 'B': 120, 'C': 100},
            '20260918': {'A': 120, 'B': 120, 'C': 100},
        }
        result = study(flows, prices, DAYS, '20260915', '20260917', '20260918', '20260915', (1,))
        same_rule = next(x for x in result['summary'] if x['rule'] == 'SELL_EASING' and x['cohort'] == 'OUT_OF_SAMPLE')
        self.assertEqual(same_rule['signalDays'], 2)
        self.assertEqual(same_rule['triggerDays'], 2)
        self.assertEqual(same_rule['observed'], 3)
        self.assertEqual(same_rule['benchmarkPoolMeanN'], 3)
        self.assertAlmostEqual(same_rule['meanExcessPct'], 40 / 9)
        self.assertAlmostEqual(same_rule['equalDayMeanExcessPct'], 10 / 3)
        daily = same_rule['signalDayBreakdown']
        self.assertEqual([row['day'] for row in daily], ['20260916', '20260917'])
        self.assertEqual([(row['events'], row['observed'], row['pending'], row['missingPrice'])
                          for row in daily], [(2, 2, 0, 0), (1, 1, 0, 0)])
        self.assertAlmostEqual(daily[0]['meanReturnPct'], 20)
        self.assertAlmostEqual(daily[0]['benchmarkPct'], 40 / 3)
        self.assertAlmostEqual(daily[0]['meanExcessPct'], 20 / 3)
        self.assertAlmostEqual(daily[1]['meanExcessPct'], 0)
        self.assertAlmostEqual(statistics.mean(row['meanExcessPct'] for row in daily),
                               same_rule['equalDayMeanExcessPct'])

    def test_daily_breakdown_keeps_immature_and_missing_separate(self):
        flows = {'20260914': {'A': flow(-4), 'B': flow(-4)},
                 '20260915': {'A': flow(-2), 'B': flow(-2)},
                 '20260916': {'A': flow(-1), 'B': flow(-1)}}
        prices = {'20260915': {'A': 100, 'B': 100},
                  '20260916': {'A': 105}, '20260917': {'A': 110}}
        result = study(flows, prices, DAYS, '20260915', '20260916', '20260916',
                       '20260915', (1,))
        summary = next(row for row in result['summary']
                       if row['rule'] == 'SELL_EASING' and row['cohort'] == 'OUT_OF_SAMPLE')
        self.assertEqual((summary['signalDays'], summary['triggerDays']), (0, 1))
        rows = summary['signalDayBreakdown']
        self.assertEqual([(row['day'], row['observed'], row['pending'], row['missingPrice'])
                          for row in rows], [('20260916', 0, 2, 0)])
        self.assertIsNone(rows[0]['meanReturnPct'])
        self.assertIsNone(rows[0]['meanExcessPct'])
        self.assertIsNone(rows[0]['benchmarkN'])

    def test_streamed_summary_matches_collected_observations(self):
        flows = {'20260914': {'A': flow(-4), 'B': flow(-4)},
                 '20260915': {'A': flow(-2), 'B': flow(-1)},
                 '20260916': {'A': flow(1), 'B': flow(-3)}}
        prices = {'20260915': {'A': 100, 'B': 100},
                  '20260916': {'A': 102, 'B': 99},
                  '20260917': {'A': 103, 'B': 100}}
        args = (flows, prices, DAYS, '20260915', '20260916', '20260917', '20260915', (1,))
        collected = study(*args)
        emitted = []
        streamed = study(*args, collect_observations=False, on_observation=emitted.append)
        self.assertEqual(streamed['observations'], [])
        self.assertEqual(streamed['observationCount'], len(collected['observations']))
        self.assertEqual(emitted, collected['observations'])
        self.assertEqual(streamed['summary'], collected['summary'])


if __name__ == '__main__':
    unittest.main()
