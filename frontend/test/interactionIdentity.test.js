import test from 'node:test'
import assert from 'node:assert/strict'
import { evidencePanelKey, requestGeneration } from '../src/interactionIdentity.js'

test('same-day report reload has a distinct component evidence identity', () => {
  const report = { mode: 'live', day: '20260922' }
  assert.notEqual(evidencePanelKey(report, 1), evidencePanelKey(report, 2))
  assert.notEqual(evidencePanelKey(report, 2), evidencePanelKey({ id: 'snapshot-1', day: report.day }, 3))
})

test('staging another window rejects both completed and failed stale requests', () => {
  const requests = requestGeneration()
  const old = requests.begin()
  assert.equal(requests.accepts(old), true)
  requests.invalidate()
  assert.equal(requests.accepts(old), false)
  const current = requests.begin()
  assert.equal(requests.accepts(old), false)
  assert.equal(requests.accepts(current), true)
})
