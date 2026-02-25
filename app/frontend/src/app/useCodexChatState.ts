import React from 'react'
import type { AgentChatUsage, AttachmentRef, ChatMcpServer } from '../types'

export type CodexResumeState = {
  attempted: boolean
  succeeded: boolean
  fallbackUsed: boolean
}

export type ChatRole = 'user' | 'assistant'
export type ChatTurn = {
  id: string
  role: ChatRole
  content: string
  createdAt: number
  attachmentRefs: AttachmentRef[]
}

export type ChatSession = {
  id: string
  title: string
  projectId: string
  turns: ChatTurn[]
  usage: AgentChatUsage | null
  mcpServers: ChatMcpServer[]
  sessionAttachmentRefs: AttachmentRef[]
  codexSessionId: string | null
  codexResumeState: CodexResumeState | null
  createdAt: number
  updatedAt: number
  lastTaskEventAt: number | null
}

export type ChatSessionServerSnapshot = {
  id: string
  title?: string
  projectId?: string
  turns?: ChatTurn[]
  usage?: AgentChatUsage | null
  mcpServers?: ChatMcpServer[]
  sessionAttachmentRefs?: AttachmentRef[]
  codexSessionId?: string | null
  codexResumeState?: CodexResumeState | null
  createdAt?: number
  updatedAt?: number
  lastTaskEventAt?: number | null
}

type PersistedCodexChatState = {
  version: 1
  activeSessionId: string
  sessions: ChatSession[]
}

const STORAGE_KEY_PREFIX = 'codex_chat_state_v1'
const MAX_SESSIONS = 20
const MAX_TURNS_PER_SESSION = 240
const DEFAULT_SESSION_TITLE_PREFIX = 'Session'

function resolveStorageKey(userId: string | null | undefined): string {
  const normalized = String(userId || '').trim()
  if (!normalized) return STORAGE_KEY_PREFIX
  return `${STORAGE_KEY_PREFIX}:${normalized}`
}

function makeId(prefix: string): string {
  return globalThis.crypto?.randomUUID?.() ?? `${prefix}-${Date.now()}-${Math.round(Math.random() * 1_000_000)}`
}

function normalizeBool(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') {
    if (value === 1) return true
    if (value === 0) return false
    return null
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on') return true
    if (normalized === 'false' || normalized === '0' || normalized === 'no' || normalized === 'off') return false
  }
  return null
}

function normalizeResumeState(value: unknown): CodexResumeState | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  const attempted = normalizeBool(
    payload.attempted
    ?? payload.resume_attempted
    ?? payload.codex_resume_attempted
  )
  const succeeded = normalizeBool(
    payload.succeeded
    ?? payload.resume_succeeded
    ?? payload.codex_resume_succeeded
  )
  const fallbackUsed = normalizeBool(
    payload.fallbackUsed
    ?? payload.fallback_used
    ?? payload.resume_fallback_used
    ?? payload.codex_resume_fallback_used
  )
  if (attempted === null && succeeded === null && fallbackUsed === null) return null
  return {
    attempted: Boolean(attempted),
    succeeded: Boolean(succeeded),
    fallbackUsed: Boolean(fallbackUsed),
  }
}

function normalizeUsage(value: unknown): AgentChatUsage | null {
  if (!value || typeof value !== 'object') return null
  const usage = value as Record<string, unknown>
  const input = Number(usage.input_tokens)
  const output = Number(usage.output_tokens)
  if (!Number.isFinite(input) || input < 0 || !Number.isFinite(output) || output < 0) return null
  const cached = Number(usage.cached_input_tokens)
  const contextLimit = Number(usage.context_limit_tokens)
  const normalized: AgentChatUsage = {
    input_tokens: Math.floor(input),
    output_tokens: Math.floor(output),
  }
  if (Number.isFinite(cached) && cached >= 0) normalized.cached_input_tokens = Math.floor(cached)
  if (Number.isFinite(contextLimit) && contextLimit > 0) normalized.context_limit_tokens = Math.floor(contextLimit)
  return normalized
}

