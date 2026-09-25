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

export function priceDirection(sign) {
  if (sign === 1) return { text: '↑ 上涨', tone: 'positive' }
  if (sign === -1) return { text: '↓ 下跌', tone: 'negative' }
  if (sign === 0) return { text: '— 平盘', tone: 'neutral' }
  return { text: '— 未知', tone: 'unknown' }
}

export function directionQuality(status) {
  if (status === 'AVAILABLE') return '方向可计算'
  if (status === 'UNKNOWN') return '资金方向不可判定'
  return '方向状态未核验'
}

export function futureCloseChange(value) {
  if (!finite(value)) return '报告窗口内未观察'
  return `${value > 0 ? '+' : ''}${value !== 0 && Math.abs(value) < .005 ? value.toExponential(2) : value.toFixed(2)}%`
}

export function snapshotClock(value) {
  if (!Number.isInteger(value) || value < 0) return '未知'
  const digits = String(value).padStart(9, '0')
  if (digits.length !== 9) return `格式待核验（原值 ${value}）`
  const hour = Number(digits.slice(0, 2))
  const minute = Number(digits.slice(2, 4))
  const second = Number(digits.slice(4, 6))
  if (hour > 23 || minute > 59 || second > 59) return `格式待核验（原值 ${value}）`
  const millis = digits.slice(6)
  return `${digits.slice(0, 2)}:${digits.slice(2, 4)}:${digits.slice(4, 6)}${millis === '000' ? '' : `.${millis}`}`
}

// Historical HTML snapshots used the visible label for "all" and a different
// sort-direction key. Normalize only the UI state; keep the frozen bundle intact.
export function normalizeCandidateFilters(saved = {}) {
  return {
    search: '', filter: 'all', direction: 'all', sort: 'default',
    ...saved,
    filter: saved.filter === '全部' ? 'all' : saved.filter || 'all',
    sortDirection: saved.sortDirection || saved.sortOrder || 'desc',
  }
}

export function summarizeCandidatePools(lists, cards) {
  if (!lists || typeof lists !== 'object' || !Object.values(lists).some(Array.isArray)) return null
  const pools = Object.entries(lists).filter(([, codes]) => Array.isArray(codes)).map(([name, codes]) => ({ name, count: codes.length }))
  const pooled = new Set(Object.values(lists).filter(Array.isArray).flat())
  const extra = cards.filter(card => card.detail && !pooled.has(card.code)).map(card => card.code)
  return { pools, extra }
}

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
