import { beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => vi.resetModules())

const references = () => [
  { ref_uid: 'first', index: 26, title: 'First reference', status: 'warning', warnings: [{ message: 'Wrong year' }],
    corrected_reference: { year: 2024, doi: '10.1234/example', arxiv_id: '2401.12345', venue: 'Journal' } },
  { ref_uid: 'second', index: 26, title: 'Second reference', status: 'verified' },
]

describe('live and historical reference actions', () => {
  it.each(['live', 'history'])('removes exactly the selected UID from the %s check', async (surface) => {
    const { useCheckStore: live } = await import('./useCheckStore')
    const { useHistoryStore: history } = await import('./useHistoryStore')
    const rows = references()
    live.setState({ references: rows })
    history.setState({ selectedCheck: { id: 1, results: rows } })
    if (surface === 'live') live.getState().removeReference('uid:first')
    else history.getState().optimisticRemoveReference('uid:first')
    const remaining = surface === 'live' ? live.getState().references : history.getState().selectedCheck.results
    expect(remaining.map(row => row.ref_uid)).toEqual(['second'])
  })

  it.each([
    ['live', false], ['live', true], ['history', false], ['history', true],
  ])('restores originally absent citation fields on %s (bulk reset: %s)', async (surface, bulk) => {
    const { useCheckStore: live } = await import('./useCheckStore')
    const { useHistoryStore: history } = await import('./useHistoryStore')
    const original = references()
    live.setState({ references: original })
    history.setState({ selectedCheck: { id: 1, results: original } })
    const read = () => surface === 'live' ? live.getState().references : history.getState().selectedCheck.results
    if (surface === 'live') live.getState().applyCorrectionInStore('uid:first')
    else history.getState().optimisticApplyCorrection('uid:first')
    expect(read()[0]).toMatchObject({ status: 'verified', doi: '10.1234/example' })
    expect(read()[1]).toEqual(original[1])
    if (surface === 'live') {
      if (bulk) live.getState().revertAllCorrections()
      else live.getState().revertCorrectionInStore('uid:first')
    } else {
      if (bulk) history.getState().revertAllOptimisticCorrections()
      else history.getState().optimisticRevertCorrection('uid:first')
    }
    expect(read()[0]).toMatchObject({ title: 'First reference', status: 'warning' })
    for (const field of ['year', 'doi', 'arxiv_id', 'venue']) expect(read()[0]).not.toHaveProperty(field)
    expect(read()[1]).toEqual(original[1])
  })
})
