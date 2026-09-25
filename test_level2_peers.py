import tempfile
import unittest
from pathlib import Path

from level2_peers import market_caps, rank_peers


class PeerTests(unittest.TestCase):
    def test_market_value_source_requires_exact_date_and_unique_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);day='20260922';file=root/f'{day}_daily_basic.csv'
            self.assertEqual(market_caps(None,day)[1]['status'],'NOT_CONFIGURED')
            self.assertEqual(market_caps(root,day)[1]['status'],'MISSING_FILE')
            file.write_text('ts_code,trade_date,total_mv\nA,20260922,100\nB,20260922,\n')
            values,evidence=market_caps(root,day)
            self.assertEqual(evidence['status'],'AVAILABLE')
            self.assertEqual(evidence['coverage'],1)
            self.assertEqual(values,{'A':100,'B':None})
            file.write_text(file.read_text()+'C,20260923,200\n')
            self.assertEqual(market_caps(root,day)[1]['status'],'INVALID_DATE')
            file.write_text('ts_code,trade_date,total_mv\nA,20260922,100\nA,20260922,101\n')
            self.assertEqual(market_caps(root,day)[1]['status'],'DUPLICATE_CODE')

    def test_cap_and_liquidity_cohorts_are_separate_and_unknown_flow_is_excluded(self):
        states={f'{index:06d}.SZ':{'amount':index+1,'level':index if index<39 else None}
                for index in range(40)}
        caps={code:40-index for index,code in enumerate(states)}
        evidence=rank_peers(states,caps,{'status':'AVAILABLE','source':'test','day':'20260922','coverage':40})
        self.assertEqual((evidence['sizeCoverage'],evidence['liquidityCoverage']),(40,40))
        first=states['000000.SZ']
        self.assertEqual((first['sizeGroup'],first['liquidityGroup']),(2,1))
        self.assertEqual((first['sizePeerCount'],first['liquidityPeerCount']),(20,20))
        self.assertAlmostEqual(first['sizeFlowPercentile'],2.5)
        self.assertAlmostEqual(first['liquidityFlowPercentile'],2.5)
        self.assertIsNone(states['000039.SZ']['liquidityFlowPercentile'])
        self.assertEqual(states['000039.SZ']['liquidityPeerCount'],19)
        self.assertEqual(states['000039.SZ']['sizePeerCount'],19)

    def test_tied_flows_get_same_midrank_and_missing_cap_stays_unknown(self):
        states={str(i):{'amount':i+1,'level':0 if i<20 else None} for i in range(20)}
        evidence=rank_peers(states,{}, {'status':'MISSING_FILE','source':'missing','day':'20260922','coverage':0})
        self.assertEqual((evidence['sizeCoverage'],evidence['liquidityCoverage']),(0,20))
        self.assertIsNone(states['0']['sizeGroup'])
        self.assertEqual(states['0']['liquidityFlowPercentile'],50)
        self.assertEqual(states['19']['liquidityFlowPercentile'],50)


if __name__=='__main__':unittest.main()
