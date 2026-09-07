import { useEffect, useMemo, useRef, useState } from 'react'
import anime from 'animejs'
import { filterIssuesForStyle } from '../../utils/formatters'
import { useStyleStore } from '../../stores/useStyleStore'
import { buildReferenceSummary } from '../../utils/referenceStatus'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Minimal "Citation health" chip. Live — recomputes on every edit because
 * it's derived from the current `references` prop. Pure CSS, matches the
 * app theme; intentionally NOT an SVG (user feedback: "minimalistic
 * design not svg"). Hover for the per-status breakdown.
 *
 * Style-aware: when the active citation style would suppress some
 * issues (style-conforming author count, NLM venue abbreviations,
 * cosmetic-only differences), those issues are excluded from the
 * error/warning counts so the score moves when the user flips the
 * dropdown. Matches what the Corrections view shows.
 */

export function computeScore(references, style) {
  const list = Array.isArray(references) ? references : []
  const total = list.length
  if (total === 0) return { score: null, total: 0 }

  // Use the canonical style-aware summary shared with the report card.
  const styleFiltered = list.map((r) => {
    if (!r) return r
    const fe = filterIssuesForStyle(r?.errors, r, style)
    const fw = filterIssuesForStyle(r?.warnings, r, style)
    if (fe === r?.errors && fw === r?.warnings) return r
    return { ...r, errors: fe, warnings: fw }
  })
  const refSummary = buildReferenceSummary({ references: styleFiltered, isComplete: true }).references
  // verified already folds suggestion-only refs in (matches the "Verified" chip).
  const verified = refSummary.verified
  const errors = refSummary.errors
  const warnings = refSummary.warnings
  // Keep this formula identical to backend/export.compute_health.
  const verifyRatio = verified / total
  const cleanRatio = Math.max(0, (total - errors) / total)
  const raw = verifyRatio * 70 + cleanRatio * 30 - (warnings / total) * 5
  const score = Math.max(0, Math.min(100, Math.round(raw)))
  return { score, total, verified, errors, warnings }
}

function colorFor(score) {
  if (score == null) return 'var(--color-text-muted)'
  if (score >= 90) return '#22c55e'
  if (score >= 70) return '#84cc16'
  if (score >= 50) return '#f59e0b'
  if (score >= 30) return '#f97316'
  return '#ef4444'
}

export default function HealthBadge({ references }) {
  const activeFormat = useStyleStore(s => s.format)
  const stats = useMemo(() => computeScore(references, activeFormat), [references, activeFormat])
  const color = colorFor(stats.score)

  // anime.js count-up: the score ticks from its previous value to the new one
  // when references change (e.g. after "apply all fixes"). Reduced-motion users
  // see the final number immediately. Snapshot kept in a ref to avoid re-anim
  // on unrelated re-renders.
  const [shown, setShown] = useState(stats.score)
  const prev = useRef(stats.score)
  useEffect(() => {
    const target = stats.score
    if (target == null) { setShown(null); prev.current = null; return undefined }
    if (prefersReducedMotion() || prev.current == null) { setShown(target); prev.current = target; return undefined }
    const obj = { v: prev.current }
    const anim = anime({
      targets: obj, v: target, duration: 650, easing: 'easeOutCubic', round: 1,
      update: () => setShown(Math.round(obj.v)),
      complete: () => { prev.current = target },
    })
    return () => anim.pause()
  }, [stats.score])
  const tooltip = stats.total === 0
    ? 'No references checked yet'
    : `${stats.verified || 0} verified · ${stats.warnings || 0} warning${stats.warnings === 1 ? '' : 's'} · ${stats.errors || 0} error${stats.errors === 1 ? '' : 's'} · ${stats.total} total`

  return (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium"
      style={{
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-secondary)',
        lineHeight: 1.4,
      }}
    >
      <span
        className="inline-block rounded-full"
        style={{ width: 6, height: 6, background: color }}
      />
      <span style={{ color: 'var(--color-text-secondary)' }}>Citation health</span>
      <span style={{ color, fontWeight: 600 }}>
        {shown == null ? '—' : `${shown}%`}
      </span>
    </span>
  )
}


