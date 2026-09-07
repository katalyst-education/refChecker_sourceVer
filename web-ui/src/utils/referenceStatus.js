const FINAL_STATUSES = ['error', 'warning', 'suggestion', 'unverified', 'verified', 'website_verified']

export const isWebsiteVerifiedReference = (reference = {}) => {
  if (reference?.verified_via_website) return true

  const baseStatus = String(reference?.status || '').trim().toLowerCase()
  const matchedDatabase = String(reference?.matched_database || '').trim().toLowerCase()
  const hasVerifiedUrl = Array.isArray(reference?.authoritative_urls)
    && reference.authoritative_urls.some(urlObj => urlObj?.type === 'verified_url' && urlObj?.url)

  return baseStatus === 'verified'
    && hasVerifiedUrl
    && (matchedDatabase === 'web page' || matchedDatabase === 'website')
}

export const getEffectiveReferenceStatus = (reference = {}, isCheckComplete = false) => {
  const baseStatus = String(reference.status || '').trim().toLowerCase()
  const hasErrors = Array.isArray(reference.errors) && reference.errors.some(
    issue => String(issue?.error_type || '').toLowerCase() !== 'unverified'
  )
  const hasWarnings = Array.isArray(reference.warnings) && reference.warnings.length > 0
  const hasSuggestions = Array.isArray(reference.suggestions) && reference.suggestions.length > 0

  if (hasErrors) return 'error'
  if (hasWarnings) return 'warning'
  if (hasSuggestions) return 'suggestion'
  if (isWebsiteVerifiedReference(reference)) return 'website_verified'

  if (baseStatus === 'error' || baseStatus === 'warning' || baseStatus === 'suggestion') {
    return 'verified'
  }
  if (FINAL_STATUSES.includes(baseStatus)) return baseStatus

  if (baseStatus === 'pending' || baseStatus === 'checking'
      || ['in_progress', 'queued', 'processing', 'started'].includes(baseStatus)) {
    if (isCheckComplete) return 'unchecked'
    return baseStatus === 'pending' ? 'pending' : 'checking'
  }

  return 'verified'
}

export const computeReferenceStats = (references = [], isCheckComplete = false) => {
  if (!Array.isArray(references) || references.length === 0) return null

  const processed = references.filter(reference => {
    const status = String(reference?.status || '').toLowerCase()
    return status && !['pending', 'checking', 'in_progress', 'queued', 'processing', 'started'].includes(status)
  })

  let errorsCount = 0
  let warningsCount = 0
  let suggestionsCount = 0
  let withErrors = 0
  let withWarnings = 0
  let withSuggestions = 0
  let withUnverified = 0
  let verified = 0

  for (const reference of processed) {
    const status = getEffectiveReferenceStatus(reference, isCheckComplete)
    errorsCount += (reference?.errors || []).filter(issue => issue?.error_type !== 'unverified').length
    warningsCount += (reference?.warnings || []).length
    suggestionsCount += (reference?.suggestions || []).length

    if (status === 'error') withErrors += 1
    else if (status === 'warning') withWarnings += 1
    else if (status === 'suggestion') withSuggestions += 1

    if (
      status === 'unverified'
      || (status !== 'checking' && reference?.errors?.some(issue => issue?.error_type === 'unverified'))
    ) {
      withUnverified += 1
    }
    if (status === 'verified' || status === 'website_verified' || status === 'suggestion') {
      verified += 1
    }
  }

  return {
    count: processed.length,
    totalProcessed: processed.length,
    errorsCount,
    warningsCount,
    suggestionsCount,
    withErrors,
    withWarnings,
    withSuggestions,
    withUnverified,
    verified,
  }
}

const numberOr = (value, fallback = 0) => (
  typeof value === 'number' && Number.isFinite(value) ? value : fallback
)

export const buildReferenceSummary = ({ stats = {}, references = [], isComplete = false } = {}) => {
  const refs = Array.isArray(references) ? references : []
  const derived = refs.length > 0 ? computeReferenceStats(refs, isComplete) : null
  const rawTotalRefs = numberOr(stats.total_refs, refs.length)
  const rawProcessedRefs = stats.processed_refs !== undefined
    ? numberOr(stats.processed_refs)
    : (isComplete && rawTotalRefs > 0 ? rawTotalRefs : numberOr(derived?.totalProcessed))
  const totalRefs = Math.max(rawTotalRefs, rawProcessedRefs)
  const processedRefs = Math.min(rawProcessedRefs, totalRefs)

  return {
    totalRefs,
    processedRefs,
    progressPercent: totalRefs > 0 ? Math.min((processedRefs / totalRefs) * 100, 100) : 0,
    references: {
      verified: derived?.verified ?? numberOr(stats.refs_verified, numberOr(stats.verified_count)),
      errors: derived?.withErrors ?? numberOr(stats.refs_with_errors),
      warnings: derived?.withWarnings ?? numberOr(stats.refs_with_warnings_only),
      suggestions: derived?.withSuggestions ?? numberOr(stats.refs_with_suggestions_only),
      unverified: derived?.withUnverified ?? numberOr(stats.unverified_count),
    },
    issues: {
      errors: derived?.errorsCount ?? numberOr(stats.errors_count),
      warnings: derived?.warningsCount ?? numberOr(stats.warnings_count),
      suggestions: derived?.suggestionsCount ?? numberOr(stats.suggestions_count),
      unverified: derived?.withUnverified ?? numberOr(stats.unverified_count),
    },
  }
}

export function applyStatusFilter(references, statusFilter, isCheckComplete = false) {
  const filters = (statusFilter || []).map(filter => String(filter).toLowerCase())
  if (filters.length === 0) return references || []

  return (references || []).filter(reference => {
    const status = String(getEffectiveReferenceStatus(reference, isCheckComplete) || '').toLowerCase()
    return filters.some(filter => {
      switch (filter) {
        case 'verified':
          return status === 'verified' || status === 'website_verified' || status === 'suggestion'
        case 'error':
          return (reference.errors || []).some(issue => issue.error_type !== 'unverified')
        case 'warning':
          return (reference.warnings || []).length > 0
        case 'suggestion':
          return (reference.suggestions || []).length > 0
        case 'unverified':
          if (status === 'checking') return false
          return status === 'unverified'
            || (reference.errors || []).some(issue => issue.error_type === 'unverified')
        default:
          return status === filter
      }
    })
  })
}

