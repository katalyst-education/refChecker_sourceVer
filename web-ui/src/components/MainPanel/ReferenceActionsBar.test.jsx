import { render, screen } from '@testing-library/react'
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
