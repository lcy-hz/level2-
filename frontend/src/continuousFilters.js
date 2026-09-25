const finite = value => typeof value === 'number' && Number.isFinite(value)

const sortable = {
  level: stock => stock.level,
  delta: stock => stock.expected === 1 ? stock.delta : stock.viewDelta,
  weighted: stock => stock.weighted,
  slope: stock => stock.slope,
  streak: stock => stock.streak,
  improve: stock => stock.expected > 1 ? stock.improve : null,
  amount: stock => stock.amount,
  amountRelative: stock => stock.amountRelativePct,
  price: stock => stock.priceReturn,
  drawdown: stock => stock.maxCloseDrawdown,
  relative: stock => stock.relativeReturn,
}

export function filterContinuousStocks(stocks, names = {}, options = {}) {
  const { query = '', change = 'all', continuity = 'all', coverage = 'all',
    sort = 'code', direction = 'asc' } = options
  const search = query.trim().toLowerCase()
  const result = stocks.filter(stock => {
    if (change !== 'all' && stock.change !== change) return false
    if (continuity === 'known' && !finite(stock.streak)) return false
    if (continuity === 'unknown' && finite(stock.streak)) return false
    const full = Number.isInteger(stock.expected) && stock.expected > 0 && stock.valid === stock.expected
    if (coverage === 'full' && !full) return false
    if (coverage === 'partial' && full) return false
    return !search || `${stock.code} ${names[stock.code] || ''}`.toLowerCase().includes(search)
  })
  const value = sortable[sort]
  result.sort((a, b) => {
    if (!value) return (direction === 'desc' ? -1 : 1) * a.code.localeCompare(b.code)
    const av = value(a), bv = value(b)
    if (!finite(av)) return finite(bv) ? 1 : a.code.localeCompare(b.code)
    if (!finite(bv)) return -1
    return (direction === 'desc' ? bv - av : av - bv) || a.code.localeCompare(b.code)
  })
  return result
}
