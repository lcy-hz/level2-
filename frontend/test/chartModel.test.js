import test from 'node:test'
import assert from 'node:assert/strict'
import { buildChartModel } from '../src/chartModel.js'

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
