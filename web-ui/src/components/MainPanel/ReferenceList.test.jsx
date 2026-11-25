import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import ReferenceList from './ReferenceList'
import { useCheckStore } from '../../stores/useCheckStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useReferenceSearchStore } from '../../stores/useReferenceSearchStore'
import { moveReferenceReviewList, startReferenceSearch } from '../../utils/api'

vi.mock('../../utils/api', () => ({
  addReferenceToCheck: vi.fn(),
  removeReferenceFromCheck: vi.fn(),
  moveReferenceReviewList: vi.fn(),
  suggestAlternativeReference: vi.fn(),
  startReferenceSearch: vi.fn(),
  startReferenceVerification: vi.fn(),
  cancelReferenceSearch: vi.fn(),
  beginAuthenticatedSourceSession: vi.fn(),
  completeAuthenticatedSourceSession: vi.fn(),
  resolveDoi: vi.fn(),
  getReferenceInvestigations: vi.fn(),
  investigateReferenceSuggestion: vi.fn(),
}))

vi.mock('../ReferenceCard/ReferenceCard', () => ({
  default: ({ reference, index }) => (
    <p data-testid="citation">{index + 1}. {reference.title}</p>
  ),
}))

const first = { index: 0, ref_uid: 'first', title: 'First citation', status: 'verified' }
const second = { index: 1, ref_uid: 'second', title: 'Second citation', status: 'verified' }
const customList = { id: 'proof-reading', name: 'Proofreading' }
const last = { index: 2, ref_uid: 'last', title: 'Third citation', status: 'verified', review_list: customList.id }

function SavedReferenceList({ activeList }) {
  const references = useHistoryStore(state => state.selectedCheck.results)
  return <ReferenceList references={references} isCheckComplete referenceLists={[customList]} activeList={activeList} />
}

const citations = () => screen.queryAllByTestId('citation').map(row => row.textContent)
const rowFor = (text) => within(screen.getByText(text).parentElement)

beforeEach(() => {
  vi.clearAllMocks()
  useHistoryStore.setState({
    selectedCheckId: 17, selectedCheck: { id: 17, results: [last, first, second] }, history: [], detailCache: {},
  })
  useCheckStore.setState({ currentCheckId: null, statusFilter: [] })
  useReferenceSearchStore.setState({ operations: {} })
})

it('files citations in document order and returns a searched citation to its original place', async () => {
  const filed = { ...first, review_list: customList.id, review_revision: 'first-move' }
  moveReferenceReviewList.mockResolvedValue({ data: { reference: filed } })
  startReferenceSearch.mockResolvedValue({ data: {
    check_id: 17, reference_key: 'uid:first', operation_id: 'search', operation_type: 'search-all', status: 'queued',
  } })
  const { rerender } = render(<SavedReferenceList />)

  expect(citations()).toEqual(['1. First citation', '2. Second citation'])
  fireEvent.change(rowFor('1. First citation').getByRole('combobox', { name: 'Move reference to list' }),
    { target: { value: customList.id } })
  await waitFor(() => expect(citations()).toEqual(['2. Second citation']))
  rerender(<SavedReferenceList activeList={customList} />)
  expect(citations()).toEqual(['1. First citation', '3. Third citation'])
  expect(rowFor('1. First citation').getByRole('option', { name: 'Unverified' })).toBeInTheDocument()

  fireEvent.click(rowFor('1. First citation').getByRole('button', { name: 'Search all DBs' }))
  await waitFor(() => expect(startReferenceSearch).toHaveBeenCalledWith(17, 'uid:first', expect.any(Object)))
  expect(citations()).toEqual(['1. First citation', '3. Third citation'])
  act(() => useReferenceSearchStore.getState().handleMessage({
    type: 'reference_search_completed', check_id: 17, reference_key: 'uid:first', operation_id: 'search',
    sequence: 1, reference: { ...first, review_revision: filed.review_revision },
  }))
  expect(citations()).toEqual(['3. Third citation'])
  rerender(<SavedReferenceList />)
  expect(citations()).toEqual(['1. First citation', '2. Second citation'])
})
