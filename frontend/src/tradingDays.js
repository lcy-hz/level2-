export function adjacentTradingDay(days, current, offset) {
  if (!Array.isArray(days) || ![-1, 1].includes(offset)) return null
  const index = days.indexOf(current)
  return index < 0 ? null : days[index + offset] || null
}

export function initialReportDay(rows) {
  if (!Array.isArray(rows)) return ''
  const dates = rows.filter(row => /^\d{8}$/.test(row?.day)).sort((a, b) => b.day.localeCompare(a.day))
  return (dates.find(row => row.status === 'ready') || dates.find(row => row.canBuild) || dates[0])?.day || ''
}

export function observationWindow(value, fallback = 3, maxWindow = 60) {
  const max = Number.isInteger(maxWindow) && maxWindow > 0 ? maxWindow : 60
  const defaultValue = Number.isInteger(fallback) && fallback >= 1 && fallback <= max ? fallback : Math.min(3, max)
  if (value === null || value === undefined || value === '') return defaultValue
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= max ? parsed : defaultValue
}

export function describeDateStatus(row) {
  if (!row) return ''
  const parts = [row.message || '报告状态未知']
  if (Array.isArray(row.missing) && row.missing.length) parts.push(`当日缺少 ${row.missing.join('、')}`)
  if (Array.isArray(row.windowMissing) && row.windowMissing.length) {
    parts.push(`最近 7 交易日缺少正式来源：${row.windowMissing.join('、')}`)
  }
  if (row.canBuild === false && (!Array.isArray(row.window) || row.window.length !== 7)) {
    parts.push('最近 7 交易日日历窗口不完整或不可读取')
  }
  if (row.minute === false) parts.push('当日分钟文件缺失；日级报告可独立判断')
  return parts.join('；')
}
