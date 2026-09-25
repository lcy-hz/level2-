export const cohortName = { TRAIN: '训练', EMBARGO: '隔离', OUT_OF_SAMPLE: '样本外' }
export const ruleName = { SELL_EASING: '净卖收敛', SELL_WORSENING: '净卖扩大', SELL_TO_BUY: '净卖转净买', BUY_TO_SELL: '净买转净卖' }

export function viewRows(result, cohort = 'OUT_OF_SAMPLE', horizon = 1) {
  if (!result || !Array.isArray(result.summary)) return []
  return result.summary.filter(row => row.cohort === cohort && row.horizon === horizon)
    .sort((a, b) => a.rule.localeCompare(b.rule))
}

export function formatPct(value) {
  if (!Number.isFinite(value)) return '不可计算'
  return `${value > 0 ? '+' : ''}${Math.abs(value) < .005 && value !== 0 ? value.toExponential(2) : value.toFixed(2)}%`
}

export function sessionDefaults(days, asof) {
  if (!Array.isArray(days)) return null
  const index = days.indexOf(asof)
  if (index < 21) return null
  return { start: days[index - 20], split: days[index - 10], end: days[index - 5], asof }
}

export function findStockCode(cards, query) {
  const value = String(query || '').trim().toLowerCase()
  if (!value) return null
  const exact = cards.filter(card => card.code?.toLowerCase() === value || card.name?.toLowerCase() === value)
  if (exact.length === 1) return exact[0].code
  if (exact.length > 1) return null
  const partial = cards.filter(card => card.code?.toLowerCase().includes(value) || card.name?.toLowerCase().includes(value))
  return partial.length === 1 ? partial[0].code : null
}
