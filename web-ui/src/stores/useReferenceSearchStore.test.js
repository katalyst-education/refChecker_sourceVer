import { beforeEach, describe, expect, it } from 'vitest'
import { useCheckStore } from './useCheckStore'
import { useHistoryStore } from './useHistoryStore'
import { useReferenceSearchStore } from './useReferenceSearchStore'

describe('reference search operation state', () => {
  it('restores the persisted sequence and rejects older replayed progress', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'reload-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'running',
      progress: { sequence: 20, completed: 8, total: 10 } })
    store.handleMessage({ type: 'reference_reextract_progress', operation_id: 'reload-job', check_id: 17,
      reference_key: 'check:reextract-errors', status: 'running', sequence: 10, completed: 2 })
    store.applySnapshot({ operation_id: 'reload-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'running',
      progress: { sequence: 15, completed: 5, total: 10 } })
    expect(store.getForReference(17, 'check:reextract-errors').progress.completed).toBe(8)
    expect(store.getForReference(17, 'check:reextract-errors').sequence).toBe(20)
  })

  it('keeps a completed run terminal when a delayed running snapshot arrives', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'done-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'completed', progress: { sequence: 30 } })
    store.applySnapshot({ operation_id: 'done-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'running', progress: { sequence: 31 } })
    expect(store.getForReference(17, 'check:reextract-errors').status).toBe('completed')
  })

  it('ignores late updates from a previous run of the same action', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'new-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'running', progress: { sequence: 1 } })
    store.handleMessage({ type: 'reference_reextract_completed', operation_id: 'old-job', check_id: 17,
      reference_key: 'check:reextract-errors', status: 'completed', sequence: 99 })
    store.applySnapshot({ operation_id: 'old-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'completed', progress: { sequence: 100 } })
    expect(store.getForReference(17, 'check:reextract-errors').operation_id).toBe('new-job')
  })

  it('retains cancellation while the server finishes the current extraction step', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'cancel-job', check_id: 17, reference_key: 'check:reextract-errors', status: 'cancelling', progress: { sequence: 1 } })
    store.handleMessage({ type: 'reference_reextract_progress', operation_id: 'cancel-job', check_id: 17,
      reference_key: 'check:reextract-errors', status: 'running', sequence: 2, completed: 3 })
    expect(store.getForReference(17, 'check:reextract-errors').status).toBe('cancelling')
    expect(store.getForReference(17, 'check:reextract-errors').progress.completed).toBe(3)
  })
  it('patches each completed row from a central re-extraction operation', () => {
    useReferenceSearchStore.setState({ operations: {} })
    useCheckStore.setState({ currentCheckId: 17, references: [{ ref_uid: 'row-1', status: 'error' }, { ref_uid: 'row-2', status: 'verified' }] })
    useHistoryStore.setState({ selectedCheckId: 17, selectedCheck: { id: 17, results: [{ ref_uid: 'row-1', status: 'error' }, { ref_uid: 'row-2', status: 'verified' }] } })
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'batch-1', check_id: 17, reference_key: 'check:reextract-errors', status: 'running' })
    store.handleMessage({ type: 'reference_reextract_progress', operation_id: 'batch-1', check_id: 17,
      reference_key: 'check:reextract-errors', updated_reference_key: 'uid:row-1', sequence: 1,
      status: 'running', total: 1, completed: 1, reference: { ref_uid: 'row-1', status: 'verified' } })
    expect(useCheckStore.getState().references.map(ref => ref.status)).toEqual(['verified', 'verified'])
    expect(store.getForReference(17, 'check:reextract-errors').completed).toBe(1)
  })
  beforeEach(() => {
    useReferenceSearchStore.setState({ operations: {} })
    useCheckStore.setState({ currentCheckId: 17, references: [{ id: 'ref-1', status: 'warning' }] })
    useHistoryStore.setState({
      selectedCheckId: 17,
      selectedCheck: { id: 17, results: [{ id: 'ref-1', status: 'warning' }] },
    })
  })

  it('tracks per-source progress and ignores older sequence numbers', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-1', session_id: 's-1', check_id: 17,
      reference_key: 'id:ref-1', status: 'queued' })
    store.handleMessage({ type: 'reference_search_source', operation_id: 'op-1',
      check_id: 17, reference_key: 'id:ref-1', sequence: 4,
      database: 'crossref', label: 'CrossRef', status: 'excluded_wrong_match',
      reason: 'title similarity is only 0.21',
      identity: { status: 'wrong_match', title_similarity: 0.21 } })
    store.handleMessage({ type: 'reference_search_source', operation_id: 'op-1',
      check_id: 17, reference_key: 'id:ref-1', sequence: 3,
      database: 'crossref', label: 'CrossRef', status: 'failed' })

    const operation = useReferenceSearchStore.getState().getForReference(17, 'id:ref-1')
    expect(operation.sources.crossref.status).toBe('excluded_wrong_match')
    expect(operation.sources.crossref.reason).toBe('title similarity is only 0.21')
    expect(operation.sources.crossref.identity.status).toBe('wrong_match')
    expect(operation.sequence).toBe(4)
  })

  it('patches the reference without changing the parent check lifecycle', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-1', session_id: 's-1', check_id: 17,
      reference_key: 'id:ref-1', status: 'running' })
    store.handleMessage({ type: 'reference_search_completed', operation_id: 'op-1',
      check_id: 17, reference_key: 'id:ref-1', sequence: 2,
      reference: { id: 'ref-1', status: 'verified' }, duration_ms: 100 })

    expect(useCheckStore.getState().references[0].status).toBe('verified')
    expect(useHistoryStore.getState().selectedCheck.results[0].status).toBe('verified')
    expect(useCheckStore.getState().status).not.toBe('completed')
  })

  it('replaces old verification fields and invalidates cached details after a search finishes offscreen', () => {
    const old = { ref_uid: 'row-139', status: 'error', errors: [{ error_type: 'author' }], verified_authors: ['Wrong match'] }
    const fresh = { ref_uid: 'row-139', status: 'verified', errors: [], warnings: [] }
    const otherCheck = { id: 18, results: [] }
    const history = { id: 17, results: [old] }
    useHistoryStore.setState({
      history: [history], selectedCheckId: 18, selectedCheck: otherCheck,
      detailCache: { 17: { check: history, fetchedAt: Date.now() } },
    })
    useCheckStore.setState({ currentCheckId: 17, references: [old] })
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-139', check_id: 17, reference_key: 'uid:row-139', status: 'running' })
    store.applySnapshot({ operation_id: 'op-139', check_id: 17, reference_key: 'uid:row-139', status: 'completed', reference: fresh })

    expect(useHistoryStore.getState().detailCache[17]).toBeUndefined()
    expect(useHistoryStore.getState().selectedCheck).toEqual(otherCheck)
    expect(useHistoryStore.getState().history[0].results[0]).toEqual(fresh)
    expect(useCheckStore.getState().references[0]).toEqual({ ...fresh, index: 0 })
  })

  it('keeps the final source summaries delivered with completion', () => {
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-final', session_id: 's-final', check_id: 17,
      reference_key: 'id:ref-1', status: 'running' })
    store.handleMessage({ type: 'reference_search_completed', operation_id: 'op-final',
      check_id: 17, reference_key: 'id:ref-1', sequence: 2,
      reference: { id: 'ref-1', status: 'verified' },
      sources: [{ database: 'crossref', label: 'CrossRef', status: 'matched',
        candidate: { title: 'Matched title', authors: ['Ada Lovelace'], year: 2024,
          url: 'https://doi.org/10.1000/example' } }],
      duration_ms: 100 })

    const operation = useReferenceSearchStore.getState().getForReference(17, 'id:ref-1')
    expect(operation.sources.crossref.candidate.authors).toEqual(['Ada Lovelace'])
    expect(operation.sources.crossref.candidate.url).toBe('https://doi.org/10.1000/example')
  })

  it('keeps duplicate citation indexes bound to the resolved row position', () => {
    const references = [
      { index: 26, title: 'Management Services', status: 'warning' },
      { index: 26, title: 'Kostenrechnung im Dienstleistungsbetrieb', status: 'unverified' },
    ]
    useCheckStore.setState({ currentCheckId: 17, references: references.map(row => ({ ...row })) })
    useHistoryStore.setState({
      selectedCheckId: 17,
      selectedCheck: { id: 17, results: references.map(row => ({ ...row })) },
    })
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-duplicate', session_id: 's-duplicate', check_id: 17,
      reference_key: 'pos:1', status: 'running' })
    store.handleMessage({ type: 'reference_search_completed', operation_id: 'op-duplicate',
      check_id: 17, reference_key: 'pos:1', sequence: 2,
      reference: { index: 26, title: 'Kostenrechnung im Dienstleistungsbetrieb', status: 'verified' },
      duration_ms: 100 })

    expect(useCheckStore.getState().references.map(row => row.status)).toEqual(['warning', 'verified'])
    expect(useHistoryStore.getState().selectedCheck.results.map(row => row.title)).toEqual([
      'Management Services',
      'Kostenrechnung im Dienstleistungsbetrieb',
    ])
  })

  it('patches the durable uid row after list positions change', () => {
    const references = [
      { ref_uid: 'row-second', index: 26, title: 'Second work', status: 'warning' },
      { ref_uid: 'row-first', index: 26, title: 'First work', status: 'warning' },
    ]
    useCheckStore.setState({ currentCheckId: 17, references })
    const store = useReferenceSearchStore.getState()
    store.register({ operation_id: 'op-uid', session_id: 's-uid', check_id: 17,
      reference_key: 'uid:row-second', status: 'running' })
    store.handleMessage({ type: 'reference_search_completed', operation_id: 'op-uid',
      check_id: 17, reference_key: 'uid:row-second', sequence: 2,
      reference: { ...references[0], status: 'verified' }, duration_ms: 100 })

    expect(useCheckStore.getState().references[0].status).toBe('verified')
    expect(useCheckStore.getState().references[1].status).toBe('warning')
  })
})
