import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MainPanel from './MainPanel'

const data = vi.hoisted(() => ({ check: {}, history: {} }))
vi.mock('../../stores/useCheckStore', () => ({ useCheckStore: (select) => select(data.check) }))
vi.mock('../../stores/useHistoryStore', () => ({ useHistoryStore: () => data.history }))
vi.mock('../../stores/useStyleStore', () => ({ useStyleStore: (select) => select({ format: 'apa', styleOptions: {} }) }))
vi.mock('./InputSection', () => ({ default: () => null }))
vi.mock('./StatusSection', () => ({ default: () => <div>Paper status</div> }))
vi.mock('./StatsSection', () => ({ default: () => <div>Check summary</div> }))
vi.mock('./ReferenceList', () => ({ default: ({ references }) => <div>Reference list: {references[0]?.title}</div> }))
vi.mock('./CorrectionsView', () => ({ default: () => <div>Correction details</div> }))
vi.mock('./OnboardingBanner', () => ({ default: () => null }))
vi.mock('./FieldGuide', () => ({ default: () => null }))
vi.mock('./GlobalDropZone', () => ({ default: () => null }))
vi.mock('./SeenReferencesView', () => ({ default: () => null }))
vi.mock('./BatchSummaryView', () => ({ default: () => null }))
vi.mock('./GraphView', () => ({ default: () => <input aria-label="Graph selection" defaultValue="" /> }))
vi.mock('./SimilarPapersPanel', () => ({ default: () => <div>Related paper results</div> }))
vi.mock('./ExploreGraphView', () => ({ default: () => null }))
vi.mock('./HealthBadge', () => ({ default: () => null }))
vi.mock('./LLMUsageBadge', () => ({ default: () => null }))
vi.mock('./RetractionCheck', () => ({ default: () => <div>Retraction tool</div> }))
vi.mock('./CitationIntegrity', () => ({ default: () => <div>Citation integrity tool</div> }))
vi.mock('./ArticleAssistant', () => ({ default: () => <div>Article assistant</div> }))
vi.mock('./GapFinder', () => ({ default: () => <input aria-label="Suggestion selection" defaultValue="" /> }))

beforeEach(() => {
  data.check = { status: 'idle', references: [], stats: {}, currentCheckId: null, clearStatusFilter: vi.fn(), statusFilter: [] }
  data.history = { selectedCheckId: 12, selectedCheck: { id: 12, status: 'completed', total_refs: 1, paper_title: 'Paper A', results: [{ title: 'Reference A', status: 'verified', errors: [], warnings: [] }] } }
})

const tab = (name) => fireEvent.click(screen.getByRole('tab', { name }))

describe('paper workflows', () => {
  it('separates checking from exploration without an overview or footer', () => {
    render(<MainPanel />)
    expect(within(screen.getByRole('tablist', { name: 'Results view' })).getAllByRole('tab').map(el => el.textContent)).toEqual(['References1', 'Corrections0'])
    expect(screen.getByText('Check summary')).toBeVisible()
    expect(screen.getByText('Retraction tool')).toBeVisible()
    expect(screen.getByText('Citation integrity tool')).toBeVisible()
    expect(screen.getByText('Article assistant')).toBeVisible()
    expect(screen.getByLabelText('Suggestion selection')).not.toBeVisible()
    tab('Explore literature')
    expect(within(screen.getByRole('tablist', { name: 'Results view' })).getAllByRole('tab').map(el => el.textContent)).toEqual(['Suggested papers', 'Related papers', 'Citation graph1'])
    expect(screen.getByText('Check summary')).not.toBeVisible()
    expect(screen.getByText('Retraction tool')).not.toBeVisible()
    expect(screen.getByText('Article assistant')).not.toBeVisible()
    expect(screen.getByLabelText('Suggestion selection')).toBeVisible()
    expect(screen.queryByRole('tab', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Ready to explore/)).not.toBeInTheDocument()
  })

  it('remembers each workflow view and keeps exploration state when switching', () => {
    render(<MainPanel />)
    tab(/Corrections/)
    tab('Explore literature')
    tab(/Citation graph/)
    fireEvent.change(screen.getByLabelText('Graph selection'), { target: { value: 'Selected node' } })
    tab('Check references')
    expect(screen.getByText('Correction details')).toBeVisible()
    tab('Explore literature')
    expect(screen.getByLabelText('Graph selection')).toBeVisible()
    expect(screen.getByLabelText('Graph selection')).toHaveValue('Selected node')
    act(() => window.dispatchEvent(new CustomEvent('refchecker:focus-reference')))
    expect(screen.getByText('Reference list: Reference A')).toBeVisible()
    expect(screen.getByRole('tab', { name: 'Check references' })).toHaveAttribute('aria-selected', 'true')
  })

  it('resets suggestions for a different paper and waits for checking to finish', () => {
    const { rerender } = render(<MainPanel />)
    tab('Explore literature')
    fireEvent.change(screen.getByLabelText('Suggestion selection'), { target: { value: 'Paper A suggestion' } })
    data.history = { ...data.history, selectedCheckId: 13, selectedCheck: { ...data.history.selectedCheck, id: 13, results: [{ title: 'Reference B' }] } }
    rerender(<MainPanel />)
    expect(screen.getByLabelText('Suggestion selection')).toHaveValue('')
    data.history.selectedCheck = { ...data.history.selectedCheck, status: 'in_progress' }
    rerender(<MainPanel />)
    expect(screen.queryByLabelText('Suggestion selection')).not.toBeInTheDocument()
    expect(screen.getByText('Suggestions will be available when reference checking finishes.')).toBeVisible()
  })
})
