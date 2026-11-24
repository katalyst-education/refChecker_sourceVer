import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/useAuthStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { useReferenceSearchStore } from '../stores/useReferenceSearchStore'
import {
  cancelReferenceSearch, createWebSocket, getActiveReferenceSearches,
  getReferenceReextractions, getReferenceSearch, startReferenceReextraction,
} from '../utils/api'
import ReferenceSearchManager from './ReferenceSearchManager'
import ReferenceReextractionButton from './MainPanel/ReferenceReextractionButton'

vi.mock('../utils/api', async (importOriginal) => ({
  ...(await importOriginal()),
  createWebSocket: vi.fn(),
  getActiveReferenceSearches: vi.fn(),
  getReferenceReextractions: vi.fn(),
  getReferenceSearch: vi.fn(),
  startReferenceReextraction: vi.fn(),
  cancelReferenceSearch: vi.fn(),
}))

const operation = (completed = 3, sequence = 15) => ({
  operation_id: 'original-job', session_id: 'original-session', check_id: 25,
  reference_key: 'check:reextract-errors', status: 'running',
  progress: { operation_type: 'reextract-errors', sequence, completed, total: 73, message: 'Extracting references…' },
})
const flush = async () => { await act(async () => {}) }

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  useAuthStore.setState({ isLoading: false, authRequired: false, user: null })
  useHistoryStore.setState({ selectedCheckId: null, selectedCheck: null })
  useReferenceSearchStore.setState({ operations: {} })
  getActiveReferenceSearches.mockResolvedValue({ data: { operations: [] } })
  getReferenceReextractions.mockResolvedValue({ data: { operations: [] } })
  getReferenceSearch.mockResolvedValue({ data: operation() })
  cancelReferenceSearch.mockResolvedValue({ data: { status: 'cancellation_requested' } })
  createWebSocket.mockImplementation((sessionId, handlers) => ({ sessionId, handlers, close: vi.fn() }))
})

afterEach(() => {
  cleanup()
  vi.clearAllTimers()
  vi.useRealTimers()
})

it('retries discovery after a transient reload failure even with an empty store', async () => {
  getActiveReferenceSearches.mockRejectedValueOnce(new Error('temporary network failure'))
    .mockResolvedValue({ data: { operations: [operation()] } })
  render(<ReferenceSearchManager />)
  await flush()
  expect(createWebSocket).not.toHaveBeenCalled()

  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

  expect(createWebSocket).toHaveBeenCalledWith('original-session', expect.any(Object))
  expect(useReferenceSearchStore.getState().getForReference(25, 'check:reextract-errors').progress.completed).toBe(3)
})

it('waits for authentication before recovering jobs', async () => {
  useAuthStore.setState({ isLoading: true })
  render(<ReferenceSearchManager />)
  await flush()
  expect(getActiveReferenceSearches).not.toHaveBeenCalled()
  await act(async () => { useAuthStore.setState({ isLoading: false }) })
  expect(getActiveReferenceSearches).toHaveBeenCalledOnce()
})

it('reconnects a dropped progress socket automatically', async () => {
  getActiveReferenceSearches.mockResolvedValue({ data: { operations: [operation()] } })
  render(<ReferenceSearchManager />)
  await flush()
  const firstSocket = createWebSocket.mock.results[0].value
  act(() => firstSocket.handlers.onClose())
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(createWebSocket).toHaveBeenCalledTimes(2)
  expect(createWebSocket.mock.calls[1][0]).toBe('original-session')
})

it('rediscovers work when the browser reconnects', async () => {
  render(<ReferenceSearchManager />)
  await flush()
  getActiveReferenceSearches.mockResolvedValue({ data: { operations: [operation()] } })
  fireEvent(window, new Event('online'))
  await flush()
  expect(createWebSocket).toHaveBeenCalledWith('original-session', expect.any(Object))
})

it('restores and cancels the same server job after a page reload', async () => {
  const references = [{ status: 'error' }, { status: 'unverified' }]
  getActiveReferenceSearches.mockResolvedValue({ data: { operations: [operation()] } })
  getReferenceReextractions.mockResolvedValue({ data: { operations: [operation()] } })
  const page = () => <><ReferenceSearchManager /><ReferenceReextractionButton checkId={25} references={references} /></>
  const firstPage = render(page())
  await flush()
  expect(screen.getByRole('status')).toHaveTextContent('(3/73)')
  const firstSocket = createWebSocket.mock.results[0].value
  firstPage.unmount()
  expect(firstSocket.close).toHaveBeenCalledOnce()
  expect(cancelReferenceSearch).not.toHaveBeenCalled()

  useReferenceSearchStore.setState({ operations: {} })
  getActiveReferenceSearches.mockResolvedValue({ data: { operations: [operation(5, 20)] } })
  getReferenceReextractions.mockResolvedValue({ data: { operations: [operation(5, 20)] } })
  render(page())
  await flush()

  expect(screen.getByRole('status')).toHaveTextContent('(5/73)')
  expect(screen.getByRole('button', { name: 'Re-extracting references…' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await flush()
  expect(cancelReferenceSearch).toHaveBeenCalledWith('original-job')
  expect(startReferenceReextraction).not.toHaveBeenCalled()
})

it('retries restoring the check summary after a temporary failure', async () => {
  getReferenceReextractions.mockRejectedValueOnce(new Error('temporary failure'))
    .mockResolvedValue({ data: { operations: [operation()] } })
  render(<ReferenceReextractionButton checkId={25} references={[{ status: 'error' }]} />)
  await flush()
  expect(screen.getByRole('alert')).toHaveTextContent('Could not restore re-extraction status')
  expect(screen.getByRole('button', { name: 'Re-extract errors & unverified (1)' })).toBeDisabled()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
  expect(startReferenceReextraction).not.toHaveBeenCalled()
})
