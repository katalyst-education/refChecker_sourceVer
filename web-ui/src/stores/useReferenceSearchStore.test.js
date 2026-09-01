import { beforeEach, describe, expect, it } from 'vitest'
import { useCheckStore } from './useCheckStore'
import { useHistoryStore } from './useHistoryStore'
import { useReferenceSearchStore } from './useReferenceSearchStore'

describe('reference search operation state', () => {
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
