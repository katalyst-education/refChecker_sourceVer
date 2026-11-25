import { useState } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { patchCompletedReference } from '../../stores/useReferenceSearchStore'
import { createReferenceList, renameReferenceList, deleteReferenceList } from '../../utils/api'

const buttonStyle = {
  color: 'var(--color-text-primary)',
  borderColor: 'var(--color-border)',
  background: 'var(--color-bg-secondary)',
}
const buttonClass = 'rounded-md border px-2.5 py-1 text-xs font-medium disabled:opacity-50'

export default function ReferenceListControls(props) {
  return <ReferenceListControlsForm key={`${props.checkId}:${props.activeList?.id || 'automated'}`} {...props} />
}

function ReferenceListControlsForm({ checkId, activeList, onSelectList }) {
  const [action, setAction] = useState(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const open = (next) => {
    setError('')
    setName(next === 'rename' ? activeList.name : '')
    setAction(next)
  }

  const save = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      let response
      if (action === 'delete') response = await deleteReferenceList(checkId, activeList.id)
      else if (action === 'rename') response = await renameReferenceList(checkId, activeList.id, name.trim())
      else response = await createReferenceList(checkId, name.trim())
      const { lists, list, references } = response.data
      for (const reference of references || []) {
        patchCompletedReference({
          check_id: checkId, reference_key: `uid:${reference.ref_uid}`,
        }, reference, { reviewMove: true })
      }
      const history = useHistoryStore.getState()
      history.updateCheckReferenceLists(checkId, lists)
      setAction(null)
      if (history.selectedCheckId === checkId) onSelectList(list?.id || null)
    } catch (e) {
      setError(e?.response?.data?.detail || 'The change to the reference list could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  if (!action) {
    return (
      <div className="flex flex-wrap items-center gap-1.5 pb-1">
        <button type="button" className={buttonClass} style={buttonStyle} onClick={() => open('create')}>
          + New list
        </button>
        {activeList && (
          <>
            <button type="button" className={buttonClass} style={buttonStyle} onClick={() => open('rename')}>
              Rename list
            </button>
            <button type="button" className={buttonClass} style={buttonStyle} onClick={() => open('delete')}>
              Delete list
            </button>
          </>
        )}
      </div>
    )
  }

  return (
    <form onSubmit={save} className="flex basis-full flex-wrap items-center gap-2 pb-2 text-xs" aria-busy={busy}>
      {action === 'delete' ? (
        <span style={{ color: 'var(--color-text-secondary)' }}>
          Delete “{activeList.name}”? Its references will move to Unverified.
        </span>
      ) : (
        <input
          autoFocus
          aria-label="List name"
          placeholder="List name"
          value={name}
          onChange={event => setName(event.target.value)}
          maxLength={80}
          disabled={busy}
          className="min-w-0 max-w-full rounded-md border px-2.5 py-1"
          style={buttonStyle}
        />
      )}
      <button
        type="submit"
        disabled={busy || (action !== 'delete' && !name.trim())}
        className={buttonClass}
        style={buttonStyle}
      >
        {action === 'delete' ? 'Delete list' : action === 'rename' ? 'Save name' : 'Create list'}
      </button>
      <button
        type="button"
        onClick={() => setAction(null)}
        disabled={busy}
        className={buttonClass}
        style={buttonStyle}
      >
        Cancel
      </button>
      {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </form>
  )
}
