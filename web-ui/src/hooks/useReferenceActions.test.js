import { act, renderHook } from '@testing-library/react'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/api', () => ({
  addReferenceToCheck: vi.fn(),
  removeReferenceFromCheck: vi.fn(),
  suggestAlternativeReference: vi.fn(),
  verifyReferenceInCheck: vi.fn(),
}))

import useReferenceActions from './useReferenceActions'
import { verifyReferenceInCheck } from '../utils/api'
import { useCheckStore } from '../stores/useCheckStore'
import { useHistoryStore } from '../stores/useHistoryStore'

const originalSelectCheck = useHistoryStore.getState().selectCheck

describe('useReferenceActions re-verification', () => {
  const reference = {
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

  it('updates only the returned row without reloading the whole check', async () => {
    let finishRequest
    verifyReferenceInCheck.mockImplementation(() => new Promise(resolve => {
      finishRequest = resolve
    }))
    const updated = {
      ...reference,
      title: 'Freshly extracted title',
      status: 'verified',
      warnings: [],
    }
    const { result } = renderHook(() => useReferenceActions())

    let request
    await act(async () => {
      request = result.current.handleReverify(reference, 0)
      await Promise.resolve()
    })

    expect(result.current.getReverifyAction('ref-1')).toBe('reextract')
    expect(result.current.isReverifying('ref-1')).toBe(true)

    await act(async () => {
      finishRequest({ data: { reference: updated } })
      await request
    })

    expect(verifyReferenceInCheck).toHaveBeenCalledWith(17, 'id:ref-1', {
      expected_id: 'ref-1',
      expected_index: 0,
      expected_title: 'Original title',
    })
    expect(useHistoryStore.getState().selectedCheck.results[0]).toMatchObject(updated)
    expect(useCheckStore.getState().references[0]).toMatchObject(updated)
    expect(useHistoryStore.getState().detailCache[17]).toBeUndefined()
    expect(useHistoryStore.getState().selectCheck).not.toHaveBeenCalled()
    expect(useHistoryStore.getState().isLoadingDetail).toBe(false)
    expect(result.current.isReverifying('ref-1')).toBe(false)
  })

  it('tracks Search all DBs separately from document re-extraction', async () => {
    verifyReferenceInCheck.mockResolvedValue({
      data: { reference: { ...reference, status: 'verified', warnings: [] } },
    })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleReverifyAllDatabases(reference, 0)
    })

    expect(verifyReferenceInCheck).toHaveBeenCalledWith(17, 'id:ref-1', expect.objectContaining({
      force_all_databases: true,
    }))
  })

  it('sends manual metadata edits as fresh verification overrides', async () => {
    verifyReferenceInCheck.mockResolvedValue({
      data: { reference: { ...reference, title: 'Edited title', status: 'verified' } },
    })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleEditMetadata(reference, 0, {
        title: 'Edited title',
        authors: ['Edited Author'],
        year: '2005',
      })
    })

    expect(verifyReferenceInCheck).toHaveBeenCalledWith(17, 'id:ref-1', expect.objectContaining({
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
    verifyReferenceInCheck.mockResolvedValue({ data: { reference } })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleRestoreExtractedMetadata(reference, 0)
    })

    expect(verifyReferenceInCheck).toHaveBeenCalledWith(17, 'id:ref-1', expect.objectContaining({
      restore_extracted: true,
      force_all_databases: true,
    }))
  })

  it('updates the persisted history row when the view remapped it to a zero-based index', async () => {
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
    verifyReferenceInCheck.mockResolvedValue({
      data: {
        reference: {
          ...persistedRows[1],
          title: 'Corrected title',
          status: 'verified',
          manual_edit: { original: { title: 'Bad extracted title' } },
        },
      },
    })
    const { result } = renderHook(() => useReferenceActions())

    await act(async () => {
      await result.current.handleEditMetadata(displayedReference, 1, {
        title: 'Corrected title',
      })
    })

    const rows = useHistoryStore.getState().selectedCheck.results
    expect(rows[0]).toMatchObject({ index: 17, title: 'Previous reference' })
    expect(rows[1]).toMatchObject({
      index: 18,
      title: 'Corrected title',
      status: 'verified',
    })
  })
})

afterAll(() => {
  useHistoryStore.setState({ selectCheck: originalSelectCheck })
  vi.unstubAllGlobals()
})
