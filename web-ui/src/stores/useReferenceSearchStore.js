import { create } from 'zustand'
import { useCheckStore } from './useCheckStore'
import { useHistoryStore } from './useHistoryStore'

export const referenceSearchKey = (checkId, referenceKey) => `${checkId}:${referenceKey}`

const TERMINAL = new Set(['completed', 'cancelled', 'error'])
const sequenceOf = (operation) => Number(operation?.sequence ?? operation?.progress?.sequence ?? 0)
const staleUpdate = (previous, incoming) => previous?.operation_id === incoming?.operation_id && (
  sequenceOf(incoming) < sequenceOf(previous)
  || (TERMINAL.has(previous.status) && !TERMINAL.has(incoming.status))
)

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

export const patchCompletedReference = (operation, reference, { reviewMove = false } = {}) => {
  if (!operation?.check_id || !reference) return
  const findPosition = rows => {
    const position = findReferencePosition(rows, reference, operation.reference_key)
    if (position < 0) return position
    const current = rows[position]
    // A search or replay from before a manual move must leave the newer row alone.
    return reviewMove || current.review_revision === reference.review_revision ? position : -1
  }
  useHistoryStore.getState().replaceHistoryReference(operation.check_id, reference, findPosition)
  const check = useCheckStore.getState()
  if (check.currentCheckId === operation.check_id) {
    const position = findPosition(check.references)
    if (position >= 0) check.updateReference(position, reference, { replace: true })
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
      if (staleUpdate(previous, payload)) return state
      if (!sameOperation && previous?.created_at && payload.created_at && payload.created_at < previous.created_at) return state
      return { operations: {
        ...state.operations,
        [key]: {
          ...(sameOperation ? previous : {}),
          ...payload,
          status: sameOperation && previous.status === 'cancelling' && ['queued', 'running'].includes(payload.status)
            ? 'cancelling' : payload.status,
          sequence: sequenceOf(payload),
          operation_type: payload.operation_type || payload.progress?.operation_type
            || (sameOperation ? previous?.operation_type : undefined),
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
    if (operation.operation_id && operation.operation_id !== operationId) return
    if (message.sequence && operation.sequence && message.sequence <= operation.sequence) return
    if (TERMINAL.has(operation.status) && !TERMINAL.has(message.status)
      && message.type !== 'reference_search_completed' && message.type !== 'reference_search_error'
      && message.type !== 'reference_search_cancelled') return

    const base = { ...operation, check_id: checkId, reference_key: referenceKey,
      operation_type: message.operation_type || operation.operation_type,
      operation_id: operationId, sequence: message.sequence || operation.sequence || 0 }
    let next = base
    if (message.type === 'reference_reextract_progress' || message.type === 'reference_reextract_completed') {
      next = { ...base, ...message, progress: { ...(base.progress || {}), ...message } }
      if (message.reference) {
        patchCompletedReference({ ...next, reference_key: message.updated_reference_key }, message.reference)
      }
      if (message.type === 'reference_reextract_completed' && useHistoryStore.getState().selectedCheckId === checkId) {
        useHistoryStore.getState().selectCheck?.(checkId, { force: true })?.catch(() => undefined)
      }
    } else if (message.type === 'reference_search_started') {
      next = { ...base, status: 'running', configured_sources: message.configured_sources || [] }
    } else if (message.type === 'reference_search_source') {
      next = { ...base, status: 'running', sources: {
        ...(base.sources || {}), [message.database]: {
          database: message.database, label: message.label, status: message.status,
          attempt: message.attempt, duration_ms: message.duration_ms,
          delay_seconds: message.delay_seconds, candidate: message.candidate,
          reason: message.reason, identity: message.identity,
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
    if (operation.status === 'cancelling' && ['queued', 'running'].includes(next.status)) next.status = 'cancelling'
    set(state => ({ operations: { ...state.operations, [key]: next } }))
  },

  applySnapshot: (snapshot) => {
    if (!snapshot?.operation_id) return
    const key = referenceSearchKey(snapshot.check_id, snapshot.reference_key)
    const current = get().operations[key] || {}
    if (current.operation_id && current.operation_id !== snapshot.operation_id) return
    if (staleUpdate(current, snapshot)) return
    const next = {
      ...current, ...snapshot,
      status: current.status === 'cancelling' && ['queued', 'running'].includes(snapshot.status)
        ? 'cancelling' : snapshot.status,
      operation_type: snapshot.operation_type || snapshot.progress?.operation_type || current.operation_type,
      sources: snapshot.progress?.sources || current.sources || {},
      configured_sources: snapshot.progress?.configured_sources || current.configured_sources || [],
      sequence: snapshot.progress?.sequence || current.sequence || 0,
    }
    if (snapshot.status === 'completed' && snapshot.reference) {
      patchCompletedReference(next, snapshot.reference)
    }
    if (snapshot.progress?.operation_type === 'reextract-errors' && ['completed', 'cancelled', 'error'].includes(snapshot.status)
      && useHistoryStore.getState().selectedCheckId === snapshot.check_id) {
      useHistoryStore.getState().selectCheck?.(snapshot.check_id, { force: true })?.catch(() => undefined)
    }
    set(state => ({ operations: { ...state.operations, [key]: next } }))
  },

  getForReference: (checkId, referenceKey) =>
    get().operations[referenceSearchKey(checkId, referenceKey)] || null,
}))
