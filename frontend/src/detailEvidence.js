// Historical HTML snapshots froze summary tables on the card itself. Keep
// that evidence distinct from the newer on-demand detail calculation.
export function savedDetailEvidence(card, day) {
  if (!card) return null
  if (card.computedDetail && card.detailEvidence &&
      ((card.detailEvidence.code && card.code && card.detailEvidence.code !== card.code) ||
       (day && card.detailEvidence.day && card.detailEvidence.day !== day))) return null
  if (card.computedDetail && card.detailEvidence &&
      Array.isArray(card.detailEvidence.segments) && Array.isArray(card.detailEvidence.parents) &&
      Array.isArray(card.detailEvidence.orders)) return card.detailEvidence
  if ((card.detail === true || card.computedDetail === true) &&
      Array.isArray(card.segments) && Array.isArray(card.parents) && Array.isArray(card.orders)) {
    const buckets = ['<5万', '5–20万', '20–100万', '≥100万']
    return {
      ...card,
      legacySummary: true,
      segments: Array.isArray(card.segments) ? [...card.segments].sort((a, b) => String(a.s).localeCompare(String(b.s))) : card.segments,
      parents: Array.isArray(card.parents) ? [...card.parents].sort((a, b) => buckets.indexOf(a.b) - buckets.indexOf(b.b)) : card.parents,
    }
  }
  return null
}
