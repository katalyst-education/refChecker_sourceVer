const HTTP_URL = /^https?:\/\//i

const addLink = (links, seen, type, value) => {
  if (typeof value !== 'string') return
  const url = value.trim()
  if (!HTTP_URL.test(url) || seen.has(url)) return
  seen.add(url)
  links.push({ type: type || 'other', url })
}

const addLinkValue = (links, seen, type, value) => {
  if (Array.isArray(value)) {
    value.forEach(item => addLinkValue(links, seen, type, item))
  } else if (value && typeof value === 'object') {
    addLink(links, seen, value.type || type, value.url || value.URL || value.href)
  } else {
    addLink(links, seen, type, value)
  }
}

export const formatReferenceLinkType = (type) => ({
  cited: 'Cited URL',
  llm_verified: 'LLM verified URL',
  verified_url: 'Verified URL',
  semantic_scholar: 'Semantic Scholar',
  arxiv: 'ArXiv',
  doi: 'DOI',
  openalex: 'OpenAlex',
  openreview: 'OpenReview',
  oa_pdf: 'Open-access PDF',
  pdf: 'PDF',
  source: 'Source',
}[type] || 'URL')

export function collectReferenceLinks(reference = {}, assessment = {}) {
  const links = []
  const seen = new Set()

  ;(reference.authoritative_urls || []).forEach(item => {
    addLinkValue(links, seen, item?.type || 'other', item)
  })
  addLink(links, seen, 'cited', reference.cited_url)
  addLink(links, seen, 'cited', reference.url)
  addLink(links, seen, 'verified_url', reference.verified_url)
  addLink(links, seen, 'verified_url', reference.ref_verified_url)
  addLink(links, seen, 'llm_verified', assessment.website_verified_url)
  addLink(links, seen, 'llm_verified', assessment.link)
  addLink(links, seen, 'oa_pdf', reference.oa_pdf_url)

  const enrichmentLinks = reference.enrichment?.links
  if (enrichmentLinks && typeof enrichmentLinks === 'object') {
    Object.entries(enrichmentLinks).forEach(([type, value]) => {
      addLinkValue(links, seen, type, value)
    })
  }
  return links
}

export function collectCandidateLinks(candidate = {}) {
  const links = []
  const seen = new Set()
  addLinkValue(links, seen, 'other', candidate.links)
  addLinkValue(links, seen, 'other', candidate.urls)
  addLink(links, seen, 'other', candidate.url)
  addLink(links, seen, 'other', candidate.link)
  return links
}
