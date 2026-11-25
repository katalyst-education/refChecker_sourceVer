import { normalizeAuthors } from '../../utils/formatters'

function fieldValue(field, value) {
  if (field === 'authors' && Array.isArray(value)) {
    return normalizeAuthors(value).join(', ') || 'Missing'
  }
  return value ? String(value) : 'Missing'
}

const repairReasons = {
  bibliography_authors: 'Bibliography author list',
  bibliography_title: 'Bibliography title',
  bibliography_venue: 'Bibliography venue',
  bibliography_parser: 'Bibliography text parser',
  pdf_layout: 'PDF page layout',
  field_cleanup: 'Parser field cleanup',
  targeted_llm_reparse: 'Reparsed this entry',
}

export default function ReferenceSourceDetails({ reference, checkId }) {
  const evidence = reference.extraction_provenance
  const repairs = evidence?.repairs ?? []
  const review = Object.entries(evidence?.review ?? {})
  if (!evidence?.source_text && !repairs.length && !review.length) return null

  const page = evidence.pdf_page
  const pageUrl = page && checkId > 0 ? `/api/paper-pdf/${checkId}#page=${page}` : null
  return (
    <details className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <summary className="cursor-pointer">
        Source bibliography{evidence.entry_number ? ` [${evidence.entry_number}]` : ''}
        {review.length > 0 && (
          <span style={{ color: 'var(--color-warning)' }}>
            {' · Review '}{review.map(([field]) => field).join(', ')}
          </span>
        )}
      </summary>
      {pageUrl && (
        <a className="underline" href={pageUrl} target="_blank" rel="noopener noreferrer"
          style={{ color: 'var(--color-link)' }}>
          Open PDF page {page}
        </a>
      )}
      {evidence.source_text && (
        <p className="my-1 whitespace-pre-wrap break-words">{evidence.source_text}</p>
      )}
      {evidence.layout_text && (
        <>
          <p className="mt-2 font-medium">Text from PDF layout</p>
          <p className="my-1 whitespace-pre-wrap break-words">{evidence.layout_text}</p>
        </>
      )}
      {repairs.map(({ field, before, after, reason }, index) => (
        <div key={`${field}-${index}`} className="mt-1 break-words">
          <span className="font-medium capitalize">{field}</span>
          {' · '}{fieldValue(field, before)}{' → '}{fieldValue(field, after)}
          {repairReasons[reason] && <span> ({repairReasons[reason]})</span>}
        </div>
      ))}
      {review.map(([field, { source, parsed }]) => (
        <div key={field} className="mt-2 grid gap-1 sm:grid-cols-2">
          <div className="break-words">
            <div className="font-medium">Source {field}</div>
            {fieldValue(field, source)}
          </div>
          <div className="break-words">
            <div className="font-medium">Parsed {field}</div>
            {fieldValue(field, parsed)}
          </div>
        </div>
      ))}
    </details>
  )
}
