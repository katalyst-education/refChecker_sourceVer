import { useEffect, useRef } from 'react'
import { createWebSocket, getActiveReferenceSearches, getReferenceSearch } from '../utils/api'
import { useReferenceSearchStore } from '../stores/useReferenceSearchStore'

const TERMINAL = new Set(['completed', 'cancelled', 'error'])

export default function ReferenceSearchManager() {
  const operations = useReferenceSearchStore(state => state.operations)
  const register = useReferenceSearchStore(state => state.register)
  const handleMessage = useReferenceSearchStore(state => state.handleMessage)
  const applySnapshot = useReferenceSearchStore(state => state.applySnapshot)
  const sockets = useRef(new Map())

  useEffect(() => {
    getActiveReferenceSearches().then(response => {
      for (const operation of response.data?.operations || []) register(operation)
    }).catch(() => undefined)
  }, [register])

  useEffect(() => {
    const active = Object.values(operations).filter(op => !TERMINAL.has(op.status))
    const activeSessions = new Set(active.map(op => op.session_id).filter(Boolean))
    for (const operation of active) {
      if (!operation.session_id || sockets.current.has(operation.session_id)) continue
      const ws = createWebSocket(operation.session_id, {
        onMessage: handleMessage,
        onClose: () => sockets.current.delete(operation.session_id),
      })
      sockets.current.set(operation.session_id, ws)
    }
    for (const [sessionId, socket] of sockets.current.entries()) {
      if (!activeSessions.has(sessionId)) {
        socket.close()
        sockets.current.delete(sessionId)
      }
    }
  }, [operations, handleMessage])

  useEffect(() => {
    const timer = setInterval(() => {
      const active = Object.values(useReferenceSearchStore.getState().operations)
        .filter(op => !TERMINAL.has(op.status) && op.operation_id)
      for (const operation of active) {
        getReferenceSearch(operation.operation_id)
          .then(response => applySnapshot(response.data))
          .catch(() => undefined)
      }
    }, 10_000)
    return () => clearInterval(timer)
  }, [applySnapshot])

  useEffect(() => () => {
    for (const socket of sockets.current.values()) socket.close()
    sockets.current.clear()
  }, [])

  return null
}

