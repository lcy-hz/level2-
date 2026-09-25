export function flowNarrative(stock, applicable) {
  if (!applicable) return '一日窗口不比较窗口外前日；资金变化不适用。'
  if (!Number.isFinite(stock?.viewDelta) || !Number.isFinite(stock?.level)) return '相邻两日方向证据不足，无法判断改善或恶化。'
  const level = stock.level > 0 ? '净买入' : stock.level < 0 ? '净卖出' : '净额为零'
  const movement = stock.viewDelta > 0
    ? stock.level < 0 ? '卖压减轻但仍为净卖出' : '主动净额比提高'
    : stock.viewDelta < 0
      ? stock.level > 0 ? '净买入仍在但边际减弱' : '主动净额比下降'
      : '主动净额比持平'
  return `当前${level}；${movement}。不构成吸筹或交易确认。`
}

export function observedTransitions(stock) {
  if (stock?.improve == null || stock?.worsen == null) return '连续改善／恶化：未知'
  return `${stock.improveCensored ? '至少 ' : ''}${stock.improve} 次连续改善 · ${stock.worsenCensored ? '至少 ' : ''}${stock.worsen} 次连续恶化`
}
