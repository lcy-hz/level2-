import test from 'node:test'
import assert from 'node:assert/strict'
import { findStockCode, formatPct, mixedSourceWarning, sessionDefaults, sourcePair, sourceStrata, viewRows } from '../src/validationModel.js'

test('source pairs expose cross-regime days without filling old snapshots', () => {
  const result = { flowSources: [
    { day: '20260831', status: 'LEGACY_CALIBRATED_ROW_GUARD' },
    { day: '20260901', status: 'NATIVE' },
    { day: '20260902', status: 'MISSING' },
    { day: '20260903', status: 'NATIVE' },
  ] }
  assert.equal(sourcePair(result, '20260901'), '旧格式已校准 → 正式新格式')
  assert.equal(sourcePair(result, '20260903'), '缺档 → 正式新格式')
  assert.equal(sourcePair(result, '20260831'), '前日来源未覆盖')
  assert.equal(sourcePair({}, '20260901'), '旧结果未保存来源')
  assert.equal(mixedSourceWarning(result), true)
  assert.equal(mixedSourceWarning({ flowSources: result.flowSources.slice(1) }), false)
  const strata = sourceStrata(result, [
    { day: '20260901', observed: 2, meanExcessPct: 1 },
    { day: '20260902', observed: 0, meanExcessPct: null },
    { day: '20260903', observed: 3, meanExcessPct: 3 },
  ])
  assert.deepEqual(strata.map(row => [row.label, row.triggerDays, row.comparableDays,
    row.comparableEvents, row.equalDayMeanExcessPct]), [
    ['旧格式已校准 → 正式新格式', 1, 1, 2, 1],
    ['正式新格式 → 缺档', 1, 0, 0, null],
    ['缺档 → 正式新格式', 1, 1, 3, 3],
  ])
  assert.equal(sourceStrata({}, []), null)
  const sameSource = { flowSources: [
    { day: '20260901', status: 'NATIVE' }, { day: '20260902', status: 'NATIVE' },
    { day: '20260903', status: 'NATIVE' },
  ] }
  assert.equal(sourceStrata(sameSource, [
    { day: '20260902', observed: 100, meanExcessPct: 1 },
    { day: '20260903', observed: 1, meanExcessPct: -1 },
  ])[0].equalDayMeanExcessPct, 0)
})

test('validation rows retain maturity and split, with no fabricated zero', () => {
  const result = { summary: [
    { cohort: 'OUT_OF_SAMPLE', horizon: 5, rule: 'SELL_EASING', observed: 0, pending: 20, meanReturnPct: null },
    { cohort: 'TRAIN', horizon: 5, rule: 'SELL_EASING', observed: 20, pending: 0, meanReturnPct: 1 },
    { cohort: 'OUT_OF_SAMPLE', horizon: 1, rule: 'BUY_TO_SELL', observed: 18, pending: 0, meanReturnPct: -0.01 },
  ] }
  assert.equal(viewRows(result, 'OUT_OF_SAMPLE', 5).length, 1)
  assert.equal(viewRows(result, 'OUT_OF_SAMPLE', 5)[0].pending, 20)
  assert.equal(formatPct(null), '不可计算')
  assert.equal(formatPct(0.0001), '+1.00e-4%')
})

test('default dates follow trading-day list without a fixed calendar date', () => {
  const days = Array.from({ length: 23 }, (_, i) => String(i + 1).padStart(8, '0'))
  assert.deepEqual(sessionDefaults(days, days[22]), {
    start: days[2], split: days[12], end: days[17], asof: days[22],
  })
  assert.equal(sessionDefaults(days.slice(0, 10), days[9]), null)
})

test('stock lookup requires an unambiguous code or name', () => {
  const cards = [{code:'301080.SZ',name:'百普赛斯'}, {code:'600584.SH',name:'长电科技'},
    {code:'601669.SH',name:'中国电建'}]
  assert.equal(findStockCode(cards,'百普赛斯'),'301080.SZ')
  assert.equal(findStockCode(cards,'600584'),'600584.SH')
  assert.equal(findStockCode(cards,'电'),null)
  assert.equal(findStockCode(cards,'unknown'),null)
})
