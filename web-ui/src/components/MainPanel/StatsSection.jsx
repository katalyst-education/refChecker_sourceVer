import { useState, useMemo } from 'react'
import { useCheckStore } from '../../stores/useCheckStore'
import { useStyleStore } from '../../stores/useStyleStore'
import { filterIssuesForStyle, plural, countLabel } from '../../utils/formatters'
import { buildReferenceSummary } from '../../utils/referenceStatus'

/**
 * Per-stage extraction breakdown for deterministic and LLM extraction.
 */
function PerStageChip({ stats, references }) {
  const refs = Array.isArray(references) ? references : []
  const total = refs.length

  // Prefer backend-emitted counts when present (most accurate). When
  // absent (e.g. older history records, cache hits) derive from the
  // refs array on the client.
  const regex = typeof stats?.regex_count === 'number'
    ? stats.regex_count
    : (stats?.extraction_method === 'bbl' || stats?.extraction_method === 'bib' || stats?.extraction_method === 'regex' ? total : 0)
  const llm = typeof stats?.llm_count === 'number'
    ? stats.llm_count
    : (stats?.extraction_method === 'llm' ? total : 0)

  if (total === 0) return null
  if (regex === 0 && llm === 0) return null

  return (
    <span
      className="inline-flex items-center gap-2 px-2 py-0.5 rounded-full text-xs"
      style={{
        border: '1px solid var(--color-border)',
        background: 'var(--color-bg-tertiary)',
        color: 'var(--color-text-secondary)',
      }}
      title="References extracted by deterministic parsers versus the configured LLM."
    >
      <span style={{ color: 'var(--color-text-muted)' }}>Extracted:</span>
      <span>
        <span style={{ color: 'var(--color-text-secondary)' }}>Regex </span>
        <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>{regex}</span>
      </span>
      <span style={{ opacity: 0.5 }}>·</span>
      <span>
        <span style={{ color: 'var(--color-text-secondary)' }}>LLM </span>
        <span style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>{llm}</span>
      </span>
    </span>
  )
}

/**
 * Stats section showing reference check summary with clickable filters
 * Compact design with refs summary and individual issue counts
 */
