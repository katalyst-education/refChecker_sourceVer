import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReferenceListControls from './ReferenceListControls'
import { renameReferenceList } from '../../utils/api'

vi.mock('../../utils/api', () => ({
  createReferenceList: vi.fn(),
  renameReferenceList: vi.fn(async () => ({ data: { lists: [], references: [] } })),
  deleteReferenceList: vi.fn(),
}))
vi.mock('../../stores/useHistoryStore', () => ({
  useHistoryStore: { getState: () => ({ selectedCheckId: 2, updateCheckReferenceLists: vi.fn() }) },
}))
vi.mock('../../stores/useReferenceSearchStore', () => ({ patchCompletedReference: vi.fn() }))

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe('list dialogs follow the selected paper and list', () => {
  it.each(['Rename list', 'Delete list'])('closes %s when navigating to another paper', (action) => {
    const props = { checkId: 1, activeList: { id: 'first', name: 'First list' }, onSelectList: vi.fn() }
    const { rerender } = render(<ReferenceListControls {...props} />)
    fireEvent.click(screen.getByText(action))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    rerender(<ReferenceListControls {...props} checkId={2} />)
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull()
    expect(screen.getByText('+ New list')).toBeInTheDocument()
  })

  it('starts a fresh edit when switching to another list in the same paper', async () => {
    const props = { checkId: 2, activeList: { id: 'first', name: 'First list' }, onSelectList: vi.fn() }
    const { rerender } = render(<ReferenceListControls {...props} />)
    fireEvent.click(screen.getByText('Rename list'))
    fireEvent.change(screen.getByLabelText('List name'), { target: { value: 'Unfinished edit' } })
    rerender(<ReferenceListControls {...props} activeList={{ id: 'second', name: 'Second list' }} />)
    fireEvent.click(screen.getByText('Rename list'))
    expect(screen.getByLabelText('List name')).toHaveValue('Second list')
    fireEvent.change(screen.getByLabelText('List name'), { target: { value: 'Updated second list' } })
    fireEvent.click(screen.getByText('Save name'))
    await waitFor(() => expect(renameReferenceList).toHaveBeenCalledWith(2, 'second', 'Updated second list'))
  })
})
