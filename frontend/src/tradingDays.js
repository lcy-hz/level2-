export function adjacentTradingDay(days, current, offset) {
  if (!Array.isArray(days) || ![-1, 1].includes(offset)) return null
  const index = days.indexOf(current)
  return index < 0 ? null : days[index + offset] || null
}
