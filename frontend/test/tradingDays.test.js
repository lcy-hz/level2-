import test from 'node:test'
import assert from 'node:assert/strict'
import { adjacentTradingDay } from '../src/tradingDays.js'

test('adjacent navigation follows the verified calendar without skipping missing-report days', () => {
  const days = ['20260918', '20260921', '20260922', '20260923']
  assert.equal(adjacentTradingDay(days, '20260922', -1), '20260921')
  assert.equal(adjacentTradingDay(days, '20260922', 1), '20260923')
  assert.equal(adjacentTradingDay(days, '20260918', -1), null)
  assert.equal(adjacentTradingDay(days, '20260924', -1), null)
})
