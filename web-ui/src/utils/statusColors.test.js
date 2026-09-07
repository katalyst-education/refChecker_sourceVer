import { describe, expect, it } from 'vitest'
import { STATUS_COLORS, getStatusColors, normalizeStatus } from './statusColors'

describe('statusColors', () => {
  it('defines colors for every supported verification status', () => {
    for (const status of ['verified', 'error', 'warning', 'suggestion', 'unverified', 'checking', 'pending', 'unchecked', 'default']) {
      expect(STATUS_COLORS).toHaveProperty(status)
      expect(STATUS_COLORS[status].fill).toMatch(/^rgba\(/)
      expect(STATUS_COLORS[status].stroke).toMatch(/^rgba\(/)
    }
  })

  it('normalizes supported statuses and falls back for unknown values', () => {
    expect(normalizeStatus(' Warning ')).toBe('warning')
    expect(normalizeStatus('unknown')).toBe('default')
    expect(getStatusColors('unknown')).toEqual(STATUS_COLORS.default)
  })
})
