import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const apiInstance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }

  return {
    apiInstance,
    create: vi.fn(() => apiInstance),
  }
})

vi.mock('axios', () => ({
  default: {
    create: mocks.create,
  },
}))

import * as api from './api'

describe('export status options', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    ['check', () => api.exportCheckFile(42, { statuses: ['warning', 'error'] })],
    ['batch', () => api.exportBatchFile('batch-1', { statuses: ['warning', 'error'] })],
  ])('sends status choices in the %s download query', (_name, download) => {
    download()
    const query = new URLSearchParams(mocks.apiInstance.get.mock.calls[0][0].split('?')[1])
    expect(query.get('statuses')).toBe('warning,error')
  })

  it('sends status choices in the publish request', () => {
    api.publishCheck(42, { adapter: 'quick_link', statuses: ['error', 'unverified'] })
    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/export/42/publish', expect.objectContaining({ statuses: 'error,unverified' }), expect.anything(),
    )
  })

  it('preserves list-only and empty-list selections in download queries', () => {
    api.exportCheckFile(42, { statuses: [], review_lists: ['custom-id'] })
    api.exportBatchFile('batch-1', { review_lists: [] })
    const queries = mocks.apiInstance.get.mock.calls.map(([url]) => new URLSearchParams(url.split('?')[1]))
    expect(queries[0].get('statuses')).toBe('')
    expect(queries[0].get('review_lists')).toBe('custom-id')
    expect(queries[1].get('review_lists')).toBe('')
  })

  it('serializes user lists for published reports', () => {
    api.publishCheck(42, { statuses: [], review_lists: ['custom-id', 'further_checks'] })
    expect(mocks.apiInstance.post.mock.calls[0][1]).toMatchObject({ statuses: '', review_lists: 'custom-id,further_checks' })
  })
})

describe('batch api helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('posts JSON to the batch URL endpoint', () => {
    const payload = { urls: ['2401.12345'], use_llm: false }

    api.startBatchCheck(payload)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/check/batch', payload, {
      timeout: 0,
    })
  })

  it('posts multipart form data to the batch files endpoint', () => {
    const formData = new FormData()
    formData.append('batch_label', 'Batch files')

    api.startBatchFileCheck(formData)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/check/batch/files', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
    })
  })

  it('posts to the batch cancellation endpoint', () => {
    api.cancelBatch('batch-123')

    expect(mocks.apiInstance.post).toHaveBeenCalledWith('/cancel/batch/batch-123')
  })

  it('patches the batch label endpoint', () => {
    api.updateBatchLabel('batch-123', 'Renamed batch')

    expect(mocks.apiInstance.patch).toHaveBeenCalledWith('/batch/batch-123', {
      batch_label: 'Renamed batch',
    })
  })
})

describe('reference verification api helper', () => {
  beforeEach(() => {
    mocks.apiInstance.post.mockClear()
  })

  it('disables the generic client timeout when every database is requested', () => {
    const payload = { force_all_databases: true, expected_title: 'Slow catalogue result' }

    api.verifyReferenceInCheck(17, 'index:4', payload)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/history/17/references/index%3A4/verify',
      payload,
      { timeout: 0 },
    )
  })

  it('keeps the shared client timeout for an ordinary verification', () => {
    const payload = { expected_title: 'Ordinary result' }

    api.verifyReferenceInCheck(17, 'index:4', payload)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/history/17/references/index%3A4/verify',
      payload,
      undefined,
    )
  })

  it('queues ordinary re-verification with a short request for job acceptance', () => {
    const payload = { expected_title: 'Queued result' }

    api.startReferenceVerification(17, 'index:4', payload)

    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/history/17/references/index%3A4/verify-async', payload,
    )
  })

  it('opens and completes a local authenticated source session', () => {
    const url = 'https://search.ebscohost.com/login.aspx?direct=true&AN=979090'

    api.beginAuthenticatedSourceSession(url)
    expect(mocks.apiInstance.post).toHaveBeenLastCalledWith(
      '/authenticated-sources/session', { url }, { timeout: 60000 },
    )

    api.completeAuthenticatedSourceSession(url)
    expect(mocks.apiInstance.post).toHaveBeenLastCalledWith(
      '/authenticated-sources/session/complete', { url }, { timeout: 60000 },
    )
  })

  it('starts a streamed all-database reference search', () => {
    const payload = { google_books_api_key: 'browser-key' }
    api.startReferenceSearch(17, 'id:ref-1', payload)
    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/history/17/references/id%3Aref-1/search-all', payload,
    )
  })

  it('cancels a streamed reference search', () => {
    api.cancelReferenceSearch('operation-1')
    expect(mocks.apiInstance.post).toHaveBeenCalledWith(
      '/reference-searches/operation-1/cancel',
    )
  })
})
