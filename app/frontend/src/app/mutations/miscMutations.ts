import React from 'react'
import { useMutation } from '@tanstack/react-query'
import { addComment, deleteComment, markAllNotificationsRead, markNotificationRead, patchMyPreferences, runAgentChatStream, stopAgentChatStream } from '../../api'
import type { ChatMcpServer, ChatReasoningEffort } from '../../types'

const ENTITY_ID_SOURCE = '[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){0,4}'
const ENTITY_ID_PATTERN = /([0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){0,4})/

type AgentEntityKind = 'projects' | 'notes' | 'tasks' | 'specifications'

function buildAgentEntityLink(kind: AgentEntityKind, id: string, projectId?: string | null): string {
  const params = new URLSearchParams()
  params.set('tab', kind)
  if (kind === 'projects') {
    params.set('project', id)
  } else if (projectId) {
    params.set('project', projectId)
  }
  if (kind === 'projects') return `?${params.toString()}`
  if (kind === 'notes') params.set('note', id)
  if (kind === 'tasks') params.set('task', id)
  if (kind === 'specifications') params.set('specification', id)
  return `?${params.toString()}`
}

function linkifyEntityLine(
  line: string,
  label: string,
  kind: AgentEntityKind,
  projectId?: string | null
): string {
  const prefixPattern = new RegExp(`(^|\\b)${label}\\s*:\\s*`, 'i')
  if (!prefixPattern.test(line)) return line
  if (line.includes('](')) return line
  const idMatch = line.match(ENTITY_ID_PATTERN)
  const id = idMatch?.[1]
  if (!id) return line
  const url = buildAgentEntityLink(kind, id, projectId)
  const prettyLabel = label.replace(/\s+ID$/i, '')
  return line.replace(
    new RegExp(`${label}\\s*:\\s*${id}`, 'i'),
    `${prettyLabel}: [${id}](${url})`
  )
}

function linkifyEntityKeyValue(
  line: string,
  key: string,
  kind: AgentEntityKind,
  projectId?: string | null
): string {
  const pattern = new RegExp(`\\b(${key})\\b\\s*([:=])\\s*(${ENTITY_ID_SOURCE})`, 'gi')
  return line.replace(pattern, (_match, rawKey: string, delimiter: string, id: string) => {
    const url = buildAgentEntityLink(kind, id, projectId)
    if (delimiter === ':') return `${rawKey}: [${id}](${url})`
    return `${rawKey}=[${id}](${url})`
  })
}

function detectProjectId(content: string): string | null {
  const match = content.match(new RegExp(`\\bproject_id\\b\\s*[:=]\\s*(${ENTITY_ID_SOURCE})`, 'i'))
  const id = match?.[1]
  return id ? String(id) : null
}

function linkifyAgentReply(content: string, projectId?: string | null): string {
  if (!content) return content
  const inferredProjectId = detectProjectId(content)
  const resolvedProjectId = inferredProjectId || projectId || null
  return content
    .split('\n')
    .map((line) => {
      let next = line
      next = linkifyEntityKeyValue(next, 'project_id', 'projects', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'task_id', 'tasks', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'note_id', 'notes', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'specification_id', 'specifications', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'spec_id', 'specifications', resolvedProjectId)
      next = linkifyEntityLine(next, 'Project ID', 'projects', resolvedProjectId)
      next = linkifyEntityLine(next, 'Note ID', 'notes', resolvedProjectId)
      next = linkifyEntityLine(next, 'Task ID', 'tasks', resolvedProjectId)
      next = linkifyEntityLine(next, 'Specification ID', 'specifications', resolvedProjectId)
      next = linkifyEntityLine(next, 'Spec ID', 'specifications', resolvedProjectId)
      return next
    })
    .join('\n')
}

