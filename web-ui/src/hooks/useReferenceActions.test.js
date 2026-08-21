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
})

afterAll(() => {
  useHistoryStore.setState({ selectCheck: originalSelectCheck })
  vi.unstubAllGlobals()
})
