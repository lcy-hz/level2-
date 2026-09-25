export const defaultPatternFilters = {
  search: '', stage: 'active', direction: 'all', quality: 'all', types: [], combination: 'any',
  timeField: 'detected', age: '', amount: '', vol: '', distanceMin: '', distanceMax: '',
  ma: 'all', macd: 'all', l2: 'all', sort: 'detected', page: 1,
}

const supplied = value => value !== '' && value != null
const numeric = value => supplied(value) && Number.isFinite(Number(value)) ? Number(value) : null
export function filterPatterns(result, options = {}, levels = {}) {
  if (!result?.stocks || !result?.catalog) return { rows: [], error: null }
  const filter = { ...defaultPatternFilters, ...options }
  const selected = Array.isArray(filter.types) ? filter.types : []
  const scope = selected.length ? selected : result.catalog.map(item => item.id)
  const age = numeric(filter.age), amount = numeric(filter.amount), vol = numeric(filter.vol)
  const distanceMin = numeric(filter.distanceMin), distanceMax = numeric(filter.distanceMax)
  if ([age, amount, vol].some(value => value !== null && value < 0) || (age !== null && !Number.isInteger(age)) ||
      (distanceMin !== null && distanceMax !== null && distanceMin > distanceMax) ||
      ['age', 'amount', 'vol', 'distanceMin', 'distanceMax'].some(key => supplied(filter[key]) && numeric(filter[key]) === null)) {
    return { rows: [], error: '筛选数值无效：检查交易日整数、非负金额与量比，以及距离上下限。' }
  }
  const query = String(filter.search || '').trim().toLowerCase()
  const rows = []
  for (const stock of result.stocks) {
    if (query && !`${stock.code} ${stock.name}`.toLowerCase().includes(query)) continue
    const coverage = scope.some(id => stock.coverage?.[id])
    const events = stock.events.filter(event => {
      if (!scope.includes(event.pattern)) return false
      if (filter.stage === 'active' && !(event.active && ['forming', 'confirmed'].includes(event.stage))) return false
      if (!['all', 'active'].includes(filter.stage) && event.stage !== filter.stage) return false
      if (filter.direction !== 'all' && event.direction !== { bull: 1, bear: -1, neutral: 0 }[filter.direction]) return false
      const moment = event[filter.timeField]
      if (age !== null && (!Number.isInteger(moment) || result.dates.length - 1 - moment > age)) return false
      if (distanceMin !== null && !(Number.isFinite(event.distance) && event.distance >= distanceMin)) return false
      if (distanceMax !== null && !(Number.isFinite(event.distance) && event.distance <= distanceMax)) return false
      return true
    }).sort((a, b) => (b.detected ?? -1) - (a.detected ?? -1) || a.eventId?.localeCompare(b.eventId || '') || 0)
    if (filter.quality === 'anomaly' ? stock.quality !== 'anomaly' :
        filter.quality === 'insufficient' ? coverage :
        filter.quality === 'none' ? !coverage || events.length > 0 :
        filter.quality === 'available' ? !coverage || !events.length : !events.length) continue
    if (selected.length && filter.combination === 'every' && !selected.every(id => events.some(event => event.pattern === id))) continue
    if (amount !== null && (!Number.isFinite(stock.amount) || stock.amount < amount * 1e8)) continue
    if (vol !== null && (!Number.isFinite(stock.volumeRatio) || stock.volumeRatio < vol)) continue
    const ma20 = stock.indicators?.ma_qfq_20, close = stock.close, macd = stock.indicators?.macd_qfq
    if (filter.ma !== 'all' && (!Number.isFinite(ma20) || !Number.isFinite(close) || (filter.ma === 'above' ? close <= ma20 : close >= ma20))) continue
    if (filter.macd !== 'all' && (!Number.isFinite(macd) || (filter.macd === 'positive' ? macd <= 0 : macd >= 0))) continue
    const flow = levels[stock.code]
    if (filter.l2 === 'positive' && !(flow > 0) || filter.l2 === 'negative' && !(flow < 0) || filter.l2 === 'unknown' && Number.isFinite(flow)) continue
    rows.push({ stock, events })
  }
  rows.sort((a, b) => filter.sort === 'name' ? a.stock.code.localeCompare(b.stock.code) :
    filter.sort === 'amount' ? (b.stock.amount ?? -Infinity) - (a.stock.amount ?? -Infinity) || a.stock.code.localeCompare(b.stock.code) :
    Math.max(-1, ...b.events.map(event => event.detected)) - Math.max(-1, ...a.events.map(event => event.detected)) || a.stock.code.localeCompare(b.stock.code))
  return { rows, error: null }
}
