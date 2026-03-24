import type { AgentAuthStatus, AgentAuthProvider } from '../types'

export function normalizeAgentExecutionProvider(value: unknown): AgentAuthProvider {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'claude') return 'claude'
  if (normalized === 'opencode') return 'opencode'
  return 'codex'
}

export function getAgentExecutionProviderLabel(value: unknown): string {
  const provider = normalizeAgentExecutionProvider(value)
  if (provider === 'claude') return 'Claude'
  if (provider === 'opencode') return 'OpenCode'
  return 'Codex'
}

export function encodeAgentExecutionModel(provider: unknown, model: unknown): string {
  const normalizedModel = String(model || '').trim()
  if (!normalizedModel) return ''
  return `${normalizeAgentExecutionProvider(provider)}:${normalizedModel}`
}

export function parseAgentExecutionModel(value: unknown): { provider: AgentAuthProvider; model: string } | null {
  const raw = String(value || '').trim()
  if (!raw) return null
  for (const separator of [':', '/']) {
    const idx = raw.indexOf(separator)
    if (idx <= 0) continue
    const provider = raw.slice(0, idx)
    const model = raw.slice(idx + 1).trim()
    if (!model) continue
    const normalizedProvider = normalizeAgentExecutionProvider(provider)
    if (String(provider || '').trim().toLowerCase() !== normalizedProvider && String(provider || '').trim().toLowerCase() !== 'claude') {
      if (String(provider || '').trim().toLowerCase() !== 'codex') continue
    }
    return { provider: normalizedProvider, model }
  }
  const lowered = raw.toLowerCase()
  if (lowered === 'sonnet' || lowered === 'opus' || lowered === 'haiku' || lowered.startsWith('claude-')) {
    return { provider: 'claude', model: raw }
  }
  const providerPrefix = lowered.split('/')[0] || ''
  if (raw.includes('/') && [
    'opencode', 'openai', 'ollama', 'openrouter', 'anthropic', 'google', 'xai',
    'mistral', 'deepseek', 'cohere', 'groq', 'cerebras', 'minimax',
  ].includes(providerPrefix)) {
    return { provider: 'opencode', model: raw }
  }
  return { provider: 'codex', model: raw }
}

export function normalizeAgentExecutionModel(value: unknown): string {
  const parsed = parseAgentExecutionModel(value)
  if (!parsed) return ''
  return encodeAgentExecutionModel(parsed.provider, parsed.model)
}

export function formatAgentExecutionModelLabel(value: unknown): string {
  const parsed = parseAgentExecutionModel(value)
  if (!parsed) return 'System default'
  return `${getAgentExecutionProviderLabel(parsed.provider)} · ${parsed.model}`
}

export function resolveActiveAgentExecutionProvider(model: unknown, defaultModel?: unknown): AgentAuthProvider {
  const parsed = parseAgentExecutionModel(model) || parseAgentExecutionModel(defaultModel)
  return parsed?.provider || 'codex'
}

export function authStatusForProvider(
  provider: AgentAuthProvider,
  codexAuthStatus: AgentAuthStatus | null | undefined,
  claudeAuthStatus: AgentAuthStatus | null | undefined,
  opencodeAuthStatus: AgentAuthStatus | null | undefined = null,
): AgentAuthStatus | null {
  if (provider === 'claude') return claudeAuthStatus ?? null
  if (provider === 'opencode') {
    if (opencodeAuthStatus) return opencodeAuthStatus
    return {
      provider: 'opencode',
      provider_label: 'OpenCode',
      configured: true,
      effective_source: 'runtime_builtin',
      host_auth_available: false,
      override_available: false,
      selected_login_method: null,
      supported_login_methods: [],
      login_session: null,
    }
  }
  return codexAuthStatus ?? null
}

export function authSourceLabel(
  provider: AgentAuthProvider,
  source: AgentAuthStatus['effective_source'] | string | null | undefined,
  targetUsername?: string | null
): string {
  const normalized = String(source || '').trim().toLowerCase()
  if (normalized === 'system_override') {
    return `Connected for ${String(targetUsername || `${provider}-bot`).trim() || `${provider}-bot`}`
  }
  if (normalized === 'host_mount') return 'Using host-mounted auth'
  if (normalized === 'runtime_builtin') return 'Built-in runtime access'
  return 'Not configured'
}
