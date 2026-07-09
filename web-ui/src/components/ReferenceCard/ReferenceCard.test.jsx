import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ReferenceCard from './ReferenceCard'

vi.mock('../../utils/formatters', async () => {
  const actual = await vi.importActual('../../utils/formatters')
  return {
    ...actual,
    copyToClipboard: vi.fn(),
  }
})

describe('ReferenceCard', () => {
  it('does not show a spinner for final unverified refs after completion', () => {
    const reference = {
      status: 'unverified',
      title: 'Unknown Paper',
      authors: ['A. Author'],
      errors: [{ error_type: 'unverified', error_details: 'Paper not found by any checker' }],
      warnings: [],
      suggestions: [],
    }

    const { container } = render(<ReferenceCard reference={reference} index={0} isCheckComplete />)

    expect(container.querySelector('svg.animate-spin')).toBeNull()
    expect(screen.getByText(/Could not verify: Unknown Paper/)).toBeTruthy()
  })

  it('renders LLM-found matching metadata without crashing', () => {
    const reference = {
      status: 'hallucination',
      title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
      authors: ['Martin Balla', 'M. Long', 'George E. James Goodman'],
      venue: 'IEEE Conference on Games',
      year: 2024,
      hallucination_assessment: {
        verdict: 'LIKELY',
        explanation: 'The paper exists with the cited metadata.',
        link: 'https://arxiv.org/abs/2405.18123',
        found_title: 'Pytag: Tabletop games for multi-agent reinforcement learning',
        found_authors: 'Martin Balla, G. E. Long, George E. James Goodman',
        found_year: '2024',
      },
      authoritative_urls: [],
      errors: [{ error_type: 'author', error_details: 'Author mismatch' }],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={3} />)

    expect(screen.getByText('Pytag: Tabletop games for multi-agent reinforcement learning')).toBeTruthy()
    expect(screen.getByText('Matched DB:')).toBeTruthy()
    expect(screen.getByText('LLM search')).toBeTruthy()
    expect(screen.queryByText(/Likely hallucinated/i)).toBeNull()
  })

  it('renders the website-verified icon and website source label', () => {
    const reference = {
      status: 'verified',
      title: 'Künstliche Intelligenz in Studium und Lehre. Empfehlungen zum Umgang an der UDE',
      authors: ['D. Gür-Seker', 'P. Hinze'],
      venue: 'University of Duisburg-Essen',
      year: 2023,
      matched_database: 'Web page',
      verified_via_website: true,
      authoritative_urls: [{ type: 'verified_url', url: 'https://www.uni-due.de/example.pdf' }],
      errors: [],
      warnings: [],
      suggestions: [],
    }

    render(<ReferenceCard reference={reference} index={4} isCheckComplete />)

    expect(screen.getByTitle('Verified from website')).toBeTruthy()
    expect(screen.getByText('Web page')).toBeTruthy()
  })
})
