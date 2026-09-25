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
