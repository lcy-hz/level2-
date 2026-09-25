export const cohortName = { TRAIN: '训练', EMBARGO: '隔离', OUT_OF_SAMPLE: '样本外' }
export const ruleName = { SELL_EASING: '净卖收敛', SELL_WORSENING: '净卖扩大', SELL_TO_BUY: '净卖转净买', BUY_TO_SELL: '净买转净卖' }
const sourceName = { NATIVE: '正式新格式', LEGACY_CALIBRATED_ROW_GUARD: '旧格式已校准',
  LEGACY_DIRECTION_UNKNOWN: '旧格式方向未知', MISSING: '缺档', UNCOMMITTED: '未提交', UNKNOWN_SCHEMA: '模式未知' }

export function sourcePair(result, day) {
  const sources = result?.flowSources
  if (!Array.isArray(sources)) return '旧结果未保存来源'
  const index = sources.findIndex(item => item.day === day)
  if (index < 1) return '前日来源未覆盖'
  const previous = sources[index - 1]?.status
  const current = sources[index]?.status
  return `${sourceName[previous] || '来源未知'} → ${sourceName[current] || '来源未知'}`
}

export function mixedSourceWarning(result) {
  const statuses = new Set(result?.flowSources?.map(item => item.status) || [])
  return statuses.has('NATIVE') && statuses.has('LEGACY_CALIBRATED_ROW_GUARD')
}

export function sourceStrata(result, dailyRows) {
  if (!Array.isArray(result?.flowSources) || !Array.isArray(dailyRows)) return null
  const strata = new Map()
  for (const day of dailyRows) {
    const label = sourcePair(result, day.day)
    if (!strata.has(label)) strata.set(label, { label, triggerDays: 0, comparableDays: 0,
      comparableEvents: 0, excessSum: 0 })
    const row = strata.get(label)
    row.triggerDays++
    if (Number.isFinite(day.meanExcessPct)) {
      row.comparableDays++
      row.comparableEvents += day.observed || 0
      row.excessSum += day.meanExcessPct
    }
  }
  return [...strata.values()].map(row => ({ label: row.label, triggerDays: row.triggerDays,
    comparableDays: row.comparableDays, comparableEvents: row.comparableEvents,
    equalDayMeanExcessPct: row.comparableDays ? row.excessSum / row.comparableDays : null }))
}

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
