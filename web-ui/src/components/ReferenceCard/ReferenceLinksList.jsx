import { formatReferenceLinkType } from '../../utils/referenceLinks'

export default function ReferenceLinksList({ links, summary = 'Links', className = '', onLinkClick }) {
  if (!Array.isArray(links) || links.length === 0) return null

  return (
    <details className={className}>
      <summary
        className="cursor-pointer select-none font-medium"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {summary} ({links.length})
      </summary>
      <ul className="mt-2 space-y-1.5">
        {links.map(({ type, url }) => (
          <li
            key={url}
            className="rounded-md px-2 py-1.5"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {formatReferenceLinkType(type)}
            </div>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onLinkClick ? onLinkClick(url) : undefined}
              className="hover:underline"
              style={{ color: 'var(--color-link)', overflowWrap: 'anywhere', wordBreak: 'break-all' }}
            >
              {url}
            </a>
          </li>
        ))}
      </ul>
    </details>
  )
}
