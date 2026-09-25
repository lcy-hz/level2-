export function filterCandidates(cards, { query = '', label = 'all', direction = 'all', order = 'default' } = {}) {
  const search = query.trim().toLowerCase()
  const result = cards.filter(card =>
    (label === 'all' || card.label === label) &&
    (direction === 'all' || (direction === 'up' ? card.returnSign > 0 : direction === 'down' ? card.returnSign < 0 : card.returnSign === 0)) &&
    (!search || card.code.toLowerCase().includes(search) || card.name.toLowerCase().includes(search)))
  if (order !== 'default') result.sort((a, b) => {
    const av = a[order], bv = b[order]
    return (av == null) - (bv == null) || (bv ?? -Infinity) - (av ?? -Infinity) || a.code.localeCompare(b.code)
  })
  return result
}