function normalizeMcpServers(value: unknown): ChatMcpServer[] {
  if (!Array.isArray(value)) return []
  const out: ChatMcpServer[] = []
  const seen = new Set<string>()
  for (const item of value) {
    const normalized = String(item || '').trim()
    if (!normalized) continue
    const key = normalized.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(normalized)
  }
  return out
}

function normalizeAttachmentRefs(value: unknown): AttachmentRef[] {
  if (!Array.isArray(value)) return []
  const out: AttachmentRef[] = []
  const seen = new Set<string>()
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const attachment = item as Record<string, unknown>
    const path = typeof attachment.path === 'string' ? attachment.path.trim() : ''
    if (!path) continue
    const dedupeKey = path.toLowerCase()
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)
    const normalized: AttachmentRef = { path }
    const name = typeof attachment.name === 'string' ? attachment.name.trim() : ''
    const mimeType = typeof attachment.mime_type === 'string' ? attachment.mime_type.trim() : ''
    const sizeBytes = Number(attachment.size_bytes)
    if (name) normalized.name = name
    if (mimeType) normalized.mime_type = mimeType
    if (Number.isFinite(sizeBytes) && sizeBytes >= 0) normalized.size_bytes = Math.floor(sizeBytes)
    out.push(normalized)
  }
  return out
}

function normalizeTurns(value: unknown): ChatTurn[] {
  if (!Array.isArray(value)) return []
  const out: ChatTurn[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const turn = item as Record<string, unknown>
    const role = turn.role === 'assistant' ? 'assistant' : turn.role === 'user' ? 'user' : null
    if (!role) continue
    const content = typeof turn.content === 'string' ? turn.content : ''
    const createdAtRaw = Number(turn.createdAt)
    out.push({
      id: typeof turn.id === 'string' && turn.id.trim() ? turn.id : makeId('turn'),
      role,
      content,
      createdAt: Number.isFinite(createdAtRaw) && createdAtRaw > 0 ? Math.floor(createdAtRaw) : Date.now(),
      attachmentRefs: normalizeAttachmentRefs(turn.attachmentRefs ?? turn.attachment_refs),
    })
  }
  return out.slice(-MAX_TURNS_PER_SESSION)
}

function summarizeSessionTitleFromTurns(turns: ChatTurn[]): string | null {
  const firstUserTurn = turns.find((turn) => turn.role === 'user' && turn.content.trim())
  if (!firstUserTurn) return null
  const compact = firstUserTurn.content.replace(/\s+/g, ' ').trim()
  if (!compact) return null
  return compact.length > 48 ? `${compact.slice(0, 45)}...` : compact
}

function deriveSessionTitle(currentTitle: string, turns: ChatTurn[]): string {
  if (!/^Session \d+$/i.test(currentTitle)) return currentTitle
  return summarizeSessionTitleFromTurns(turns) ?? currentTitle
}

function nextSessionTitle(sessions: ChatSession[]): string {
  let max = 0
  for (const session of sessions) {
    const match = session.title.match(/^Session (\d+)$/i)
    if (!match) continue
    const num = Number(match[1])
    if (Number.isFinite(num) && num > max) max = num
  }
  const next = max > 0 ? max + 1 : sessions.length + 1
  return `${DEFAULT_SESSION_TITLE_PREFIX} ${next}`
}

function createSession(title: string, projectId = ''): ChatSession {
  const now = Date.now()
  return {
    id: makeId('chat'),
    title: title.trim() || `${DEFAULT_SESSION_TITLE_PREFIX} 1`,
    projectId,
    turns: [],
    usage: null,
    mcpServers: [],
    sessionAttachmentRefs: [],
    codexSessionId: null,
    codexResumeState: null,
    createdAt: now,
    updatedAt: now,
    lastTaskEventAt: null,
  }
}

function latestSessionByProject(sessions: ChatSession[], projectId: string): ChatSession | null {
  let latest: ChatSession | null = null
  for (const session of sessions) {
    if (session.projectId !== projectId) continue
    if (!latest || session.updatedAt > latest.updatedAt) latest = session
  }
  return latest
}

