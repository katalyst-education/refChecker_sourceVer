import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  addConfig: vi.fn(),
  updateConfig: vi.fn(),
  multiuser: false,
  validateLLMConfig: vi.fn(),
  listLLMModels: vi.fn(),
  configs: [],
  hasKey: vi.fn(),
  getKey: vi.fn(),
}))

vi.mock('../../stores/useConfigStore', () => ({
  useConfigStore: () => ({
    addConfig: mocks.addConfig,
    updateConfig: mocks.updateConfig,
    configs: mocks.configs,
    selectConfig: vi.fn(),
    selectHallucinationConfig: vi.fn(),
  }),
}))

vi.mock('../../stores/useAuthStore', () => ({
  useAuthStore: (selector) => selector({ multiuser: mocks.multiuser }),
}))

vi.mock('../../stores/useKeyStore', () => {
  const useKeyStore = () => ({})
  useKeyStore.getState = () => ({ setKey: vi.fn(), getKey: mocks.getKey, hasKey: mocks.hasKey })
  return { useKeyStore }
})

vi.mock('../../utils/api', () => ({
  validateLLMConfig: mocks.validateLLMConfig,
  listLLMModels: mocks.listLLMModels,
}))

vi.mock('../../utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

import LLMConfigModal from './LLMConfigModal'

describe('LLMConfigModal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.multiuser = false
    mocks.configs = []
    mocks.hasKey.mockReturnValue(false)
    mocks.getKey.mockReturnValue(null)
    mocks.validateLLMConfig.mockResolvedValue({ data: { valid: true } })
    mocks.listLLMModels.mockResolvedValue({
      data: { models: [], model_details: {}, source: 'live' },
    })
    mocks.addConfig.mockResolvedValue({ id: 9, provider: 'anthropic', model: 'claude-sonnet-4-6' })
  })

  it('shows single-user help text when not in multiuser mode', () => {
    mocks.multiuser = false
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    expect(screen.getByText('Stored encrypted in the local RefChecker database and never shown again.')).toBeTruthy()
    expect(screen.queryByText(/never saved on the server/)).toBeNull()
  })

  it('shows browser-only storage help text in multiuser mode', () => {
    mocks.multiuser = true
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    expect(screen.getByText('Retrieved from this encrypted browser cache for the local web interface and not stored in the local database or on the server.')).toBeTruthy()
    expect(screen.queryByText('Stored encrypted in the local RefChecker database and never shown again.')).toBeNull()
  })

  it('creates hallucination configs without selecting them for extraction', async () => {
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} selectionMode="hallucination" />)

    fireEvent.change(screen.getByLabelText(/API Key/i), {
      target: { value: 'test-key' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add Configuration/i }))

    await waitFor(() => {
      expect(mocks.addConfig).toHaveBeenCalledWith(
        expect.objectContaining({ provider: 'anthropic' }),
        { selectFor: 'hallucination' },
      )
    })
  })

  it('allows server environment keys to satisfy validation in multiuser mode', async () => {
    mocks.multiuser = true
    mocks.configs = [{
      id: 'env:anthropic',
      provider: 'anthropic',
      model: 'claude-sonnet-4-6',
      has_key: true,
      key_source: 'environment',
      env_key_available: true,
    }]

    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)
    expect(screen.getByText('Using the server environment key by default. Enter a key here to override it for this browser.')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Test connection/i }))

    await waitFor(() => {
      expect(mocks.validateLLMConfig).toHaveBeenCalledWith(expect.objectContaining({
        provider: 'anthropic',
        api_key: undefined,
      }))
    })
  })

  it('saves LM Studio with the selected reasoning effort', async () => {
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'lmstudio' },
    })
    fireEvent.change(screen.getByLabelText('Model'), {
      target: { value: 'qwen/qwen3.6-35b-a3b' },
    })
    fireEvent.change(screen.getByLabelText('Reasoning effort'), {
      target: { value: 'low' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add Configuration/i }))

    await waitFor(() => {
      expect(mocks.validateLLMConfig).toHaveBeenCalledWith(expect.objectContaining({
        provider: 'lmstudio',
        model: 'qwen/qwen3.6-35b-a3b',
        endpoint: 'http://localhost:1234',
        reasoning_effort: 'low',
        max_tokens: 4000,
        timeout_seconds: 300,
      }))
      expect(mocks.addConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'lmstudio',
          reasoning_effort: 'low',
          max_tokens: 4000,
          context_length: null,
          timeout_seconds: 300,
        }),
        { selectFor: 'extraction' },
      )
    })
  })

  it('reads LM Studio context metadata and estimates reference-page input', async () => {
    mocks.listLLMModels.mockResolvedValue({
      data: {
        models: ['qwen/qwen3.6-35b-a3b'],
        model_details: {
          'qwen/qwen3.6-35b-a3b': {
            loaded: true,
            context_length: 8192,
            max_context_length: 262144,
          },
        },
        source: 'live',
      },
    })
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'lmstudio' },
    })
    fireEvent.change(screen.getByLabelText('Model'), {
      target: { value: 'qwen/qwen3.6-35b-a3b' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Fetch' }))

    await waitFor(() => {
      expect(screen.getByLabelText('Loaded model context').value).toBe('8192')
      expect(screen.getByText(/Safe bibliography input per extraction call/).textContent)
        .toMatch(/3[,.]892 tokens/)
      expect(screen.getByText(/Safe bibliography input per extraction call/).textContent)
        .toContain('4–6 reference pages')
    })

    fireEvent.change(screen.getByLabelText('Loaded model context'), {
      target: { value: '16384' },
    })
    fireEvent.change(screen.getByLabelText('Maximum output tokens'), {
      target: { value: '6000' },
    })
    fireEvent.change(screen.getByLabelText('Generation timeout (seconds)'), {
      target: { value: '21600' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add Configuration/i }))

    await waitFor(() => {
      expect(mocks.addConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'lmstudio',
          max_tokens: 6000,
          context_length: 16384,
          timeout_seconds: 21600,
        }),
        { selectFor: 'extraction' },
      )
    })
  })

  it('hides local providers in multiuser mode', () => {
    mocks.multiuser = true
    render(<LLMConfigModal isOpen={true} onClose={vi.fn()} />)

    expect(screen.queryByRole('option', { name: 'LM Studio (Local)' })).toBeNull()
    expect(screen.queryByRole('option', { name: 'vLLM (Local)' })).toBeNull()
  })
})
