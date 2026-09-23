"""Independent invariant checks for the embedded, source-backed HTML report."""
import json
import math
import re
from pathlib import Path

path = Path(__file__).with_name('level2-market-scan_20260922.html')
html = path.read_text(encoding='utf-8')
start = re.search(r'const\s+D\s*=\s*', html)
assert start, 'Missing report data'
data, _ = json.JSONDecoder().raw_decode(html[start.end():])
expected_days = ['20260914', '20260915', '20260916', '20260917', '20260918', '20260921', '20260922']
assert [x['day'] for x in data['markets']] == expected_days
cards = {x['code']: x for x in data['cards']}
assert len(cards) == len(data['cards']), 'Duplicate security cards'
assert len(cards) == data['markets'][-1]['stocks'], 'Search universe is smaller than reported coverage'
assert data['markets'][-1]['up'] == 2284
assert data['markets'][-1]['down'] == 2783
assert sum(c['returnSign'] > 0 for c in cards.values()) == data['markets'][-1]['up']
assert sum(c['returnSign'] < 0 for c in cards.values()) == data['markets'][-1]['down']
assert sum(c['returnSign'] == 0 for c in cards.values()) == 142
assert math.isclose(cards['600006.SH']['close'], 5.31, abs_tol=.001), 'Delayed closing snapshot omitted'
bp = cards['301080.SZ']
assert math.isclose(bp['close'], 118.8, abs_tol=.005)
assert math.isclose(bp['ret'], (118.8/116.2-1)*100, abs_tol=.01)
assert math.isclose(bp['amount'], 2608166736.51, abs_tol=1)
assert math.isclose(bp['net'], 63277755.05, abs_tol=1)
assert bp['bookTime'] == 145657000
assert bp['bid'] == 11488 and bp['ask'] == 5900
assert [x['day'] for x in bp['history']] == expected_days
assert bp['history'][-1]['f1'] is None and bp['history'][-1]['f3'] is None
assert math.isclose(bp['history'][0]['ret'], 16.56925031766199, abs_tol=.01)
assert math.isclose(bp['history'][0]['f1'], (90.21/91.74-1)*100, abs_tol=.01)
assert math.isclose(bp['history'][0]['f3'], (99.28/91.74-1)*100, abs_tol=.01)
for card in cards.values():
    if card.get('parents'):
        assert abs(sum(x['n'] for x in card['parents'])-card['net']) <= len(card['parents'])+1, card['code']
    if card.get('history') and card['history'][-1]['day'] == expected_days[-1]:
        assert card['history'][-1]['f1'] is None and card['history'][-1]['f3'] is None, card['code']
    for row in card.get('history', []):
        index = expected_days.index(row['day'])
        if index + 3 >= len(expected_days):
            assert row['f3'] is None, (card['code'], row['day'], 'Future leakage')
print(f'PASS: {len(cards)} stocks, 7 dates; close, return, amount, net, depth, order buckets, and future-boundary checks.')
