import { useMemo } from 'react'
import ReferenceCard from '../ReferenceCard/ReferenceCard'
import { useCheckStore } from '../../stores/useCheckStore'
import { applyStatusFilter, getEffectiveReferenceStatus } from '../../utils/referenceStatus'
import useReferenceActions from '../../hooks/useReferenceActions'
import { useStyleStore } from '../../stores/useStyleStore'
import {
  CITATION_STYLES,
  filterIssuesForStyle,
  listCustomCitationStyles,
} from '../../utils/formatters'
import { referenceRowIdentity } from '../../utils/referenceIdentity'
import {
  AddReferencePanel,
  SuggestAltPanel,
  ReferenceRowActions,
} from './ReferenceActionsBar'

/**
 * Derive status from reference data, trusting backend final statuses
 * @param {Object} ref - Reference object
 * @param {boolean} isCheckComplete - Whether the overall check has completed/cancelled
 */
const computeDerivedStatus = (ref, isCheckComplete = false) => {
  return getEffectiveReferenceStatus(ref, isCheckComplete)
}

/**
 * List of references being checked
 */
export default function ReferenceList({ references, isLoading, isCheckComplete = false }) {
  const statusFilter = useCheckStore(s => s.statusFilter)
  const {
    selectedCheckId,
    busyKey,
    globalBusy,
    showAdd,
    setShowAdd,
    newRef,
    setNewRef,
    suggestFor,
    setSuggestFor,
    handleAddRef,
    handleRemoveRef,
    handleSuggestAlt,
    handleReverify,
    handleReverifyAllDatabases,
    getReferenceSearchOperation,
    handleCancelReferenceSearch,
    handleEditMetadata,
    handleRestoreExtractedMetadata,
    removedRefs,
    handleRestoreRef,
    clearRemovedRefs,
    getReverifyAction,
    isReverifying,
    isSuggesting,
    isRemoving,
  } = useReferenceActions()

  const activeStyle = useStyleStore(s => s.format)

  // Memoize all derived data to ensure consistency within a render
  const { sortedReferences, filteredReferences } = useMemo(() => {
    const sorted = (references || []).slice().sort((a, b) => {
      const aIndex = typeof a?.index === 'number' ? a.index : Number.MAX_SAFE_INTEGER
      const bIndex = typeof b?.index === 'number' ? b.index : Number.MAX_SAFE_INTEGER
      return aIndex - bIndex
    })

    // Apply style-aware issue filtering BEFORE deriving status. Without
    // this, a ref whose only issue is a style-suppressed venue mismatch
    // (e.g. "AJNR Am J Neuroradiol" under Vancouver) renders with a red
    // error indicator on the row even though the Summary chips, health
    // badge, and Corrections tab — all of which DO style-filter —
    // report 0 errors / 0 corrections / 100% health. Aligning the row's
    // status with the rest of the UI removes that contradiction.
    const styleFiltered = sorted.map(ref => {
      const filteredErrors = filterIssuesForStyle(ref.errors, ref, activeStyle)
      const filteredWarnings = filterIssuesForStyle(ref.warnings, ref, activeStyle)
      if (filteredErrors === ref.errors && filteredWarnings === ref.warnings) {
        return ref
      }
      return { ...ref, errors: filteredErrors, warnings: filteredWarnings }
    })

    const normalized = styleFiltered.map(ref => ({
      ...ref,
      status: computeDerivedStatus(ref, isCheckComplete),
      errors: Array.isArray(ref.errors) ? ref.errors : [],
      warnings: Array.isArray(ref.warnings) ? ref.warnings : [],
    }))

    // Keep the list filter and the Summary chips on the same shared status
    // contract. In particular, a reference verified from a website is part of
    // the verified bucket even though it has a distinct display icon.
    const filtered = applyStatusFilter(normalized, statusFilter, isCheckComplete)

    return { sortedReferences: sorted, filteredReferences: filtered }
  }, [references, statusFilter, isCheckComplete, activeStyle])

  if (isLoading) {
    return (
        <div
            className="rounded-lg border p-8 text-center"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: 'var(--color-border)',
            }}
        >
          <svg
              className="animate-spin h-8 w-8 mx-auto mb-3"
              fill="none"
              viewBox="0 0 24 24"
              style={{ color: 'var(--color-accent)' }}
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p style={{ color: 'var(--color-text-muted)' }}>
            Loading references...
          </p>
        </div>
    )
  }

  if (!references || references.length === 0) {
    // Differentiate "still extracting" from "extractor finished and found
    // nothing" — the latter case used to look identical to a working check
    // mid-extraction, which confused users into thinking the tool had hung.
    const finished = !!isCheckComplete
    return (
        <div
            className="rounded-lg border p-8 text-center"
            style={{
              backgroundColor: 'var(--color-bg-secondary)',
              borderColor: finished ? 'var(--color-warning, #f59e0b)' : 'var(--color-border)',
            }}
        >
          <svg
              className="w-12 h-12 mx-auto mb-3 opacity-60"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              style={{ color: finished ? 'var(--color-warning, #f59e0b)' : 'var(--color-text-muted)' }}
          >
            {finished ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            )}
          </svg>
          <p style={{ color: 'var(--color-text-primary)', fontWeight: 600 }}>
            {finished ? 'No references found in this document' : 'No references extracted yet'}
          </p>
          <p
              className="text-sm mt-1"
              style={{ color: 'var(--color-text-muted)' }}
          >
            {finished
                ? 'The extractor finished but produced zero references. The file may have no bibliography, the wrong format, or the extraction mode may need to be changed (Settings → Reference Extraction).'
                : 'References will appear here as they are found.'}
          </p>
        </div>
    )
  }

  return (
      <div
          className="rounded-lg border overflow-hidden relative"
          style={{
            backgroundColor: 'var(--color-bg-secondary)',
            borderColor: 'var(--color-border)',
          }}
      >
        <div
            className="px-4 py-3 border-b flex items-center justify-between relative"
            style={{ borderColor: 'var(--color-border)', minHeight: '48px' }}
        >
          <h3
              className="font-semibold"
              style={{ color: 'var(--color-text-primary)' }}
          >
            References ({sortedReferences.length})
          </h3>
          <div className="flex items-center gap-3 absolute right-4">
            {statusFilter.length > 0 && (
                <span
                    className="text-sm px-2 py-1 rounded"
                    style={{
                      backgroundColor: 'var(--color-bg-tertiary)',
                      color: 'var(--color-text-secondary)'
                    }}
                >
              Showing {filteredReferences.length} ({statusFilter.join(', ')})
            </span>
            )}
            {selectedCheckId && <SuggestionStylePicker />}
            {selectedCheckId && (
                <button
                    onClick={() => setShowAdd(v => !v)}
                    className="text-xs px-2 py-1 rounded"
                    style={{
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg-tertiary)',
                      color: 'var(--color-text-secondary)',
                    }}
                    title="Add a missing reference and verify it"
                >
                  {showAdd ? 'Cancel' : '+ Add reference'}
                </button>
            )}
          </div>
        </div>

        {showAdd && (
            <AddReferencePanel
                newRef={newRef}
                setNewRef={setNewRef}
                busyKey={busyKey}
                onSave={handleAddRef}
                onCancel={() => setShowAdd(false)}
            />
        )}

        <SuggestAltPanel suggestFor={suggestFor} onClose={() => setSuggestFor(null)} />

        <RemovedRefsStrip
            removedRefs={removedRefs}
            busyKey={busyKey}
            onRestore={handleRestoreRef}
            onClear={clearRemovedRefs}
        />

        <div
            className="divide-y"
            style={{ borderColor: 'var(--color-border)' }}
        >
          {filteredReferences.map((ref, displayIndex) => (
              <div key={referenceRowIdentity(ref, displayIndex)}>
                <ReferenceCard
                    reference={ref}
                    index={ref.index ?? displayIndex}
                    displayIndex={displayIndex}
                    totalRefs={sortedReferences.length}
                    isCheckComplete={isCheckComplete}
                />
                {selectedCheckId && (() => {
                  const ident = referenceRowIdentity(ref, displayIndex)
                  return (
                      <ReferenceRowActions
                          reference={ref}
                          displayIndex={displayIndex}
                          selectedCheckId={selectedCheckId}
                          onSuggest={handleSuggestAlt}
                          onRemove={handleRemoveRef}
                          onReverify={handleReverify}
                          onReverifyAllDatabases={handleReverifyAllDatabases}
                          searchOperation={getReferenceSearchOperation(ref, displayIndex)}
                          onCancelReferenceSearch={handleCancelReferenceSearch}
                          onEditMetadata={handleEditMetadata}
                          onRestoreExtractedMetadata={handleRestoreExtractedMetadata}
                          reverifyBusy={isReverifying(ident)}
                          reverifyAction={getReverifyAction(ident)}
                          suggestBusy={isSuggesting(ident)}
                          removeBusy={isRemoving(ident)}
                          globalBusy={!!globalBusy}
                      />
                  )
                })()}
              </div>
          ))}
        </div>
      </div>
  )
}

