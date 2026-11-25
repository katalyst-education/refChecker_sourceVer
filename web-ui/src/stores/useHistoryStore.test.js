import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'

// Mock the api module
vi.mock('../utils/api', () => ({
  getHistory: vi.fn(() => Promise.resolve({ data: [] })),
  getCheckDetail: vi.fn(() => Promise.resolve({ data: {} })),
  deleteCheck: vi.fn(() => Promise.resolve({ data: {} })),
  updateCheckLabel: vi.fn(() => Promise.resolve({ data: {} })),
}))

describe('useHistoryStore', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('keeps the latest check selected when detail responses arrive out of order', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    let finishFirst
    api.getCheckDetail.mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve }))
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 2, status: 'completed', results: [] } })
    const first = useHistoryStore.getState().selectCheck(1)
    await useHistoryStore.getState().selectCheck(2)
    finishFirst({ data: { id: 1, status: 'completed', results: [] } })
    await first
    expect(useHistoryStore.getState().selectedCheckId).toBe(2)
    expect(useHistoryStore.getState().selectedCheck.id).toBe(2)
  })

  it('ignores an earlier request failure after selecting another check', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    let failFirst
    api.getCheckDetail.mockImplementationOnce(() => new Promise((_resolve, reject) => { failFirst = reject }))
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 2, status: 'completed', results: [] } })
    const first = useHistoryStore.getState().selectCheck(1)
    await useHistoryStore.getState().selectCheck(2)
    failFirst(new Error('Earlier check failed'))
    await first
    expect(useHistoryStore.getState().error).toBeNull()
    expect(useHistoryStore.getState().selectedCheck.id).toBe(2)
  })

  it('keeps a background history refresh from replacing a newer paper selection', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    const completed = { id: 1, status: 'completed', results: [] }
    useHistoryStore.setState({ selectedCheckId: 1, selectedCheck: { id: 1, status: 'in_progress' } })
    api.getHistory.mockResolvedValueOnce({ data: [completed] })
    let finishRefresh
    api.getCheckDetail.mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve }))
    const refreshing = useHistoryStore.getState().fetchHistory()
    await vi.waitFor(() => expect(finishRefresh).toBeTypeOf('function'))
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 2, status: 'completed', results: [] } })
    await useHistoryStore.getState().selectCheck(2)
    finishRefresh({ data: completed })
    await refreshing
    expect(useHistoryStore.getState().selectedCheckId).toBe(2)
    expect(useHistoryStore.getState().selectedCheck.id).toBe(2)
  })

  it('keeps the newest detail when returning to a check with an older request pending', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    let finishOld
    api.getCheckDetail.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 2, status: 'completed', results: [] } })
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 1, status: 'completed',
      reference_lists: [{ id: 'custom', name: 'Current name' }], results: [],
    } })
    const oldRequest = useHistoryStore.getState().selectCheck(1)
    await useHistoryStore.getState().selectCheck(2)
    await useHistoryStore.getState().selectCheck(1)
    finishOld({ data: { id: 1, status: 'completed',
      reference_lists: [{ id: 'custom', name: 'Old name' }], results: [],
    } })
    await oldRequest
    expect(useHistoryStore.getState().selectedCheck.reference_lists[0].name).toBe('Current name')
  })

  it('keeps freshly fetched list names after the detail cache is invalidated', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    useHistoryStore.setState({ history: [{ id: 1, status: 'completed',
      reference_lists: [{ id: 'custom', name: 'Old name' }],
      results: [{ index: 0, status: 'verified' }],
    }] })
    api.getCheckDetail.mockResolvedValueOnce({ data: { id: 1, status: 'completed',
      reference_lists: [{ id: 'custom', name: 'Current name' }],
      results: [{ index: 0, status: 'verified' }],
    } })
    await useHistoryStore.getState().selectCheck(1, { force: true })
    useHistoryStore.setState({ selectedCheck: null, selectedCheckId: null, detailCache: {} })
    await useHistoryStore.getState().selectCheck(1)
    expect(useHistoryStore.getState().selectedCheck.reference_lists).toEqual([{ id: 'custom', name: 'Current name' }])
  })

  it('should initialize with empty history', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(result.current.history).toEqual([])
    expect(result.current.selectedCheckId).toBeNull()
    expect(result.current.selectedCheck).toBeNull()
    expect(result.current.isLoading).toBe(false)
  })

  it('should have fetchHistory method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.fetchHistory).toBe('function')
  })

  it('should have selectCheck method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.selectCheck).toBe('function')
  })

  it.each(['initializeWithPlaceholder', 'fetchHistory'])('restores saved lists on the first selection after %s', async (loadHistory) => {
    const api = await import('../utils/api')
    const { useHistoryStore } = await import('./useHistoryStore')
    const check = {
      id: 42,
      status: 'completed',
      reference_lists: [
        { id: 'further_checks', name: 'Further Checks' },
        { id: 'custom-id', name: 'Check print edition' },
      ],
      results: [{ index: 1, title: 'Filed reference', status: 'verified', review_list: 'custom-id' }],
    }
    api.getHistory.mockResolvedValueOnce({ data: [check] })
    api.getCheckDetail.mockClear()

    await useHistoryStore.getState()[loadHistory]()
    await useHistoryStore.getState().selectCheck(42)

    const selected = useHistoryStore.getState().selectedCheck
    expect(selected.reference_lists).toEqual(check.reference_lists)
    expect(selected.results[0].review_list).toBe('custom-id')
    expect(api.getCheckDetail).not.toHaveBeenCalled()
  })

  it('should have deleteCheck method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.deleteCheck).toBe('function')
  })

  it('should have updateLabel method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.updateLabel).toBe('function')
  })

  it('should have clearSelection method', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    
    expect(typeof result.current.clearSelection).toBe('function')
  })

  it('should populate history results from live reference updates', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())

    act(() => {
      useHistoryStore.setState({
        history: [{ id: 42, status: 'in_progress', total_refs: 3, results: undefined }],
      })
    })

    act(() => {
      result.current.updateHistoryReference(42, 1, {
        title: 'Updated ref',
        status: 'unverified',
        errors: [{ error_type: 'unverified' }],
      })
    })

    const updated = result.current.history.find(item => item.id === 42)
    expect(updated.results).toHaveLength(3)
    expect(updated.results[0].status).toBe('pending')
    expect(updated.results[1]).toMatchObject({
      index: 1,
      title: 'Updated ref',
      status: 'unverified',
    })
  })

  it('should preserve live results when progress payload fields are undefined', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())

    act(() => {
      useHistoryStore.setState({
        history: [{
          id: 43,
          status: 'in_progress',
          total_refs: 1,
          results: [{ index: 0, title: 'Live ref', status: 'verified' }],
        }],
      })
    })

    act(() => {
      result.current.updateHistoryProgress(43, {
        status: 'completed',
        results: undefined,
      })
    })

    const updated = result.current.history.find(item => item.id === 43)
    expect(updated.status).toBe('completed')
    expect(updated.results).toEqual([{ index: 0, title: 'Live ref', status: 'verified' }])
  })

  it('preserves a server citation index when updating an array position', async () => {
    const { useHistoryStore } = await import('./useHistoryStore')
    const { result } = renderHook(() => useHistoryStore())
    const check = {
      id: 44,
      total_refs: 1,
      results: [{ index: 18, title: 'Extracted title', status: 'unverified' }],
    }
    act(() => {
      useHistoryStore.setState({ history: [check], selectedCheckId: 44, selectedCheck: check })
      result.current.updateHistoryReference(44, 0, {
        index: 18,
        title: 'Edited title',
        status: 'verified',
      })
    })

    expect(result.current.selectedCheck.results[0]).toMatchObject({
      index: 18,
      title: 'Edited title',
      status: 'verified',
    })
  })
})
