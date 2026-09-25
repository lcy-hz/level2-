import test from 'node:test'
import assert from 'node:assert/strict'
import { flowNarrative, observedTransitions } from '../src/continuousEvidence.js'

test('funding narrative separates current sign from marginal change', () => {
  assert.match(flowNarrative({ level: -2, viewDelta: 0.001 }, true), /卖压减轻但仍为净卖出/)
  assert.match(flowNarrative({ level: 2, viewDelta: -0.001 }, true), /净买入仍在但边际减弱/)
  assert.match(flowNarrative({ level: 0, viewDelta: 0 }, true), /净额为零；主动净额比持平/)
  assert.match(flowNarrative({ level: null, viewDelta: null }, true), /证据不足/)
  assert.match(flowNarrative({ level: 1, viewDelta: 1 }, false), /一日窗口/)
})

test('continuous transition counts preserve left censoring and unknown', () => {
  assert.equal(observedTransitions({ improve: 2, worsen: 1, improveCensored: true, worsenCensored: false }), '至少 2 次连续改善 · 1 次连续恶化')
  assert.equal(observedTransitions({ improve: 0, worsen: 2, improveCensored: false, worsenCensored: true }), '0 次连续改善 · 至少 2 次连续恶化')
  assert.match(observedTransitions({ improve: null, worsen: 2 }), /未知/)
})
