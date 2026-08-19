import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

// API layer — addReferenceToCheck is the only call the add form makes (plus a
// best-effort verify which we no-op). The real useReferenceActions hook runs.
const addReferenceToCheck = vi.hoisted(() => vi.fn())
const verifyReferenceInCheck = vi.hoisted(() => vi.fn())
const decideReferenceWarning = vi.hoisted(() => vi.fn())
vi.mock('../../utils/api', () => ({
  addReferenceToCheck,
  verifyReferenceInCheck,
  decideReferenceWarning,
  removeReferenceFromCheck: vi.fn(),
  suggestAlternativeReference: vi.fn(),
}))

// Zustand stores — each hook applies the selector to a static mock state and
// exposes a matching getState(). selectedCheckId is truthy so the add form is
// enabled and handleAddRef proceeds to the API call. Built inside vi.hoisted so
// the helper is available to the hoisted vi.mock factories below.
const { historyState, checkState, styleState, mkStore } = vi.hoisted(() => {
  const mkStore = (state) => {
    const hook = (selector) => (selector ? selector(state) : state)
    hook.getState = () => state
    return hook
  }
  return {
    historyState: {
      selectedCheckId: 5,
      selectedCheck: null,
      selectCheck: vi.fn().mockResolvedValue(undefined),
      updateHistoryReference: vi.fn(),
      optimisticApplyCorrection: vi.fn(),
      optimisticRevertCorrection: vi.fn(),
      optimisticRemoveReference: vi.fn(),
    },
    checkState: {
      statusFilter: [],
      references: [],
      updateReference: vi.fn(),
      removeReference: vi.fn(),
      restoreReference: vi.fn(),
      applyCorrectionInStore: vi.fn(),
      revertCorrectionInStore: vi.fn(),
    },
    styleState: { format: 'apa', setFormat: vi.fn(), styleOptions: {}, setStyleOptions: vi.fn() },
    mkStore,
  }
})
vi.mock('../../stores/useHistoryStore', () => ({ useHistoryStore: mkStore(historyState) }))
vi.mock('../../stores/useCheckStore', () => ({ useCheckStore: mkStore(checkState) }))
vi.mock('../../stores/useStyleStore', () => ({ useStyleStore: mkStore(styleState) }))

import CorrectionsView from './CorrectionsView'

// One flagged reference so `categorized` is non-empty and the toolbar (which
// hosts the "+ Add reference" toggle) renders instead of the empty state.
const FLAGGED_REFS = [{
  id: 'ref-1', index: 1, title: 'A Flagged Reference', status: 'error',
  errors: [{ error_type: 'doi', error_details: 'DOI mismatch' }],
  warnings: [], suggestions: [],
  corrected_reference: { doi: '10.1000/corrected' },
}]

let alertSpy
beforeEach(() => {
  addReferenceToCheck.mockReset()
  verifyReferenceInCheck.mockReset().mockResolvedValue({ data: {} })
  decideReferenceWarning.mockReset().mockResolvedValue({ data: {} })
  checkState.references = []
  checkState.updateReference.mockReset()
  historyState.selectedCheck = null
  historyState.updateHistoryReference.mockReset()
  alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
})
afterEach(() => { alertSpy.mockRestore() })

const openAddForm = async () => {
  // The "+ Add reference" toggle button reveals the manual-add form.
  fireEvent.click(screen.getByRole('button', { name: /\+ add reference/i }))
  return screen.findByPlaceholderText('Title')
}

describe('CorrectionsView — R17 add-form 409 duplicate surfacing', () => {
  it('alerts "already reference [N]" when the backend rejects the manual add with 409', async () => {
    const err = new Error('Request failed with status code 409')
    err.response = { status: 409, data: { duplicate: true, existing_index: 4, message: 'Already reference [4] in this check.' } }
    addReferenceToCheck.mockRejectedValue(err)

    render(<CorrectionsView references={FLAGGED_REFS} isCheckComplete={true} />)
    const titleInput = await openAddForm()
    fireEvent.change(titleInput, { target: { value: 'Attention Is All You Need' } })
    fireEvent.click(screen.getByText('Save reference'))

    await waitFor(() => expect(alertSpy).toHaveBeenCalled())
    expect(alertSpy.mock.calls[0][0]).toMatch(/already reference \[4\]/i)
    // The friendly duplicate message wins over a generic "Add failed".
    expect(alertSpy.mock.calls[0][0]).not.toMatch(/add failed/i)
  })

  it('a successful add does not alert (no false duplicate path)', async () => {
    addReferenceToCheck.mockResolvedValue({ data: { reference: { id: 'manual-1' }, inserted_index: 2 } })

    render(<CorrectionsView references={FLAGGED_REFS} isCheckComplete={true} />)
    const titleInput = await openAddForm()
    fireEvent.change(titleInput, { target: { value: 'A Genuinely New Work' } })
    fireEvent.click(screen.getByText('Save reference'))

    await waitFor(() => expect(addReferenceToCheck).toHaveBeenCalled())
    expect(alertSpy).not.toHaveBeenCalled()
  })
})

