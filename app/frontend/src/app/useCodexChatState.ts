import React from 'react'
import type { AgentChatUsage } from '../types'

export type ChatRole = 'user' | 'assistant'
export type ChatTurn = { id: string; role: ChatRole; content: string; createdAt: number }

export type ChatSession = {
  id: string
  title: string
  projectId: string
  turns: ChatTurn[]
  usage: AgentChatUsage | null
  createdAt: number
  updatedAt: number
  lastTaskEventAt: number | null
}

type PersistedCodexChatState = {
  version: 1
  activeSessionId: string
  sessions: ChatSession[]
}

const STORAGE_KEY = 'codex_chat_state_v1'
const MAX_SESSIONS = 20
const MAX_TURNS_PER_SESSION = 240
const DEFAULT_SESSION_TITLE_PREFIX = 'Session'

function makeId(prefix: string): string {
  return globalThis.crypto?.randomUUID?.() ?? `${prefix}-${Date.now()}-${Math.round(Math.random() * 1_000_000)}`
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
  return {
    id,
    title: typeof session.title === 'string' && session.title.trim()
      ? session.title.trim()
      : `${DEFAULT_SESSION_TITLE_PREFIX} 1`,
    projectId: typeof session.projectId === 'string' ? session.projectId : '',
    turns,
    usage: normalizeUsage(session.usage),
    createdAt,
    updatedAt,
    lastTaskEventAt:
      Number.isFinite(lastTaskEventAtRaw) && lastTaskEventAtRaw > 0 ? Math.floor(lastTaskEventAtRaw) : null,
  }
}

function loadPersistedState(): PersistedCodexChatState | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
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

export function useCodexChatState() {
  const initialState = React.useMemo<PersistedCodexChatState>(() => {
    const restored = loadPersistedState()
    if (restored) return restored
    const firstSession = createSession(`${DEFAULT_SESSION_TITLE_PREFIX} 1`)
    return {
      version: 1,
      activeSessionId: firstSession.id,
      sessions: [firstSession],
    }
  }, [])

  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatInstruction, setCodexChatInstruction] = React.useState('')
  const [codexChatSessions, setCodexChatSessions] = React.useState<ChatSession[]>(initialState.sessions)
  const [codexChatActiveSessionId, setCodexChatActiveSessionId] = React.useState<string>(initialState.activeSessionId)
  const [isCodexChatRunning, setIsCodexChatRunning] = React.useState(false)
  const [codexChatRunStartedAt, setCodexChatRunStartedAt] = React.useState<number | null>(null)
  const [codexChatElapsedSeconds, setCodexChatElapsedSeconds] = React.useState(0)

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
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
      // Ignore quota/storage failures; chat continues in-memory.
    }
  }, [codexChatActiveSessionId, codexChatSessions])

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
    patchSession(sessionId, (session) => ({
      ...session,
      usage: normalizeUsage(usage),
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
  }
}