export default function StatsSection({ stats, isComplete, references, healthBadge, usageChip }) {
  const statusFilter = useCheckStore(s => s.statusFilter)
  const setStatusFilter = useCheckStore(s => s.setStatusFilter)
  // Hovered filter chip id. Tracked in state (not imperative DOM writes) so a
  // chip never keeps a stale hover fill when the selection changes under the
  // cursor.
  const [hoveredChip, setHoveredChip] = useState(null)

  const handleFilterClick = (filterId) => {
    setStatusFilter(filterId)
  }

  const isFilterActive = statusFilter.length > 0

  // Style-aware summary counters. When the active citation style would
  // suppress an issue (style-conforming author count, NLM venue
  // abbreviation, cosmetic-only), the issue is filtered out of the
  // counts so the chips and progress totals move on style change.
  const styleFormat = useStyleStore(s => s.format)
  const styleFilteredReferences = useMemo(() => {
    if (!Array.isArray(references) || references.length === 0) return references || []
    return references.map(r => {
      if (!r) return r
      const filteredErrors = filterIssuesForStyle(r.errors, r, styleFormat)
      const filteredWarnings = filterIssuesForStyle(r.warnings, r, styleFormat)
      if (filteredErrors === r.errors && filteredWarnings === r.warnings) return r
      return { ...r, errors: filteredErrors, warnings: filteredWarnings }
    })
  }, [references, styleFormat])

  // Suppress style-filtered issue totals from the persisted stats too —
  // otherwise the backend's stats.errors_count/warnings_count would
  // leak through buildReferenceSummary's fallback path even when the
  // derived per-ref counts say zero. Recompute totals from the
  // filtered refs.
  const styleAwareStats = useMemo(() => {
    if (!stats || !Array.isArray(styleFilteredReferences)) return stats
    let errorsCount = 0
    let warningsCount = 0
    let suggestionsCount = 0
    let refsWithErrors = 0
    let refsWithWarningsOnly = 0
    let refsWithSuggestionsOnly = 0
    for (const r of styleFilteredReferences) {
      const e = (r?.errors || []).filter(i => (i?.error_type || '').toLowerCase() !== 'unverified').length
      const w = (r?.warnings || []).length
      const s = (r?.suggestions || []).length
      errorsCount += e
      warningsCount += w
      suggestionsCount += s
      if (e > 0) refsWithErrors += 1
      else if (w > 0) refsWithWarningsOnly += 1
      else if (s > 0) refsWithSuggestionsOnly += 1
    }
    return {
      ...stats,
      errors_count: errorsCount,
      warnings_count: warningsCount,
      suggestions_count: suggestionsCount,
      refs_with_errors: refsWithErrors,
      refs_with_warnings_only: refsWithWarningsOnly,
      refs_with_suggestions_only: refsWithSuggestionsOnly,
    }
  }, [stats, styleFilteredReferences])

  const summaryCounts = useMemo(
    () => buildReferenceSummary({ stats: styleAwareStats, references: styleFilteredReferences, isComplete }),
    [styleAwareStats, styleFilteredReferences, isComplete]
  )

  const refsWithErrors = summaryCounts.references.errors
  const refsWithWarningsOnly = summaryCounts.references.warnings
  const refsWithSuggestionsOnly = summaryCounts.references.suggestions
  const refsVerified = summaryCounts.references.verified
  const refsUnverified = summaryCounts.references.unverified
  const processedRefs = summaryCounts.processedRefs
  const totalRefs = summaryCounts.totalRefs

  const isVerifiedSelected = statusFilter.includes('verified')
  const isErrorSelected = statusFilter.includes('error')
  const isWarningSelected = statusFilter.includes('warning')
  const isSuggestionSelected = statusFilter.includes('suggestion')
  const isUnverifiedSelected = statusFilter.includes('unverified')

  return (
    <div 
      className="rounded-lg border p-3"
      style={{
        backgroundColor: 'var(--color-bg-secondary)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Header row. The summary details wrap within the left group while the
          filter reset remains anchored at the right. */}
      <div className="flex items-start justify-between mb-3 gap-2">
        <div className="flex items-center gap-3 flex-wrap min-w-0 flex-1">
          <h3
            className="font-semibold text-sm"
            style={{ color: 'var(--color-text-primary)' }}
          >
            Summary
          </h3>
          {!isComplete && processedRefs > 0 && processedRefs < totalRefs && (
            <span
              className="text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {processedRefs}/{totalRefs} checked
            </span>
          )}
          {healthBadge}
          {usageChip}
          {/* Per-stage extraction breakdown. */}
          <PerStageChip stats={stats} references={references} />
        </div>
        {/* Right side controls */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Filter indicator — single 'Clear filters' chip whenever any
              of the multi-select Summary chips is active. */}
          {isFilterActive && (
            <button
              onClick={() => useCheckStore.getState().clearStatusFilter()}
              className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium transition-opacity hover:opacity-80 min-w-0 max-w-[220px]"
              style={{
                backgroundColor: 'var(--color-bg-tertiary)',
                color: 'var(--color-text-primary)',
                border: '1px solid var(--color-border)',
              }}
              title="Clear all active filters"
            >
              {/* Capped and truncated: with four or five filters active the
                  label would otherwise crowd out the left-hand badges. */}
              <span className="truncate">
                Filtered: {statusFilter.join(', ')}
              </span>
              <svg className="w-3 h-3 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* The animated walkthrough "video" lives ONLY in the Share popup
          (ShareModal), not inline in the Summary stats — keep this view a
          plain stats summary. (Reverts R24's stats-page placement.) */}

      {/* Reference counts row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>References</span>
        {/* Verified */}
        <button
          onClick={() => handleFilterClick('verified')}
          className="flex items-center gap-1 px-2 py-1 rounded border transition-colors cursor-pointer"
          style={{ 
            backgroundColor: (isVerifiedSelected || hoveredChip === 'verified') ? 'var(--color-success-bg)' : 'transparent',
            borderColor: isVerifiedSelected ? 'var(--color-success)' : 'transparent',
          }}
          onMouseEnter={() => setHoveredChip('verified')}
          onMouseLeave={() => setHoveredChip(prev => (prev === 'verified' ? null : prev))}
          title={`${countLabel(refsVerified, 'reference')} fully verified`}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-success)" />
            <path d="M8.5 12.5l2.5 2.5 4.5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-sm font-bold" style={{ color: 'var(--color-success)' }}>{refsVerified}</span>
        </button>

        {/* Errors */}
        <button
          onClick={() => handleFilterClick('error')}
          disabled={refsWithErrors === 0}
          className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors ${
            refsWithErrors > 0 ? 'cursor-pointer' : 'cursor-default opacity-50'
          }`}
          style={{ 
            backgroundColor: (isErrorSelected || (refsWithErrors > 0 && hoveredChip === 'error')) ? 'var(--color-error-bg)' : 'transparent',
            borderColor: isErrorSelected ? 'var(--color-error)' : 'transparent',
          }}
          onMouseEnter={() => setHoveredChip('error')}
          onMouseLeave={() => setHoveredChip(prev => (prev === 'error' ? null : prev))}
          title={refsWithErrors > 0 ? `${countLabel(refsWithErrors, 'reference')} with ${plural(refsWithErrors, 'an error', 'errors')}` : 'No references with errors'}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" fill="var(--color-error)" />
            <path d="M12 7v6" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1.2" fill="#fff" />
          </svg>
          <span className="text-sm font-bold" style={{ color: refsWithErrors > 0 ? 'var(--color-error)' : 'var(--color-text-muted)' }}>{refsWithErrors}</span>
        </button>

        {/* Warnings */}
        <button
          onClick={() => handleFilterClick('warning')}
          disabled={refsWithWarningsOnly === 0}
          className={`flex items-center gap-1 px-2 py-1 rounded border transition-colors ${
            refsWithWarningsOnly > 0 ? 'cursor-pointer' : 'cursor-default opacity-50'
          }`}
          style={{ 
            backgroundColor: (isWarningSelected || (refsWithWarningsOnly > 0 && hoveredChip === 'warning')) ? 'var(--color-warning-bg)' : 'transparent',
            borderColor: isWarningSelected ? 'var(--color-warning)' : 'transparent',
          }}
          onMouseEnter={() => setHoveredChip('warning')}
          onMouseLeave={() => setHoveredChip(prev => (prev === 'warning' ? null : prev))}
          title={refsWithWarningsOnly > 0 ? `${countLabel(refsWithWarningsOnly, 'reference')} with ${plural(refsWithWarningsOnly, 'a warning', 'warnings')} only` : 'No references with warnings only'}
        >
          <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <path d="M12 2L2 20h20L12 2z" fill="var(--color-warning)" />
            <path d="M12 9v4" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
            <circle cx="12" cy="15.5" r="1" fill="#fff" />
          </svg>
          <span className="text-sm font-bold" style={{ color: refsWithWarningsOnly > 0 ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>{refsWithWarningsOnly}</span>
        </button>

        {/* Suggestions */}
        {refsWithSuggestionsOnly > 0 && (
          <button
            onClick={() => handleFilterClick('suggestion')}
            className="flex items-center gap-1 px-2 py-1 rounded border transition-colors cursor-pointer"
            style={{
              backgroundColor: (isSuggestionSelected || hoveredChip === 'suggestion') ? 'var(--color-suggestion-bg)' : 'transparent',
              borderColor: isSuggestionSelected ? 'var(--color-suggestion)' : 'transparent',
            }}
            onMouseEnter={() => setHoveredChip('suggestion')}
            onMouseLeave={() => setHoveredChip(prev => (prev === 'suggestion' ? null : prev))}
            title={`${countLabel(refsWithSuggestionsOnly, 'reference')} with ${plural(refsWithSuggestionsOnly, 'a suggestion', 'suggestions')} only`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" style={{ color: 'var(--color-suggestion)' }}>
              <path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
            </svg>
            <span className="text-sm font-bold" style={{ color: 'var(--color-suggestion)' }}>{refsWithSuggestionsOnly}</span>
          </button>
        )}

        {/* Unverified - only show if > 0 */}
        {refsUnverified > 0 && (
          <button
            onClick={() => handleFilterClick('unverified')}
            className="flex items-center gap-1 px-2 py-1 rounded border transition-colors cursor-pointer"
            style={{ 
              backgroundColor: (isUnverifiedSelected || hoveredChip === 'unverified') ? 'var(--color-bg-tertiary)' : 'transparent',
              borderColor: isUnverifiedSelected ? 'var(--color-text-muted)' : 'transparent',
            }}
            onMouseEnter={() => setHoveredChip('unverified')}
            onMouseLeave={() => setHoveredChip(prev => (prev === 'unverified' ? null : prev))}
            title={`${countLabel(refsUnverified, 'reference')} could not be verified`}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" fill="var(--color-text-muted)" />
              <text x="12" y="16" textAnchor="middle" fill="#fff" fontSize="12" fontWeight="bold">?</text>
            </svg>
            <span className="text-sm font-bold" style={{ color: 'var(--color-text-muted)' }}>{refsUnverified}</span>
          </button>
        )}

        {/* Separator and total */}
        <span className="text-xs px-1" style={{ color: 'var(--color-text-muted)' }}>of {processedRefs}</span>
      </div>

    </div>
  )
}

