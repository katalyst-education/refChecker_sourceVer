import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/api', () => ({
  getBatch: vi.fn(), getCheckDetail: vi.fn(), deleteCheck: vi.fn(), updateCheckLabel: vi.fn(),
}))
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const check = (id, extra = {}) => ({ id, status: 'completed', results: [{ title: `Paper ${id}`, status: 'verified' }], ...extra })

beforeEach(() => { vi.resetModules(); vi.resetAllMocks() })
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers() })

describe('batch navigation', () => {
  it.each(['success', 'failure'])('hides the previous batch and keeps loading after an outdated %s', async (outcome) => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    store.setState({ selectedBatchId: 'old', selectedBatch: { batch_id: 'old' } })
    const first = deferred(), second = deferred()
    api.getBatch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const one = store.getState().selectBatch('one')
    const two = store.getState().selectBatch('two')
    expect(store.getState().selectedBatch).toBeNull()
    if (outcome === 'success') first.resolve({ data: { batch_id: 'one' } })
    else first.reject(new Error('Earlier batch failed'))
    await one
    expect(store.getState().isLoadingBatch).toBe(true)
    expect(store.getState().batchError).toBeNull()
    second.resolve({ data: { batch_id: 'two' } })
    await two
    expect(store.getState().selectedBatch.batch_id).toBe('two')
    expect(store.getState().isLoadingBatch).toBe(false)
  })

  it('clears batch context when starting a new check', async () => {
    const { useHistoryStore: store } = await import('./useHistoryStore')
    store.setState({ selectedBatchId: 'old', selectedBatch: { batch_id: 'old' } })
    await store.getState().selectCheck(-1)
    expect(store.getState().selectedBatchId).toBeNull()
    expect(store.getState().selectedBatch).toBeNull()
    expect(store.getState().selectedCheckId).toBe(-1)
  })

  it('keeps the newest response when reloading the same batch', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    const older = deferred()
    api.getBatch.mockReturnValueOnce(older.promise).mockResolvedValueOnce({ data: { batch_id: 'one', batch_label: 'New label' } })
    const first = store.getState().selectBatch('one')
    await store.getState().selectBatch('one')
    older.resolve({ data: { batch_id: 'one', batch_label: 'Old label' } })
    await first
    expect(store.getState().selectedBatch.batch_label).toBe('New label')
  })

  it('clears the batch timeout after a successful load', async () => {
    vi.useFakeTimers()
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    api.getBatch.mockResolvedValueOnce({ data: { batch_id: 'one' } })
    await store.getState().selectBatch('one')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shows loading and a recoverable error for a batch paper that fails to open', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    store.setState({ selectedBatchId: 'batch', selectedCheck: check(1), selectedCheckId: 1 })
    const request = deferred()
    api.getCheckDetail.mockReturnValueOnce(request.promise)
    const opening = store.getState().openBatchChild(2)
    expect(store.getState().isLoadingDetail).toBe(true)
    request.reject(new Error('Could not open paper'))
    await opening
    expect(store.getState().error).toBe('Could not open paper')
    expect(store.getState().isLoadingDetail).toBe(false)
    expect(store.getState().selectedBatchId).toBe('batch')
  })
})

describe('history mutations', () => {
  it.each(['label', 'title'])('keeps the updated %s when returning through the detail cache', async (field) => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    const paper = check(1, { custom_label: 'Old', paper_title: 'Old' })
    store.setState({ history: [paper], selectedCheck: paper, selectedCheckId: 1,
      detailCache: { 1: { check: paper, fetchedAt: Date.now() } } })
    api.updateCheckLabel.mockResolvedValueOnce({ data: {} })
    if (field === 'label') await store.getState().updateLabel(1, 'New')
    else store.getState().updateHistoryItemTitle(1, 'New')
    store.getState().clearSelection()
    await store.getState().selectCheck(1)
    expect(store.getState().selectedCheck[field === 'label' ? 'custom_label' : 'paper_title']).toBe('New')
  })

  it('deleting a background paper leaves the current paper alone and removes cached deleted data', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    const first = check(1), second = check(2)
    store.setState({ history: [first, second], selectedCheckId: 2, selectedCheck: second,
      detailCache: { 1: { check: first, fetchedAt: Date.now() } } })
    api.deleteCheck.mockResolvedValueOnce({})
    await store.getState().deleteCheck(1)
    expect(api.getCheckDetail).not.toHaveBeenCalled()
    expect(store.getState().selectedCheck).toBe(second)
    expect(store.getState().detailCache[1]).toBeUndefined()
  })

  it('keeps the latest selection while loading the paper selected after deletion', async () => {
    const api = await import('../utils/api')
    const { useHistoryStore: store } = await import('./useHistoryStore')
    store.setState({ history: [check(1), check(2), check(3)], selectedCheckId: 1, selectedCheck: check(1) })
    api.deleteCheck.mockResolvedValueOnce({})
    const loading = deferred()
    api.getCheckDetail.mockReturnValueOnce(loading.promise)
    const deleting = store.getState().deleteCheck(1)
    await vi.waitFor(() => expect(store.getState().selectedCheckId).toBe(2))
    await store.getState().selectCheck(3)
    loading.resolve({ data: check(2) })
    await deleting
    expect(store.getState().selectedCheckId).toBe(3)
    expect(store.getState().selectedCheck.id).toBe(3)
  })

  it('deduplicates repeated history insertion for the same check', async () => {
    const { useHistoryStore: store } = await import('./useHistoryStore')
    store.getState().addToHistory(check(1))
    store.getState().addToHistory(check(1, { paper_title: 'Updated' }))
    expect(store.getState().history).toHaveLength(1)
    expect(store.getState().history[0].paper_title).toBe('Updated')
  })
})
