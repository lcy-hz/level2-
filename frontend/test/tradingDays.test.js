import test from 'node:test'
import assert from 'node:assert/strict'
import { adjacentTradingDay, describeDateStatus, initialReportDay } from '../src/tradingDays.js'

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

test('date status names missing files and trading days without treating minute data as the report gate', () => {
  const blocked = describeDateStatus({ message: '报告待计算', missing: ['deal', 'COMMITTED'],
    window: ['20260901', '20260903'], windowMissing: ['20260901'], canBuild: false, minute: false })
  assert.match(blocked, /当日缺少 deal、COMMITTED/)
  assert.match(blocked, /正式来源：20260901/)
  assert.match(blocked, /交易日日历窗口不完整或不可读取/)
  assert.match(blocked, /分钟文件缺失；日级报告可独立判断/)
  const calendar = describeDateStatus({ message: '报告待计算', missing: [], window: [],
    windowMissing: [], canBuild: false, minute: true })
  assert.match(calendar, /交易日日历窗口不完整或不可读取/)
  assert.equal(describeDateStatus({ message: '报告可查看', missing: [],
    window: Array(7).fill('20260922'), windowMissing: [], canBuild: true, minute: true }), '报告可查看')
})
