import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useReferenceSearchStore } from '../../stores/useReferenceSearchStore'
import { cancelReferenceSearch, getReferenceReextractions, startReferenceReextraction } from '../../utils/api'
import ReferenceReextractionButton from './ReferenceReextractionButton'

vi.mock('../../utils/api', () => ({
  startReferenceReextraction: vi.fn(),
  cancelReferenceSearch: vi.fn(),
  getReferenceReextractions: vi.fn(),
}))

const references = ['error', 'unverified', 'verified', 'warning'].map((status, index) => ({ index: index + 1, status }))

beforeEach(() => {
  vi.clearAllMocks()
  useReferenceSearchStore.setState({ operations: {} })
  getReferenceReextractions.mockResolvedValue({ data: { operations: [] } })
})

it('starts one central operation for errors and unverified references', async () => {
  startReferenceReextraction.mockResolvedValue({ data: {
    operation_id: 'batch-1', session_id: 's-1', check_id: 25,
    reference_key: 'check:reextract-errors', operation_type: 'reextract-errors', status: 'queued',
  } })
  render(<ReferenceReextractionButton checkId={25} references={references} />)

  await waitFor(() => expect(screen.getByRole('button', { name: 'Re-extract errors & unverified (2)' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Re-extract errors & unverified (2)' }))

  await waitFor(() => expect(startReferenceReextraction).toHaveBeenCalledWith(25))
  expect(await screen.findByRole('button', { name: 'Re-extracting references…' })).toBeDisabled()
  expect(useReferenceSearchStore.getState().getForReference(25, 'check:reextract-errors').operation_id).toBe('batch-1')
})

it('disables re-extraction when there are no eligible references', () => {
  render(<ReferenceReextractionButton checkId={25} references={references.slice(2)} />)
  expect(screen.getByRole('button', { name: 'Re-extract errors & unverified (0)' })).toBeDisabled()
})

it('recovers progress and offers cancellation', async () => {
  useReferenceSearchStore.getState().register({
    operation_id: 'batch-1', check_id: 25, reference_key: 'check:reextract-errors', status: 'running',
    progress: { total: 2, completed: 1, message: 'Verifying re-extracted references…' },
  })
  cancelReferenceSearch.mockResolvedValue({ data: {} })
  render(<ReferenceReextractionButton checkId={25} references={references} />)

  expect(screen.getByRole('status')).toHaveTextContent('(1/2)')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(cancelReferenceSearch).toHaveBeenCalledWith('batch-1'))
  expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled()
})

it('explains which references still need review', async () => {
  useReferenceSearchStore.getState().register({
    operation_id: 'batch-1', check_id: 25, reference_key: 'check:reextract-errors', status: 'completed',
    progress: { message: 'Re-extracted and verified 1 of 2 references.', failures: [{ index: 21, message: 'Source entry needs review.' }] },
  })
  render(<ReferenceReextractionButton checkId={25} references={references} />)
  expect(screen.getByText('References needing review (1)')).toBeInTheDocument()
  expect(screen.getByText('[21] Source entry needs review.')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Re-extract errors & unverified (2)' })).toBeEnabled())
})

it('restores a running job and completed earlier summaries after reload', async () => {
  getReferenceReextractions.mockResolvedValue({ data: { operations: [
    { operation_id: 'original-job', check_id: 25, session_id: 'original-session', reference_key: 'check:reextract-errors',
      status: 'running', progress: { sequence: 20, completed: 5, total: 73, message: 'Extracting references…' } },
    { operation_id: 'previous-job', status: 'completed', progress: { message: 'Re-extracted and verified 53 of 73 references. 20 references need review.' } },
  ] } })
  render(<ReferenceReextractionButton checkId={25} references={references} />)

  expect(await screen.findByRole('button', { name: 'Cancel' })).toBeEnabled()
  expect(screen.getByRole('status')).toHaveTextContent('(5/73)')
  expect(screen.getByText(/Completed: Re-extracted and verified 53 of 73 references/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Re-extracting references…' })).toBeDisabled()
  expect(startReferenceReextraction).not.toHaveBeenCalled()
})

it('uses the latest persisted counters after a snapshot', async () => {
  getReferenceReextractions.mockResolvedValue({ data: { operations: [
    { operation_id: 'job', check_id: 25, reference_key: 'check:reextract-errors', status: 'running',
      progress: { sequence: 20, completed: 8, total: 10, message: 'Restored progress' } },
  ] } })
  useReferenceSearchStore.getState().register({ operation_id: 'job', check_id: 25, reference_key: 'check:reextract-errors',
    status: 'running', sequence: 10, completed: 2, progress: { sequence: 10, completed: 2, total: 10 } })
  render(<ReferenceReextractionButton checkId={25} references={references} />)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('(8/10)'))
})

it('restores a run that finished while the page was closed', async () => {
  getReferenceReextractions.mockResolvedValue({ data: { operations: [
    { operation_id: 'finished-job', check_id: 25, reference_key: 'check:reextract-errors', status: 'completed',
      progress: { sequence: 274, completed: 73, total: 73, updated: 53,
        message: 'Re-extracted and verified 53 of 73 references. 20 references need review.',
        failures: [{ index: 21, message: 'Source entry needs review.' }] } },
  ] } })
  render(<ReferenceReextractionButton checkId={25} references={references} />)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('53 of 73 references. 20 references need review.'))
  expect(screen.getByText('References needing review (1)')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  expect(startReferenceReextraction).not.toHaveBeenCalled()
})
