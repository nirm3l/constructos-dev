import React from 'react'
import { useMutation } from '@tanstack/react-query'
import { addComment, deleteComment, markNotificationRead, patchMyPreferences, runAgentChatStream } from '../../api'
import type { ChatMcpServer } from '../../types'

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

export function useMiscMutations(c: any) {
  const activeChatAbortControllerRef = React.useRef<AbortController | null>(null)

  const clearChatRunningState = React.useCallback(() => {
    c.setIsCodexChatRunning(false)
    c.setCodexChatRunStartedAt(null)
    c.setCodexChatElapsedSeconds(0)
  }, [c])

  const cancelAgentChat = React.useCallback(() => {
    const controller = activeChatAbortControllerRef.current
    if (!controller) return
    controller.abort()
    clearChatRunningState()
  }, [clearChatRunningState])

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

  const markReadMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Mark read failed')
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
      mcpServers?: ChatMcpServer[]
      attachmentRefs?: Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }>
      sessionAttachmentRefs?: Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }>
    }) => {
      const sessionId = payload.sessionId || c.codexChatSessionId
      const assistantTurnId = globalThis.crypto?.randomUUID?.() ?? `a-${Date.now()}`
      const assistantCreatedAt = Date.now()
      const thinkingFrames = ['Thinking.', 'Thinking..', 'Thinking...']
      let thinkingFrameIndex = 0
      let thinkingTimer: ReturnType<typeof globalThis.setInterval> | null = null
      let hasAssistantDelta = false
      const setAssistantTurnContent = (content: string) => {
        setChatTurnsForSession(sessionId, (prev: any[]) =>
          prev.map((turn: any) =>
            turn.id === assistantTurnId
              ? { ...turn, content }
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
          setAssistantTurnContent(thinkingFrames[thinkingFrameIndex] || 'Thinking...')
          thinkingFrameIndex = (thinkingFrameIndex + 1) % thinkingFrames.length
        }, 320)
      }
      setChatTurnsForSession(sessionId, (prev: any[]) => [
        ...prev,
        {
          id: assistantTurnId,
          role: 'assistant',
          content: 'Thinking...',
          createdAt: assistantCreatedAt,
        },
      ])
      startThinkingAnimation()

      let streamedReply = ''
      let pendingStreamDelta = ''
      let streamFlushTimer: ReturnType<typeof globalThis.setTimeout> | null = null
      let streamDrainResolver: (() => void) | null = null

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
        setAssistantTurnContent(streamedReply)
        streamFlushTimer = globalThis.setTimeout(flushStreamDeltaStep, 16)
      }

      const enqueueStreamDelta = (delta: string) => {
        if (!delta) return
        if (!hasAssistantDelta) {
          hasAssistantDelta = true
          stopThinkingAnimation()
        }
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
            allow_mutations: true,
          },
          {
            onAssistantDelta: (delta) => {
              enqueueStreamDelta(delta)
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
          const stoppedContent = streamedReply.trim() ? streamedReply : 'Stopped.'
          setChatTurnsForSession(sessionId, (prev: any[]) =>
            prev.map((turn: any) =>
              turn.id === assistantTurnId
                ? { ...turn, content: stoppedContent }
                : turn
            )
          )
          throw err
        }
        const msg = err instanceof Error ? err.message : 'Chat failed'
        setChatTurnsForSession(sessionId, (prev: any[]) =>
          prev.map((turn: any) =>
            turn.id === assistantTurnId
              ? { ...turn, content: `Error: ${msg}` }
              : turn
          )
        )
        throw err
      } finally {
        activeChatAbortControllerRef.current = null
      }
    },
    onSuccess: async (result, variables) => {
      const { response, assistantTurnId, assistantCreatedAt, streamedReply, sessionId } = result
      c.setUiError(null)
      setChatCodexSessionForSession(sessionId, response.codex_session_id ?? null)
      if (response.usage) {
        setChatUsageForSession(sessionId, response.usage)
      }
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
          return { ...turn, content: reply }
        })
        if (found) return next
        return [
          ...next,
          {
            id: assistantTurnId,
            role: 'assistant',
            content: reply,
            createdAt: assistantCreatedAt,
          },
        ]
      })
      if (response.ok === false) {
        c.setUiError(response.summary || response.comment || 'Chat request failed')
      }
      clearChatRunningState()
      await c.invalidateAll()
    },
    onError: (err) => {
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
    themeMutation,
    addCommentMutation,
    deleteCommentMutation,
    runAgentChatMutation,
    cancelAgentChat,
  }
}
