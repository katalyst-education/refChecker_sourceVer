import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SuggestAltPanel } from './ReferenceActionsBar'
import { getReferenceInvestigations, investigateReferenceSuggestion } from '../../utils/api'
import { useHistoryStore } from '../../stores/useHistoryStore'

vi.mock('../../utils/api', () => ({
  getReferenceInvestigations: vi.fn(() => Promise.resolve({ data: { investigations: [] } })),
  investigateReferenceSuggestion: vi.fn(),
  beginAuthenticatedSourceSession: vi.fn(),
  completeAuthenticatedSourceSession: vi.fn(),
  resolveDoi: vi.fn(),
}))

const suggestion = {
  check_id: 42, api_ref_id: 'uid:original', ref_id: '16',
  candidates: [
    { title: 'Strong candidate', authors: ['An Author'], year: 2007, source: 'llm', strong_fit: true, fit_reasons: ['Very close title', 'Same year'] },
    { title: 'Another candidate', authors: ['Another Author'], year: 2008, source: 'crossref' },
  ],
}

describe('Suggestion selection and investigation', () => {
  it('shows merged sources separately from citation fit and verification', () => {
    render(<SuggestAltPanel suggestFor={{ ...suggestion, candidates: [{
      ...suggestion.candidates[0], source: 'crossref', sources: ['llm', 'crossref'],
      discovery_status: 'database_candidate',
      links: [{ url: 'https://example.org/report', type: 'source' }, { url: 'https://doi.org/10.1000/report', type: 'doi' }],
    }] }} onClose={vi.fn()} />)
    expect(screen.getByText('llm')).toBeInTheDocument()
    expect(screen.getByText('crossref')).toBeInTheDocument()
    expect(screen.getByText(/Strong citation fit/)).toBeInTheDocument()
    expect(screen.getByText('Found in database search · verification pending')).toBeInTheDocument()
    expect(screen.getByText('https://example.org/report')).toBeInTheDocument()
    expect(screen.getByText('https://doi.org/10.1000/report')).toBeInTheDocument()
  })

  it('shows field differences against the retrieved source', async () => {
    investigateReferenceSuggestion.mockResolvedValue({ data: {
      reference: { status: 'verified' }, saved: false, save_reason: 'retrieved_metadata_differs',
      original_comparison: { confirmed: false, fields: [{ field: 'year', cited: 2007, actual: 2009, status: 'different' }] },
      retrieved_at: '2026-09-08T10:00:00Z',
    } })
    render(<SuggestAltPanel suggestFor={suggestion} onClose={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Investigate this suggestion' })[0])
    expect(await screen.findByRole('table')).toHaveTextContent('2007')
    expect(screen.getByRole('table')).toHaveTextContent('2009')
    expect(screen.getByRole('table')).toHaveTextContent('Different')
    expect(screen.getByText(/The retrieved source differs/)).toBeInTheDocument()
    expect(screen.getByText(/Evidence recorded:/)).toBeInTheDocument()
  })
  it('loads persisted investigation evidence when the panel reopens', async () => {
    getReferenceInvestigations.mockResolvedValueOnce({ data: { investigations: [{
      id: 'evidence-1',
      decision: 'recorded',
      created_at: '2026-10-12T10:00:00Z',
      evidence: {
        selected_suggestion: { title: 'Previously investigated candidate' },
        matched_database: 'CrossRef',
        comparison: { fields: [{ field: 'year', cited: 2007, actual: 2009, status: 'different' }] },
      },
    }] } })
    render(<SuggestAltPanel suggestFor={suggestion} onClose={vi.fn()} />)
    expect(await screen.findByText('Investigation history (1)')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Investigation history (1)'))
    expect(screen.getByText(/Candidate: Previously investigated candidate/)).toBeInTheDocument()
    expect(screen.getByText('Matched source: CrossRef')).toBeInTheDocument()
    expect(screen.getAllByText('Field comparison')).toHaveLength(1)
    expect(getReferenceInvestigations).toHaveBeenCalledWith(42, 'uid:original')
  })
  it('updates the original row when its confirmation was saved', async () => {
    useHistoryStore.setState({ selectedCheck: { id: 42, results: [{ ref_uid: 'original', title: 'Original', status: 'unverified' }] } })
    investigateReferenceSuggestion.mockResolvedValue({ data: {
      reference: { status: 'verified' },
      updated_reference: { ref_uid: 'original', title: 'Original', status: 'verified' },
      saved: true, cache_saved: true,
    } })
    render(<SuggestAltPanel suggestFor={{ ...suggestion, ref_id: 'uid:original' }} onClose={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Investigate this suggestion' })[0])
    expect(await screen.findByText(/Original reference verified and saved/)).toBeInTheDocument()
    expect(screen.getByText('Saved to the local reference database.')).toBeInTheDocument()
    expect(useHistoryStore.getState().selectedCheck.results[0].status).toBe('verified')
  })
  it('highlights a strong fit and investigates the candidate the user chooses', async () => {
    investigateReferenceSuggestion.mockResolvedValue({ data: {
      reference: { status: 'verified', matched_database: 'CrossRef', authoritative_urls: [{ type: 'doi', url: 'https://doi.org/10.1000/test' }] },
      sources: [{ database: 'crossref', label: 'CrossRef', status: 'matched' }], saved: false,
    } })
    render(<SuggestAltPanel suggestFor={suggestion} onClose={vi.fn()} />)
    expect(screen.getAllByText(/Strong citation fit/)).toHaveLength(1)
    expect(screen.getByText(/not independently verified/)).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: 'Investigate this suggestion' })
    fireEvent.click(buttons[1])
    expect(investigateReferenceSuggestion).toHaveBeenCalledWith(42, 'uid:original', suggestion.candidates[1])
    await waitFor(() => expect(screen.getByText(/Investigation result: verified/)).toBeInTheDocument())
    expect(screen.getByText(/Original reference unchanged/)).toBeInTheDocument()
    expect(screen.getByText('Matched source: CrossRef')).toBeInTheDocument()
    expect(screen.getByText('https://doi.org/10.1000/test')).toHaveAttribute('href', 'https://doi.org/10.1000/test')
  })

  it('shows failures and allows retry', async () => {
    investigateReferenceSuggestion.mockRejectedValue(new Error('Source unavailable'))
    render(<SuggestAltPanel suggestFor={suggestion} onClose={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Investigate this suggestion' })[0])
    expect(await screen.findByText('Source unavailable')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Investigate this suggestion' })[0]).toBeEnabled()
  })

  it('does not attach an old investigation to a newly opened suggestion list', async () => {
    let finish
    investigateReferenceSuggestion.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { rerender } = render(<SuggestAltPanel suggestFor={suggestion} onClose={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Investigate this suggestion' })[0])
    expect(screen.getByRole('button', { name: 'Investigating…' })).toBeDisabled()
    rerender(<SuggestAltPanel suggestFor={{ ...suggestion, ref_id: '17', api_ref_id: 'uid:other' }} onClose={vi.fn()} />)
    finish({ data: { reference: { status: 'verified' } } })
    await waitFor(() => expect(screen.queryByText(/Investigation result/)).not.toBeInTheDocument())
  })
})
