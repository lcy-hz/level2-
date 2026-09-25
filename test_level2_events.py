import unittest

from level2_events import observe


def row(day, ratio, unknown=0):
    return {'day': day, 'ratio': ratio, 'amount': 100,
            'net': None if ratio is None else ratio, 'unknown': unknown}


class DailyEventTests(unittest.TestCase):
    def test_trigger_then_lifecycle_uses_only_later_observations(self):
        history=[row('01',-8),row('02',-6),row('03',-4),row('04',2)]
        first=observe(history[:2])[0]
        self.assertEqual((first['kind'],first['status'],first['triggerDay']),('SELL_EASING','ACTIVE','02'))
        self.assertEqual(observe(history[:3])[0]['status'],'ACTIVE')
        final=observe(history)[0]
        self.assertEqual((final['status'],final['endDay']),('RESOLVED','04'))
        cross=next(event for event in observe(history) if event['kind']=='SELL_TO_BUY')
        self.assertEqual((cross['triggerDay'],cross['status']),('04','ACTIVE'))
        self.assertEqual(first['evidence'],final['evidence'])

    def test_gap_unknown_stops_continuity_without_recovery_or_false_zero(self):
        history=[row('01',-8),row('02',-6),row('03',None),row('04',-4)]
        events=observe(history)
        self.assertEqual(len(events),1)
        self.assertEqual((events[0]['status'],events[0]['endDay']),('UNKNOWN','03'))
        self.assertEqual(observe([row('01',-8),row('02',-6,unknown=1)]),[])

    def test_strict_crossing_zero_and_worsening_invalidation(self):
        self.assertEqual(observe([row('01',-1),row('02',0),row('03',1)]),[])
        history=[row('01',-3),row('02',-5),row('03',-4)]
        event=observe(history)[0]
        self.assertEqual((event['kind'],event['status'],event['endDay']),('SELL_WORSENING','INVALIDATED','03'))
        reverse=observe([row('01',2),row('02',-1),row('03',-2),row('04',0)])[0]
        self.assertEqual((reverse['kind'],reverse['status'],reverse['endDay']),('BUY_TO_SELL','INVALIDATED','04'))

    def test_one_day_no_window_internal_event(self):
        self.assertEqual(observe([row('02',-6)]),[])


if __name__=='__main__':
    unittest.main()
