import { normalizeAuthors } from '../../utils/formatters'

function fieldValue(field, value) {
  if (field === 'authors' && Array.isArray(value)) {
    return normalizeAuthors(value).join(', ') || 'Missing'
  }
  if (Array.isArray(value)) return value.join(' / ') || 'Missing'
  return value ? String(value) : 'Missing'
}

const repairReasons = {
  bibliography_authors: 'Bibliography author list',
  bibliography_title: 'Bibliography title',
  bibliography_venue: 'Bibliography venue',
  bibliography_url: 'Bibliography URL',
  bibliography_publication: 'Bibliography publication details',
  bibliography_parser: 'Bibliography text parser',
  pdf_layout: 'PDF page layout',
  field_cleanup: 'Parser field cleanup',
  targeted_llm_reparse: 'Reparsed this entry',
}

const publicationLabels = {
  edition: 'Edition',
  isbn: 'ISBN',
  volume: 'Volume',
  issue: 'Issue',
  pages: 'Pages',
  article_number: 'Article number',
  publisher: 'Publisher',
  series: 'Series',
}

export default function ReferenceSourceDetails({ reference, checkId }) {
  const evidence = reference.extraction_provenance
  const repairs = evidence?.repairs ?? []
  const review = Object.entries(evidence?.review ?? {})
  const publication = Object.entries(publicationLabels).filter(([field]) => reference.cited_metadata?.[field])
  if (!evidence?.source_text && !repairs.length && !review.length && !publication.length) return null

  const page = evidence?.pdf_page
  const pageUrl = page && checkId > 0 ? `/api/paper-pdf/${checkId}#page=${page}` : null
  return (
    <details className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <summary className="cursor-pointer">
        Source bibliography{evidence?.entry_number ? ` [${evidence.entry_number}]` : ''}
        {review.length > 0 && (
          <span style={{ color: 'var(--color-warning)' }}>
            {' · Review '}{review.map(([field]) => publicationLabels[field] || field).join(', ')}
          </span>
        )}
      </summary>
      {pageUrl && (
        <a className="underline" href={pageUrl} target="_blank" rel="noopener noreferrer"
          style={{ color: 'var(--color-link)' }}>
          Open PDF page {page}
        </a>
      )}
      {evidence?.source_text && (
        <p className="my-1 whitespace-pre-wrap break-words">{evidence.source_text}</p>
      )}
      {publication.length > 0 && (
        <dl className="my-1 grid grid-cols-[auto_1fr] gap-x-2">
          {publication.map(([field, label]) => (
            <div className="contents" key={field}>
              <dt className="font-medium">{label}</dt>
              <dd className="break-words">{reference.cited_metadata[field]}</dd>
            </div>
          ))}
        </dl>
      )}
      {evidence?.layout_text && (
        <>
          <p className="mt-2 font-medium">Text from PDF layout</p>
          <p className="my-1 whitespace-pre-wrap break-words">{evidence.layout_text}</p>
        </>
      )}
      {repairs.map(({ field, before, after, reason }, index) => (
        <div key={`${field}-${index}`} className="mt-1 break-words">
          <span className="font-medium capitalize">{publicationLabels[field] || field}</span>
          {' · '}{fieldValue(field, before)}{' → '}{fieldValue(field, after)}
          {repairReasons[reason] && <span> ({repairReasons[reason]})</span>}
        </div>
      ))}
      {review.map(([field, { source, parsed }]) => (
        <div key={field} className="mt-2 grid gap-1 sm:grid-cols-2">
          <div className="break-words">
            <div className="font-medium">Source {publicationLabels[field]?.toLowerCase() || field}</div>
            {fieldValue(field, source)}
          </div>
          <div className="break-words">
            <div className="font-medium">Parsed {publicationLabels[field]?.toLowerCase() || field}</div>
            {fieldValue(field, parsed)}
          </div>
        </div>
      ))}
    </details>
  )
}
