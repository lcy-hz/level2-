import test from 'node:test'
import assert from 'node:assert/strict'
import { filterCandidates, normalizeCandidateFilters, stateNarrative } from '../src/candidateFilters.js'

const rows = [
  { code: '000001.SZ', name: '甲', label: '主动', returnSign: 1, net: 10 },
  { code: '000002.SZ', name: '乙', label: '被动', returnSign: -1, net: null },
  { code: '000003.SZ', name: '丙', label: '主动', returnSign: 1, net: 20 },
]

test('historical snapshot filter labels restore without changing the frozen bundle', () => {
  const saved = { search: '000001', filter: '全部', direction: 'all', sort: 'net', sortOrder: 'asc' }
  const restored = normalizeCandidateFilters(saved)
  assert.equal(restored.filter, 'all')
  assert.equal(restored.sortDirection, 'asc')
  assert.deepEqual(filterCandidates(rows, { query: restored.search, label: restored.filter,
    direction: restored.direction, order: restored.sort, orderDirection: restored.sortDirection }).map(row => row.code), ['000001.SZ'])
  assert.equal(saved.filter, '全部')
  assert.equal(saved.sortDirection, undefined)
  assert.equal(normalizeCandidateFilters({ filter: '被动', sortDirection: 'desc', sortOrder: 'asc' }).filter, '被动')
  assert.equal(normalizeCandidateFilters({ sortDirection: 'desc', sortOrder: 'asc' }).sortDirection, 'desc')
})

test('search and direction intersect without mutating source', () => {
  const original = rows.map(row => row.code)
  assert.deepEqual(filterCandidates(rows, { query: '00000', direction: 'up' }).map(row => row.code), ['000001.SZ', '000003.SZ'])
  assert.deepEqual(filterCandidates(rows, { label: '被动', direction: 'down' }).map(row => row.code), ['000002.SZ'])
  assert.deepEqual(rows.map(row => row.code), original)
})

test('descending sort leaves unknown values last', () => {
  assert.deepEqual(filterCandidates(rows, { order: 'net' }).map(row => row.code), ['000003.SZ', '000001.SZ', '000002.SZ'])
})

test('legacy focus defaults to deep-researched cards but explicit filters use the full universe', () => {
  const sample = rows.map((row, index) => ({ ...row, detail: index !== 1 }))
  assert.deepEqual(filterCandidates(sample, { focusOnly: true }).map(row => row.code),
    ['000001.SZ', '000003.SZ'])
  assert.deepEqual(filterCandidates(sample, { query: '乙', focusOnly: false }).map(row => row.code),
    ['000002.SZ'])
})

test('default candidate order preserves each report or frozen snapshot record order', () => {
  const report = [rows[2], rows[0], rows[1]].map(card => ({ ...card, detail: true }))
  assert.deepEqual(filterCandidates(report, { focusOnly: true }).map(card => card.code),
    ['000003.SZ', '000001.SZ', '000002.SZ'])
  assert.deepEqual(report.map(card => card.code), ['000003.SZ', '000001.SZ', '000002.SZ'])
})

test('candidate filters intersect with the applied continuous window and sort missing last both ways', () => {
  const stateView = { applicable: true, stocks: [
    { code: '000001.SZ', change: 'improve', level: -1, viewDelta: 0.00001, streak: 2 },
    { code: '000002.SZ', change: 'unknown', level: null, viewDelta: null, streak: null },
    { code: '000003.SZ', change: 'worsen', level: 1, viewDelta: -2, streak: 1 },
  ] }
  const codes = options => filterCandidates(rows, { stateView, ...options }).map(row => row.code)
  assert.deepEqual(codes({ order: 'stateDelta', orderDirection: 'desc' }), ['000001.SZ', '000003.SZ', '000002.SZ'])
  assert.deepEqual(codes({ order: 'stateDelta', orderDirection: 'asc' }), ['000003.SZ', '000001.SZ', '000002.SZ'])
  assert.deepEqual(codes({ label: '主动', stateChange: 'improve', stateContinuity: 'known' }), ['000001.SZ'])
  assert.deepEqual(codes({ stateContinuity: 'unknown' }), ['000002.SZ'])
  assert.deepEqual(filterCandidates(rows, { order: 'net', orderDirection: 'asc' }).map(row => row.code),
    ['000001.SZ', '000003.SZ', '000002.SZ'])
  assert.deepEqual(rows.map(row => row.code), ['000001.SZ', '000002.SZ', '000003.SZ'])
})

test('one-day state sorts valid prior-day delta but has no within-window transition filter', () => {
  const stateView = { applicable: false, stocks: [
    { code: '000001.SZ', expected: 1, delta: 1, viewDelta: null },
    { code: '000002.SZ', expected: 1, delta: null, viewDelta: null },
    { code: '000003.SZ', expected: 1, delta: -1, viewDelta: null },
  ] }
  assert.deepEqual(filterCandidates(rows, { stateView, order: 'stateDelta' }).map(row => row.code),
    ['000001.SZ', '000003.SZ', '000002.SZ'])
  assert.deepEqual(filterCandidates(rows, { stateView, stateChange: 'improve' }), [])
})

test('narrative separates flow and price, and unknown never becomes absorption claim', () => {
  assert.match(stateNarrative({ ret: 2 }, { level: -2, viewDelta: 1 }), /仍为净卖出.*价格上涨与主动净卖出并存/)
  assert.match(stateNarrative({ ret: -1 }, { level: 2, viewDelta: -1 }), /净买入.*边际减弱.*价格下跌/)
  assert.match(stateNarrative({ ret: 1 }, { level: null, viewDelta: 1 }), /证据不足/)
  assert.match(stateNarrative({ ret: 1 }, null), /未应用/)
})
