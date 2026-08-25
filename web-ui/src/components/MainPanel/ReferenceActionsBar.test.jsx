import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
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
