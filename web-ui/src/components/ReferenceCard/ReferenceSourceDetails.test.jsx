import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import ReferenceSourceDetails from './ReferenceSourceDetails'

it('shows ambiguous author evidence alongside the original text and PDF page', () => {
  const reference = {
    extraction_provenance: {
      entry_number: 49,
      pdf_page: 177,
      source_text: '[49] R.A.MarquesLameirinhas, “Photovoltaic review,” 2022.',
      layout_text: '[49] R. A. Marques Lameirinhas, “Photovoltaic review,” 2022.',
      review: {
        authors: { source: 'R. A. Marques Lameirinhas', parsed: ['T. A. Marques Lameirinhas'] },
      },
    },
  }

  render(<ReferenceSourceDetails reference={reference} checkId={7} />)
  screen.getByText(/Review authors/).closest('details').open = true

  expect(screen.getByText(reference.extraction_provenance.source_text)).toBeVisible()
  expect(screen.getByText(reference.extraction_provenance.layout_text)).toBeVisible()
  expect(screen.getByText('Source authors')).toBeVisible()
  expect(screen.getByText('Parsed authors')).toBeVisible()
  expect(screen.getByRole('link', { name: 'Open PDF page 177' }))
    .toHaveAttribute('href', '/api/paper-pdf/7#page=177')
})
