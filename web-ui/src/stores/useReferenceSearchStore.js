import { create } from 'zustand'
import { useCheckStore } from './useCheckStore'
import { useHistoryStore } from './useHistoryStore'

export const referenceSearchKey = (checkId, referenceKey) => `${checkId}:${referenceKey}`

const findReferencePosition = (references, updated, referenceKey) => {
  const rows = Array.isArray(references) ? references : []
  if (referenceKey?.startsWith('uid:')) {
    const uid = referenceKey.slice(4)
    const found = rows.findIndex(row => String(row?.ref_uid || '') === uid)
    if (found >= 0) return found
  }
  if (referenceKey?.startsWith('pos:')) {
    const position = Number(referenceKey.slice(4))
    const candidate = Number.isInteger(position) ? rows[position] : null
    const sameId = updated?.id != null && String(candidate?.id ?? '') === String(updated.id)
    const sameTitle = updated?.title && String(candidate?.title || '').trim().toLocaleLowerCase()
      === String(updated.title).trim().toLocaleLowerCase()
    if (candidate && (sameId || sameTitle)) return position
  }
  if (referenceKey?.startsWith('id:')) {
    const id = referenceKey.slice(3)
    const found = rows.findIndex(row => String(row?.id ?? '') === id)
    if (found >= 0) return found
  }
  if (referenceKey?.startsWith('index:')) {
    const index = referenceKey.slice(6)
    const hits = rows
      .map((row, position) => [row, position])
      .filter(([row]) => String(row?.index ?? '') === index)
    if (hits.length === 1) return hits[0][1]
    if (hits.length > 1 && updated?.title) {
      const title = String(updated.title).trim().toLocaleLowerCase()
      const titledHit = hits.find(([row]) => (
        String(row?.title || '').trim().toLocaleLowerCase() === title
      ))
      if (titledHit) return titledHit[1]
    }
  }
  const exactIdentity = rows.findIndex(row => (
    updated?.id != null && String(row?.id ?? '') === String(updated.id)
  ) || (
    updated?.title && String(row?.title || '').trim().toLocaleLowerCase()
      === String(updated.title).trim().toLocaleLowerCase()
  ))
  if (exactIdentity >= 0) return exactIdentity
  const indexHits = updated?.index == null ? [] : rows
    .map((row, position) => [row, position])
    .filter(([row]) => String(row?.index ?? '') === String(updated.index))
  return indexHits.length === 1 ? indexHits[0][1] : -1
}

const patchCompletedReference = (operation, reference) => {
  if (!operation?.check_id || !reference) return
  const history = useHistoryStore.getState()
  const historyPosition = findReferencePosition(
    history.selectedCheck?.results, reference, operation.reference_key,
  )
  if (historyPosition >= 0) {
    history.updateHistoryReference?.(operation.check_id, historyPosition, reference)
  }
  const check = useCheckStore.getState()
  if (check.currentCheckId === operation.check_id) {
    const position = findReferencePosition(check.references, reference, operation.reference_key)
    if (position >= 0) check.updateReference?.(position, reference)
  }
}

const sourcesByDatabase = (sources) => {
  if (!Array.isArray(sources)) return sources || {}
  return Object.fromEntries(
    sources
      .filter(source => source?.database)
      .map(source => [source.database, source]),
  )
}

export const useReferenceSearchStore = create((set, get) => ({
  operations: {},

  register: (payload) => {
    if (!payload?.operation_id) return
    const key = referenceSearchKey(payload.check_id, payload.reference_key)
    set(state => {
      const previous = state.operations[key]
      const sameOperation = previous?.operation_id === payload.operation_id
      return { operations: {
        ...state.operations,
        [key]: {
          ...(sameOperation ? previous : {}),
          ...payload,
          sources: payload.sources || payload.progress?.sources || (sameOperation ? previous?.sources : {}) || {},
        },
      } }
    })
  },

  handleMessage: (message) => {
    const operationId = message?.operation_id
    if (!operationId) return
    const current = Object.values(get().operations).find(op => op.operation_id === operationId)
    const checkId = message.check_id ?? current?.check_id
    const referenceKey = message.reference_key ?? current?.reference_key
    if (!checkId || !referenceKey) return
    const key = referenceSearchKey(checkId, referenceKey)
    const operation = get().operations[key] || current || {}
    if (message.sequence && operation.sequence && message.sequence <= operation.sequence) return

    const base = { ...operation, check_id: checkId, reference_key: referenceKey,
      operation_id: operationId, sequence: message.sequence || operation.sequence || 0 }
    let next = base
    if (message.type === 'reference_search_started') {
      next = { ...base, status: 'running', configured_sources: message.configured_sources || [] }
    } else if (message.type === 'reference_search_source') {
      next = { ...base, status: 'running', sources: {
        ...(base.sources || {}), [message.database]: {
          database: message.database, label: message.label, status: message.status,
          attempt: message.attempt, duration_ms: message.duration_ms,
          delay_seconds: message.delay_seconds, candidate: message.candidate,
        },
      } }
    } else if (message.type === 'reference_search_completed') {
      next = { ...base, status: 'completed', reference: message.reference,
        duration_ms: message.duration_ms,
        sources: { ...(base.sources || {}), ...sourcesByDatabase(message.sources) } }
      patchCompletedReference(next, message.reference)
    } else if (message.type === 'reference_search_cancelled') {
      next = { ...base, status: 'cancelled', error_code: message.error_code,
        error_message: message.message,
        sources: { ...(base.sources || {}), ...sourcesByDatabase(message.sources) } }
    } else if (message.type === 'reference_search_error') {
      next = { ...base, status: 'error', error_code: message.error_code,
        error_message: message.message,
        sources: { ...(base.sources || {}), ...sourcesByDatabase(message.sources) } }
    }
    set(state => ({ operations: { ...state.operations, [key]: next } }))
  },

  applySnapshot: (snapshot) => {
    if (!snapshot?.operation_id) return
    const key = referenceSearchKey(snapshot.check_id, snapshot.reference_key)
    const current = get().operations[key] || {}
    const next = {
      ...current, ...snapshot,
      sources: snapshot.progress?.sources || current.sources || {},
      configured_sources: snapshot.progress?.configured_sources || current.configured_sources || [],
      sequence: snapshot.progress?.sequence || current.sequence || 0,
    }
    if (snapshot.status === 'completed' && snapshot.reference) {
      patchCompletedReference(next, snapshot.reference)
    }
    set(state => ({ operations: { ...state.operations, [key]: next } }))
  },

  getForReference: (checkId, referenceKey) =>
    get().operations[referenceSearchKey(checkId, referenceKey)] || null,
}))
