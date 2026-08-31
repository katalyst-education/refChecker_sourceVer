import { describe, expect, it } from 'vitest'
import {
  referenceMatchesIdentity,
  referenceRowIdentity,
  toApiReferenceId,
} from './referenceIdentity'

describe('reference row identity', () => {
  it('prefers the durable uid over duplicate citation indexes', () => {
    const first = { ref_uid: 'row-first', index: 26, title: 'First work' }
    const second = { ref_uid: 'row-second', index: 26, title: 'Second work' }

    expect(referenceRowIdentity(first, 0)).toBe('uid:row-first')
    expect(referenceRowIdentity(second, 1)).toBe('uid:row-second')
    expect(toApiReferenceId(second, 1)).toBe('uid:row-second')
    expect(referenceMatchesIdentity(first, 0, 'uid:row-second')).toBe(false)
    expect(referenceMatchesIdentity(second, 1, 'uid:row-second')).toBe(true)
  })

  it('keeps legacy duplicate indexes separate until a uid arrives', () => {
    const first = { index: 26, title: 'First work' }
    const second = { index: 26, title: 'Second work' }

    expect(referenceRowIdentity(first, 0)).not.toBe(referenceRowIdentity(second, 1))
  })
})

