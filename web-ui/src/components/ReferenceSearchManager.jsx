import { useEffect, useRef, useState } from 'react'
import { createWebSocket, getActiveReferenceSearches, getReferenceSearch } from '../utils/api'
import { useReferenceSearchStore } from '../stores/useReferenceSearchStore'
import { useAuthStore } from '../stores/useAuthStore'

const TERMINAL = new Set(['completed', 'cancelled', 'error'])

export default function ReferenceSearchManager() {
  const operations = useReferenceSearchStore(state => state.operations)
  const register = useReferenceSearchStore(state => state.register)
  const handleMessage = useReferenceSearchStore(state => state.handleMessage)
  const applySnapshot = useReferenceSearchStore(state => state.applySnapshot)
  const sockets = useRef(new Map())
  const reconnectTimers = useRef(new Map())
  const [connectionAttempt, setConnectionAttempt] = useState(0)
  const authLoading = useAuthStore(state => state.isLoading)
  const authRequired = useAuthStore(state => state.authRequired)
  const userId = useAuthStore(state => state.user?.id)
  const ready = !authLoading && (!authRequired || userId != null)

  useEffect(() => {
    if (!ready) return
    let stopped = false
    let discovering = false
    const pendingSnapshots = new Set()
    const recover = async () => {
      if (discovering) return
      discovering = true
      try {
        const response = await getActiveReferenceSearches()
        if (!stopped) {
          for (const operation of response.data?.operations || []) register(operation)
        }
      } catch { /* the next poll, focus, or network recovery retries discovery */ }
      finally { discovering = false }
    }
    const sync = () => {
      recover()
      for (const operation of Object.values(useReferenceSearchStore.getState().operations)) {
        if (TERMINAL.has(operation.status) || !operation.operation_id || pendingSnapshots.has(operation.operation_id)) continue
        pendingSnapshots.add(operation.operation_id)
        getReferenceSearch(operation.operation_id)
          .then(response => { if (!stopped) applySnapshot(response.data) })
          .catch(() => undefined)
          .finally(() => pendingSnapshots.delete(operation.operation_id))
      }
    }
    const onVisible = () => { if (document.visibilityState === 'visible') sync() }
    sync()
    const timer = setInterval(sync, 10_000)
    window.addEventListener('online', sync)
    window.addEventListener('focus', sync)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      clearInterval(timer)
      window.removeEventListener('online', sync)
      window.removeEventListener('focus', sync)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [ready, userId, register, applySnapshot])

  useEffect(() => {
    if (!ready) return
    const active = Object.values(operations).filter(op => !TERMINAL.has(op.status))
    const activeSessions = new Set(active.map(op => op.session_id).filter(Boolean))
    for (const operation of active) {
      if (!operation.session_id || sockets.current.has(operation.session_id)) continue
      const ws = createWebSocket(operation.session_id, {
        onMessage: handleMessage,
        onClose: () => {
          if (sockets.current.get(operation.session_id) !== ws) return
          sockets.current.delete(operation.session_id)
          if (reconnectTimers.current.has(operation.session_id)) return
          const timer = setTimeout(() => {
            reconnectTimers.current.delete(operation.session_id)
            const current = Object.values(useReferenceSearchStore.getState().operations)
              .find(op => op.session_id === operation.session_id)
            if (current && !TERMINAL.has(current.status)) setConnectionAttempt(value => value + 1)
          }, 1000)
          reconnectTimers.current.set(operation.session_id, timer)
        },
      })
      sockets.current.set(operation.session_id, ws)
    }
    for (const [sessionId, socket] of sockets.current.entries()) {
      if (!activeSessions.has(sessionId)) {
        socket.close()
        sockets.current.delete(sessionId)
      }
    }
  }, [ready, operations, handleMessage, connectionAttempt])

  useEffect(() => () => {
    for (const timer of reconnectTimers.current.values()) clearTimeout(timer)
    reconnectTimers.current.clear()
    for (const socket of sockets.current.values()) socket.close()
    sockets.current.clear()
  }, [])

  return null
}

