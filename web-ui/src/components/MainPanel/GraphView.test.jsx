import { describe, expect, it } from 'vitest'
import { STATUS_COLOR } from './graphStatusColors'

describe('GraphView status colours', () => {
  it('uses the website-verification colour from the reference card', () => {
    expect(STATUS_COLOR.website_verified).toBe('#0ea5e9')
  })
})
