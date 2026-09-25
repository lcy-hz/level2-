// Historical HTML snapshots froze summary tables on the card itself. Keep
// that evidence distinct from the newer on-demand detail calculation.
export function savedDetailEvidence(card) {
  if (!card) return null
  if (card.computedDetail) return card.detailEvidence || card
  if (card.detail === true) {
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
