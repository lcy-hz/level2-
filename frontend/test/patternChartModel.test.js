import test from 'node:test'
import assert from 'node:assert/strict'
import { buildPatternChart } from '../src/patternChartModel.js'

test('pattern chart keeps missing sessions as gaps and does not connect MA across them', () => {
  const detail = { dates: ['1', '2', '3'], bars: [[10, 11, 9, 10, 100, 2], null, [10, 12, 9, 11, 200, 3]],
    indicators: [{ ma_qfq_5: 10, macd_qfq: .1 }, {}, { ma_qfq_5: 11, macd_qfq: .2 }] }
  const event = { start: 0, key: 10, stop: 9, anchors: [], transitions: [] }
  const model = buildPatternChart(detail, event)
  assert.equal(model.bars[1].missing, true)
  assert.equal(model.bars[2].volumeHeight, 35)
  assert.equal(model.mas[0].lines.length, 2)
  assert.deepEqual(model.signals.map(row => row.label), ['关键位', '失效位'])
})
