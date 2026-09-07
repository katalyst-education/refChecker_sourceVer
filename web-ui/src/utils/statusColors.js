/**
 * Shared status-to-colour map for document and graph highlights.
 */
export const STATUS_COLORS = Object.freeze({
  verified: { fill: 'rgba(16,185,129,0.30)', stroke: 'rgba(16,185,129,0.95)' },
  error: { fill: 'rgba(239,68,68,0.32)', stroke: 'rgba(220,38,38,0.95)' },
  warning: { fill: 'rgba(245,158,11,0.32)', stroke: 'rgba(202,138,4,0.95)' },
  suggestion: { fill: 'rgba(139,92,246,0.30)', stroke: 'rgba(124,58,237,0.95)' },
  unverified: { fill: 'rgba(148,163,184,0.30)', stroke: 'rgba(100,116,139,0.85)' },
  checking: { fill: 'rgba(16,163,127,0.26)', stroke: 'rgba(16,163,127,0.9)' },
  pending: { fill: 'rgba(148,163,184,0.26)', stroke: 'rgba(100,116,139,0.8)' },
  unchecked: { fill: 'rgba(148,163,184,0.26)', stroke: 'rgba(100,116,139,0.8)' },
  default: { fill: 'rgba(148,163,184,0.28)', stroke: 'rgba(100,116,139,0.85)' },
})

export function normalizeStatus(status) {
  const key = String(status || '').trim().toLowerCase()
  if (!key) return 'default'
  return Object.prototype.hasOwnProperty.call(STATUS_COLORS, key) ? key : 'default'
}

export function getStatusColors(status) {
  return STATUS_COLORS[normalizeStatus(status)]
}

export default getStatusColors

