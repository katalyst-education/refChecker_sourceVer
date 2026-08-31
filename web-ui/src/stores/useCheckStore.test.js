import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

describe('useCheckStore', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('should initialize with idle status', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    expect(result.current.status).toBe('idle')
    expect(result.current.sessionId).toBeNull()
    expect(result.current.references).toEqual([])
    expect(result.current.progress).toBe(0)
  })

  it('should have startCheck method', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    expect(typeof result.current.startCheck).toBe('function')
  })

  it('should set status to checking when startCheck is called', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    act(() => {
      result.current.startCheck('test-session-123')
    })
    
    expect(result.current.status).toBe('checking')
    expect(result.current.sessionId).toBe('test-session-123')
  })

  it('should have reset method', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    expect(typeof result.current.reset).toBe('function')
  })

  it('should reset state when reset is called', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    // Set some state
    act(() => {
      result.current.startCheck('test-session-123')
    })
    expect(result.current.status).toBe('checking')
    
    // Reset
    act(() => {
      result.current.reset()
    })
    
    expect(result.current.status).toBe('idle')
    expect(result.current.sessionId).toBeNull()
  })

  it('should handle WebSocket messages', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    expect(typeof result.current.handleWebSocketMessage).toBe('function')
  })

  it('should update progress on progress message', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    act(() => {
      result.current.startCheck('test-session-123')
    })
    
    act(() => {
      result.current.handleWebSocketMessage({
        type: 'progress',
        percent: 50,
      })
    })
    
    expect(result.current.progress).toBe(50)
  })

  it('should set error on error message', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    act(() => {
      result.current.startCheck('test-session-123')
    })
    
    act(() => {
      result.current.handleWebSocketMessage({
        type: 'error',
        message: 'Something went wrong',
      })
    })
    
    expect(result.current.status).toBe('error')
    expect(result.current.error).toBe('Something went wrong')
  })

  it('should set completed status on completed message', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    const { result } = renderHook(() => useCheckStore())
    
    act(() => {
      result.current.startCheck('test-session-123')
    })
    
    act(() => {
      result.current.handleWebSocketMessage({
        type: 'completed',
      })
    })
    
    expect(result.current.status).toBe('completed')
  })

  it('does not merge duplicate citation indexes into the wrong row', async () => {
    const { useCheckStore } = await import('./useCheckStore')
    useCheckStore.setState({
      references: [
        { ref_uid: 'row-first', index: 26, title: 'First', status: 'verified' },
        { ref_uid: 'row-second', index: 26, title: 'Second', status: 'warning' },
      ],
    })

    act(() => {
      useCheckStore.getState().setReferences([
        { ref_uid: 'row-first', index: 26, title: 'First', status: 'pending' },
        { ref_uid: 'row-second', index: 26, title: 'Second', status: 'pending' },
      ])
    })

    expect(useCheckStore.getState().references.map(row => row.title)).toEqual(['First', 'Second'])
    expect(useCheckStore.getState().references.map(row => row.status)).toEqual(['verified', 'warning'])
  })
})
