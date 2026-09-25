import test from 'node:test'
import assert from 'node:assert/strict'
import { filterContinuousStocks } from '../src/continuousFilters.js'

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
