import test from 'node:test'
import assert from 'node:assert/strict'
import { buildChartModel, minuteBarReturnText, minuteDrawdownText } from '../src/chartModel.js'

test('minute selected bar reports change from previous close without filling unknown baseline', () => {
  assert.equal(minuteBarReturnText([0, 10, 10, 10, 10.5], 10), '较昨收 +5.00%')
  assert.equal(minuteBarReturnText([0, 10, 10, 10, 9.5], 10), '较昨收 -5.00%')
  assert.equal(minuteBarReturnText([0, 10, 10, 10, 10.0001], 10), '较昨收 +0.0010%')
  assert.equal(minuteBarReturnText([0, 10, 10, 10, 10], null), '相对昨收未知')
})

test('minute zero axis remains vertically centered around previous close', () => {
  const model = buildChartModel({ labels: ['09:31', '09:32'], preClose: 10, bars: [[0, 10, 13, 9, 12, 100, 120000]] }, 'minute')
  assert.equal(model.zero, 105)
  assert.equal(model.gaps.length, 1)
  assert.equal(model.gaps[0].label, '09:32')
  assert.equal(model.bars[0].volumeHeight, 40)
})

test('missing previous close keeps zero axis unknown and missing volume unfilled', () => {
  const model = buildChartModel({ labels: ['20260922'], preClose: null, bars: [[0, 10, 11, 9, 10, null, null]] }, 'minute')
  assert.equal(model.zero, null)
  assert.equal(model.bars[0].volumeHeight, null)
  assert.equal(model.bars[0].rising, true)
  assert.deepEqual(buildChartModel({ labels: [], bars: [] }, 'day').bars, [])
})

test('minute close drawdown distinguishes measured, unavailable and old snapshots', () => {
  assert.match(minuteDrawdownText({ minuteCloseDrawdown: { status: 'OBSERVED', valuePct: -2.1247,
    peakTime: '09:42', troughTime: '14:34', tradedMinutes: 238, expectedMinutes: 240 } }),
  /-2\.12%（09:42 → 14:34）；成交分钟 238\/240/)
  assert.match(minuteDrawdownText({ minuteCloseDrawdown: { status: 'MISSING_PRE_CLOSE' } }), /未知/)
  assert.match(minuteDrawdownText({ minuteCloseDrawdown: { status: 'NO_TRADED_MINUTES' } }), /未知/)
  assert.match(minuteDrawdownText({}), /未保存/)
})
