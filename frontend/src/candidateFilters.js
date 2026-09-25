const finite = value => typeof value === 'number' && Number.isFinite(value)
const stateMetric = {
  stateLevel: stock => stock.level,
  stateDelta: stock => stock.expected === 1 ? stock.delta : stock.viewDelta,
  stateWeighted: stock => stock.weighted,
  stateSlope: stock => stock.expected > 1 ? stock.slope : null,
  stateStreak: stock => stock.streak,
  stateImprove: stock => stock.expected > 1 ? stock.improve : null,
}
const cardMetrics = new Set(['net', 'ret', 'amount'])

export function filterCandidates(cards, { query = '', label = 'all', direction = 'all', order = 'default',
  orderDirection = 'desc', stateChange = 'all', stateContinuity = 'all', stateView = null,
  focusOnly = false } = {}) {
  const search = query.trim().toLowerCase()
  const states = new Map((stateView?.stocks || []).map(stock => [stock.code, stock]))
  const result = cards.filter(card =>
    (!focusOnly || card.detail) &&
    (label === 'all' || card.label === label) &&
    (direction === 'all' || (direction === 'up' ? card.returnSign > 0 : direction === 'down' ? card.returnSign < 0 : card.returnSign === 0)) &&
    (!search || card.code.toLowerCase().includes(search) || card.name.toLowerCase().includes(search)) &&
    (stateChange === 'all' || (stateView?.applicable && states.get(card.code)?.change === stateChange)) &&
    (stateContinuity === 'all' || (stateContinuity === 'known' ? finite(states.get(card.code)?.streak) : !finite(states.get(card.code)?.streak))))
  if (cardMetrics.has(order) || Object.hasOwn(stateMetric, order)) result.sort((a, b) => {
    const metric = Object.hasOwn(stateMetric, order) ? stateMetric[order] : null
    const av = metric ? metric(states.get(a.code) || {}) : a[order]
    const bv = metric ? metric(states.get(b.code) || {}) : b[order]
    if (!finite(av)) return finite(bv) ? 1 : a.code.localeCompare(b.code)
    if (!finite(bv)) return -1
    return (orderDirection === 'asc' ? av - bv : bv - av) || a.code.localeCompare(b.code)
  })
  return result
}

export function stateNarrative(card, stock, applicable = true) {
  if (!stock) return '未应用同日报告的连续观察窗口，无法描述资金变化。'
  const delta = applicable ? stock.viewDelta : stock.delta
  if (!finite(stock.level) || !finite(delta)) return '主动方向或相邻日证据不足，资金变化未知；不得补零。'
  const flow = stock.level < 0
    ? delta > 0 ? '仍为净卖出，但净额比较前日改善' : delta < 0 ? '净卖出且净额比继续恶化' : '净卖出且净额比持平'
    : stock.level > 0
      ? delta < 0 ? '仍为净买入，但净额比边际减弱' : delta > 0 ? '净买入且净额比继续改善' : '净买入且净额比持平'
      : '当日净额比为零；较前日变化需单独观察'
  const divergence = card.ret > 0 && stock.level < 0 ? '；价格上涨与主动净卖出并存'
    : card.ret < 0 && stock.level > 0 ? '；价格下跌与主动净买入并存' : ''
  return `${flow}${divergence}。这不证明被动吸筹、派发或可交易买卖点。`
}
