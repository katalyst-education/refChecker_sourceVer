import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const authApi = vi.hoisted(() => ({
  begin: vi.fn(),
  complete: vi.fn(),
}))

vi.mock('../../utils/api', async (importOriginal) => ({
  ...(await importOriginal()),
  beginAuthenticatedSourceSession: authApi.begin,
  completeAuthenticatedSourceSession: authApi.complete,
}))

import { ReferenceRowActions } from './ReferenceActionsBar'

const baseProps = {
  reference: { id: 'ref-1', title: 'A reference' },
  displayIndex: 0,
  selectedCheckId: 17,
  onSuggest: vi.fn(),
  onRemove: vi.fn(),
  onReverify: vi.fn(),
  onReverifyAllDatabases: vi.fn(),
  onEditMetadata: vi.fn(),
  onRestoreExtractedMetadata: vi.fn(),
}

describe('ReferenceRowActions progress feedback', () => {
  it('opens an authenticated browser and retries with the shared verifier', async () => {
    authApi.begin.mockResolvedValue({ data: { active: true } })
    authApi.complete.mockResolvedValue({ data: { authenticated: true } })
    const onReverify = vi.fn().mockResolvedValue({ status: 'verified' })
    const url = 'https://search.ebscohost.com/login.aspx?direct=true&AN=979090'
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={{
          id: 'ref-1',
          title: 'Protected reference',
          cited_url: url,
          warnings: [{
            warning_type: 'authentication',
            warning_details: 'Authentication required',
            requires_authentication: true,
            authentication_url: url,
          }],
        }}
        onReverify={onReverify}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Sign in and retry' }))
    await waitFor(() => expect(authApi.begin).toHaveBeenCalledWith(url))
    fireEvent.click(await screen.findByRole('button', { name: "I've signed in - retry" }))

    await waitFor(() => expect(authApi.complete).toHaveBeenCalledWith(url))
    expect(onReverify).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'ref-1' }),
      0,
      { use_authenticated_browser: true },
    )
  })

  it('offers authenticated retry for a legacy sign-in title mismatch on any domain', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={{
          id: 'ref-1',
          title: 'Protected reference',
          cited_url: 'https://catalogue.example.org/record/123',
          warnings: [{
            error_type: 'title',
            error_details: 'Title mismatch:\n       cited: Protected reference\n       actual: Provider Sign In',
          }],
        }}
      />,
    )

    expect(screen.getByRole('button', { name: 'Sign in and retry' })).toBeInTheDocument()
  })

  it('offers browser retry when an older result captured a loading title', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={{
          id: 'ref-1',
          title: 'Protected reference',
          cited_url: 'https://catalogue.example.org/record/123',
          warnings: [{
            error_type: 'title',
            error_details: 'Title mismatch:\n       cited: Protected reference\n       actual: Wird geladen ... - Research Databases',
          }],
        }}
      />,
    )

    expect(screen.getByRole('button', { name: 'Sign in and retry' })).toBeInTheDocument()
  })

  it('offers browser retry for a legacy Shibboleth authentication request', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={{
          id: 'ref-1',
          title: 'Protected reference',
          cited_url: 'https://proxy.example.org/record/123',
          warnings: [{
            error_type: 'title',
            error_details: 'Title mismatch:\n       cited: Protected reference\n       actual: Shibboleth Authentication Request',
          }],
        }}
      />,
    )

    expect(screen.getByRole('button', { name: 'Sign in and retry' })).toBeInTheDocument()
  })

  it('shows document re-extraction progress inside the card', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        reverifyBusy
        reverifyAction="reextract"
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      'Re-extracting this reference from the document, then verifying it…',
    )
    expect(screen.getByRole('button', { name: 'Re-extracting…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Search all DBs' })).toBeDisabled()
  })

  it('shows all-database search progress inside the card', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        reverifyBusy
        reverifyAction="all-databases"
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent(
      'Searching every configured database for this reference…',
    )
    expect(screen.getByRole('button', { name: 'Searching all DBs…' })).toBeDisabled()
  })

  it('animates while database sources are still pending', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        searchOperation={{
          status: 'running',
          configured_sources: [
            { database: 'crossref', label: 'CrossRef' },
            { database: 'openalex', label: 'OpenAlex' },
          ],
          sources: {
            crossref: { database: 'crossref', label: 'CrossRef', status: 'searching' },
          },
        }}
      />,
    )

    const progress = screen.getByRole('status', { name: 'Database search in progress' })
    expect(progress).toHaveTextContent('Searching databases')
    expect(progress.querySelector('svg')).toHaveClass('motion-safe:animate-spin')

    fireEvent.click(screen.getByText('Database results (2)'))
    expect(screen.getByText('Searching').closest('span').querySelector('svg'))
      .toHaveClass('motion-safe:animate-spin')
    expect(screen.getByText('Waiting').closest('span')).toHaveClass('motion-safe:animate-pulse')
  })

  it('shows a collapsible result row for every configured database', () => {
    render(
      <ReferenceRowActions
        {...baseProps}
        searchOperation={{
          status: 'completed',
          duration_ms: 1250,
          configured_sources: [
            { database: 'crossref', label: 'CrossRef' },
            { database: 'openalex', label: 'OpenAlex' },
            { database: 'semantic_scholar', label: 'Semantic Scholar' },
          ],
          sources: {
            crossref: {
              database: 'crossref', label: 'CrossRef', status: 'confirmed_same_work',
              candidate: {
                title: 'A database title', authors: ['Ada Lovelace', 'Grace Hopper'],
                corporate_contributors: ['Example Research Institute'],
                year: 2024, url: 'https://doi.org/10.1000/example',
                links: [
                  { type: 'doi', url: 'https://doi.org/10.1000/example' },
                  { type: 'pdf', url: 'https://example.org/paper.pdf' },
                ],
              },
            },
            openalex: {
              database: 'openalex', label: 'OpenAlex', status: 'excluded_wrong_match',
              reason: 'title similarity is only 0.31',
            },
            dnb: {
              database: 'dnb', label: 'DNB Catalogue', status: 'metadata_conflict',
              reason: 'The database author list does not contain every cited personal author.',
            },
          },
        }}
      />,
    )

    expect(screen.getByText('Database results (4)')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Database results (4)'))
    expect(screen.getByText('CrossRef')).toBeInTheDocument()
    expect(screen.getByText('OpenAlex')).toBeInTheDocument()
    expect(screen.getByText('Semantic Scholar')).toBeInTheDocument()
    expect(screen.getByText('DNB Catalogue')).toBeInTheDocument()
    expect(screen.getByText('A database title')).toBeInTheDocument()
    expect(screen.getByText('Ada Lovelace, Grace Hopper · 2024')).toBeInTheDocument()
    expect(screen.getByText('Corporate contributor: Example Research Institute')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Links (2)'))
    expect(screen.getByRole('link', { name: 'https://doi.org/10.1000/example' }))
      .toHaveAttribute('href', 'https://doi.org/10.1000/example')
    expect(screen.getByRole('link', { name: 'https://example.org/paper.pdf' }))
      .toHaveAttribute('href', 'https://example.org/paper.pdf')
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.getByText('Excluded: likely wrong match')).toBeInTheDocument()
    expect(screen.getByText('Metadata conflict')).toBeInTheDocument()
    expect(screen.getByText('title similarity is only 0.31')).toBeInTheDocument()
    expect(screen.getByText('Not searched')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})

describe('ReferenceRowActions metadata editor', () => {
  it('edits title, authors, year, and identifiers before verification', async () => {
    const onEditMetadata = vi.fn().mockResolvedValue({ status: 'verified' })
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={{
          id: 'ref-1',
          title: 'Technologieund Innovationsmanagement',
          authors: ['Alexander Gerybadze'],
          year: 2004,
          venue: 'Vahlen',
        }}
        onEditMetadata={onEditMetadata}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Edit metadata' }))
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Technologie- und Innovationsmanagement' },
    })
    fireEvent.change(screen.getByLabelText('Author 1'), {
      target: { value: 'Alexander A. Gerybadze' },
    })
    fireEvent.click(screen.getByRole('button', { name: '+ Add author' }))
    fireEvent.change(screen.getByLabelText('Author 2'), {
      target: { value: 'Second Author' },
    })
    fireEvent.change(screen.getByLabelText('Year'), { target: { value: '2005' } })
    fireEvent.change(screen.getByLabelText('URL'), { target: { value: 'https://example.org/book' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save and verify' }))

    await waitFor(() => expect(onEditMetadata).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'ref-1' }),
      0,
      expect.objectContaining({
        title: 'Technologie- und Innovationsmanagement',
        authors: ['Alexander A. Gerybadze', 'Second Author'],
        year: '2005',
        cited_url: 'https://example.org/book',
      }),
    ))
    expect(screen.queryByText('Edit extracted metadata')).not.toBeInTheDocument()
  })

  it('offers a persistent undo action for user-edited metadata', () => {
    const onRestoreExtractedMetadata = vi.fn()
    const reference = {
      id: 'ref-1',
      title: 'Edited title',
      manual_edit: {
        original: { title: 'Extracted title' },
        edited_fields: ['title', 'year'],
      },
    }
    render(
      <ReferenceRowActions
        {...baseProps}
        reference={reference}
        onRestoreExtractedMetadata={onRestoreExtractedMetadata}
      />,
    )

    expect(screen.getByText(/Edited by user/)).toHaveTextContent('title, year')
    fireEvent.click(screen.getByRole('button', { name: 'Undo metadata edit' }))
    expect(onRestoreExtractedMetadata).toHaveBeenCalledWith(reference, 0)
  })
})