function normalizeSession(value: unknown): ChatSession | null {
  if (!value || typeof value !== 'object') return null
  const session = value as Record<string, unknown>
  const id = typeof session.id === 'string' && session.id.trim() ? session.id : makeId('chat')
  const turns = normalizeTurns(session.turns)
  const createdAtRaw = Number(session.createdAt)
  const updatedAtRaw = Number(session.updatedAt)
  const createdAt = Number.isFinite(createdAtRaw) && createdAtRaw > 0 ? Math.floor(createdAtRaw) : Date.now()
  const updatedAt = Number.isFinite(updatedAtRaw) && updatedAtRaw > 0 ? Math.floor(updatedAtRaw) : createdAt
  const lastTaskEventAtRaw = Number(session.lastTaskEventAt)
  const codexSessionId =
    typeof session.codexSessionId === 'string' && session.codexSessionId.trim()
      ? session.codexSessionId.trim()
      : null
  const codexResumeState = normalizeResumeState(session.codexResumeState ?? session.codex_resume_state ?? session.usage)
  return {
    id,
    title: typeof session.title === 'string' && session.title.trim()
      ? session.title.trim()
      : `${DEFAULT_SESSION_TITLE_PREFIX} 1`,
    projectId: typeof session.projectId === 'string' ? session.projectId : '',
    turns,
    usage: normalizeUsage(session.usage),
    mcpServers: normalizeMcpServers(session.mcpServers),
    sessionAttachmentRefs: normalizeAttachmentRefs(session.sessionAttachmentRefs ?? session.session_attachment_refs),
    codexSessionId,
    codexResumeState,
    createdAt,
    updatedAt,
    lastTaskEventAt:
      Number.isFinite(lastTaskEventAtRaw) && lastTaskEventAtRaw > 0 ? Math.floor(lastTaskEventAtRaw) : null,
  }
}

function normalizeTimestampMs(value: unknown, fallback: number): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return fallback
  return Math.floor(numeric)
}

function createInitialState(): PersistedCodexChatState {
  const firstSession = createSession(`${DEFAULT_SESSION_TITLE_PREFIX} 1`)
  return {
    version: 1,
    activeSessionId: firstSession.id,
    sessions: [firstSession],
  }
}

function loadPersistedState(storageKey: string): PersistedCodexChatState | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return null
    const payload = parsed as Record<string, unknown>
    const sessionsRaw = Array.isArray(payload.sessions) ? payload.sessions : []
    const sessions = sessionsRaw.map(normalizeSession).filter((item): item is ChatSession => Boolean(item))
    if (!sessions.length) return null
    const trimmedSessions = sessions.slice(-MAX_SESSIONS)
    const lastSession = trimmedSessions[trimmedSessions.length - 1]
    if (!lastSession) return null
    const rawActiveId = typeof payload.activeSessionId === 'string' ? payload.activeSessionId : ''
    const activeSessionId = trimmedSessions.some((session) => session.id === rawActiveId)
      ? rawActiveId
      : lastSession.id
    return {
      version: 1,
      activeSessionId,
      sessions: trimmedSessions,
    }
  } catch {
    return null
  }
}

