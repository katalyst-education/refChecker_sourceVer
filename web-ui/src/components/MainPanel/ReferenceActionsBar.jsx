import { useState } from 'react'
import { openExternal } from '../../utils/tauriBridge'
import { useStyleStore } from '../../stores/useStyleStore'
import {
  CITATION_STYLE_DEFAULTS,
  CITATION_STYLES,
  exportReferenceAsStyle,
} from '../../utils/formatters'
import { resolveDoi } from '../../utils/api'

const databaseStatusLabel = (status) => ({
  matched: 'Match',
  verified_fulltext_evidence: 'Full-text match',
  no_match: 'No match',
  rejected_wrong_paper: 'Rejected wrong paper',
  rate_limited: 'Rate limited',
  timed_out: 'Timed out',
  failed: 'Failed',
  cancelled: 'Cancelled',
  searching: 'Searching',
  waiting: 'Waiting',
  not_searched: 'Not searched',
}[status] || String(status || 'Waiting').replaceAll('_', ' '))

const databaseStatusColor = (status) => {
  if (status === 'matched' || status === 'verified_fulltext_evidence') return 'var(--color-success, #16a34a)'
  if (status === 'searching') return 'var(--color-accent)'
  if (['failed', 'timed_out', 'rate_limited'].includes(status)) return 'var(--color-error, #ef4444)'
  return 'var(--color-text-muted)'
}

const safeResultUrl = (candidate) => {
  const value = candidate?.url || candidate?.link
  return typeof value === 'string' && /^https?:\/\//i.test(value) ? value : null
}

const candidateAuthorText = (candidate) => {
  const values = Array.isArray(candidate?.authors)
    ? candidate.authors
    : candidate?.authors ? [candidate.authors] : []
  return values.map(author => {
    if (typeof author === 'string') return author
    return author?.name || author?.display_name || ''
  }).filter(Boolean).join(', ')
}

