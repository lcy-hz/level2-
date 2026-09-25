import test from 'node:test'
import assert from 'node:assert/strict'
import { adjacentTradingDay, initialReportDay } from '../src/tradingDays.js'

test('adjacent navigation follows the verified calendar without skipping missing-report days', () => {
  const days = ['20260918', '20260921', '20260922', '20260923']
  assert.equal(adjacentTradingDay(days, '20260922', -1), '20260921')
  assert.equal(adjacentTradingDay(days, '20260922', 1), '20260923')
  assert.equal(adjacentTradingDay(days, '20260918', -1), null)
  assert.equal(adjacentTradingDay(days, '20260924', -1), null)
})

test('initial report date prefers latest ready evidence, then buildable source', () => {
  assert.equal(initialReportDay([{ day: '20260924', status: 'missing', canBuild: true },
    { day: '20260922', status: 'ready' }, { day: '20260923', status: 'ready' }]), '20260923')
  assert.equal(initialReportDay([{ day: '20260921', status: 'missing' },
    { day: '20260922', status: 'missing', canBuild: true }]), '20260922')
  assert.equal(initialReportDay([{ day: '20260921', status: 'missing' }]), '20260921')
  assert.equal(initialReportDay([]), '')
})
