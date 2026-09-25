import test from 'node:test'
import assert from 'node:assert/strict'
import { filterCandidates } from '../src/candidateFilters.js'

const rows = [
  { code: '000001.SZ', name: '甲', label: '主动', returnSign: 1, net: 10 },
  { code: '000002.SZ', name: '乙', label: '被动', returnSign: -1, net: null },
  { code: '000003.SZ', name: '丙', label: '主动', returnSign: 1, net: 20 },
]

test('search and direction intersect without mutating source', () => {
  const original = rows.map(row => row.code)
  assert.deepEqual(filterCandidates(rows, { query: '00000', direction: 'up' }).map(row => row.code), ['000001.SZ', '000003.SZ'])
  assert.deepEqual(filterCandidates(rows, { label: '被动', direction: 'down' }).map(row => row.code), ['000002.SZ'])
  assert.deepEqual(rows.map(row => row.code), original)
})

test('descending sort leaves unknown values last', () => {
  assert.deepEqual(filterCandidates(rows, { order: 'net' }).map(row => row.code), ['000003.SZ', '000001.SZ', '000002.SZ'])
})