export function useCodexChatState(storageUserId?: string | null) {
  const storageKey = React.useMemo(() => resolveStorageKey(storageUserId), [storageUserId])
  const initialState = React.useMemo<PersistedCodexChatState>(() => {
    const restored = loadPersistedState(storageKey)
    if (restored) return restored
    return createInitialState()
  }, [storageKey])

  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatInstruction, setCodexChatInstruction] = React.useState('')
  const [codexChatSessions, setCodexChatSessions] = React.useState<ChatSession[]>(initialState.sessions)
  const [codexChatActiveSessionId, setCodexChatActiveSessionId] = React.useState<string>(initialState.activeSessionId)
  const [isCodexChatRunning, setIsCodexChatRunning] = React.useState(false)
  const [codexChatRunStartedAt, setCodexChatRunStartedAt] = React.useState<number | null>(null)
  const [codexChatElapsedSeconds, setCodexChatElapsedSeconds] = React.useState(0)

  React.useEffect(() => {
    const restored = loadPersistedState(storageKey)
    if (restored) {
      setCodexChatSessions(restored.sessions)
      setCodexChatActiveSessionId(restored.activeSessionId)
    } else {
      const fallback = createInitialState()
      setCodexChatSessions(fallback.sessions)
      setCodexChatActiveSessionId(fallback.activeSessionId)
    }
    setCodexChatInstruction('')
    setIsCodexChatRunning(false)
    setCodexChatRunStartedAt(null)
    setCodexChatElapsedSeconds(0)
  }, [storageKey])

  React.useEffect(() => {
    if (codexChatSessions.length > 0) return
    const session = createSession(`${DEFAULT_SESSION_TITLE_PREFIX} 1`)
    setCodexChatSessions([session])
    setCodexChatActiveSessionId(session.id)
  }, [codexChatSessions])

  React.useEffect(() => {
    if (!codexChatSessions.length) return
    if (codexChatSessions.some((session) => session.id === codexChatActiveSessionId)) return
    const lastSession = codexChatSessions[codexChatSessions.length - 1]
    if (!lastSession) return
    setCodexChatActiveSessionId(lastSession.id)
  }, [codexChatActiveSessionId, codexChatSessions])

  React.useEffect(() => {
    if (typeof window === 'undefined' || !codexChatSessions.length) return
    const lastSession = codexChatSessions[codexChatSessions.length - 1]
    if (!lastSession) return
    const activeId = codexChatSessions.some((session) => session.id === codexChatActiveSessionId)
      ? codexChatActiveSessionId
      : lastSession.id
    const payload: PersistedCodexChatState = {
      version: 1,
      activeSessionId: activeId,
      sessions: codexChatSessions,
    }
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(payload))
    } catch {
      // Ignore quota/storage failures; chat continues in-memory.
    }
  }, [codexChatActiveSessionId, codexChatSessions, storageKey])

  const patchSession = React.useCallback((sessionId: string, mutate: (session: ChatSession) => ChatSession) => {
    setCodexChatSessions((prev) => {
      let changed = false
      const next = prev.map((session) => {
        if (session.id !== sessionId) return session
        const mutated = mutate(session)
        if (mutated !== session) changed = true
        return mutated
      })
      return changed ? next : prev
    })
  }, [])

  const setCodexChatTurnsForSession = React.useCallback((
    sessionId: string,
    value: React.SetStateAction<ChatTurn[]>
  ) => {
    patchSession(sessionId, (session) => {
      const nextTurnsRaw = typeof value === 'function'
        ? (value as (prev: ChatTurn[]) => ChatTurn[])(session.turns)
        : value
      const nextTurns = normalizeTurns(nextTurnsRaw)
      const nextTitle = deriveSessionTitle(session.title, nextTurns)
      return {
        ...session,
        title: nextTitle,
        turns: nextTurns,
        updatedAt: Date.now(),
      }
    })
  }, [patchSession])

  const setCodexChatUsageForSession = React.useCallback((sessionId: string, usage: AgentChatUsage | null) => {
    patchSession(sessionId, (session) => {
      const normalizedUsage = normalizeUsage(usage)
      const inferredResumeState = normalizeResumeState(usage)
      return {
        ...session,
        usage: normalizedUsage,
        codexResumeState: inferredResumeState ?? session.codexResumeState,
        updatedAt: Date.now(),
      }
    })
  }, [patchSession])

  const setCodexChatMcpServersForSession = React.useCallback((sessionId: string, servers: ChatMcpServer[]) => {
    patchSession(sessionId, (session) => ({
      ...session,
      mcpServers: normalizeMcpServers(servers),
      updatedAt: Date.now(),
    }))
  }, [patchSession])

  const setCodexChatSessionAttachmentRefsForSession = React.useCallback((
    sessionId: string,
    refs: AttachmentRef[]
  ) => {
    patchSession(sessionId, (session) => ({
      ...session,
      sessionAttachmentRefs: normalizeAttachmentRefs(refs),
      updatedAt: Date.now(),
    }))
  }, [patchSession])

  const setCodexChatCodexSessionIdForSession = React.useCallback((sessionId: string, codexSessionId: string | null) => {
    patchSession(sessionId, (session) => ({
      ...session,
      codexSessionId: codexSessionId && codexSessionId.trim() ? codexSessionId.trim() : null,
      updatedAt: Date.now(),
    }))
  }, [patchSession])

  const setCodexChatResumeStateForSession = React.useCallback((sessionId: string, resumeState: CodexResumeState | null) => {
    patchSession(sessionId, (session) => ({
      ...session,
      codexResumeState: normalizeResumeState(resumeState) ?? null,
      updatedAt: Date.now(),
    }))
  }, [patchSession])

  const setCodexChatLastTaskEventAtForSession = React.useCallback((sessionId: string, at: number | null) => {
    patchSession(sessionId, (session) => ({
      ...session,
      lastTaskEventAt: at,
      updatedAt: Date.now(),
    }))
  }, [patchSession])

  const mergeCodexChatSessionsFromServer = React.useCallback((
    incomingSnapshots: ChatSessionServerSnapshot[],
    opts?: { activeSessionId?: string | null }
  ) => {
    let nextActiveSessionId = ''
    setCodexChatSessions((prev) => {
      const byId = new Map<string, ChatSession>(prev.map((session) => [session.id, session]))
      const now = Date.now()

      for (const snapshot of incomingSnapshots) {
        const id = String(snapshot?.id || '').trim()
        if (!id) continue
        const existing = byId.get(id)
        const createdAt = normalizeTimestampMs(snapshot.createdAt, existing?.createdAt ?? now)
        const updatedAt = normalizeTimestampMs(snapshot.updatedAt, existing?.updatedAt ?? createdAt)
        const turns = normalizeTurns(snapshot.turns ?? existing?.turns ?? [])
        const lastTaskEventAt = snapshot.lastTaskEventAt === null
          ? null
          : snapshot.lastTaskEventAt === undefined
            ? (existing?.lastTaskEventAt ?? null)
            : normalizeTimestampMs(snapshot.lastTaskEventAt, existing?.lastTaskEventAt ?? now)
        const resumeState = normalizeResumeState(
          snapshot.codexResumeState
          ?? snapshot.usage
          ?? existing?.codexResumeState
        )
        byId.set(id, {
          id,
          title: String(snapshot.title || existing?.title || `${DEFAULT_SESSION_TITLE_PREFIX} 1`).trim()
            || `${DEFAULT_SESSION_TITLE_PREFIX} 1`,
          projectId: String(snapshot.projectId ?? existing?.projectId ?? ''),
          turns,
          usage: normalizeUsage(snapshot.usage ?? existing?.usage ?? null),
          mcpServers: normalizeMcpServers(snapshot.mcpServers ?? existing?.mcpServers ?? []),
          sessionAttachmentRefs: normalizeAttachmentRefs(
            snapshot.sessionAttachmentRefs
            ?? existing?.sessionAttachmentRefs
            ?? []
          ),
          codexSessionId:
            snapshot.codexSessionId !== undefined
              ? (snapshot.codexSessionId && String(snapshot.codexSessionId).trim()
                ? String(snapshot.codexSessionId).trim()
                : null)
              : (existing?.codexSessionId ?? null),
          codexResumeState: resumeState,
          createdAt,
          updatedAt,
          lastTaskEventAt,
        })
      }

      const merged = Array.from(byId.values())
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_SESSIONS)

      const preferredActiveId = String(opts?.activeSessionId || '').trim()
      const incomingIds = new Set(
        incomingSnapshots
          .map((item) => String(item?.id || '').trim())
          .filter(Boolean)
      )
      const currentActive = merged.find((session) => session.id === codexChatActiveSessionId) ?? null
      const shouldKeepCurrentActive = Boolean(
        currentActive
        && (incomingIds.size === 0
          || incomingIds.has(currentActive.id)
          || currentActive.turns.length > 0)
      )

      if (shouldKeepCurrentActive) {
        nextActiveSessionId = codexChatActiveSessionId
      } else if (preferredActiveId && merged.some((session) => session.id === preferredActiveId)) {
        nextActiveSessionId = preferredActiveId
      } else {
        nextActiveSessionId = merged[0]?.id ?? ''
      }
      return merged
    })
    if (nextActiveSessionId && nextActiveSessionId !== codexChatActiveSessionId) {
      setCodexChatActiveSessionId(nextActiveSessionId)
    }
  }, [codexChatActiveSessionId])

  const createCodexChatSession = React.useCallback((opts?: { title?: string; projectId?: string }) => {
    const projectId = String(opts?.projectId ?? '')
    const title = String(opts?.title ?? '').trim() || nextSessionTitle(codexChatSessions)
    const nextSession = createSession(title, projectId)
    setCodexChatSessions((prev) => [...prev, nextSession].slice(-MAX_SESSIONS))
    setCodexChatActiveSessionId(nextSession.id)
    return nextSession.id
  }, [codexChatSessions])

  const selectCodexChatProject = React.useCallback((projectId: string) => {
    const normalizedProjectId = String(projectId || '')
    const existing = latestSessionByProject(codexChatSessions, normalizedProjectId)
    if (existing) {
      setCodexChatActiveSessionId(existing.id)
      return
    }
    const nextSession = createSession(nextSessionTitle(codexChatSessions), normalizedProjectId)
    setCodexChatSessions((prev) => [...prev, nextSession].slice(-MAX_SESSIONS))
    setCodexChatActiveSessionId(nextSession.id)
  }, [codexChatSessions])

  const deleteCodexChatSession = React.useCallback((sessionId: string) => {
    let nextActiveSessionId = ''
    setCodexChatSessions((prev) => {
      if (prev.length <= 1) return prev
      const removed = prev.find((session) => session.id === sessionId) ?? null
      let next = prev.filter((session) => session.id !== sessionId)
      if (!next.length) return prev
      if (codexChatActiveSessionId === sessionId) {
        const projectId = removed?.projectId ?? ''
        const sameProject = latestSessionByProject(next, projectId)
        if (sameProject) {
          nextActiveSessionId = sameProject.id
        } else {
          const replacement = createSession(nextSessionTitle(next), projectId)
          next = [...next, replacement].slice(-MAX_SESSIONS)
          nextActiveSessionId = replacement.id
        }
      }
      return next
    })
    if (nextActiveSessionId) setCodexChatActiveSessionId(nextActiveSessionId)
  }, [codexChatActiveSessionId])

  const activeSession = React.useMemo(() => {
    if (!codexChatSessions.length) return null
    return codexChatSessions.find((session) => session.id === codexChatActiveSessionId)
      ?? codexChatSessions[codexChatSessions.length - 1]
  }, [codexChatActiveSessionId, codexChatSessions])

  const codexChatSessionId = activeSession?.id ?? ''
  const codexChatProjectId = activeSession?.projectId ?? ''
  const codexChatTurns = activeSession?.turns ?? []
  const codexChatUsage = activeSession?.usage ?? null
  const codexChatMcpServers = normalizeMcpServers(activeSession?.mcpServers)
  const codexChatSessionAttachmentRefs = normalizeAttachmentRefs(activeSession?.sessionAttachmentRefs)
  const codexChatCodexSessionId = activeSession?.codexSessionId ?? null
  const codexChatResumeState = activeSession?.codexResumeState ?? null
  const codexChatLastTaskEventAt = activeSession?.lastTaskEventAt ?? null
  const codexChatActiveSessionTitle = activeSession?.title ?? ''
  const codexChatProjectSessions = React.useMemo(() => {
    const filtered = codexChatSessions.filter((session) => session.projectId === codexChatProjectId)
    filtered.sort((a, b) => b.updatedAt - a.updatedAt)
    return filtered
  }, [codexChatProjectId, codexChatSessions])

  const setCodexChatProjectId = React.useCallback((projectId: string) => {
    if (!codexChatSessionId) return
    patchSession(codexChatSessionId, (session) => ({
      ...session,
      projectId,
      updatedAt: Date.now(),
    }))
  }, [codexChatSessionId, patchSession])

  const setCodexChatTurns = React.useCallback((value: React.SetStateAction<ChatTurn[]>) => {
    if (!codexChatSessionId) return
    setCodexChatTurnsForSession(codexChatSessionId, value)
  }, [codexChatSessionId, setCodexChatTurnsForSession])

  const setCodexChatUsage = React.useCallback((usage: AgentChatUsage | null) => {
    if (!codexChatSessionId) return
    setCodexChatUsageForSession(codexChatSessionId, usage)
  }, [codexChatSessionId, setCodexChatUsageForSession])

  const setCodexChatMcpServers = React.useCallback((servers: ChatMcpServer[]) => {
    if (!codexChatSessionId) return
    setCodexChatMcpServersForSession(codexChatSessionId, servers)
  }, [codexChatSessionId, setCodexChatMcpServersForSession])

  const setCodexChatSessionAttachmentRefs = React.useCallback((refs: AttachmentRef[]) => {
    if (!codexChatSessionId) return
    setCodexChatSessionAttachmentRefsForSession(codexChatSessionId, refs)
  }, [codexChatSessionId, setCodexChatSessionAttachmentRefsForSession])

  const setCodexChatCodexSessionId = React.useCallback((codexSessionId: string | null) => {
    if (!codexChatSessionId) return
    setCodexChatCodexSessionIdForSession(codexChatSessionId, codexSessionId)
  }, [codexChatSessionId, setCodexChatCodexSessionIdForSession])

  const setCodexChatResumeState = React.useCallback((resumeState: CodexResumeState | null) => {
    if (!codexChatSessionId) return
    setCodexChatResumeStateForSession(codexChatSessionId, resumeState)
  }, [codexChatSessionId, setCodexChatResumeStateForSession])

  const setCodexChatLastTaskEventAt = React.useCallback((at: number | null) => {
    if (!codexChatSessionId) return
    setCodexChatLastTaskEventAtForSession(codexChatSessionId, at)
  }, [codexChatSessionId, setCodexChatLastTaskEventAtForSession])

  return {
    showCodexChat,
    setShowCodexChat,
    codexChatSessions,
    codexChatProjectSessions,
    codexChatActiveSessionId,
    setCodexChatActiveSessionId,
    codexChatActiveSessionTitle,
    createCodexChatSession,
    selectCodexChatProject,
    deleteCodexChatSession,
    codexChatProjectId,
    setCodexChatProjectId,
    codexChatMcpServers,
    setCodexChatMcpServers,
    codexChatSessionAttachmentRefs,
    setCodexChatSessionAttachmentRefs,
    setCodexChatSessionAttachmentRefsForSession,
    codexChatInstruction,
    setCodexChatInstruction,
    codexChatTurns,
    setCodexChatTurns,
    setCodexChatTurnsForSession,
    codexChatSessionId,
    isCodexChatRunning,
    setIsCodexChatRunning,
    codexChatRunStartedAt,
    setCodexChatRunStartedAt,
    codexChatElapsedSeconds,
    setCodexChatElapsedSeconds,
    codexChatLastTaskEventAt,
    setCodexChatLastTaskEventAt,
    setCodexChatLastTaskEventAtForSession,
    codexChatUsage,
    setCodexChatUsage,
    setCodexChatUsageForSession,
    codexChatCodexSessionId,
    setCodexChatCodexSessionId,
    setCodexChatCodexSessionIdForSession,
    codexChatResumeState,
    setCodexChatResumeState,
    setCodexChatResumeStateForSession,
    setCodexChatMcpServersForSession,
    mergeCodexChatSessionsFromServer,
  }
}
