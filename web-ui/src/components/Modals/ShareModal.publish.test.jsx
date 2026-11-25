import { act, render, cleanup, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The share dialog's report options (which sections to include, and whether to
// add suggested corrections) were only ever applied to the DOWNLOAD. Both
// publish paths — "Publish to web" and "Quick link" — called publishCheck with
// nothing but the adapter/token, so the server re-rendered the full default
// report. A user who unchecked a section and published a link still received
// the full default report. Nothing reported the discrepancy.

vi.mock('./ShareAnimationCanvas', () => ({
  default: () => <div data-testid="share-video" />,
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

const publishCheck = vi.fn(() => Promise.resolve({ data: { url: 'https://example.com/r' } }))
const exportCheckFile = vi.fn(() => Promise.resolve({ data: new Blob(['x']) }))
const exportBatchFile = vi.fn(() => Promise.resolve({ data: new Blob(['x']) }))
vi.mock('../../utils/api', () => ({
  exportCheckFile: (...a) => exportCheckFile(...a),
  exportBatchFile: (...a) => exportBatchFile(...a),
  publishCheck: (...a) => publishCheck(...a),
}))

const checkState = { references: [], stats: {} }
vi.mock('../../stores/useCheckStore', () => {
  const useCheckStore = (selector) => (selector ? selector(checkState) : checkState)
  useCheckStore.getState = () => checkState
  return { useCheckStore }
})

let historyState = { selectedCheck: null }
vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = (selector) => (selector ? selector(historyState) : historyState)
  useHistoryStore.getState = () => historyState
  return { useHistoryStore }
})

let styleState = { format: 'ieee' }
vi.mock('../../stores/useStyleStore', () => {
  const useStyleStore = (selector) => (selector ? selector(styleState) : styleState)
  useStyleStore.getState = () => styleState
  return { useStyleStore }
})

import ShareModal from './ShareModal'

const references = [
  { status: 'verified', errors: [], warnings: [] },
  { status: 'error', errors: [{ error_type: 'author', message: 'author mismatch' }], warnings: [] },
]

beforeEach(() => {
  historyState = {
    selectedCheck: {
      id: 42,
      status: 'completed',
      results: references,
    },
  }
  styleState = { format: 'ieee' }
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

const open = () => render(<ShareModal checkId={42} title="Parity Paper" onClose={() => {}} />)

const uncheck = (label) => {
  const box = ['Verified', 'Warning', 'Error', 'Unverified'].includes(label)
    ? screen.getByRole('checkbox', { name: label, exact: true })
    : screen.getByLabelText(label, { exact: false })
  fireEvent.click(box)
}

describe('publish paths carry the dialog’s report options', () => {
  it.each(['Full reference list', 'Include suggested corrections', 'Error'])('clears an existing link after changing %s', async (label) => {
    open()
    fireEvent.click(screen.getByText('Quick link'))
    await screen.findByDisplayValue('https://example.com/r')
    uncheck(label)
    expect(screen.queryByDisplayValue('https://example.com/r')).toBeNull()
  })

  it('discards a link generated for an earlier status selection', async () => {
    let finish
    publishCheck.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    open()
    fireEvent.click(screen.getByText('Quick link'))
    uncheck('Error')
    await act(async () => { finish({ data: { url: 'https://example.com/earlier' } }) })
    expect(screen.queryByDisplayValue('https://example.com/earlier')).toBeNull()
    expect(screen.getByText('Quick link')).toBeEnabled()
  })

  it('exports a user list on its own through downloads and quick links', async () => {
    historyState.selectedCheck.reference_lists = [
      { id: 'custom-id', name: 'Follow up with author' },
      { id: 'further_checks', name: 'Further Checks' },
    ]
    open()
    for (const label of ['Verified', 'Warning', 'Error', 'Unverified', 'Further Checks']) uncheck(label)
    fireEvent.click(screen.getByText('Quick link'))
    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    expect(publishCheck.mock.calls[0][1]).toMatchObject({ statuses: [], review_lists: ['custom-id'] })
    await waitFor(() => expect(screen.getByRole('button', { name: /^Download/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /^Download/ }))
    expect(exportCheckFile.mock.calls[0][1]).toMatchObject({ statuses: [], review_lists: ['custom-id'] })
  })

  it('combines a status category and user lists when publishing to web', async () => {
    historyState.selectedCheck.reference_lists = [{ id: 'custom-id', name: 'Ask author' }]
    open()
    for (const label of ['Verified', 'Warning', 'Unverified']) uncheck(label)
    fireEvent.click(screen.getByText('Publish to web'))
    fireEvent.change(screen.getByPlaceholderText(/GitHub token/i), { target: { value: 'tok' } })
    fireEvent.click(screen.getByText('Publish & get link'))
    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    expect(publishCheck.mock.calls[0][1]).toMatchObject({ statuses: ['error'], review_lists: ['custom-id'] })
  })

  it('shows user lists from every paper in a batch', () => {
    historyState.selectedBatch = { batch_id: 'batch-1', checks: [
      { reference_lists: [{ id: 'further_checks', name: 'Further Checks' }] },
      { reference_lists: [{ id: 'custom-id', name: 'Ask author' }, { id: 'further_checks', name: 'Further Checks' }] },
    ] }
    render(<ShareModal batchId="batch-1" title="Batch" onClose={() => {}} />)
    for (const label of ['Verified', 'Warning', 'Error', 'Unverified', 'Further Checks']) uncheck(label)
    fireEvent.click(screen.getByRole('button', { name: /^Download/ }))
    expect(exportBatchFile.mock.calls[0][1]).toMatchObject({ statuses: [], review_lists: ['custom-id'] })
    uncheck('Ask author')
    expect(screen.getByRole('status')).toHaveTextContent('Select at least one result type or user list')
  })

  it('sends the same status combination to downloads and quick links', async () => {
    open()
    uncheck('Verified')
    uncheck('Unverified')
    fireEvent.click(screen.getByText('Quick link'))
    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    expect(publishCheck.mock.calls[0][1].statuses).toEqual(['warning', 'error'])
    await waitFor(() => expect(screen.getByRole('button', { name: /^Download/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /^Download/ }))
    expect(exportCheckFile.mock.calls[0][1].statuses).toEqual(['warning', 'error'])
  })

  it('applies status choices to batch downloads', () => {
    render(<ShareModal batchId="batch-1" title="Batch" onClose={() => {}} />)
    uncheck('Verified')
    uncheck('Warning')
    uncheck('Unverified')
    fireEvent.click(screen.getByRole('button', { name: /^Download/ }))
    expect(exportBatchFile).toHaveBeenCalledWith('batch-1', expect.objectContaining({ statuses: ['error'] }))
  })

  it('requires at least one selected status for every sharing action', () => {
    open()
    for (const label of ['Verified', 'Warning', 'Error', 'Unverified']) uncheck(label)
    expect(screen.getByRole('button', { name: /^Download/ })).toBeDisabled()
    expect(screen.getByText('Quick link')).toBeDisabled()
    fireEvent.click(screen.getByText('Publish to web'))
    fireEvent.change(screen.getByPlaceholderText(/GitHub token/i), { target: { value: 'tok' } })
    expect(screen.getByText('Publish & get link')).toBeDisabled()
  })

  it('quick link sends the selected sections', async () => {
    open()
    uncheck('Issues to address')
    fireEvent.click(screen.getByText('Quick link'))

    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const [, opts] = publishCheck.mock.calls[0]
    expect(opts.adapter).toBe('quick_link')
    expect(opts.include).toBeTruthy()
    expect(opts.include.split(',')).not.toContain('issues')
    expect(opts.include.split(',')).toContain('references')
  })

  it('publish to web sends the selected sections and the corrections flag', async () => {
    open()
    uncheck('Full reference list')
    uncheck('Include suggested corrections')
    fireEvent.click(screen.getByText('Publish to web'))
    fireEvent.change(screen.getByPlaceholderText(/GitHub token/i), { target: { value: 'tok' } })
    fireEvent.click(screen.getByText('Publish & get link'))

    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const [, opts] = publishCheck.mock.calls[0]
    expect(opts.adapter).toBe('github_gist')
    expect(opts.corrections).toBe(true)
    expect(opts.include.split(',')).not.toContain('references')
  })

  it('publishes the same canonical summary the download uses', async () => {
    open()
    fireEvent.click(screen.getByText('Quick link'))
    await waitFor(() => expect(publishCheck).toHaveBeenCalled())
    const publishSummary = publishCheck.mock.calls[0][1].summary

    fireEvent.click(screen.getByRole('button', { name: /^Download/ }))
    await waitFor(() => expect(exportCheckFile).toHaveBeenCalled())
    const downloadSummary = exportCheckFile.mock.calls[0][1].summary

    // Same numbers in the published link as in the downloaded file — otherwise
    // a shared report disagrees with the badge the user is looking at.
    expect(publishSummary).toEqual(downloadSummary)
    expect(publishSummary).toBeTruthy()
  })
})