describe('CorrectionsView — speculative match confirmation', () => {
  const candidateRef = [{
    id: 'candidate-1', index: 1, title: 'Original title', status: 'warning',
    errors: [], suggestions: [],
    warnings: [{
      error_type: 'possible_alternative',
      error_details: 'Title and authors could not be found. Possibly this title and authors were meant.',
      requires_user_confirmation: true,
    }],
    corrected_reference: { title: 'Possible intended title', authors: [{ name: 'Same Author' }] },
  }]

  it('shows the candidate and makes the replace-versus-retain choice explicit', () => {
    render(<CorrectionsView references={candidateRef} isCheckComplete={true} />)

    expect(document.body.textContent).toContain('Possible intended title')
    expect(document.body.textContent).toContain('Original title')
    expect(screen.getByRole('button', { name: 'Use matched paper' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep cited reference' })).toBeInTheDocument()
  })

  it('keeps the cited metadata when the possible match is rejected', async () => {
    render(<CorrectionsView references={candidateRef} isCheckComplete={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Keep cited reference' }))

    await waitFor(() => expect(decideReferenceWarning).toHaveBeenCalledWith(
      5,
      'id:candidate-1',
      expect.objectContaining({ decision: 'dismissed' }),
    ))
    expect(verifyReferenceInCheck).not.toHaveBeenCalled()
  })

  it('does not accept a possible match through the bulk apply action', () => {
    render(<CorrectionsView references={candidateRef} isCheckComplete={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Apply all visible' }))

    expect(verifyReferenceInCheck).not.toHaveBeenCalled()
  })

  it('updates the clicked id rather than a neighbouring row with the same numeric index', async () => {
    const ref = { ...candidateRef[0], id: 14, index: 15 }
    checkState.references = [
      { index: 14, title: 'Neighbouring reference' },
      ref,
    ]
    decideReferenceWarning.mockResolvedValue({
      data: { reference: { ...ref, status: 'unverified', warnings: [], match_decision: 'kept_cited' } },
    })
    render(<CorrectionsView references={[ref]} isCheckComplete={true} />)

    fireEvent.click(screen.getByRole('button', { name: 'Keep cited reference' }))

    await waitFor(() => expect(checkState.updateReference).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ match_decision: 'kept_cited' }),
    ))
  })
})

describe('CorrectionsView — unverified references', () => {
  it('omits a not-found reference whose suggested correction would be unchanged', () => {
    const notFoundRef = {
      id: 'gorleben',
      index: 2,
      title: 'Gorleben',
      authors: ['Michael Bogacki'],
      year: 2016,
      cited_url: 'http://www.gns.de/gorleben',
      status: 'unverified',
      errors: [{ error_type: 'unverified', error_details: 'Web page not found (404)' }],
      warnings: [],
      suggestions: [],
      corrected_reference: null,
    }

    render(<CorrectionsView references={[notFoundRef]} isCheckComplete={true} />)

    expect(screen.getByText('No actionable corrections.')).toBeInTheDocument()
    expect(screen.queryByText('Gorleben')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply fix' })).not.toBeInTheDocument()
  })

  it('omits warning rows whose suggested correction is identical to the citation', () => {
    const warningRefs = [
      {
        id: 'energiewende', index: 12, title: 'Vorbild Deutsche Energiewende',
        authors: ['Forsa'], year: 2016, status: 'warning',
        cited_url: 'http://www.kernenergie.de/kernenergie-wAssets/docs/themen/2013-05-forsa-umfrage-kernkraft.pdf',
        errors: [],
        warnings: [{ error_type: 'url', error_details: 'Web page not found (404)' }],
        suggestions: [], corrected_reference: null,
      },
      {
        id: 'direkt-strom', index: 31, title: 'Direkt Strom',
        authors: ['Mirko Ravens'], year: 2016, status: 'warning',
        cited_url: 'https://www.eon.de/pk/de/strom/optimalstrom/optimalstrom-oeko.html',
        errors: [],
        warnings: [{ error_type: 'url', error_details: 'Source could not be confirmed' }],
        suggestions: [], corrected_reference: null,
      },
    ]

    render(<CorrectionsView references={warningRefs} isCheckComplete={true} />)

    expect(screen.getByText('No actionable corrections.')).toBeInTheDocument()
    expect(screen.queryByText(/Vorbild Deutsche Energiewende/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Direkt Strom/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply fix' })).not.toBeInTheDocument()
  })

  it('continues to show genuine correction errors beside an unverified result', () => {
    const notFoundRef = {
      id: 'missing', index: 2, title: 'Missing web page', status: 'unverified',
      errors: [{ error_type: 'unverified', error_details: 'Web page not found (404)' }],
      warnings: [], suggestions: [], corrected_reference: null,
    }
    const actionableRef = {
      id: 'wrong-year', index: 3, title: 'Actionable reference', status: 'error',
      errors: [{ error_type: 'year', error_details: 'Publication year differs' }],
      warnings: [], suggestions: [], corrected_reference: { year: 2022 },
    }

    render(<CorrectionsView references={[notFoundRef, actionableRef]} isCheckComplete={true} />)

    expect(screen.queryByText('Missing web page')).not.toBeInTheDocument()
    expect(screen.getByText(/Actionable reference/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply fix' })).toBeInTheDocument()
  })
})
