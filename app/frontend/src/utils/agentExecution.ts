import type { AgentAuthStatus, AgentAuthProvider } from '../types'

export function normalizeAgentExecutionProvider(value: unknown): AgentAuthProvider {
  return String(value || '').trim().toLowerCase() === 'claude' ? 'claude' : 'codex'
}

export function getAgentExecutionProviderLabel(value: unknown): string {
  return normalizeAgentExecutionProvider(value) === 'claude' ? 'Claude' : 'Codex'
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
  claudeAuthStatus: AgentAuthStatus | null | undefined
): AgentAuthStatus | null {
  return provider === 'claude' ? (claudeAuthStatus ?? null) : (codexAuthStatus ?? null)
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
  return 'Not configured'
}
