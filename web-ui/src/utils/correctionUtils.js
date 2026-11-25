import { exportReferenceAsStyle, hasAuthorListMembershipMismatch } from './formatters'
import { getEffectiveReferenceStatus } from './referenceStatus'

/** Categories used consistently by the Corrections list and its tab count. */
export function classifyCorrectionReference(ref, isCheckComplete = false) {
  const tags = new Set()
  const status = getEffectiveReferenceStatus(ref, isCheckComplete)
  if (status === 'error') tags.add('error')
  else if (status === 'warning') tags.add('warning')
  else if (status === 'suggestion') tags.add('suggestion')
  else if (status === 'unverified') tags.add('unverified')
  return tags
}

/** Reference shell containing cited values only, with no correction overlays. */
export function citedReferenceShell(ref) {
  const cited = ref.cited_metadata
  return {
    ...ref,
    ...(cited && {
      ...cited,
      authors: cited.authors ?? [],
      venue: cited.venue || cited.journal,
      cited_url: cited.cited_url || cited.url,
      doi: cited.doi,
      arxiv_id: cited.arxiv_id,
    }),
    errors: [],
    warnings: [],
    suggestions: [],
    authoritative_urls: [],
    corrected_reference: null,
  }
}

/** True only when the correction preview visibly changes the citation. */
export function hasActionableCorrection(ref, style, index = 0, options = null) {
  try {
    const cited = exportReferenceAsStyle(citedReferenceShell(ref), style, index, options).trim()
    // A catalogue link alone does not resolve a contributor-list discrepancy.
    const previewRef = hasAuthorListMembershipMismatch(ref) ? { ...ref, authoritative_urls: [] } : ref
    const suggested = exportReferenceAsStyle(previewRef, style, index, options).trim()
    return cited !== suggested
  } catch {
    // A formatter failure must not silently hide a potentially editable row.
    return true
  }
}
