const finite = value => typeof value === 'number' && Number.isFinite(value)
const usable = row => row && finite(row.ratio) && finite(row.amount) && row.amount > 0 && finite(row.net) && !(row.unknown > 0)

export function parseAdvancedFilters(raw = {}) {
  const numeric = ['amountMin', 'amountMax', 'levelMin', 'levelMax', 'deltaMin', 'deltaMax',
    'weightedMin', 'weightedMax', 'priceMin', 'priceMax', 'buyDays', 'sellDays', 'improveTimes', 'worsenTimes']
  const filters = {}
  for (const [key, value] of Object.entries(raw)) {
    if (value === '' || value == null || value === 'all') continue
    if (!numeric.includes(key)) { filters[key] = value; continue }
    const number = Number(value)
    if (!Number.isFinite(number) || (key.startsWith('amount') && number < 0) ||
        (['buyDays', 'sellDays', 'improveTimes', 'worsenTimes'].includes(key) && (!Number.isInteger(number) || number < 1))) {
      return { filters: {}, error: '条件无效：金额须非负，持续次数须为正整数，数值须有限。' }
    }
    filters[key] = number
  }
  for (const key of ['amount', 'level', 'delta', 'weighted', 'price']) {
    if (filters[`${key}Min`] !== undefined && filters[`${key}Max`] !== undefined && filters[`${key}Min`] > filters[`${key}Max`])
      return { filters: {}, error: '条件无效：筛选下限不能大于上限。' }
  }
  return { filters, error: '' }
}

export function matchesAdvanced(stock, filters = {}) {
  const sign = (value, wanted) => !wanted || wanted === 'all' || (finite(value) &&
    (wanted === 'positive' ? value > 0 : wanted === 'negative' ? value < 0 : value === 0))
  if (!sign(stock.priceReturn, filters.price) || !sign(stock.level, filters.levelSign) ||
      !sign(stock.weighted, filters.weightedSign) || !sign(stock.amountChange, filters.volume)) return false
  const p = filters.preset
  if (p === 'relief' && !(stock.level < 0 && stock.viewDelta > 0) ||
      p === 'buyStrong' && !(stock.level > 0 && stock.viewDelta > 0) ||
      p === 'buyWeak' && !(stock.level > 0 && finite(stock.viewDelta) && stock.viewDelta < 0) ||
      p === 'sellStrong' && !(stock.level < 0 && finite(stock.viewDelta) && stock.viewDelta < 0) ||
      p === 'upSell' && !(stock.priceReturn > 0 && finite(stock.weighted) && stock.weighted < 0) ||
      p === 'downBuy' && !(finite(stock.priceReturn) && stock.priceReturn < 0 && stock.weighted > 0)) return false
  const previous = stock.history?.at(-2), latest = stock.history?.at(-1)
  if (filters.turn && filters.turn !== 'all' && (!usable(previous) || !usable(latest) ||
      !(filters.turn === 'toBuy' ? previous.ratio < 0 && latest.ratio > 0 :
        filters.turn === 'toSell' ? previous.ratio > 0 && latest.ratio < 0 :
          filters.turn === 'buy' ? previous.ratio > 0 && latest.ratio > 0 : previous.ratio < 0 && latest.ratio < 0))) return false
  for (const [key, field, scale] of [['amount', 'amount', 1e8], ['level', 'level', 1],
    ['delta', 'viewDelta', 1], ['weighted', 'weighted', 1], ['price', 'priceReturn', 1]]) {
    for (const edge of ['Min', 'Max']) {
      const bound = filters[`${key}${edge}`]
      if (bound !== undefined && (!finite(stock[field]) ||
          (edge === 'Min' ? stock[field] < bound * scale : stock[field] > bound * scale))) return false
    }
  }
  for (const [key, field] of [['buyDays', 'streak'], ['sellDays', 'streak'],
    ['improveTimes', 'improve'], ['worsenTimes', 'worsen']]) {
    if (filters[key] !== undefined && (!finite(stock[field]) || stock[field] < filters[key] ||
        (key === 'buyDays' && stock.sign !== 1) || (key === 'sellDays' && stock.sign !== -1))) return false
  }
  return true
}

const sortable = {
  level: stock => stock.level,
  delta: stock => stock.expected === 1 ? stock.delta : stock.viewDelta,
  weighted: stock => stock.weighted,
  slope: stock => stock.slope,
  streak: stock => stock.streak,
  improve: stock => stock.expected > 1 ? stock.improve : null,
  amount: stock => stock.amount,
  amountRelative: stock => stock.amountRelativePct,
  sizePeer: stock => stock.sizeFlowPercentile,
  liquidityPeer: stock => stock.liquidityFlowPercentile,
  price: stock => stock.priceReturn,
  drawdown: stock => stock.maxCloseDrawdown,
  minuteDrawdown: stock => stock.observedMinuteCloseDrawdown?.status === 'OBSERVED' ? stock.observedMinuteCloseDrawdown.valuePct : null,
  relative: stock => stock.relativeReturn,
}

export function filterContinuousStocks(stocks, names = {}, options = {}) {
  const { query = '', change = 'all', continuity = 'all', coverage = 'all', advanced = {},
    sort = 'code', direction = 'asc' } = options
  const search = query.trim().toLowerCase()
  const result = stocks.filter(stock => {
    if (change !== 'all' && stock.change !== change) return false
    if (continuity === 'known' && !finite(stock.streak)) return false
    if (continuity === 'unknown' && finite(stock.streak)) return false
    const full = Number.isInteger(stock.expected) && stock.expected > 0 && stock.valid === stock.expected
    if (coverage === 'full' && !full) return false
    if (coverage === 'partial' && full) return false
    if (coverage === 'unknown' && finite(stock.level)) return false
    if (!matchesAdvanced(stock, advanced)) return false
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
