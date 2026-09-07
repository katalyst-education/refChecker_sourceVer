import { useCallback, useEffect, useState } from 'react'
import { useConfigStore } from '../../stores/useConfigStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { useAuthStore } from '../../stores/useAuthStore'
import { useKeyStore } from '../../stores/useKeyStore'
import { openExternal, isTauri } from '../../utils/tauriBridge'
import * as api from '../../utils/api'

/**
 * First-launch guidance for the app.
 *
 * Shown above the input section when:
 *  - the user hasn't dismissed it in this browser, AND
 *  - they're missing an LLM config, or in single-user/local mode have no
 *    local database directory configured.
 *
 * Dismissed state persists per-browser via localStorage.
 */
const DISMISS_KEY = 'refchecker.onboarding.dismissed.v1'
const API_KEYS_CHANGED_EVENT = 'refchecker:api-keys-updated'

export default function OnboardingBanner({ onOpenSettings }) {
  const configs = useConfigStore(s => s.configs)
  const settings = useSettingsStore(s => s.settings)
  const multiuser = useAuthStore(s => s.multiuser)
  const browserKeys = useKeyStore(s => s.keys)
  const hasLocalKey = useKeyStore(s => s.hasKey)
  const [semanticScholarHasKey, setSemanticScholarHasKey] = useState(false)
  const [paperclipHasKey, setPaperclipHasKey] = useState(false)
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISS_KEY) === '1' } catch { return false }
  })

  // Refetch settings the first time we render so the offline-DB hint
  // doesn't show during the initial paint when settings are still null.
  const fetchSettings = useSettingsStore(s => s.fetchSettings)
  useEffect(() => { fetchSettings?.() }, [fetchSettings])

  const refreshBonusKeyStatuses = useCallback(() => {
    let cancelled = false
    api.getSemanticScholarKeyStatus()
      .then(res => { if (!cancelled) setSemanticScholarHasKey(!!res.data?.has_key) })
      .catch(() => { if (!cancelled) setSemanticScholarHasKey(false) })
    api.getPaperclipKeyStatus()
      .then(res => { if (!cancelled) setPaperclipHasKey(!!res.data?.has_key) })
      .catch(() => { if (!cancelled) setPaperclipHasKey(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const cancelRefresh = refreshBonusKeyStatuses()
    const handleApiKeysChanged = () => { refreshBonusKeyStatuses() }
    window.addEventListener(API_KEYS_CHANGED_EVENT, handleApiKeysChanged)
    return () => {
      cancelRefresh?.()
      window.removeEventListener(API_KEYS_CHANGED_EVENT, handleApiKeysChanged)
    }
  }, [refreshBonusKeyStatuses])

  if (dismissed) return null

  const hasLlm = Array.isArray(configs) && configs.some(c => c.has_key || c.id)
  const dbPathSet = !!settings?.db_path?.value
  const hasBrowserKey = (key) => Boolean(browserKeys?.[key]) || Boolean(hasLocalKey?.(key))
  const hasSemanticScholarKey = hasBrowserKey('semantic_scholar') || semanticScholarHasKey
  const hasPaperclipKey = hasBrowserKey('paperclip') || paperclipHasKey
  // Previously auto-hid the banner when LLM and DB were both
  // configured, but that also hid the OPTIONAL bonus steps (Semantic
  // Scholar key, Paperclip key) before the user ever saw them. Users
  // reported "the guide on first page isn't shown" once their
  // primary setup was done. Keep the banner visible until the user
  // explicitly clicks Dismiss; the steps themselves render a green
  // "configured" tag next to their checklist items so the banner
  // doesn't nag for things already done.
  // const allDone = hasLlm && (multiuser || dbPathSet)
  // if (allDone) return null
  void hasLlm; void dbPathSet

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, '1') } catch { /* storage may be blocked (private mode); dismissal is best-effort */ }
    setDismissed(true)
  }

  return (
    <div
      className="rounded-lg border p-4 mb-4"
      style={{
        borderColor: 'var(--color-info)',
        backgroundColor: 'var(--color-info-bg)',
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>
            Welcome to RefChecker
          </div>
          <p className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
            {multiuser
              ? 'Adding an LLM API key will make bibliography parsing more accurate. You can paste an ArXiv ID right now and it will still work using public APIs.'
              : 'Two quick things will make it noticeably faster and more accurate. Both are optional — you can paste an ArXiv ID right now and it will work out of the box using public APIs.'}
          </p>

          <ol className="space-y-3 text-sm" style={{ color: 'var(--color-text-primary)' }}>
            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: hasLlm ? 'var(--color-success, #22c55e)' : 'var(--color-accent, #3b82f6)',
                  color: 'white',
                }}
              >
                {hasLlm ? '✓' : '1'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  Add an LLM API key {hasLlm && <span style={{ color: 'var(--color-success, #22c55e)' }}>— configured</span>}
                </div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Used for accurate bibliography parsing.
                  {multiuser
                    ? ' OpenAI, Anthropic, Google, or Azure are supported.'
                    : ' OpenAI, Anthropic, Google, Azure, a local vLLM server, or LM Studio are supported.'}
                  Open <button type="button" onClick={() => onOpenSettings?.('LLM')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → LLM</button>{' '}
                  to paste your key — click <b>Test connection</b> first, then Save.
                </div>
              </div>
            </li>

            {!multiuser && (
              <li className="flex items-start gap-2">
                <span
                  className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                  style={{
                    width: 22, height: 22, flexShrink: 0,
                    backgroundColor: dbPathSet ? 'var(--color-success, #22c55e)' : 'var(--color-accent, #3b82f6)',
                    color: 'white',
                  }}
                >
                  {dbPathSet ? '✓' : '2'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium">
                    (Optional) Download the offline database pack {dbPathSet && <span style={{ color: 'var(--color-success, #22c55e)' }}>— directory configured</span>}
                  </div>
                  <div style={{ color: 'var(--color-text-secondary)' }}>
                    Speeds up verification and supports checks without an internet round-trip.
                    Open <button type="button" onClick={() => onOpenSettings?.('General')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → General</button>,
                    click <b>Use default</b> next to <i>Local Database Directory</i>, then{' '}
                    <b>Build local databases</b> below it.
                  </div>
                </div>
              </li>
            )}

            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: hasSemanticScholarKey ? 'var(--color-success, #22c55e)' : 'var(--color-text-muted, #94a3b8)',
                  color: 'white',
                }}
              >
                {hasSemanticScholarKey ? '✓' : 'i'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  Bonus: Semantic Scholar API key {hasSemanticScholarKey && <span style={{ color: 'var(--color-success, #22c55e)' }}>— configured</span>}
                </div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Reduces verification delays. Get a free key at{' '}
                  <button type="button" onClick={() => openExternal('https://www.semanticscholar.org/product/api')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>
                    semanticscholar.org/product/api
                  </button>
                  {' '}and add it under <button type="button" onClick={() => onOpenSettings?.('API Keys')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → API Keys</button>.
                </div>
              </div>
            </li>

            <li className="flex items-start gap-2">
              <span
                className="inline-flex items-center justify-center rounded-full text-xs font-semibold"
                style={{
                  width: 22, height: 22, flexShrink: 0,
                  backgroundColor: hasPaperclipKey ? 'var(--color-success, #22c55e)' : 'var(--color-text-muted, #94a3b8)',
                  color: 'white',
                }}
              >
                {hasPaperclipKey ? '✓' : 'i'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-medium">
                  Bonus: Paperclip key (biomedical / arXiv full-text) {hasPaperclipKey && <span style={{ color: 'var(--color-success, #22c55e)' }}>— configured</span>}
                </div>
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  Adds full-text sources for medical and life-sciences references. Get a key at{' '}
                  <button type="button" onClick={() => openExternal('https://paperclip.gxl.ai/keys')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>
                    paperclip.gxl.ai/keys
                  </button>
                  {' '}and add it under <button type="button" onClick={() => onOpenSettings?.('API Keys')} className="underline" style={{ color: 'var(--color-accent, #3b82f6)' }}>Settings → API Keys</button>.
                </div>
              </div>
            </li>
          </ol>
        </div>

        <button
          type="button"
          onClick={dismiss}
          className="text-xs px-2 py-1 rounded border"
          style={{
            backgroundColor: 'var(--color-bg-primary)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
          title="Hide this banner (re-show by clearing site data)"
        >
          Dismiss
        </button>
      </div>
      {isTauri() && (
        <div className="mt-3 text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          Tip: keys live in the encrypted local DB, never on a server. Updates are checked on every launch (Settings → App updates).
        </div>
      )}
    </div>
  )
}

