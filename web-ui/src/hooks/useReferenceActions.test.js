import { act, renderHook } from '@testing-library/react'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/api', () => ({
  addReferenceToCheck: vi.fn(),
  removeReferenceFromCheck: vi.fn(),
  suggestAlternativeReference: vi.fn(),
  startReferenceSearch: vi.fn(),
  startReferenceVerification: vi.fn(),
  cancelReferenceSearch: vi.fn(),
}))

import useReferenceActions from './useReferenceActions'
import { startReferenceSearch, startReferenceVerification, suggestAlternativeReference } from '../utils/api'
import { referenceRowIdentity } from '../utils/referenceIdentity'
import { useCheckStore } from '../stores/useCheckStore'
import { useHistoryStore } from '../stores/useHistoryStore'

const originalSelectCheck = useHistoryStore.getState().selectCheck

describe('useReferenceActions re-verification', () => {
  const reference = {
    ref_uid: 'row-ref-1',
    id: 'ref-1',
    index: 0,
    title: 'Original title',
    status: 'warning',
    errors: [],
    warnings: [{ warning_type: 'title' }],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    const selectedCheck = {
      id: 17,
      total_refs: 1,
      status: 'completed',
      results: [reference],
    }
    useHistoryStore.setState({
      selectedCheckId: 17,
      selectedCheck,
      history: [selectedCheck],
      detailCache: { 17: { check: selectedCheck, fetchedAt: Date.now() } },
      isLoadingDetail: false,
      selectCheck: vi.fn(),
    })
    useCheckStore.setState({
      currentCheckId: 17,
      references: [reference],
    })
    vi.stubGlobal('alert', vi.fn())
  })

  it('queues re-verification without waiting for the verifier response', async () => {
    startReferenceVerification.mockResolvedValue({ data: {
      operation_id: 'op-verify-1', session_id: 'reference-verify-1', check_id: 17,
      reference_key: 'uid:row-ref-1', operation_type: 'verify', status: 'queued',
    } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleReverify(reference, 0)
    })

    expect(startReferenceVerification).toHaveBeenCalledWith(17, 'uid:row-ref-1', {
      expected_id: 'ref-1',
      expected_index: 0,
      expected_title: 'Original title',
    })
    expect(result.current.getReferenceSearchOperation(reference, 0)).toMatchObject({
      operation_id: 'op-verify-1', operation_type: 'verify', status: 'queued',
    })
    expect(useHistoryStore.getState().selectCheck).not.toHaveBeenCalled()
    expect(result.current.isReverifying('uid:row-ref-1')).toBe(false)
  })

  it('tracks Search all DBs separately from document re-extraction', async () => {
    startReferenceSearch.mockResolvedValue({
      data: {
        operation_id: 'op-1', session_id: 'reference-search-1', check_id: 17,
        reference_key: 'uid:row-ref-1', status: 'queued',
      },
    })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleReverifyAllDatabases(reference, 0)
    })

    expect(startReferenceSearch).toHaveBeenCalledWith(17, 'uid:row-ref-1', expect.objectContaining({
      expected_id: 'ref-1',
      expected_index: 0,
      expected_title: 'Original title',
    }))
    expect(result.current.getReferenceSearchOperation(reference, 0)).toMatchObject({
      operation_id: 'op-1',
      status: 'queued',
    })
    expect(startReferenceVerification).not.toHaveBeenCalled()
  })

  it('keeps duplicate citation indexes on separate action identities', async () => {
    const duplicateRows = [
      { ref_uid: 'row-first', index: 26, title: 'First work', status: 'unverified' },
      { ref_uid: 'row-second', index: 26, title: 'Second work', status: 'unverified' },
    ]
    useHistoryStore.setState({
      selectedCheckId: 17,
      selectedCheck: { id: 17, status: 'completed', results: duplicateRows },
    })
    let finishSuggestion
    suggestAlternativeReference.mockImplementation(() => new Promise(resolve => {
      finishSuggestion = resolve
    }))
    const { result } = renderHook(() => useReferenceActions())

    let request
    await act(async () => {
      request = result.current.handleSuggestAlt(duplicateRows[1], 1)
      await Promise.resolve()
    })

    expect(suggestAlternativeReference).toHaveBeenCalledWith(17, 'uid:row-second')
    expect(result.current.isSuggesting(referenceRowIdentity(duplicateRows[0], 0))).toBe(false)
    expect(result.current.isSuggesting(referenceRowIdentity(duplicateRows[1], 1))).toBe(true)

    await act(async () => {
      finishSuggestion({ data: { suggestions: [] } })
      await request
    })
  })

  it('sends manual metadata edits as fresh verification overrides', async () => {
    startReferenceVerification.mockResolvedValue({ data: {
      operation_id: 'op-edit', session_id: 'reference-verify-edit', check_id: 17,
      reference_key: 'uid:row-ref-1', operation_type: 'verify', status: 'queued',
    } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleEditMetadata(reference, 0, {
        title: 'Edited title',
        authors: ['Edited Author'],
        year: '2005',
      })
    })

    expect(startReferenceVerification).toHaveBeenCalledWith(17, 'uid:row-ref-1', expect.objectContaining({
      manual_edit: true,
      force_all_databases: true,
      overrides: {
        title: 'Edited title',
        authors: ['Edited Author'],
        year: '2005',
      },
    }))
  })

  it('restores the server-side extracted metadata snapshot', async () => {
    startReferenceVerification.mockResolvedValue({ data: {
      operation_id: 'op-restore', session_id: 'reference-verify-restore', check_id: 17,
      reference_key: 'uid:row-ref-1', operation_type: 'verify', status: 'queued',
    } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleRestoreExtractedMetadata(reference, 0)
    })

    expect(startReferenceVerification).toHaveBeenCalledWith(17, 'uid:row-ref-1', expect.objectContaining({
      restore_extracted: true,
      force_all_databases: true,
    }))
  })

  it('queues an edit against the clicked persisted identity when the view remapped it', async () => {
    const persistedRows = [
      { index: 17, title: 'Previous reference', status: 'verified' },
      { index: 18, title: 'Bad extracted title', status: 'unverified' },
    ]
    const displayedReference = {
      ...persistedRows[1],
      index: 1,
    }
    const selectedCheck = {
      id: 17,
      total_refs: 2,
      status: 'completed',
      results: persistedRows,
    }
    useHistoryStore.setState({
      selectedCheckId: 17,
      selectedCheck,
      history: [selectedCheck],
    })
    useCheckStore.setState({ currentCheckId: null, references: [] })
    startReferenceVerification.mockResolvedValue({ data: {
      operation_id: 'op-remapped', session_id: 'reference-verify-remapped', check_id: 17,
      reference_key: 'uid:row-remapped', operation_type: 'verify', status: 'queued',
    } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleEditMetadata(displayedReference, 1, {
        title: 'Corrected title',
      })
    })

    expect(startReferenceVerification).toHaveBeenCalledWith(17, 'index:1', expect.objectContaining({
      expected_index: 1,
      expected_title: 'Bad extracted title',
      manual_edit: true,
    }))
  })
})

afterAll(() => {
  useHistoryStore.setState({ selectCheck: originalSelectCheck })
  vi.unstubAllGlobals()
})
