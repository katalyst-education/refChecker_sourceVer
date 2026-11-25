import { act, renderHook } from '@testing-library/react'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/api', () => ({
  addReferenceToCheck: vi.fn(),
  removeReferenceFromCheck: vi.fn(),
  moveReferenceReviewList: vi.fn(),
  startReferenceSearch: vi.fn(),
  startReferenceVerification: vi.fn(),
  cancelReferenceSearch: vi.fn(),
  suggestAlternativeReference: vi.fn(),
}))

import useReferenceActions from './useReferenceActions'
import {
  moveReferenceReviewList,
  addReferenceToCheck,
  removeReferenceFromCheck,
  startReferenceSearch,
  startReferenceVerification,
  suggestAlternativeReference,
} from '../utils/api'
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

  it('restores a rejected removal at its original position in live and saved views', async () => {
    const second = { ref_uid: 'second', index: 0, title: 'Second', status: 'verified' }
    const rows = [reference, second]
    useCheckStore.setState({ references: rows })
    useHistoryStore.setState({ selectedCheck: { id: 17, results: rows }, history: [{ id: 17, results: rows }] })
    removeReferenceFromCheck.mockRejectedValueOnce(new Error('Remove rejected'))
    const { result } = renderHook(() => useReferenceActions())
    await act(async () => { await result.current.handleRemoveRef(reference, 0) })
    expect(useCheckStore.getState().references).toEqual(rows)
    expect(useHistoryStore.getState().selectedCheck.results).toEqual(rows)
    expect(result.current.removedRefs).toEqual([])
  })

  it('finishing a removal after navigation keeps the new paper open and its trash empty', async () => {
    let finish
    removeReferenceFromCheck.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { result } = renderHook(() => useReferenceActions())
    let removing
    act(() => { removing = result.current.handleRemoveRef(reference, 0) })
    act(() => { useHistoryStore.setState({ selectedCheckId: 18, selectedCheck: { id: 18, results: [] } }) })
    await act(async () => { finish({}); await removing })
    expect(useHistoryStore.getState().selectCheck).not.toHaveBeenCalled()
    expect(useHistoryStore.getState().selectedCheck.id).toBe(18)
    expect(result.current.removedRefs).toEqual([])
    expect(useHistoryStore.getState().history.find(row => row.id === 17).results).toEqual([])
    expect(useHistoryStore.getState().detailCache[17]).toBeUndefined()
  })

  it('leaves the active check feed unchanged when removing a reference from another paper', async () => {
    const liveRows = [{ ...reference, title: 'Other paper citation' }]
    useCheckStore.setState({ currentCheckId: 99, references: liveRows })
    removeReferenceFromCheck.mockResolvedValueOnce({})
    const { result } = renderHook(() => useReferenceActions())
    await act(async () => { await result.current.handleRemoveRef(reference, 0) })
    expect(useCheckStore.getState().references).toEqual(liveRows)
    expect(useHistoryStore.getState().history[0].results).toEqual([])
  })

  it('keeps an Undo placeholder out of an unrelated active paper', async () => {
    const liveRows = [{ ...reference, title: 'Unrelated citation' }]
    useCheckStore.setState({ currentCheckId: 99, references: liveRows })
    let finish
    addReferenceToCheck.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { result } = renderHook(() => useReferenceActions())
    let restoring
    act(() => { restoring = result.current.handleRestoreRef({ _stashKey: 'old', title: 'Removed citation', _originalPosition: 0 }) })
    expect(useCheckStore.getState().references).toEqual(liveRows)
    await act(async () => { finish({ data: {} }); await restoring })
    expect(useCheckStore.getState().references).toEqual(liveRows)
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

  it('saves a move to Unverified in both views without enqueuing a search', async () => {
    const reviewed = { ...reference, status: 'unverified', warnings: [], review_revision: 'move-1' }
    moveReferenceReviewList.mockResolvedValue({ data: { reference: reviewed } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleMoveReviewList(reference, 0, 'unverified')
    })

    expect(moveReferenceReviewList).toHaveBeenCalledWith(17, 'uid:row-ref-1', 'unverified')
    expect(useHistoryStore.getState().selectedCheck.results[0]).toEqual(reviewed)
    expect(useCheckStore.getState().references[0]).toEqual(reviewed)
    expect(startReferenceSearch).not.toHaveBeenCalled()
    expect(startReferenceVerification).not.toHaveBeenCalled()
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

describe('useReferenceActions alternative suggestions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useHistoryStore.setState({
      selectedCheckId: null,
      selectedCheck: null,
    })
  })

  it('tracks duplicate citation indexes by stable row identity', async () => {
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
    expect(result.current.isSuggesting('uid:row-first')).toBe(false)
    expect(result.current.isSuggesting('uid:row-second')).toBe(true)

    await act(async () => {
      finishSuggestion({ data: { candidates: [] } })
      await request
    })

    expect(result.current.isSuggesting('uid:row-second')).toBe(false)
    expect(result.current.suggestFor).toEqual({
      ref_id: 'uid:row-second',
      check_id: 17,
      api_ref_id: 'uid:row-second',
      candidates: [],
    })
  })
})

afterAll(() => {
  useHistoryStore.setState({ selectCheck: originalSelectCheck })
  vi.unstubAllGlobals()
})
