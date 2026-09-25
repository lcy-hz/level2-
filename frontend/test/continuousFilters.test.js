import test from 'node:test'
import assert from 'node:assert/strict'
import { filterContinuousStocks, parseAdvancedFilters } from '../src/continuousFilters.js'

const stocks = [
  { code: '000003.SZ', change: 'unknown', level: null, viewDelta: null, weighted: null, slope: null, streak: null, improve: null, valid: 1, expected: 3 },
  { code: '000002.SZ', change: 'improve', level: -2, viewDelta: 0.00001, weighted: -1, slope: 0.1, streak: 3, improve: 2, valid: 3, expected: 3 },
  { code: '000001.SZ', change: 'worsen', level: 2, viewDelta: -0.5, weighted: 1, slope: -0.2, streak: 2, improve: 0, valid: 3, expected: 3 },
  { code: '000004.SZ', change: 'improve', level: -1, viewDelta: 0.00001, weighted: -0.5, slope: null, streak: 1, improve: 0, valid: 2, expected: 3 },
]
const codes = rows => rows.map(row => row.code)

test('both sort directions keep unknown last, preserve numeric precision, and tie by code', () => {
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { sort: 'delta', direction: 'desc' })),
    ['000002.SZ', '000004.SZ', '000001.SZ', '000003.SZ'])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { sort: 'delta', direction: 'asc' })),
    ['000001.SZ', '000002.SZ', '000004.SZ', '000003.SZ'])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { sort: 'code', direction: 'desc' })),
    ['000004.SZ', '000003.SZ', '000002.SZ', '000001.SZ'])
  assert.deepEqual(codes(stocks), ['000003.SZ', '000002.SZ', '000001.SZ', '000004.SZ'])
})

test('search, change, coverage and continuity filters intersect without filling missing values', () => {
  assert.deepEqual(codes(filterContinuousStocks(stocks, { '000002.SZ': '百普赛斯' },
    { query: '百普', change: 'improve', continuity: 'known', coverage: 'full' })), ['000002.SZ'])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { continuity: 'unknown' })), ['000003.SZ'])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { coverage: 'partial' })), ['000003.SZ', '000004.SZ'])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { change: 'flat' })), [])
  assert.deepEqual(codes(filterContinuousStocks(stocks, {}, { coverage: 'unknown' })), ['000003.SZ'])
})

test('legacy advanced presets, numeric ranges and strict turn filters retain unknown values', () => {
  const rows = [
    { code: 'A', level: -2, viewDelta: 0.2, weighted: -1, priceReturn: 1, amount: 2e8,
      amountChange: -4, sign: -1, streak: 2, improve: 1, history: [
        { ratio: -3, amount: 10, net: -3 }, { ratio: -2, amount: 10, net: -2 }] },
    { code: 'B', level: 2, viewDelta: 3, weighted: 1, priceReturn: -1, amount: 3e8,
      amountChange: 5, sign: 1, streak: 1, improve: 2, history: [
        { ratio: -1, amount: 10, net: -1 }, { ratio: 2, amount: 10, net: 2 }] },
    { code: 'C', level: null, viewDelta: null, weighted: null, priceReturn: null, amount: null },
  ]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { preset: 'relief', amountMin: 1 } })), ['A'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { preset: 'downBuy', turn: 'toBuy' } })), ['B'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { levelMin: -2, levelMax: 2, price: 'positive' } })), ['A'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { amountMax: 1 } })), [])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { buyDays: 1 } })), ['B'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { advanced: { volume: 'negative' } })), ['A'])
})

test('advanced numeric parser rejects invalid bounds instead of treating blanks or unknown as zero', () => {
  assert.deepEqual(parseAdvancedFilters({ amountMin: '', preset: 'all' }), { filters: {}, error: '' })
  assert.equal(parseAdvancedFilters({ amountMin: '2', amountMax: '1' }).error.length > 0, true)
  assert.equal(parseAdvancedFilters({ improveTimes: '0' }).error.length > 0, true)
  assert.equal(parseAdvancedFilters({ levelMin: 'Infinity' }).error.length > 0, true)
  assert.deepEqual(parseAdvancedFilters({ levelMin: '-0.1', amountMax: '3' }).filters,
    { levelMin: -0.1, amountMax: 3 })
})

test('one-day improvement count cannot be ranked as measured persistence', () => {
  const rows = [{ code: 'A', expected: 1, improve: 0 }, { code: 'B', expected: 2, improve: 1 }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'improve' })), ['B', 'A'])
})

test('one-day stock delta may compare with a valid prior day outside the window', () => {
  const rows = [{ code: 'A', expected: 1, delta: 0.1, viewDelta: null },
    { code: 'B', expected: 1, delta: null, viewDelta: null },
    { code: 'C', expected: 1, delta: -0.2, viewDelta: null }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'delta', direction: 'desc' })), ['A', 'C', 'B'])
})

test('close drawdown sorts zero as observed and missing values last', () => {
  const rows = [{ code: 'A', maxCloseDrawdown: 0 }, { code: 'B', maxCloseDrawdown: -12 },
    { code: 'C', maxCloseDrawdown: null }, { code: 'D', maxCloseDrawdown: -3 }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'drawdown', direction: 'asc' })), ['B', 'D', 'A', 'C'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'drawdown', direction: 'desc' })), ['A', 'D', 'B', 'C'])
})

test('window minute drawdown sorts only observed values and keeps unavailable last', () => {
  const observed = valuePct => ({ status: 'OBSERVED', valuePct })
  const rows = [{ code: 'A', observedMinuteCloseDrawdown: observed(0) },
    { code: 'B', observedMinuteCloseDrawdown: observed(-8) },
    { code: 'C', observedMinuteCloseDrawdown: { status: 'INCOMPLETE_MINUTES', valuePct: null } },
    { code: 'D' }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'minuteDrawdown', direction: 'asc' })), ['B', 'A', 'C', 'D'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'minuteDrawdown', direction: 'desc' })), ['A', 'B', 'C', 'D'])
})

test('relative benchmark sort retains legitimate zero and unknown last', () => {
  const rows = [{ code: 'A', relativeReturn: 0 }, { code: 'B', relativeReturn: -2 },
    { code: 'C', relativeReturn: null }, { code: 'D', relativeReturn: 3 }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'relative', direction: 'asc' })), ['B', 'A', 'D', 'C'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'relative', direction: 'desc' })), ['D', 'A', 'B', 'C'])
})

test('relative turnover sorts observed zero while missing stays last', () => {
  const rows = [{ code: 'A', amountRelativePct: 0 }, { code: 'B', amountRelativePct: -25 },
    { code: 'C', amountRelativePct: null }, { code: 'D', amountRelativePct: 50 }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'amountRelative', direction: 'asc' })), ['B', 'A', 'D', 'C'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'amountRelative', direction: 'desc' })), ['D', 'A', 'B', 'C'])
})

test('peer percentile sorts valid observations and leaves unknown last', () => {
  const rows = [{ code: 'A', sizeFlowPercentile: 50, liquidityFlowPercentile: null },
    { code: 'B', sizeFlowPercentile: 20, liquidityFlowPercentile: 80 },
    { code: 'C', sizeFlowPercentile: null, liquidityFlowPercentile: 20 }]
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'sizePeer', direction: 'desc' })), ['A', 'B', 'C'])
  assert.deepEqual(codes(filterContinuousStocks(rows, {}, { sort: 'liquidityPeer', direction: 'asc' })), ['C', 'B', 'A'])
})
