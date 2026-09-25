export function buildChartModel(data, kind) {
  const bars = Array.isArray(data?.bars) ? data.bars : []
  const labels = Array.isArray(data?.labels) ? data.labels : []
  if (!bars.length || !labels.length) return { bars: [], gaps: [], ticks: [], zero: null, labels }
  const low = Math.min(...bars.map(bar => bar[3]))
  const high = Math.max(...bars.map(bar => bar[2]))
  const anchor = kind === 'minute' && Number.isFinite(data.preClose) && data.preClose > 0 ? data.preClose : null
  let floor, ceiling
  if (anchor != null) {
    const deviation = Math.max(Math.abs(high - anchor), Math.abs(low - anchor))
    const radius = deviation + Math.max(deviation * .09, anchor * .003, .01)
    floor = anchor - radius
    ceiling = anchor + radius
  } else {
    const padding = Math.max((high - low) * .09, high * .003, .01)
    floor = low - padding
    ceiling = high + padding
  }
  const top = 14, bottom = 196, left = 52, right = 480
  const step = (right - left) / labels.length
  const width = Math.max(kind === 'minute' ? .8 : 2, step * .58)
  const y = value => top + (ceiling - value) / (ceiling - floor) * (bottom - top)
  const present = new Set(bars.map(bar => bar[0]))
  const maxVolume = Math.max(1, ...bars.map(bar => Number.isFinite(bar[5]) ? bar[5] : 0))
  return {
    labels,
    ticks: Array.from({ length: 5 }, (_, i) => ({ price: floor + (ceiling - floor) * i / 4, y: y(floor + (ceiling - floor) * i / 4) })),
    zero: anchor == null ? null : y(anchor),
    gaps: labels.map((label, index) => ({ label, index, x: left + index * step, width: step })).filter(row => !present.has(row.index)),
    bars: bars.map((bar, index) => {
      const x = left + (bar[0] + .5) * step
      const rising = bar[4] >= bar[1]
      return {
        index, slot: bar[0], x, width, highY: y(bar[2]), lowY: y(bar[3]),
        bodyY: Math.min(y(bar[1]), y(bar[4])), bodyHeight: Math.max(1, Math.abs(y(bar[1]) - y(bar[4]))),
        volumeY: Number.isFinite(bar[5]) ? 268 - bar[5] / maxVolume * 40 : null,
        volumeHeight: Number.isFinite(bar[5]) ? bar[5] / maxVolume * 40 : null,
        color: rising ? '#ff7d8a' : '#55dda1', rising,
      }
    }),
  }
}

export function minuteDrawdownText(data) {
  const item = data?.minuteCloseDrawdown
  if (!item) return '此图表未保存分钟收盘回撤'
  if (item.status === 'MISSING_PRE_CLOSE') return '昨收缺失，分钟收盘回撤未知'
  if (item.status === 'NO_TRADED_MINUTES') return '无可用成交分钟，分钟收盘回撤未知'
  if (item.status !== 'OBSERVED' || !Number.isFinite(item.valuePct)) return '分钟收盘回撤未知'
  const times = item.peakTime && item.troughTime ? `（${item.peakTime} → ${item.troughTime}）` : ''
  return `已观测分钟收盘最大回撤 ${item.valuePct.toFixed(2)}%${times}；成交分钟 ${item.tradedMinutes}/${item.expectedMinutes}`
}
