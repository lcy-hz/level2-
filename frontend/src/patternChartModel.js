const palette = ['#f4ce80', '#83c9ff', '#d29adb']
export const indicatorFields = {
  MACD: ['macd_dif_qfq', 'macd_dea_qfq', 'macd_qfq'],
  RSI6: ['rsi_qfq_6'],
  KDJ: ['kdj_k_qfq', 'kdj_d_qfq', 'kdj_qfq'],
}

export function buildPatternChart(detail, event, options = {}) {
  if (!detail?.dates || !event) return null
  const begin = Math.max(0, event.start - 20), end = detail.dates.length - 1
  const valid = detail.bars.slice(begin).filter(Boolean)
  if (!valid.length) return null
  const indicator = options.indicator || 'MACD'
  const showMA = options.showMA !== false, showSignals = options.showSignals !== false
  const prices = valid.flatMap(bar => [bar[1], bar[2]])
  if (showMA) for (const row of detail.indicators.slice(begin)) for (const field of ['ma_qfq_5', 'ma_qfq_20']) {
    if (Number.isFinite(row?.[field])) prices.push(row[field])
  }
  if (showSignals) for (const value of [event.key, event.stop]) if (Number.isFinite(value)) prices.push(value)
  const min = Math.min(...prices), max = Math.max(...prices)
  const pad = Math.max((max - min) * .02, max * .002, .01)
  const lo = min - pad, hi = max + pad
  const step = 530 / (end - begin + 1), x = index => 55 + (index - begin + .5) * step
  const y = value => 200 - (value - lo) / (hi - lo) * 175
  const volumeMax = Math.max(1, ...valid.map(bar => bar[4] || 0))
  const bars = []
  for (let index = begin; index <= end; index++) {
    const bar = detail.bars[index]
    if (!bar) { bars.push({ index, x: x(index), missing: true, width: step }); continue }
    const rising = bar[3] >= bar[0]
    bars.push({ index, x: x(index), missing: false, width: Math.max(2, step * .6),
      highY: y(bar[1]), lowY: y(bar[2]), bodyY: Math.min(y(bar[0]), y(bar[3])),
      bodyHeight: Math.max(1, Math.abs(y(bar[0]) - y(bar[3]))),
      volumeY: Number.isFinite(bar[4]) ? 250 - bar[4] / volumeMax * 35 : null,
      volumeHeight: Number.isFinite(bar[4]) ? bar[4] / volumeMax * 35 : null,
      color: rising ? '#ff8795' : '#53ddbc', rising })
  }
  function segments(field, transform) {
    const lines = []; let points = []
    for (let index = begin; index <= end; index++) {
      const value = detail.indicators[index]?.[field]
      if (Number.isFinite(value)) points.push(`${x(index)},${transform(value)}`)
      else if (points.length) { lines.push(points.join(' ')); points = [] }
    }
    if (points.length) lines.push(points.join(' '))
    return lines
  }
  const mas = showMA ? [['ma_qfq_5', '#f5d07e'], ['ma_qfq_20', '#83c9ff']].map(([field, color]) => ({ field, color, lines: segments(field, y) })) : []
  const fields = indicatorFields[indicator] || indicatorFields.MACD
  const values = detail.indicators.slice(begin).flatMap(row => fields.map(field => row?.[field]).filter(Number.isFinite))
  const lower = Math.min(0, ...values), upper = Math.max(1, ...values)
  const iy = value => 330 - (value - lower) / (upper - lower) * 60
  return { begin, end, bars, mas, indicators: values.length ? fields.map((field, index) => ({ field, color: palette[index], lines: segments(field, iy) })) : [],
    signals: showSignals ? [['关键位', event.key], ['失效位', event.stop]].filter(([, value]) => Number.isFinite(value)).map(([label, value]) => ({ label, value, y: y(value) })) : [],
    anchors: showSignals ? (event.anchors || []).map(([index, value]) => ({ index, x: x(index), y: y(value) })) : [],
    transitions: showSignals ? (event.transitions || []).filter(item => detail.bars[item.index]).map(item => ({ ...item, x: x(item.index), y: y(detail.bars[item.index][1]) - 7 })) : [],
    ticks: Array.from({ length: 4 }, (_, index) => ({ price: lo + (hi - lo) * index / 3, y: y(lo + (hi - lo) * index / 3) })),
    x, indicator,
  }
}
