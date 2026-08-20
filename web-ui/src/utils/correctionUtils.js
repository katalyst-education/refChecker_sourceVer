import { exportReferenceAsStyle } from './formatters'
import { getEffectiveReferenceStatus } from './referenceStatus'

/** Categories used consistently by the Corrections list and its tab count. */
export function classifyCorrectionReference(ref, isCheckComplete = false) {
  const tags = new Set()
  const status = getEffectiveReferenceStatus(ref, isCheckComplete)
  if (status === 'error') tags.add('error')
  else if (status === 'warning') tags.add('warning')
  else if (status === 'suggestion') tags.add('suggestion')
  else if (status === 'unverified') tags.add('unverified')
  else if (status === 'hallucinated' || status === 'hallucination') tags.add('hallucination')
  if (ref.hallucination_assessment?.verdict?.toUpperCase?.() === 'LIKELY') {
    tags.add('hallucination')
  }
  return tags
}

/** Reference shell containing cited values only, with no correction overlays. */
export function citedReferenceShell(ref) {
  return {
    ...ref,
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
    const suggested = exportReferenceAsStyle(ref, style, index, options).trim()
    return cited !== suggested
  } catch {
    // A formatter failure must not silently hide a potentially editable row.
    return true
  }
}
