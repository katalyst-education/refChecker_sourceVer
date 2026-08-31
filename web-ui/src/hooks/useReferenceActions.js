import { useEffect, useRef, useState } from 'react'
import {
  addReferenceToCheck,
  removeReferenceFromCheck,
  suggestAlternativeReference,
  startReferenceSearch,
  cancelReferenceSearch,
  verifyReferenceInCheck,
} from '../utils/api'
import { useHistoryStore } from '../stores/useHistoryStore'
import { useCheckStore } from '../stores/useCheckStore'
import { useKeyStore } from '../stores/useKeyStore'
import { referenceSearchKey, useReferenceSearchStore } from '../stores/useReferenceSearchStore'
import { referenceRowIdentity, toApiReferenceId } from '../utils/referenceIdentity'

const EMPTY_NEW = { title: '', authors: '', year: '', doi: '', arxiv_id: '' }

// Add/remove an ident from a Set state without mutating the previous value
// (zustand-style immutable update so React re-renders pick it up).
const enterBusy = (setter, ident) =>
    setter(prev => {
      const next = new Set(prev)
      next.add(ident)
      return next
    })
const leaveBusy = (setter, ident) =>
    setter(prev => {
      const next = new Set(prev)
      next.delete(ident)
      return next
    })

const findReferencePosition = (list, target, fallbackPosition = -1) => {
  const refs = Array.isArray(list) ? list : []
  if (target?.ref_uid != null && String(target.ref_uid) !== '') {
    const byUid = refs.findIndex(ref => String(ref?.ref_uid || '') === String(target.ref_uid))
    if (byUid >= 0) return byUid
  }
  if (target?.id != null && String(target.id) !== '') {
    const byId = refs.findIndex(ref => ref?.id != null && String(ref.id) === String(target.id))
    if (byId >= 0) return byId
  }
  if (target?.index != null && String(target.index) !== '') {
    const indexHits = refs
        .map((ref, index) => [ref, index])
        .filter(([ref]) => ref?.index != null && String(ref.index) === String(target.index))
    if (indexHits.length === 1) return indexHits[0][1]
    if (indexHits.length > 1 && target?.title) {
      const title = String(target.title).trim().toLocaleLowerCase()
      const titledHit = indexHits.find(([ref]) => (
        String(ref?.title || '').trim().toLocaleLowerCase() === title
      ))
      if (titledHit) return titledHit[1]
    }
  }
  if (target?.title) {
    const title = String(target.title).trim().toLocaleLowerCase()
    const hits = refs
        .map((ref, index) => [ref, index])
        .filter(([ref]) => String(ref?.title || '').trim().toLocaleLowerCase() === title)
    if (hits.length === 1) return hits[0][1]
  }
  return fallbackPosition >= 0 && fallbackPosition < refs.length ? fallbackPosition : -1
}

