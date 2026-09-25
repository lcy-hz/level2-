import test from 'node:test'
import assert from 'node:assert/strict'
import { savedDetailEvidence } from '../src/detailEvidence.js'

test('legacy focus summary remains visible without inventing modern deep evidence', () => {
  const card = { code: '002128.SZ', detail: true, segments: [{ s: '10:30–11:30', a: 9 }, { s: '09:30–10:00', a: 10 }], parents: [{ b: '≥100万', n: 3 }, { b: '<5万', n: 1 }], orders: [{ t: '0', s: 'B' }] }
  const result = savedDetailEvidence(card)
  assert.equal(result.legacySummary, true)
  assert.deepEqual(result.segments.map(row => row.s), ['09:30–10:00', '10:30–11:30'])
  assert.deepEqual(result.parents.map(row => row.b), ['<5万', '≥100万'])
  assert.deepEqual(result.orders, card.orders)
  assert.equal(result.quotePath, undefined)
  assert.equal(card.legacySummary, undefined)
  assert.equal(card.segments[0].s, '10:30–11:30')
  assert.equal(savedDetailEvidence({ detail: false, segments: card.segments }), null)
})

test('modern frozen detail keeps its saved result unchanged', () => {
  const card = { computedDetail: true, detailEvidence: { segments: [], quotePath: { status: 'AVAILABLE' } } }
  assert.equal(savedDetailEvidence(card), card.detailEvidence)
  assert.equal(savedDetailEvidence(null), null)
})
