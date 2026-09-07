import { describe, expect, it } from 'vitest'
import {
  applyStatusFilter,
  buildReferenceSummary,
  computeReferenceStats,
  getEffectiveReferenceStatus,
  isWebsiteVerifiedReference,
} from './referenceStatus'

describe('referenceStatus', () => {
  it('uses error, warning, suggestion, and verification precedence', () => {
    expect(getEffectiveReferenceStatus({ status: 'verified', errors: [{ error_type: 'title' }], warnings: [] }, true)).toBe('error')
    expect(getEffectiveReferenceStatus({ status: 'verified', errors: [], warnings: [{}] }, true)).toBe('warning')
    expect(getEffectiveReferenceStatus({ status: 'verified', errors: [], warnings: [], suggestions: [{}] }, true)).toBe('suggestion')
    expect(getEffectiveReferenceStatus({ status: 'unverified', errors: [], warnings: [] }, true)).toBe('unverified')
  })

  it('recognizes a website-grounded verified reference', () => {
    const reference = {
      status: 'verified',
      matched_database: 'website',
      authoritative_urls: [{ type: 'verified_url', url: 'https://example.org/source' }],
    }
    expect(isWebsiteVerifiedReference(reference)).toBe(true)
    expect(getEffectiveReferenceStatus(reference, true)).toBe('website_verified')
  })

  it('derives display buckets and inclusive issue totals', () => {
    const references = [
      { status: 'verified', errors: [], warnings: [], suggestions: [] },
      { status: 'error', errors: [{ error_type: 'title' }, { error_type: 'unverified' }], warnings: [{}], suggestions: [] },
      { status: 'warning', errors: [], warnings: [{}], suggestions: [] },
      { status: 'unverified', errors: [{ error_type: 'unverified' }], warnings: [], suggestions: [] },
    ]
    expect(computeReferenceStats(references, true)).toMatchObject({
      totalProcessed: 4,
      verified: 1,
      withErrors: 1,
      withWarnings: 1,
      withUnverified: 2,
      errorsCount: 1,
      warningsCount: 2,
    })
  })

  it('builds a bounded summary and falls back to stored counts without rows', () => {
    const summary = buildReferenceSummary({
      stats: {
        total_refs: 4,
        processed_refs: 5,
        verified_count: 1,
        refs_with_errors: 1,
        refs_with_warnings_only: 1,
        unverified_count: 1,
      },
      references: [],
      isComplete: true,
    })
    expect(summary.totalRefs).toBe(5)
    expect(summary.processedRefs).toBe(5)
    expect(summary.progressPercent).toBe(100)
    expect(summary.references).toEqual({ verified: 1, errors: 1, warnings: 1, suggestions: 0, unverified: 1 })
  })

  it('filters errors and abstentions explicitly', () => {
    const references = [
      { index: 1, status: 'verified', errors: [], warnings: [] },
      { index: 2, status: 'error', errors: [{ error_type: 'title' }], warnings: [] },
      { index: 3, status: 'unverified', errors: [{ error_type: 'unverified' }], warnings: [] },
    ]
    expect(applyStatusFilter(references, ['error'], true).map(ref => ref.index)).toEqual([2])
    expect(applyStatusFilter(references, ['unverified'], true).map(ref => ref.index)).toEqual([3])
  })
})