export default function useReferenceActions() {
  const selectedCheckId = useHistoryStore(s => s.selectedCheckId)
  const referenceSearches = useReferenceSearchStore(state => state.operations)
  const registerReferenceSearch = useReferenceSearchStore(state => state.register)
  // Per-action in-flight tracking, so Re-verify and Suggest-alternative
  // (and Remove) on the same row don't clobber each other's busy
  // indicators when the user fires them concurrently (#18). Each Set
  // holds the row idents currently running that action.
  // Map each row to the re-verification action currently running. Keeping the
  // action type lets the card explain whether it is re-extracting the document
  // or searching all configured databases.
  const [reverifyBusy, setReverifyBusy] = useState(() => new Map())
  const [suggestBusy, setSuggestBusy] = useState(() => new Set())
  const [removeBusy, setRemoveBusy] = useState(() => new Set())
  // Global busy slot: '__add__' while Add-reference is in flight,
  // '__restore__' during Undo, null otherwise. Kept separate from the
  // per-row sets so per-row ops survive a parallel Undo.
  const [globalBusy, setGlobalBusy] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newRef, setNewRef] = useState(EMPTY_NEW)
  const [suggestFor, setSuggestFor] = useState(null)
  // Track the most-recently-started Suggest so a slow earlier request
  // can't clobber the panel after the user moved on to a newer one.
  const latestSuggestRef = useRef(null)
  // Session-local "trash" so the user can Undo a removal. Scoped to the
  // currently-selected check — switching checks discards the trash.
  const [removedRefs, setRemovedRefs] = useState([])

  useEffect(() => {
    setRemovedRefs([])
  }, [selectedCheckId])

  const reloadCheck = async () => {
    if (!selectedCheckId) return
    // Force refetch — the store short-circuits same-id selects, but after an
    // Apply Fix / Re-verify we need the freshly-updated reference list so the
    // HealthBadge + Summary tiles recompute against the new statuses.
    await useHistoryStore.getState().selectCheck?.(selectedCheckId, { force: true })
  }

  const handleAddRef = async (override) => {
    if (!selectedCheckId) return null
    setGlobalBusy('__add__')
    // Accept an optional override patch so callers can pass in fields
    // that the parent's `newRef` state hasn't received yet (the "Add by
    // DOI" panel resolves a DOI on click — setNewRef is async, so by
    // the time handleAddRef reads its closure of `newRef`, the new DOI
    // hasn't landed yet. The override merges deterministically over the
    // closure's `newRef`, closing that race).
    const eff = { ...newRef, ...(override || {}) }
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: (eff.title || '').trim() || null,
        authors: (eff.authors || '').trim()
            ? eff.authors.split(',').map(s => s.trim()).filter(Boolean)
            : null,
        year: eff.year ? parseInt(eff.year, 10) : null,
        doi: (eff.doi || '').trim() || null,
        arxiv_id: (eff.arxiv_id || '').trim() || null,
      })
      const addedId = res?.data?.id ?? res?.data?.reference?.id ?? null
      setShowAdd(false)
      setNewRef(EMPTY_NEW)
      // Kick off live re-verification on the new ref so the UI doesn't
      // sit on a permanent 'pending'.
      if (addedId != null) {
        try {
          await verifyReferenceInCheck(selectedCheckId, String(addedId))
        } catch {
          /* server may not support it yet; reload still surfaces the row */
        }
      }
      await reloadCheck()
      return addedId
    } catch (e) {
      // R17 (G3) — the backend rejects a duplicate with 409 and a friendly
      // top-level envelope ({duplicate, existing_index, message}). Surface
      // "already reference [N]" instead of a generic "Add failed".
      const r = e?.response
      if (r?.status === 409 && r?.data?.duplicate) {
        alert(r.data.message || `Already reference [${r.data.existing_index}] in this check.`)
        return null
      }
      alert(e?.response?.data?.detail || e?.message || 'Add failed')
      return null
    } finally {
      setGlobalBusy(null)
    }
  }

  const handleRemoveRef = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = referenceRowIdentity(ref, i)
    const apiRefId = toApiReferenceId(ref, i)
    enterBusy(setRemoveBusy, ident)
    // Snapshot the ref so Undo can re-create it. We stash the metadata
    // the add endpoint needs, plus a synthetic key so the UI can render
    // a stable list of removed items.
    // Capture the original 0-based position so Undo can put the ref
    // back exactly where it was, not at the bottom of the list.
    const storeRefs = useCheckStore.getState().references || []
    let originalPosition = findReferencePosition(storeRefs, ref, i)
    if (originalPosition === -1) originalPosition = typeof i === 'number' ? i : 0
    const snapshot = {
      _stashKey: `${ident}-${Date.now()}`,
      _originalPosition: originalPosition,
      title: ref.title || '',
      authors: Array.isArray(ref.authors) ? ref.authors.join(', ') : (ref.authors || ''),
      year: ref.year ?? '',
      doi: ref.doi || '',
      arxiv_id: ref.arxiv_id || '',
      venue: ref.venue || '',
    }
    // Optimistically drop from the live checkStore feed. When the user
    // is viewing the active check, displayRefs comes from checkStore,
    // not from selectedCheck.results — without this, the row stays
    // visible and the health badge doesn't move until they navigate
    // away and back.
    const removedFromStore = (useCheckStore.getState().references || []).find(
        (r, idx) => (
            String(r?.id ?? '') === ident ||
            String(r?.index ?? '') === ident ||
            String(idx) === ident
        )
    )
    useCheckStore.getState().removeReference(ident)
    // Also drop it from the historical-view source so the badge/list move
    // immediately when displayRefs reads selectedCheck.results (not checkStore).
    useHistoryStore.getState().optimisticRemoveReference?.(ident)
    try {
      await removeReferenceFromCheck(selectedCheckId, apiRefId)
      setRemovedRefs(prev => [snapshot, ...prev].slice(0, 20))
      await reloadCheck()
    } catch (e) {
      // Server rejected the delete — put the ref back so the optimistic
      // remove doesn't strand the UI in a worse state than it started.
      if (removedFromStore) useCheckStore.getState().restoreReference(removedFromStore)
      alert(e?.response?.data?.detail || e?.message || 'Remove failed')
    } finally {
      leaveBusy(setRemoveBusy, ident)
    }
  }

  const handleRestoreRef = async (snapshot) => {
    if (!selectedCheckId || !snapshot) return
    setGlobalBusy('__restore__')
    // Optimistic put-back: drop a placeholder row into the live
    // checkStore *immediately* so the user sees the restore instantly
    // instead of staring at a spinning button for the 5-10s the
    // network roundtrip + re-verify takes.
    const optimisticId = `restoring-${snapshot._stashKey}`
    const authorsArr = (snapshot.authors || '').trim()
        ? snapshot.authors.split(',').map(s => s.trim()).filter(Boolean)
        : []
    const placeholder = {
      id: optimisticId,
      title: snapshot.title || '',
      authors: authorsArr,
      year: snapshot.year || null,
      doi: snapshot.doi || null,
      arxiv_id: snapshot.arxiv_id || null,
      venue: snapshot.venue || null,
      status: 'pending',
      errors: [],
      warnings: [],
      suggestions: [{ message: 'Restoring…', error_type: 'manual' }],
    }
    try {
      useCheckStore.getState().restoreReference(placeholder, snapshot._originalPosition)
    } catch { /* store may not have action yet */ }
    // Pop from the trash strip right away — user sees the placeholder
    // in the list and the trash entry gone in the same render.
    setRemovedRefs(prev => prev.filter(r => r._stashKey !== snapshot._stashKey))
    try {
      const res = await addReferenceToCheck(selectedCheckId, {
        title: (snapshot.title || '').trim() || null,
        authors: authorsArr.length ? authorsArr : null,
        year: snapshot.year ? parseInt(snapshot.year, 10) : null,
        doi: (snapshot.doi || '').trim() || null,
        arxiv_id: (snapshot.arxiv_id || '').trim() || null,
        venue: (snapshot.venue || '').trim() || null,
        // Send the original position so the backend inserts there,
        // not at the bottom. Falls back to append when None.
        insert_at_index: typeof snapshot._originalPosition === 'number' ? snapshot._originalPosition : null,
      })
      const addedId = res?.data?.id ?? res?.data?.reference?.id ?? null
      // Re-verify runs in the background — don't await. The reload
      // below will pick up its result on the next progress tick.
      if (addedId != null) {
        verifyReferenceInCheck(selectedCheckId, String(addedId)).catch(() => {})
      }
      // reload picks up the real persisted row (with the server-assigned
      // manual-XXX id) and replaces our placeholder.
      await reloadCheck()
    } catch (e) {
      // Roll back the optimistic restore and put the ref back in the trash.
      try { useCheckStore.getState().removeReference(optimisticId) } catch { /* */ }
      setRemovedRefs(prev => [snapshot, ...prev])
      alert(e?.response?.data?.detail || e?.message || 'Restore failed')
    } finally {
      setGlobalBusy(null)
    }
  }

  const clearRemovedRefs = () => setRemovedRefs([])

  const handleSuggestAlt = async (ref, i) => {
    if (!selectedCheckId) return
    const ident = referenceRowIdentity(ref, i)
    const apiRefId = toApiReferenceId(ref, i)
    enterBusy(setSuggestBusy, ident)
    latestSuggestRef.current = ident
    try {
      const res = await suggestAlternativeReference(selectedCheckId, apiRefId)
      // Discard the result if the user has since started a newer Suggest
      // (e.g. clicked Suggest on a different row while this one was slow).
      // Without this, a slower earlier response can overwrite the panel
      // the user is actively reading.
      if (latestSuggestRef.current === ident) {
        setSuggestFor({ ref_id: ident, candidates: res.data?.candidates || [] })
      }
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Suggest failed')
    } finally {
      leaveBusy(setSuggestBusy, ident)
    }
  }

  const handleReverify = async (ref, i, opts = {}) => {
    if (!selectedCheckId) return
    const ident = referenceRowIdentity(ref, i)
    const apiRefId = toApiReferenceId(ref, i)
    const action = opts.restore_extracted
      ? 'restore-extracted'
      : opts.manual_edit
        ? 'manual-edit'
        : opts.force_all_databases
          ? 'all-databases'
          : 'reextract'
    setReverifyBusy(prev => {
      const next = new Map(prev)
      next.set(ident, action)
      return next
    })
    try {
      const response = await verifyReferenceInCheck(selectedCheckId, apiRefId, {
        ...opts,
        expected_id: ref?.id ?? null,
        expected_index: ref?.index ?? null,
        expected_title: ref?.title ?? null,
      })
      const updated = response?.data?.reference
      if (!updated) {
        throw new Error('The verification finished without returning the updated reference.')
      }

      // The endpoint returns the complete persisted row, so update that row
      // directly instead of force-reloading the whole check. This preserves
      // the list's scroll position and keeps the user's card in view.
      const historyStore = useHistoryStore.getState()
      const historyPosition = findReferencePosition(
          historyStore.selectedCheck?.results,
          // Completed history views remap citation indices to local 0-based
          // display positions. The response carries the original persisted
          // index, so use it to replace the saved row instead of its neighbor.
          updated,
          i,
      )
      if (historyPosition >= 0) {
        historyStore.updateHistoryReference?.(selectedCheckId, historyPosition, updated)
      }
      const checkStore = useCheckStore.getState()
      if (checkStore.currentCheckId === selectedCheckId) {
        const checkPosition = findReferencePosition(checkStore.references, ref, i)
        if (checkPosition >= 0) checkStore.updateReference?.(checkPosition, updated)
      }
      return updated
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Re-verify failed')
      return null
    } finally {
      setReverifyBusy(prev => {
        const next = new Map(prev)
        next.delete(ident)
        return next
      })
    }
  }

  const handleReverifyAllDatabases = async (ref, i) => {
    if (!selectedCheckId) return null
    const ident = referenceRowIdentity(ref, i)
    setReverifyBusy(prev => new Map(prev).set(ident, 'all-databases'))
    try {
      const keyStore = useKeyStore.getState()
      const response = await startReferenceSearch(selectedCheckId, toApiReferenceId(ref, i), {
        expected_id: ref?.id ?? null,
        expected_index: ref?.index ?? null,
        expected_title: ref?.title ?? null,
        semantic_scholar_api_key: keyStore.getKey('semantic_scholar'),
        google_books_api_key: keyStore.getKey('google_books'),
        paperclip_api_key: keyStore.getKey('paperclip'),
      })
      registerReferenceSearch(response.data)
      return response.data
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Search could not be started')
      return null
    } finally {
      setReverifyBusy(prev => {
        const next = new Map(prev)
        next.delete(ident)
        return next
      })
    }
  }

  const getReferenceSearchOperation = (ref, i) => {
    if (!selectedCheckId) return null
    const identity = referenceRowIdentity(ref, i)
    const direct = referenceSearches[referenceSearchKey(selectedCheckId, identity)]
    if (direct) return direct

    // Backward compatibility for an operation started by the previous
    // position-keyed implementation and recovered after a frontend reload.
    const historyRefs = useHistoryStore.getState().selectedCheck?.results
    const currentRefs = useCheckStore.getState().references
    const sourceRefs = Array.isArray(historyRefs) && historyRefs.length ? historyRefs : currentRefs
    const position = findReferencePosition(sourceRefs, ref, i)
    return position < 0
      ? null
      : referenceSearches[referenceSearchKey(selectedCheckId, `pos:${position}`)] || null
  }

  const handleCancelReferenceSearch = async (operation) => {
    if (!operation?.operation_id) return
    try {
      await cancelReferenceSearch(operation.operation_id)
      useReferenceSearchStore.getState().register({ ...operation, status: 'cancelling' })
    } catch (e) {
      alert(e?.response?.data?.detail || e?.message || 'Cancellation failed')
    }
  }

  const handleEditMetadata = async (ref, i, overrides) =>
      handleReverify(ref, i, {
        overrides,
        manual_edit: true,
        force_all_databases: true,
      })

  const handleRestoreExtractedMetadata = async (ref, i) =>
      handleReverify(ref, i, {
        restore_extracted: true,
        force_all_databases: true,
      })

  // Back-compat: a few callers (AddReferencePanel) still expect a single
  // `busyKey` string. Map the global slot onto it so '__add__'/'__restore__'
  // sentinels keep working without touching those components.
  const busyKey = globalBusy

  const getReverifyAction = (ident) => reverifyBusy.get(String(ident)) || null
  const isReverifying = (ident) => !!getReverifyAction(ident)
  const isSuggesting = (ident) => suggestBusy.has(String(ident))
  const isRemoving = (ident) => removeBusy.has(String(ident))

  return {
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
  }
}