function SuggestionStylePicker() {
  const format = useStyleStore(s => s.format)
  const setFormat = useStyleStore(s => s.setFormat)
  const customs = listCustomCitationStyles()

  return (
      <select
          value={format}
          onChange={(event) => setFormat(event.target.value, { userSelected: true })}
          className="text-xs px-2 py-1 rounded border"
          style={{
            background: 'var(--color-bg-tertiary)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
          title="Citation style used to render suggested alternatives"
      >
        {CITATION_STYLES.map(style => (
            <option key={style.id} value={style.id}>{style.label}</option>
        ))}
        {customs.length > 0 && (
            <optgroup label="Custom">
              {customs.map(style => (
                  <option key={style.id} value={`custom:${style.id}`}>
                    {style.label || style.id}
                  </option>
              ))}
            </optgroup>
        )}
      </select>
  )
}

/**
 * Inline "Removed (N) — Undo" strip rendered above the references list.
 * Stash is scoped per-check (see useReferenceActions) so switching to
 * another history item starts fresh. Each entry has an Undo button that
 * calls addReferenceToCheck + verify, restoring the ref and moving the
 * health badge back.
 */
function RemovedRefsStrip({ removedRefs, busyKey, onRestore, onClear }) {
  if (!removedRefs || removedRefs.length === 0) return null
  // Block Undo only while another global action (Add / Restore) is in
  // flight. Per-row actions (Re-verify / Remove) live in
  // their own sets and don't conflict with the global busy slot, so
  // Undo can run in parallel with them. Clear stays enabled — it's
  // purely local.
  const restoring = !!busyKey
  return (
      <div
          className="px-4 py-2 border-t text-xs flex items-center gap-2 flex-wrap"
          style={{
            borderColor: 'var(--color-border)',
            background: 'var(--color-bg-tertiary)',
            color: 'var(--color-text-secondary)',
          }}
      >
      <span style={{ fontWeight: 600 }}>
        Removed ({removedRefs.length})
      </span>
        <span style={{ color: 'var(--color-text-muted)' }}>
        — click Undo to put a reference back and re-verify it.
      </span>
        <div className="flex flex-wrap gap-1.5 ml-auto">
          {removedRefs.slice(0, 6).map(snap => {
            const label = (snap.title || snap.doi || snap.arxiv_id || '(untitled)').toString()
            const short = label.length > 48 ? `${label.slice(0, 48)}…` : label
            return (
                <button
                    key={snap._stashKey}
                    onClick={() => onRestore(snap)}
                    disabled={restoring}
                    className="px-2 py-0.5 rounded-md"
                    style={{
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg-primary)',
                      color: 'var(--color-text-secondary)',
                      opacity: restoring ? 0.6 : 1,
                    }}
                    title={`Undo remove: ${label}`}
                >
                  ↺ {short}
                </button>
            )
          })}
          {removedRefs.length > 6 && (
              <span style={{ color: 'var(--color-text-muted)' }}>
            +{removedRefs.length - 6} more
          </span>
          )}
          <button
              onClick={onClear}
              className="px-2 py-0.5 rounded-md"
              style={{
                border: '1px solid transparent',
                background: 'transparent',
                color: 'var(--color-text-muted)',
              }}
              title="Discard the undo list"
          >
            Clear
          </button>
        </div>
      </div>
  )
}