function isAbortLikeError(err: unknown): boolean {
  if (typeof DOMException !== 'undefined' && err instanceof DOMException) {
    return err.name === 'AbortError'
  }
  if (err instanceof Error) {
    const name = String(err.name || '').toLowerCase()
    const message = String(err.message || '').toLowerCase()
    return name === 'aborterror' || message.includes('abort')
  }
  return false
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

function normalizeResumeStateFromResponse(response: any): { attempted: boolean; succeeded: boolean; fallbackUsed: boolean } | null {
  const attempted = normalizeBool(response?.resume_attempted ?? response?.usage?.codex_resume_attempted)
  const succeeded = normalizeBool(response?.resume_succeeded ?? response?.usage?.codex_resume_succeeded)
  const fallbackUsed = normalizeBool(response?.resume_fallback_used ?? response?.usage?.codex_resume_fallback_used)
  if (attempted === null && succeeded === null && fallbackUsed === null) return null
  return {
    attempted: Boolean(attempted),
    succeeded: Boolean(succeeded),
    fallbackUsed: Boolean(fallbackUsed),
  }
}

export function useMiscMutations(c: any) {
  const activeChatAbortControllerRef = React.useRef<AbortController | null>(null)
  const activeChatRunRef = React.useRef<{
    workspaceId: string
    sessionId: string
    runId: string | null
  } | null>(null)
  const stopRequestedBySessionRef = React.useRef<Record<string, number>>({})
  const stopFallbackTimerBySessionRef = React.useRef<Record<string, number>>({})

  const clearChatRunningState = React.useCallback(() => {
    c.setIsCodexChatRunning(false)
    c.setCodexChatRunStartedAt(null)
    c.setCodexChatElapsedSeconds(0)
  }, [c])

  const clearStopFallbackTimerForSession = React.useCallback((sessionId: string) => {
    if (!sessionId) return
    const timerId = stopFallbackTimerBySessionRef.current[sessionId]
    if (timerId) {
      globalThis.clearTimeout(timerId)
      delete stopFallbackTimerBySessionRef.current[sessionId]
    }
  }, [])

  React.useEffect(() => {
    return () => {
      const controller = activeChatAbortControllerRef.current
      if (controller) controller.abort()
      activeChatRunRef.current = null
      Object.values(stopFallbackTimerBySessionRef.current).forEach((timerId) => {
        if (timerId) globalThis.clearTimeout(timerId)
      })
      stopFallbackTimerBySessionRef.current = {}
      stopRequestedBySessionRef.current = {}
    }
  }, [])

  const cancelAgentChat = React.useCallback(() => {
    const activeRun = activeChatRunRef.current
    const workspaceId = String(activeRun?.workspaceId || c.workspaceId || '').trim()
    const sessionId = String(activeRun?.sessionId || c.codexChatSessionId || '').trim()
    const runId = String(activeRun?.runId || c.codexChatLiveRunId || '').trim()
    const abortLocal = () => {
      const controller = activeChatAbortControllerRef.current
      if (controller) controller.abort()
    }

    if (!workspaceId || !sessionId) {
      abortLocal()
      return
    }

    clearStopFallbackTimerForSession(sessionId)

    stopRequestedBySessionRef.current[sessionId] = Date.now()
    if (typeof c.setCodexChatLiveRunForSession === 'function') {
      c.setCodexChatLiveRunForSession(sessionId, {
        liveStatusText: 'Stop requested…',
        liveRunActive: false,
        liveRunId: null,
        liveRunSeq: 0,
        liveStopRequested: true,
      })
    }

    void stopAgentChatStream(c.userId, {
      workspace_id: workspaceId,
      session_id: sessionId,
      run_id: runId || null,
    }).catch(() => {
      // Ignore stop API errors; local abort already applied.
    })

    // Immediately stop local stream consumption.
    abortLocal()
    clearChatRunningState()
    activeChatRunRef.current = null

    // Safety net for stale controllers.
    const fallbackTimer = globalThis.setTimeout(() => {
      abortLocal()
    }, 2_000)
    stopFallbackTimerBySessionRef.current[sessionId] = fallbackTimer
  }, [c, clearChatRunningState, clearStopFallbackTimerForSession])

  const setChatTurnsForSession = (
    sessionId: string,
    updater: (prev: any[]) => any[]
  ) => {
    if (sessionId && typeof c.setCodexChatTurnsForSession === 'function') {
      c.setCodexChatTurnsForSession(sessionId, updater)
      return
    }
    c.setCodexChatTurns(updater)
  }

  const setChatUsageForSession = (
    sessionId: string,
    usage: any
  ) => {
    if (sessionId && typeof c.setCodexChatUsageForSession === 'function') {
      c.setCodexChatUsageForSession(sessionId, usage)
      return
    }
    c.setCodexChatUsage(usage)
  }

  const setChatCodexSessionForSession = (
    sessionId: string,
    codexSessionId: string | null | undefined
  ) => {
    const normalized = codexSessionId && String(codexSessionId).trim() ? String(codexSessionId).trim() : null
    if (sessionId && typeof c.setCodexChatCodexSessionIdForSession === 'function') {
      c.setCodexChatCodexSessionIdForSession(sessionId, normalized)
      return
    }
    if (typeof c.setCodexChatCodexSessionId === 'function') {
      c.setCodexChatCodexSessionId(normalized)
    }
  }

  const setChatResumeStateForSession = (
    sessionId: string,
    resumeState: { attempted: boolean; succeeded: boolean; fallbackUsed: boolean } | null
  ) => {
    if (sessionId && typeof c.setCodexChatResumeStateForSession === 'function') {
      c.setCodexChatResumeStateForSession(sessionId, resumeState)
      return
    }
    if (typeof c.setCodexChatResumeState === 'function') {
      c.setCodexChatResumeState(resumeState)
    }
  }

  const setChatLiveRunForSession = (
    sessionId: string,
    patch: {
      liveRunId?: string | null
      liveRunSeq?: number
      liveRunActive?: boolean
      liveAssistantTurnId?: string | null
      liveStatusText?: string
      liveRunStartedAt?: number | null
      liveStopRequested?: boolean
    }
  ) => {
    if (sessionId && typeof c.setCodexChatLiveRunForSession === 'function') {
      c.setCodexChatLiveRunForSession(sessionId, patch)
    }
  }

  const markReadMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Mark read failed')
  })

  const markAllReadMutation = useMutation({
    mutationFn: () => markAllNotificationsRead(c.userId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Mark all read failed')
  })

  const themeMutation = useMutation({
    mutationFn: (nextTheme: 'light' | 'dark') => patchMyPreferences(c.userId, { theme: nextTheme }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['bootstrap'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Theme update failed')
  })

  const addCommentMutation = useMutation({
    mutationFn: () => addComment(c.userId, c.selectedTaskId as string, c.commentBody.trim()),
    onSuccess: async () => {
      c.setUiError(null)
      c.setCommentBody('')
      c.setScrollToNewestComment(true)
      await c.qc.invalidateQueries({ queryKey: ['comments', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Comment failed')
  })

  const deleteCommentMutation = useMutation({
    mutationFn: (commentId: number) => deleteComment(c.userId, c.selectedTaskId as string, commentId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['comments', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Delete comment failed')
  })

  const runAgentChatMutation = useMutation({
    mutationFn: async (payload: {
      instruction: string
      history: Array<{ role: 'user' | 'assistant'; content: string }>
      projectId: string | null
      sessionId: string
      commandId?: string
      mcpServers?: ChatMcpServer[]
      model?: string | null
      reasoningEffort?: ChatReasoningEffort | string | null
      attachmentRefs?: Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }>
      sessionAttachmentRefs?: Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }>
    }) => {
      const sessionId = payload.sessionId || c.codexChatSessionId
      if (sessionId) {
        delete stopRequestedBySessionRef.current[sessionId]
      }
      const assistantTurnId = globalThis.crypto?.randomUUID?.() ?? `a-${Date.now()}`
      const assistantCreatedAt = Date.now()
      const thinkingFrames = ['Thinking.', 'Thinking..', 'Thinking...']
      let thinkingFrameIndex = 0
      let thinkingTimer: ReturnType<typeof globalThis.setInterval> | null = null
      let hasAssistantDelta = false
      const setAssistantTurnContent = (content: string, lastStreamChunk = '', streamShimmerChunk = '') => {
        setChatTurnsForSession(sessionId, (prev: any[]) =>
          prev.map((turn: any) =>
            turn.id === assistantTurnId
              ? { ...turn, content, lastStreamChunk, streamShimmerChunk }
              : turn
          )
        )
      }
      const stopThinkingAnimation = () => {
        if (thinkingTimer === null) return
        globalThis.clearInterval(thinkingTimer)
        thinkingTimer = null
      }
      const startThinkingAnimation = () => {
        thinkingTimer = globalThis.setInterval(() => {
          if (hasAssistantDelta) return
          setAssistantTurnContent(thinkingFrames[thinkingFrameIndex] || 'Thinking...', '', '')
          thinkingFrameIndex = (thinkingFrameIndex + 1) % thinkingFrames.length
        }, 320)
      }
      setChatTurnsForSession(sessionId, (prev: any[]) => [
        ...prev,
        {
          id: assistantTurnId,
          role: 'assistant',
          content: 'Thinking...',
          lastStreamChunk: '',
          streamShimmerChunk: '',
          createdAt: assistantCreatedAt,
        },
      ])
      setChatLiveRunForSession(sessionId, {
        liveRunId: null,
        liveRunSeq: 0,
        liveRunActive: true,
        liveAssistantTurnId: assistantTurnId,
        liveStatusText: 'Running…',
        liveRunStartedAt: Date.now(),
        liveStopRequested: false,
      })
      startThinkingAnimation()

      let streamedReply = ''
      let pendingStreamDelta = ''
      let streamFlushTimer: ReturnType<typeof globalThis.setTimeout> | null = null
      let streamDrainResolver: (() => void) | null = null
      let shimmerWindowStartIndex = 0
      let shimmerWindowLastIncomingAt = 0

      const resolveStreamDrainIfIdle = () => {
        if (!pendingStreamDelta && streamFlushTimer === null && streamDrainResolver) {
          const resolver = streamDrainResolver
          streamDrainResolver = null
          resolver()
        }
      }

      const flushStreamDeltaStep = () => {
        if (!pendingStreamDelta) {
          streamFlushTimer = null
          resolveStreamDrainIfIdle()
          return
        }
        const nextChunk = pendingStreamDelta.slice(0, 48)
        pendingStreamDelta = pendingStreamDelta.slice(nextChunk.length)
        streamedReply += nextChunk
        const shimmerStart = Math.max(0, Math.min(shimmerWindowStartIndex, streamedReply.length))
        const shimmerChunk = streamedReply.slice(shimmerStart)
        setAssistantTurnContent(streamedReply, nextChunk, shimmerChunk)
        streamFlushTimer = globalThis.setTimeout(flushStreamDeltaStep, 16)
      }

      const enqueueStreamDelta = (delta: string) => {
        if (!delta) return
        if (!hasAssistantDelta) {
          hasAssistantDelta = true
          stopThinkingAnimation()
        }
        const nowMs = Date.now()
        const bufferedLength = streamedReply.length + pendingStreamDelta.length
        if (nowMs - shimmerWindowLastIncomingAt <= 500) {
          // Keep current shimmer window start while deltas belong to the same short burst.
        } else {
          // Start a new shimmer window at the beginning of this new burst.
          shimmerWindowStartIndex = Math.max(0, bufferedLength)
        }
        shimmerWindowLastIncomingAt = nowMs
        pendingStreamDelta += delta
        if (streamFlushTimer !== null) return
        flushStreamDeltaStep()
      }

      const waitForStreamDrain = async () => {
        if (!pendingStreamDelta && streamFlushTimer === null) return
        await new Promise<void>((resolve) => {
          streamDrainResolver = resolve
        })
      }

      const cancelStreamFlush = () => {
        stopThinkingAnimation()
        if (streamFlushTimer !== null) {
          globalThis.clearTimeout(streamFlushTimer)
          streamFlushTimer = null
        }
        pendingStreamDelta = ''
        resolveStreamDrainIfIdle()
      }

      try {
        if (activeChatAbortControllerRef.current) {
          activeChatAbortControllerRef.current.abort()
        }
        const abortController = new AbortController()
        activeChatAbortControllerRef.current = abortController
        activeChatRunRef.current = {
          workspaceId: String(c.workspaceId || '').trim(),
          sessionId: String(sessionId || '').trim(),
          runId: null,
        }
        const response = await runAgentChatStream(
          c.userId,
          {
            workspace_id: c.workspaceId,
            project_id: payload.projectId,
            session_id: sessionId,
            instruction: payload.instruction,
            history: payload.history,
            attachment_refs: payload.attachmentRefs || [],
            session_attachment_refs: payload.sessionAttachmentRefs || [],
            mcp_servers: payload.mcpServers,
            model: payload.model || null,
            reasoning_effort: payload.reasoningEffort || null,
            allow_mutations: true,
            command_id: payload.commandId || null,
          },
          {
            onAssistantDelta: (delta) => {
              if (sessionId && stopRequestedBySessionRef.current[sessionId]) return
              enqueueStreamDelta(delta)
            },
            onRunId: (runId) => {
              const normalizedRunId = String(runId || '').trim()
              if (normalizedRunId) {
                const current = activeChatRunRef.current
                if (current && String(current.sessionId || '').trim() === String(sessionId || '').trim()) {
                  activeChatRunRef.current = {
                    ...current,
                    runId: normalizedRunId,
                  }
                }
              }
              const persistedStartedAt = Number(
                c.codexChatLiveRunStartedAt
                ?? c.codexChatRunStartedAt
                ?? 0
              )
              setChatLiveRunForSession(sessionId, {
                liveRunId: runId,
                liveRunActive: true,
                liveAssistantTurnId: assistantTurnId,
                liveRunStartedAt:
                  Number.isFinite(persistedStartedAt) && persistedStartedAt > 0
                    ? persistedStartedAt
                    : Date.now(),
              })
            },
            onSeq: (seq) => {
              setChatLiveRunForSession(sessionId, {
                liveRunSeq: seq,
                liveRunActive: true,
                liveAssistantTurnId: assistantTurnId,
              })
            },
            onStatus: (message) => {
              setChatLiveRunForSession(sessionId, {
                liveStatusText: message || '',
                liveRunActive: true,
                liveAssistantTurnId: assistantTurnId,
              })
            },
            onUsage: (usage) => {
              setChatUsageForSession(sessionId, usage ?? null)
            },
            signal: abortController.signal,
          }
        )
        await waitForStreamDrain()
        stopThinkingAnimation()
        return { response, assistantTurnId, assistantCreatedAt, streamedReply, sessionId }
      } catch (err) {
        cancelStreamFlush()
        if (isAbortLikeError(err)) {
          setChatTurnsForSession(sessionId, (prev: any[]) =>
            prev.map((turn: any) =>
              turn.id === assistantTurnId
                ? {
                    ...turn,
                    content: streamedReply.trim() ? streamedReply : String(turn?.content || ''),
                    lastStreamChunk: '',
                    streamShimmerChunk: '',
                  }
                : turn
            )
          )
          throw err
        }
        const msg = err instanceof Error ? err.message : 'Chat failed'
        setChatTurnsForSession(sessionId, (prev: any[]) =>
          prev.map((turn: any) =>
            turn.id === assistantTurnId
              ? { ...turn, content: `Error: ${msg}`, lastStreamChunk: '', streamShimmerChunk: '' }
              : turn
          )
        )
        throw err
      } finally {
        activeChatAbortControllerRef.current = null
        activeChatRunRef.current = null
      }
    },
    onSuccess: async (result, variables) => {
      const { response, assistantTurnId, assistantCreatedAt, streamedReply, sessionId } = result
      const stopRequested = Boolean(sessionId && stopRequestedBySessionRef.current[sessionId])
      if (sessionId) {
        delete stopRequestedBySessionRef.current[sessionId]
        clearStopFallbackTimerForSession(sessionId)
      }
      c.setUiError(null)
      setChatCodexSessionForSession(sessionId, response.codex_session_id ?? null)
      setChatResumeStateForSession(sessionId, normalizeResumeStateFromResponse(response))
      if (response.usage) {
        setChatUsageForSession(sessionId, response.usage)
      }
      if (!stopRequested) {
        const fallbackReply = [response.summary, response.comment].filter(Boolean).join('\n\n').trim()
        const rawReply = streamedReply.trim() ? streamedReply : fallbackReply
        const reply = linkifyAgentReply(
          rawReply,
          variables.projectId || c.codexChatProjectId || c.selectedProjectId || null
        )
        setChatTurnsForSession(sessionId, (prev: any[]) => {
          if (!reply) {
            return prev.filter((turn: any) => turn.id !== assistantTurnId)
          }
          let found = false
          const next = prev.map((turn: any) => {
            if (turn.id !== assistantTurnId) return turn
            found = true
            return { ...turn, content: reply, lastStreamChunk: '', streamShimmerChunk: '' }
          })
          if (found) return next
          return [
            ...next,
            {
              id: assistantTurnId,
              role: 'assistant',
              content: reply,
              lastStreamChunk: '',
              streamShimmerChunk: '',
              createdAt: assistantCreatedAt,
            },
          ]
        })
      } else {
        setChatTurnsForSession(sessionId, (prev: any[]) =>
          prev.map((turn: any) =>
            turn.id === assistantTurnId
              ? { ...turn, lastStreamChunk: '', streamShimmerChunk: '' }
              : turn
          )
        )
      }
      if (response.ok === false) {
        c.setUiError(response.summary || response.comment || 'Chat request failed')
      }
      setChatLiveRunForSession(sessionId, {
        liveRunId: null,
        liveRunSeq: 0,
        liveRunActive: false,
        liveAssistantTurnId: null,
        liveStatusText: '',
        liveRunStartedAt: null,
      })
      clearChatRunningState()
      if (!stopRequested) {
        await c.invalidateAll()
      }
    },
    onError: (err) => {
      const sessionId = String(c.codexChatSessionId || '').trim()
      if (sessionId) {
        delete stopRequestedBySessionRef.current[sessionId]
        clearStopFallbackTimerForSession(sessionId)
      }
      if (sessionId) {
        setChatLiveRunForSession(sessionId, {
          liveRunActive: false,
          liveRunId: null,
          liveRunSeq: 0,
          liveAssistantTurnId: null,
          liveStatusText: '',
          liveRunStartedAt: null,
        })
      }
      clearChatRunningState()
      if (isAbortLikeError(err)) {
        c.setUiError(null)
        return
      }
      const msg = err instanceof Error ? err.message : 'Chat failed'
      c.setUiError(msg)
    }
  })

  return {
    markReadMutation,
    markAllReadMutation,
    themeMutation,
    addCommentMutation,
    deleteCommentMutation,
    runAgentChatMutation,
    cancelAgentChat,
  }
}