export function AddReferencePanel({ newRef, setNewRef, busyKey, onSave, onCancel }) {
  const disabled = busyKey === '__add__'
  // Two entry modes:
  //   'doi'    — paste a DOI, click Resolve, all fields auto-fill from CrossRef.
  //   'manual' — fill in title/authors/year/etc. by hand (the original form).
  // We default to 'doi' because that's the path the user explicitly asked
  // for ("Automated reference adding by only doi"); the manual form stays
  // available for cases where CrossRef doesn't have the paper.
  const [mode, setMode] = useState('doi')
  const [doiInput, setDoiInput] = useState(newRef.doi || '')
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState(null)
  const [resolved, setResolved] = useState(null) // { title, authors, year, venue }

  const handleResolve = async () => {
    const value = (doiInput || '').trim()
    if (!value) { setResolveError('Enter a DOI first'); return }
    setResolving(true); setResolveError(null); setResolved(null)
    try {
      const res = await resolveDoi(value)
      const meta = res?.data || {}
      const authorsText = Array.isArray(meta.authors) ? meta.authors.join(', ') : (meta.authors || '')
      setNewRef({
        ...newRef,
        title: meta.title || '',
        authors: authorsText,
        year: meta.year ? String(meta.year) : '',
        doi: meta.doi || value,
        arxiv_id: newRef.arxiv_id || '',
      })
      setResolved(meta)
    } catch (e) {
      setResolveError(e?.response?.data?.detail || e?.message || 'Resolution failed')
    } finally {
      setResolving(false)
    }
  }

  const handleAddAndResolve = async () => {
    // Convenience: if the user clicks Add reference with only a DOI typed
    // but never clicked Resolve, the backend will still fall back to
    // CrossRef inside the add endpoint — so just forward what we have.
    // setNewRef is async (React state batch), so we can't depend on
    // newRef.doi being updated by the time onSave reads it; pass the
    // typed DOI through onSave's override path instead. The parent's
    // handleAddRef accepts a patch and merges it over its closure of
    // newRef before building the request body.
    if (mode === 'doi' && doiInput && !newRef.doi) {
      const trimmed = doiInput.trim()
      setNewRef({ ...newRef, doi: trimmed })
      onSave({ doi: trimmed })
      return
    }
    onSave()
  }

  const switchMode = (next) => {
    setMode(next)
    setResolveError(null)
  }

  const fieldStyle = { borderColor: 'var(--color-border)', background: 'var(--color-bg-secondary)' }

  return (
      <div
          className="px-4 py-3 border-t text-sm"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
      >
        {/* Mode toggle — tab strip */}
        <div className="flex items-center gap-1 mb-3 text-xs">
          <button
              onClick={() => switchMode('doi')}
              className="px-2 py-1 rounded font-medium"
              style={{
                background: mode === 'doi' ? 'var(--color-accent)' : 'transparent',
                color: mode === 'doi' ? '#fff' : 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
          >
            By DOI (auto-fill)
          </button>
          <button
              onClick={() => switchMode('manual')}
              className="px-2 py-1 rounded font-medium"
              style={{
                background: mode === 'manual' ? 'var(--color-accent)' : 'transparent',
                color: mode === 'manual' ? '#fff' : 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
          >
            Manual entry
          </button>
        </div>

        {mode === 'doi' ? (
            <div>
              <div className="flex gap-2">
                <input
                    className="flex-1 px-2 py-1 rounded border"
                    placeholder="DOI (e.g. 10.1038/s41586-023-06924-6) or https://doi.org/..."
                    value={doiInput}
                    onChange={e => setDoiInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !resolving) handleResolve() }}
                    style={fieldStyle}
                />
                <button
                    onClick={handleResolve}
                    disabled={resolving || !doiInput.trim()}
                    className="px-3 py-1 rounded text-sm font-medium"
                    style={{
                      background: 'var(--color-accent)',
                      color: '#fff',
                      opacity: (resolving || !doiInput.trim()) ? 0.6 : 1,
                    }}
                >
                  {resolving ? 'Resolving…' : 'Resolve'}
                </button>
              </div>
              {resolveError && (
                  <div className="mt-2 text-xs" style={{ color: 'var(--color-error, #ef4444)' }}>
                    {resolveError}
                  </div>
              )}
              {resolved && (
                  <div
                      className="mt-2 p-2 rounded text-xs"
                      style={{
                        background: 'var(--color-bg-secondary)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                      }}
                  >
                    <div style={{ fontWeight: 600 }}>{resolved.title || '(no title)'}</div>
                    {(resolved.authors || []).length > 0 && (
                        <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
                          {(resolved.authors || []).slice(0, 6).join(', ')}
                          {(resolved.authors || []).length > 6 ? ', …' : ''}
                        </div>
                    )}
                    <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
                      {resolved.venue || '—'}{resolved.year ? ` · ${resolved.year}` : ''}
                    </div>
                  </div>
              )}
              <div className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                Paste a DOI and we'll fill in title, authors, year, and venue from CrossRef.
                If you skip Resolve, we'll still try when you click Add.
              </div>
            </div>
        ) : (
            <div className="grid grid-cols-2 gap-2">
              <input
                  className="px-2 py-1 rounded border"
                  placeholder="Title"
                  value={newRef.title}
                  onChange={e => setNewRef({ ...newRef, title: e.target.value })}
                  style={fieldStyle}
              />
              <input
                  className="px-2 py-1 rounded border"
                  placeholder="Authors (comma-separated)"
                  value={newRef.authors}
                  onChange={e => setNewRef({ ...newRef, authors: e.target.value })}
                  style={fieldStyle}
              />
              <input
                  className="px-2 py-1 rounded border"
                  placeholder="Year"
                  value={newRef.year}
                  onChange={e => setNewRef({ ...newRef, year: e.target.value })}
                  style={fieldStyle}
              />
              <input
                  className="px-2 py-1 rounded border"
                  placeholder="DOI"
                  value={newRef.doi}
                  onChange={e => setNewRef({ ...newRef, doi: e.target.value })}
                  style={fieldStyle}
              />
              <input
                  className="px-2 py-1 rounded border col-span-2"
                  placeholder="arXiv ID (e.g. 2401.12345)"
                  value={newRef.arxiv_id}
                  onChange={e => setNewRef({ ...newRef, arxiv_id: e.target.value })}
                  style={fieldStyle}
              />
            </div>
        )}
        <div className="mt-2 flex gap-2 justify-end">
          <button
              onClick={onCancel}
              className="px-3 py-1 rounded text-sm"
              style={{ borderColor: 'var(--color-border)', border: '1px solid' }}
          >
            Cancel
          </button>
          <button
              onClick={handleAddAndResolve}
              disabled={disabled}
              className="px-3 py-1 rounded text-sm"
              style={{ background: 'var(--color-accent)', color: '#fff', opacity: disabled ? 0.6 : 1 }}
          >
            {disabled ? 'Adding…' : 'Add reference'}
          </button>
        </div>
      </div>
  )
}

export function SuggestAltPanel({ suggestFor, onClose }) {
  // Render suggestions in the user's currently-selected citation style so
  // the candidates can be copied straight into the bibliography without
  // any further formatting work.
  const format = useStyleStore(s => s.format)
  const styleOptions = useStyleStore(s => s.styleOptions)
  if (!suggestFor) return null
  const styleLabel = CITATION_STYLES.find(s => s.id === format)?.label || (format.startsWith('custom:') ? 'Custom' : format)
  const effectiveOpts = {
    ...(CITATION_STYLE_DEFAULTS[format] || {}),
    ...(styleOptions || {}),
  }
  const renderInStyle = (c, i) => {
    try {
      return exportReferenceAsStyle(c, format, i, effectiveOpts)
    } catch {
      return c.title || ''
    }
  }
  const copyToClipboard = async (text) => {
    try { await navigator.clipboard.writeText(text) } catch { /* ignore */ }
  }
  return (
      <div
          className="px-4 py-3 border-t text-sm"
          style={{ borderColor: 'var(--color-border)', background: 'var(--color-bg-tertiary)' }}
      >
        <div className="flex items-center justify-between mb-2">
          <strong>Suggested alternatives for ref {suggestFor.ref_id}</strong>
          <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            rendered as {styleLabel}
          </span>
            <button
                onClick={onClose}
                className="text-xs px-2 py-0.5 rounded border"
                style={{ borderColor: 'var(--color-border)' }}
            >
              Close
            </button>
          </div>
        </div>
        {(!suggestFor.candidates || suggestFor.candidates.length === 0) ? (
            <div style={{ color: 'var(--color-text-muted)' }}>No alternatives found.</div>
        ) : (
            <ul className="space-y-2">
              {suggestFor.candidates.map((c, i) => {
                const styled = renderInStyle(c, i)
                return (
                    <li
                        key={i}
                        className="flex flex-col gap-1 rounded-md p-2"
                        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div
                            className="flex-1 min-w-0"
                            style={{
                              color: 'var(--color-text-primary)',
                              fontFamily: format === 'bibtex' || format === 'bibitem' ? 'ui-monospace, monospace' : undefined,
                              fontSize: format === 'bibtex' || format === 'bibitem' ? '0.78rem' : undefined,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                            }}
                        >
                          {styled}
                        </div>
                        <button
                            onClick={() => copyToClipboard(styled)}
                            className="text-xs px-2 py-0.5 rounded flex-shrink-0"
                            style={{
                              border: '1px solid var(--color-border)',
                              background: 'var(--color-bg-primary)',
                              color: 'var(--color-text-secondary)',
                            }}
                            title="Copy this citation"
                        >
                          Copy
                        </button>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {c.source && (
                            <span
                                className="px-1.5 py-0.5 rounded"
                                style={{
                                  background: 'var(--color-bg-tertiary)',
                                  border: '1px solid var(--color-border)',
                                }}
                            >
                      {c.source === 'llm' ? 'LLM' : c.source === 'semantic_scholar' ? 'S2' : c.source}
                    </span>
                        )}
                        {typeof c.overlap === 'number' && c.overlap > 0 && (
                            <span
                                className="px-1.5 py-0.5 rounded"
                                style={{
                                  background: 'rgba(34,197,94,0.12)',
                                  color: 'var(--color-success, #16a34a)',
                                  border: '1px solid rgba(34,197,94,0.35)',
                                }}
                                title="Shares N other references with this paper's bibliography (co-citation overlap)"
                            >
                      shares {c.overlap} ref{c.overlap === 1 ? '' : 's'}
                              {c.overlap_winner ? ' · best match' : ''}
                    </span>
                        )}
                        {c.url && (
                            <a
                                href={c.url}
                                onClick={e => { e.preventDefault(); openExternal(c.url) }}
                                style={{ color: 'var(--color-accent)' }}
                            >
                              {c.url.length > 80 ? `${c.url.slice(0, 80)}…` : c.url}
                            </a>
                        )}
                      </div>
                      {c.reason && (
                          <div style={{ color: 'var(--color-text-muted)', fontSize: '0.8em', fontStyle: 'italic' }}>
                            {c.reason}
                          </div>
                      )}
                    </li>
                )
              })}
            </ul>
        )}
      </div>
  )
}

export function ReferenceRowActions({
                                      reference,
                                      displayIndex,
                                      selectedCheckId,
                                      onSuggest,
                                      onRemove,
                                      onReverify,
                                      onReverifyAllDatabases,
                                      searchOperation = null,
                                      onCancelReferenceSearch,
                                      onEditMetadata,
                                      onRestoreExtractedMetadata,
                                      // Per-action busy flags so Re-verify and Suggest-alternative can
                                      // run in parallel on the same row without each disabling/clobbering
                                      // the other's spinner (#18). globalBusy blocks every per-row action
                                      // while Add or Restore is in flight so we don't race those state
                                      // resets.
                                      reverifyBusy = false,
                                      reverifyAction = null,
                                      suggestBusy = false,
                                      removeBusy = false,
                                      globalBusy = false,
                                    }) {
  const referenceAuthors = Array.isArray(reference?.authors)
    ? reference.authors
    : reference?.authors
      ? [reference.authors]
      : []
  const authorNames = referenceAuthors
      .map(author => {
        if (typeof author === 'string') return author
        if (!author || typeof author !== 'object') return ''
        return author.name || [author.givenName, author.familyName].filter(Boolean).join(' ')
      })
      .filter(Boolean)
  const makeDraft = () => ({
    title: reference?.title || '',
    authors: authorNames.length ? authorNames : [''],
    year: reference?.year == null ? '' : String(reference.year),
    venue: reference?.venue || reference?.journal || '',
    doi: reference?.doi || '',
    arxiv_id: reference?.arxiv_id || '',
    cited_url: reference?.cited_url || reference?.url || '',
  })
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(makeDraft)
  const [saving, setSaving] = useState(false)
  const fieldStyle = {
    borderColor: 'var(--color-border)',
    background: 'var(--color-bg-secondary)',
    color: 'var(--color-text-primary)',
  }
  const openEditor = () => {
    setDraft(makeDraft())
    setEditing(true)
  }
  const updateAuthor = (authorIndex, value) => {
    setDraft(current => ({
      ...current,
      authors: current.authors.map((author, index) => index === authorIndex ? value : author),
    }))
  }
  const removeAuthor = (authorIndex) => {
    setDraft(current => ({
      ...current,
      authors: current.authors.length > 1
        ? current.authors.filter((_, index) => index !== authorIndex)
        : [''],
    }))
  }
  const saveMetadata = async (event) => {
    event.preventDefault()
    setSaving(true)
    try {
      const updated = await onEditMetadata?.(reference, displayIndex, {
        ...draft,
        authors: draft.authors.map(author => author.trim()).filter(Boolean),
        year: draft.year.trim() || null,
      })
      if (updated) setEditing(false)
    } finally {
      setSaving(false)
    }
  }
  // Match Settings panel button styling — pill, subtle border, hover lift.
  const baseStyle = {
    border: '1px solid var(--color-border)',
    background: 'var(--color-bg-primary)',
    color: 'var(--color-text-secondary)',
    transition: 'background 120ms ease, color 120ms ease, border-color 120ms ease',
  }
  const styleFor = (busy) => ({ ...baseStyle, opacity: (busy || !selectedCheckId || globalBusy) ? 0.55 : 1 })
  const activeSearch = ['queued', 'running', 'cancelling'].includes(searchOperation?.status)
  const databaseSources = (() => {
    const sourceMap = searchOperation?.sources || {}
    const configured = Array.isArray(searchOperation?.configured_sources)
      ? searchOperation.configured_sources
      : []
    const listed = configured.map(source => ({
      ...source,
      status: activeSearch ? 'waiting' : 'not_searched',
      ...(sourceMap[source.database] || {}),
    }))
    const configuredNames = new Set(configured.map(source => source.database))
    return [
      ...listed,
      ...Object.values(sourceMap).filter(source => !configuredNames.has(source.database)),
    ]
  })()
  const disableFor = (busy) => busy || activeSearch || !selectedCheckId || globalBusy || editing
  const reextracting = reverifyBusy && reverifyAction === 'reextract'
  const searchingAll = reverifyBusy && reverifyAction === 'all-databases'
  const savingEdit = reverifyBusy && reverifyAction === 'manual-edit'
  const restoringExtracted = reverifyBusy && reverifyAction === 'restore-extracted'
  return (
      <div className="px-4 pb-3 pt-1 text-xs" aria-busy={(reverifyBusy || activeSearch) || undefined}>
        <div className="flex flex-wrap gap-1.5">
          <button
              type="button"
              onClick={() => onReverify(reference, displayIndex)}
              disabled={disableFor(reverifyBusy)}
              className="px-2.5 py-1 rounded-md font-medium"
              style={styleFor(reverifyBusy)}
              title="Extract this reference again from the document, then verify it"
          >
            {reextracting ? 'Re-extracting…' : 'Re-extract & verify'}
          </button>
          <button
              type="button"
              onClick={() => activeSearch
                ? onCancelReferenceSearch?.(searchOperation)
                : onReverifyAllDatabases?.(reference, displayIndex)}
              disabled={searchOperation?.status === 'cancelling' || reverifyBusy || !selectedCheckId || globalBusy || editing}
              className="px-2.5 py-1 rounded-md font-medium"
              style={styleFor(reverifyBusy)}
              title={activeSearch ? 'Cancel this database search' : 'Keep the saved citation fields and search every configured database'}
          >
            {searchOperation?.status === 'cancelling'
              ? 'Cancelling…'
              : activeSearch
                ? 'Cancel search'
                : searchingAll ? 'Searching all DBs…' : 'Search all DBs'}
          </button>
          <button
              type="button"
              onClick={openEditor}
              disabled={disableFor(reverifyBusy)}
              className="px-2.5 py-1 rounded-md font-medium"
              style={styleFor(reverifyBusy)}
              title="Edit the extracted title, authors, year, venue, and identifiers, then verify the changes"
          >
            {savingEdit ? 'Saving edit…' : 'Edit metadata'}
          </button>
          {reference?.manual_edit?.original && (
              <button
                  type="button"
                  onClick={() => onRestoreExtractedMetadata?.(reference, displayIndex)}
                  disabled={disableFor(reverifyBusy)}
                  className="px-2.5 py-1 rounded-md font-medium"
                  style={styleFor(reverifyBusy)}
                  title="Restore the metadata originally extracted from the document and verify it again"
              >
                {restoringExtracted ? 'Restoring…' : 'Undo metadata edit'}
              </button>
          )}
          <button
              type="button"
              onClick={() => onSuggest(reference, displayIndex)}
              disabled={disableFor(suggestBusy)}
              className="px-2.5 py-1 rounded-md font-medium"
              style={styleFor(suggestBusy)}
              title="Suggest a real paper the author might have meant"
          >
            {suggestBusy ? '…' : 'Suggest alternative'}
          </button>
          <button
              type="button"
              onClick={() => onRemove(reference, displayIndex)}
              disabled={disableFor(removeBusy)}
              className="px-2.5 py-1 rounded-md font-medium"
              style={{
                ...styleFor(removeBusy),
                color: 'var(--color-error, #ef4444)',
                borderColor: 'var(--color-error, #ef4444)55',
              }}
              title="Remove this reference from the check"
          >
            {removeBusy ? '…' : 'Remove'}
          </button>
        </div>
        {searchOperation && (
          <div
            className="mt-2 rounded-md p-2"
            style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-tertiary)' }}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                {activeSearch ? 'Searching databases' : searchOperation.status === 'completed' ? 'Database search complete' : searchOperation.status === 'cancelled' ? 'Database search cancelled' : 'Database search failed'}
              </span>
              {searchOperation.duration_ms != null && (
                <span style={{ color: 'var(--color-text-muted)' }}>{(searchOperation.duration_ms / 1000).toFixed(1)}s</span>
              )}
            </div>
            {databaseSources.length > 0 && (
              <details className="mt-2">
                <summary
                  className="cursor-pointer select-none font-medium"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  Database results ({databaseSources.length})
                </summary>
                <ul className="mt-2 space-y-1.5">
                  {databaseSources.map(source => {
                    const candidate = source.candidate || {}
                    const authors = candidateAuthorText(candidate)
                    const resultUrl = safeResultUrl(candidate)
                    const hasOverview = candidate.title || authors || candidate.year || resultUrl
                    return (
                      <li
                        key={source.database}
                        className="rounded-md px-2 py-1.5"
                        style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {source.label || source.database}
                          </span>
                          <span className="flex-shrink-0" style={{ color: databaseStatusColor(source.status) }}>
                            {databaseStatusLabel(source.status)}
                          </span>
                        </div>
                        {hasOverview && (
                          <div className="mt-1 space-y-0.5" style={{ color: 'var(--color-text-muted)' }}>
                            {candidate.title && (
                              <div style={{ color: 'var(--color-text-secondary)' }}>{candidate.title}</div>
                            )}
                            {(authors || candidate.year) && (
                              <div>{[authors, candidate.year].filter(Boolean).join(' · ')}</div>
                            )}
                            {resultUrl && (
                              <a
                                href={resultUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: 'var(--color-accent)', wordBreak: 'break-all' }}
                              >
                                Open database result ↗
                              </a>
                            )}
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </details>
            )}
            {searchOperation.error_message && (
              <div className="mt-1.5" style={{ color: searchOperation.status === 'cancelled' ? 'var(--color-text-muted)' : 'var(--color-error)' }}>
                {searchOperation.error_message}
              </div>
            )}
          </div>
        )}
        {reference?.manual_edit?.original && !editing && (
            <div className="mt-2" style={{ color: 'var(--color-text-muted)' }}>
              Edited by user
              {(reference.manual_edit.edited_fields || []).length > 0
                ? ` · ${reference.manual_edit.edited_fields.join(', ')}`
                : ''}
            </div>
        )}
        {editing && (
            <form
                onSubmit={saveMetadata}
                className="mt-3 p-3 rounded-md space-y-3"
                style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-tertiary)' }}
            >
              <div className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                Edit extracted metadata
              </div>
              <label className="block">
                <span className="block mb-1" style={{ color: 'var(--color-text-muted)' }}>Title</span>
                <input
                    aria-label="Title"
                    className="w-full min-w-0 px-2 py-1.5 rounded border"
                    value={draft.title}
                    onChange={event => setDraft(current => ({ ...current, title: event.target.value }))}
                    style={fieldStyle}
                />
              </label>
              <fieldset>
                <legend className="mb-1" style={{ color: 'var(--color-text-muted)' }}>Authors</legend>
                <div className="space-y-1.5">
                  {draft.authors.map((author, authorIndex) => (
                      <div className="flex min-w-0 gap-1.5" key={`author-${authorIndex}`}>
                        <input
                            aria-label={`Author ${authorIndex + 1}`}
                            className="flex-1 min-w-0 px-2 py-1.5 rounded border"
                            value={author}
                            onChange={event => updateAuthor(authorIndex, event.target.value)}
                            style={fieldStyle}
                        />
                        <button
                            type="button"
                            aria-label={`Remove author ${authorIndex + 1}`}
                            onClick={() => removeAuthor(authorIndex)}
                            className="px-2 rounded"
                            style={baseStyle}
                        >
                          Remove
                        </button>
                      </div>
                  ))}
                </div>
                <button
                    type="button"
                    onClick={() => setDraft(current => ({ ...current, authors: [...current.authors, ''] }))}
                    className="mt-1.5 px-2 py-1 rounded"
                    style={baseStyle}
                >
                  + Add author
                </button>
              </fieldset>
              <div className="grid min-w-0 grid-cols-1 sm:grid-cols-2 gap-2">
                {[
                  ['year', 'Year'],
                  ['venue', 'Venue / publisher'],
                  ['doi', 'DOI'],
                  ['arxiv_id', 'arXiv ID'],
                  ['cited_url', 'URL'],
                ].map(([field, label]) => (
                    <label className={`min-w-0 ${field === 'cited_url' ? 'sm:col-span-2' : ''}`} key={field}>
                      <span className="block mb-1" style={{ color: 'var(--color-text-muted)' }}>{label}</span>
                      <input
                          aria-label={label}
                          inputMode={field === 'year' ? 'numeric' : undefined}
                          className="w-full min-w-0 px-2 py-1.5 rounded border"
                          value={draft[field]}
                          onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))}
                          style={fieldStyle}
                      />
                    </label>
                ))}
              </div>
              <div style={{ color: 'var(--color-text-muted)' }}>
                Saving verifies these exact values without extracting the document again.
              </div>
              <div className="flex gap-2 justify-end">
                <button
                    type="button"
                    onClick={() => setEditing(false)}
                    disabled={saving}
                    className="px-3 py-1.5 rounded font-medium"
                    style={baseStyle}
                >
                  Cancel
                </button>
                <button
                    type="submit"
                    disabled={saving || !draft.title.trim()}
                    className="px-3 py-1.5 rounded font-medium"
                    style={{
                      background: 'var(--color-accent)',
                      color: '#fff',
                      opacity: (saving || !draft.title.trim()) ? 0.6 : 1,
                    }}
                >
                  {saving ? 'Saving and verifying…' : 'Save and verify'}
                </button>
              </div>
            </form>
        )}
        {reverifyBusy && (
            <div
                role="status"
                aria-live="polite"
                className="mt-2 flex items-center gap-2"
                style={{ color: 'var(--color-text-muted)' }}
            >
              <svg
                  aria-hidden="true"
                  className="animate-spin h-3.5 w-3.5 shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  style={{ color: 'var(--color-accent)' }}
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>
            {searchingAll
                ? 'Searching every configured database for this reference…'
                : savingEdit
                  ? 'Saving the edited metadata, then verifying it…'
                  : restoringExtracted
                    ? 'Restoring the originally extracted metadata, then verifying it…'
                    : 'Re-extracting this reference from the document, then verifying it…'}
          </span>
            </div>
        )}
      </div>
  )
}
