import test from 'node:test'
import assert from 'node:assert/strict'
import { filterPatterns } from '../src/patternFilters.js'

const result = { dates: ['1', '2', '3'], catalog: [{ id: 'a' }, { id: 'b' }], stocks: [
  { code: '000001.SZ', name: '甲', quality: 'available', coverage: { a: true, b: true }, close: 10,
    amount: 2e8, volumeRatio: 1.5, indicators: { ma_qfq_20: 9, macd_qfq: 1 },
    events: [{ pattern: 'a', stage: 'confirmed', active: true, direction: 1, detected: 2, distance: 2 }] },
  { code: '000002.SZ', name: '乙', quality: 'insufficient', coverage: { a: false, b: false }, amount: null,
    events: [] },
  { code: '000003.SZ', name: '丙', quality: 'available', coverage: { a: true, b: true }, amount: 1e8,
    events: [{ pattern: 'b', stage: 'invalidated', active: false, direction: -1, detected: 1, distance: -2 }] },
] }

test('pattern stages, coverage, combinations and L2 levels remain independent', () => {
  assert.deepEqual(filterPatterns(result).rows.map(row => row.stock.code), ['000001.SZ'])
  assert.deepEqual(filterPatterns(result, { stage: 'all' }).rows.map(row => row.stock.code), ['000001.SZ', '000003.SZ'])
  assert.deepEqual(filterPatterns(result, { quality: 'insufficient' }).rows.map(row => row.stock.code), ['000002.SZ'])
  assert.equal(filterPatterns(result, { types: ['a', 'b'], combination: 'every' }).rows.length, 0)
  assert.deepEqual(filterPatterns(result, { l2: 'positive' }, { '000001.SZ': 1 }).rows.map(row => row.stock.code), ['000001.SZ'])
  assert.equal(filterPatterns(result, { l2: 'unknown' }, { '000001.SZ': 1 }).rows.length, 0)
})

test('invalid range and numeric criteria do not silently become zero', () => {
  assert.match(filterPatterns(result, { distanceMin: '2', distanceMax: '1' }).error, /无效/)
  assert.match(filterPatterns(result, { age: '1.5' }).error, /无效/)
  assert.deepEqual(filterPatterns(result, { amount: '1.5' }).rows.map(row => row.stock.code), ['000001.SZ'])
  assert.deepEqual(filterPatterns(result, { age: '0' }).rows.map(row => row.stock.code), ['000001.SZ'])
})

test('recently detected event is the visible leading evidence', () => {
  const many = structuredClone(result)
  many.stocks[0].events.unshift({ pattern: 'a', eventId: 'old', stage: 'forming', active: true, direction: 1, detected: 0, distance: 1 })
  many.stocks[0].events[1].eventId = 'new'
  assert.deepEqual(filterPatterns(many).rows[0].events.map(event => event.eventId), ['new', 'old'])
})
