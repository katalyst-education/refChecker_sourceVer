import { useEffect, useState } from 'react'
import { cancelReferenceSearch, getReferenceReextractions, startReferenceReextraction } from '../../utils/api'
import { referenceSearchKey, useReferenceSearchStore } from '../../stores/useReferenceSearchStore'
import { getReviewList } from '../../utils/referenceStatus'

export default function ReferenceReextractionButton({ checkId, references, disabled = false }) {
  const operation = useReferenceSearchStore(s => s.operations[referenceSearchKey(checkId, 'check:reextract-errors')])
  const register = useReferenceSearchStore(s => s.register)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [recovering, setRecovering] = useState(true)
  const [recoveryError, setRecoveryError] = useState('')
  const [recoveryAttempt, setRecoveryAttempt] = useState(0)
  const [recentRuns, setRecentRuns] = useState([])
  const count = (references || []).filter(ref =>
    getReviewList(ref) === 'automated' && ['error', 'unverified'].includes(ref.status)
  ).length
  const active = ['queued', 'running', 'cancelling'].includes(operation?.status)
  const progress = operation?.progress || operation || {}
  const failures = progress.failures || []
  const previousRuns = recentRuns.filter(run => run.operation_id !== operation?.operation_id
    && ['completed', 'cancelled', 'error'].includes(run.status))

  useEffect(() => {
    if (!checkId || checkId < 1) return
    let disposed = false
    setRecovering(true)
    setRecoveryError('')
    getReferenceReextractions(checkId).then(response => {
      if (disposed) return
      const runs = response.data?.operations || []
      setRecentRuns(runs)
      const latest = runs.find(run => ['queued', 'running', 'cancelling'].includes(run.status)) || runs[0]
      if (latest) register(latest)
    }).catch(e => {
      if (!disposed) setRecoveryError(e?.response?.data?.detail || 'Could not restore re-extraction status. Retry to reconnect.')
    }).finally(() => { if (!disposed) setRecovering(false) })
    return () => { disposed = true }
  }, [checkId, register, recoveryAttempt])

  useEffect(() => {
    if (['completed', 'cancelled', 'error'].includes(operation?.status)) {
      setRecoveryAttempt(value => value + 1)
    }
  }, [operation?.operation_id, operation?.status])

  useEffect(() => {
    if (!recoveryError) return
    const timer = setTimeout(() => setRecoveryAttempt(value => value + 1), 5000)
    return () => clearTimeout(timer)
  }, [recoveryError])

  const start = async () => {
    setStarting(true)
    setError('')
    try {
      const response = await startReferenceReextraction(checkId)
      register(response.data)
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Could not start re-extraction.')
    } finally {
      setStarting(false)
    }
  }
  const cancel = async () => {
    try {
      await cancelReferenceSearch(operation.operation_id)
      register({ ...operation, status: 'cancelling' })
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Could not cancel re-extraction.')
    }
  }

  if (!checkId || checkId < 1) return null
  return (
    <div className="text-xs space-y-2" style={{ color: 'var(--color-text-secondary)' }}>
      <div className="flex items-center flex-wrap gap-2">
        <button type="button" onClick={start}
          disabled={disabled || starting || active || recovering || !!recoveryError || count === 0}
          className="px-3 py-1.5 rounded-md border font-medium disabled:opacity-50"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-accent)', background: 'var(--color-bg-secondary)' }}
          title="Read the document once and re-extract error and unverified references. Changed citation data triggers a search across all databases; unchanged entries retain their current results.">
          {starting || active ? 'Re-extracting references…' : `Re-extract errors & unverified (${count})`}
        </button>
        {active && <button type="button" onClick={cancel} disabled={operation.status === 'cancelling'}
          className="underline disabled:opacity-50">{operation.status === 'cancelling' ? 'Cancelling…' : 'Cancel'}</button>}
        {(recovering || active || operation?.status) && <span role="status" aria-live="polite">
          {operation?.error_message || progress.message || (recovering ? 'Restoring re-extraction status…' : 'Waiting to re-extract references…')}
          {active && progress.total > 0 ? ` (${progress.completed || 0}/${progress.total})` : ''}
        </span>}
      </div>
      {error && <p role="alert" style={{ color: 'var(--color-error)' }}>{error}</p>}
      {recoveryError && <p role="alert" style={{ color: 'var(--color-error)' }}>
        {recoveryError} <button type="button" className="underline" onClick={() => setRecoveryAttempt(value => value + 1)}>Retry connection</button>
      </p>}
      {failures.length > 0 && <details>
        <summary className="cursor-pointer">References needing review ({failures.length})</summary>
        <ul className="mt-1 space-y-1">{failures.map((failure, i) =>
          <li key={`${failure.index}-${i}`}>[{failure.index}] {failure.message}</li>)}</ul>
      </details>}
      {previousRuns.length > 0 && <details>
        <summary className="cursor-pointer">Previous re-extractions ({previousRuns.length})</summary>
        <ul className="mt-1 space-y-1">{previousRuns.map(run => <li key={run.operation_id}>
          {run.status === 'completed' ? 'Completed' : run.status === 'cancelled' ? 'Cancelled' : 'Interrupted'}: {run.error_message || run.progress?.message}
        </li>)}</ul>
      </details>}
    </div>
  )
}
