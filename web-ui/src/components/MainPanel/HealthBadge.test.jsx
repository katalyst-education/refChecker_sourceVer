import { describe, expect, it } from 'vitest'
import { computeScore } from './HealthBadge'

describe('HealthBadge citation-health score', () => {
  it('counts an authoritative web-URL verification as verified', () => {
    const stats = computeScore([{
      status: 'verified',
      verified_via_website: true,
      matched_database: 'Web page',
      authoritative_urls: [{ type: 'verified_url', url: 'https://example.org/paper' }],
      errors: [],
      warnings: [],
      suggestions: [],
    }], 'apa')

    expect(stats.verified).toBe(1)
    expect(stats.score).toBe(100)
  })

  it('recognizes the stored web-verification metadata fallback', () => {
    const stats = computeScore([{
      status: 'verified',
      matched_database: 'Website',
      authoritative_urls: [{ type: 'verified_url', url: 'https://example.org/reference' }],
      errors: [],
      warnings: [],
      suggestions: [],
    }], 'apa')

    expect(stats.verified).toBe(1)
    expect(stats.score).toBe(100)
  })

  it('preserves error precedence for a web-verified reference with an error', () => {
    const stats = computeScore([{
      status: 'verified',
      verified_via_website: true,
      errors: [{ error_type: 'title', cited: 'Wrong title', actual_value: 'Correct title' }],
      warnings: [],
      suggestions: [],
    }], 'apa')

    expect(stats.verified).toBe(0)
    expect(stats.errors).toBe(1)
    expect(stats.score).toBe(0)
  })

  it('counts a suggestion-only reference as verified', () => {
    const stats = computeScore([{
      status: 'suggestion',
      errors: [],
      warnings: [],
      suggestions: [{ suggestion_type: 'doi', suggestion_details: 'Add the DOI' }],
    }], 'apa')

    expect(stats.verified).toBe(1)
    expect(stats.score).toBe(100)
  })
})
