import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DocumentViewer from './DocumentViewer'
import StatusSection, { buildCitationViewerSpans } from './StatusSection'

const historyState = vi.hoisted(() => ({
  selectedCheckId: 42,
  selectedCheck: {
    id: 42,
    status: 'in_progress',
    paper_title: 'Active paper',
    paper_source: 'https://example.com/paper.pdf',
    source_type: 'url',
    total_refs: 0,
    processed_refs: 0,
    llm_provider: 'google',
    llm_model: 'gemini-3.1-flash-lite-preview',
  },
  history: [],
  updateHistoryProgress: vi.fn(),
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

vi.mock('./NativePdfViewer', () => ({ default: () => null }))

vi.mock('./DocumentViewer', async (importOriginal) => {
  const { default: Viewer } = await importOriginal()
  return { default: vi.fn((props) => <Viewer {...props} />) }
})

vi.mock('../../stores/useCheckStore', () => {
  const state = {
    status: 'idle',
    statusMessage: '',
    progress: 0,
    stats: {},
    paperTitle: null,
    paperSource: null,
    sourceType: null,
    sessionId: null,
    currentCheckId: null,
    cancelCheck: vi.fn(),
  }
  const useCheckStore = (selector) => selector ? selector(state) : state
  useCheckStore.getState = () => state
  return { useCheckStore }
})

vi.mock('../../stores/useHistoryStore', () => {
  const useHistoryStore = (selector) => selector ? selector(historyState) : historyState
  useHistoryStore.getState = () => historyState
  return { useHistoryStore }
})

describe('StatusSection model display', () => {
  beforeEach(() => {
    historyState.selectedCheckId = 42
    historyState.selectedCheck = {
      id: 42,
      status: 'in_progress',
      paper_title: 'Active paper',
      paper_source: 'https://example.com/paper.pdf',
      source_type: 'url',
      total_refs: 0,
      processed_refs: 0,
      llm_provider: 'google',
      llm_model: 'gemini-3.1-flash-lite-preview',
    }
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows extraction model metadata', () => {
    render(<StatusSection />)

    expect(screen.getByText('Extraction Model:')).toBeInTheDocument()
    expect(screen.getByText('google / gemini-3.1-flash-lite-preview')).toBeInTheDocument()
  })

  it('retries thumbnail after a check completes', () => {
    const { rerender } = render(<StatusSection />)
    const image = screen.getByAltText('Paper thumbnail')
    expect(image.getAttribute('src')).toBe('/api/thumbnail/42?phase=active')

    fireEvent.error(image)
    expect(screen.queryByAltText('Paper thumbnail')).toBeNull()

    historyState.selectedCheck = {
      ...historyState.selectedCheck,
      status: 'completed',
      total_refs: 10,
      processed_refs: 10,
    }
    rerender(<StatusSection />)

    const retriedImage = screen.getByAltText('Paper thumbnail')
    expect(retriedImage.getAttribute('src')).toBe('/api/thumbnail/42?phase=completed')
  })

  const openPreview = (count) => {
    vi.stubGlobal('fetch', vi.fn(async (url) => ({
      ok: url === '/api/preview/42/page-count',
      json: async () => ({ count }),
    })))
    render(<StatusSection />)
    const thumbnail = screen.getByAltText('Paper thumbnail')
    fireEvent.load(thumbnail)
    fireEvent.click(thumbnail)
  }

  it('replaces the raster preview with the document viewer if a page image fails', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    openPreview(2)
    const page = await screen.findByAltText('Page 2 of 2')
    fireEvent.keyDown(document, { key: '+' })
    expect(page.parentElement).toHaveStyle({ width: '113vw' })

    fireEvent.error(page)

    expect(screen.queryByAltText('Page 1 of 2')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Passages in document' })).toBeInTheDocument()
    expect(DocumentViewer.mock.lastCall[0]).toMatchObject({
      checkId: 42, sourceType: 'url', paperSource: 'https://example.com/paper.pdf',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Close', exact: true }))
    expect(screen.queryByRole('dialog', { name: 'Passages in document' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByAltText('Paper thumbnail'))
    expect(screen.getByAltText('Page 2 of 2')).toBeInTheDocument()
  })

  it('tries the thumbnail once before opening the document viewer if the single preview fails', async () => {
    openPreview(0)
    const image = await screen.findByAltText('Paper preview')
    expect(image).toHaveAttribute('src', '/api/preview/42?phase=active')

    fireEvent.error(image)
    expect(image).toHaveAttribute('src', '/api/thumbnail/42?phase=active')
    expect(screen.queryByRole('dialog', { name: 'Passages in document' })).not.toBeInTheDocument()

    fireEvent.error(image)
    expect(screen.queryByAltText('Paper preview')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Passages in document' })).toBeInTheDocument()
  })

  it('closes Find before dismissing the fallback document viewer on Escape', async () => {
    openPreview(0)
    const image = await screen.findByAltText('Paper preview')
    fireEvent.error(image)
    fireEvent.error(image)
    const viewer = screen.getByRole('dialog', { name: 'Passages in document' })

    vi.useFakeTimers()
    fireEvent.keyDown(viewer, { key: 'f', ctrlKey: true })
    expect(screen.getByPlaceholderText('Find in document')).toBeInTheDocument()
    fireEvent.keyDown(viewer, { key: 'Escape' })
    act(() => vi.runAllTimers())
    expect(screen.queryByPlaceholderText('Find in document')).not.toBeInTheDocument()
    expect(viewer).toBeInTheDocument()

    fireEvent.keyDown(viewer, { key: 'Escape' })
    act(() => vi.runAllTimers())
    expect(viewer).not.toBeInTheDocument()
  })
})

// R28 (S6) — clicking an inline citation must hyperlink to the reference list
// INSIDE the same PDF. buildCitationViewerSpans appends the reference-list entry
// as a second locatable span and wires the citation span's `refEntryIndex` so
// the native viewer scrolls + flashes that entry in-document on click.
describe('buildCitationViewerSpans in-PDF reference jump (R28)', () => {
  it('appends the reference-list entry span and wires refEntryIndex', () => {
    const spans = buildCitationViewerSpans({
      text: 'The method outperforms the baseline by a wide margin [4].',
      status: 'verified',
      refId: '4',
      refTitle: 'A Study of Convergence in Deep Networks',
      label: '[4]',
    })

    expect(spans).toHaveLength(2)
    // Span 0 is the cited sentence, pointing at span 1 as its in-PDF jump target.
    expect(spans[0].quote).toContain('outperforms the baseline')
    expect(spans[0].refEntryIndex).toBe(1)
    expect(spans[0].status).toBe('verified')
    // Span 1 is the reference-list entry, located by the reference title.
    expect(spans[1].kind).toBe('ref-entry')
    expect(spans[1].quote).toBe('A Study of Convergence in Deep Networks')
    expect(spans[1].refId).toBe('4')
  })

  it('omits the entry span (and refEntryIndex) when no reference title is known', () => {
    const spans = buildCitationViewerSpans({
      text: 'A cited sentence with no resolvable reference title here.',
      refId: '9',
    })
    expect(spans).toHaveLength(1)
    expect(spans[0].refEntryIndex).toBeUndefined()
    expect(spans[0].kind).toBeUndefined()
  })

  it('returns an empty array for no citation target', () => {
    expect(buildCitationViewerSpans(null)).toEqual([])
    expect(buildCitationViewerSpans({})).toEqual([])
  })
})
