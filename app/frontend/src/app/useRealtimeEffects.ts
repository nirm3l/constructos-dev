import React from 'react'
import type { Notification } from '../types'
import { listChatSessionMessages, listChatSessions } from '../api'
import type { ChatSessionServerSnapshot } from './useCodexChatState'

const CHAT_NEAR_BOTTOM_THRESHOLD_PX = 28

export function useRealtimeEffects(c: any) {
  const PROJECT_EMBEDDING_INDEX_UPDATED = 'ProjectEmbeddingIndexUpdated'
  const {
    qc,
    realtimeRefreshTimerRef,
    tab,
    selectedProjectId,
    selectedTaskId,
    userId,
    workspaceId,
    showCodexChat,
    setCodexChatLastTaskEventAt,
    isCodexChatRunning,
    codexChatRunStartedAt,
    setCodexChatElapsedSeconds,
    codexChatHistoryRef,
    codexChatTurns,
    codexChatActiveSessionId,
    mergeCodexChatSessionsFromServer,
  } = c
  const shouldStickChatToBottomRef = React.useRef(true)
  const isChatNearBottom = React.useCallback((el: HTMLDivElement) => {
    const distanceToBottom = el.scrollHeight - el.clientHeight - el.scrollTop
    return distanceToBottom <= CHAT_NEAR_BOTTOM_THRESHOLD_PX
  }, [])

  const scheduleRealtimeRefresh = React.useCallback(() => {
    if (realtimeRefreshTimerRef.current !== null) {
      window.clearTimeout(realtimeRefreshTimerRef.current)
    }
    realtimeRefreshTimerRef.current = window.setTimeout(() => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: ['project-tags'] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['bootstrap'] })
      if (selectedTaskId) {
        qc.invalidateQueries({ queryKey: ['comments', userId, selectedTaskId] })
        qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
        qc.invalidateQueries({ queryKey: ['automation-status', userId, selectedTaskId] })
      }
      realtimeRefreshTimerRef.current = null
    }, 250)
  }, [qc, realtimeRefreshTimerRef, selectedTaskId, userId])

  const parseTimestampMs = React.useCallback((value: string | null | undefined, fallback: number): number => {
    const parsed = Date.parse(String(value || ''))
    if (!Number.isFinite(parsed) || parsed <= 0) return fallback
    return Math.floor(parsed)
  }, [])

  const normalizeAttachmentRefs = React.useCallback((value: unknown) => {
    if (!Array.isArray(value)) return []
    const out: Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }> = []
    const seen = new Set<string>()
    for (const item of value) {
      if (!item || typeof item !== 'object') continue
      const attachment = item as Record<string, unknown>
      const path = typeof attachment.path === 'string' ? attachment.path.trim() : ''
      if (!path) continue
      const dedupeKey = path.toLowerCase()
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)
      const normalized: { path: string; name?: string; mime_type?: string; size_bytes?: number } = { path }
      const name = typeof attachment.name === 'string' ? attachment.name.trim() : ''
      const mimeType = typeof attachment.mime_type === 'string' ? attachment.mime_type.trim() : ''
      const sizeBytes = Number(attachment.size_bytes)
      if (name) normalized.name = name
      if (mimeType) normalized.mime_type = mimeType
      if (Number.isFinite(sizeBytes) && sizeBytes >= 0) normalized.size_bytes = Math.floor(sizeBytes)
      out.push(normalized)
    }
    return out
  }, [])

  const refreshChatFromServer = React.useCallback(async () => {
    if (!userId || !workspaceId) return
    if (isCodexChatRunning) return
    if (typeof mergeCodexChatSessionsFromServer !== 'function') return
    try {
      const sessions = await listChatSessions(userId, workspaceId, { include_archived: false, limit: 40 })
      if (!Array.isArray(sessions) || sessions.length === 0) return
      const messagesBySession = new Map<string, Awaited<ReturnType<typeof listChatSessionMessages>>>()
      await Promise.all(
        sessions.map(async (session) => {
          const sessionId = String(session?.id || '').trim()
          if (!sessionId) return
          const messages = await listChatSessionMessages(userId, workspaceId, sessionId, { include_deleted: false, limit: 400 })
          messagesBySession.set(sessionId, Array.isArray(messages) ? messages : [])
        })
      )

      const now = Date.now()
      const snapshots: ChatSessionServerSnapshot[] = sessions.map((session) => {
        const sessionId = String(session.id || '').trim()
        const rawMessages = messagesBySession.get(sessionId) ?? []
        const turns = rawMessages
          .map((message) => {
            const role: 'user' | 'assistant' =
              String(message.role || '').trim().toLowerCase() === 'assistant' ? 'assistant' : 'user'
            return {
              id: String(message.id || '').trim() || `turn-${Date.now()}-${Math.random()}`,
              role,
              content: String(message.content || ''),
              createdAt: parseTimestampMs(message.created_at, now),
              attachmentRefs: normalizeAttachmentRefs(message.attachment_refs),
            }
          })
          .sort((a, b) => a.createdAt - b.createdAt)
        return {
          id: sessionId,
          title: String(session.title || '').trim() || 'Session',
          projectId: String(session.project_id || ''),
          turns,
          usage: session.usage ?? null,
          mcpServers: Array.isArray(session.mcp_servers) ? session.mcp_servers : [],
          sessionAttachmentRefs: normalizeAttachmentRefs(session.session_attachment_refs),
          codexSessionId: session.codex_session_id || null,
          createdAt: parseTimestampMs(session.created_at, now),
          updatedAt: parseTimestampMs(session.updated_at || session.last_message_at, now),
          lastTaskEventAt: session.last_task_event_at ? parseTimestampMs(session.last_task_event_at, now) : null,
        }
      })
      mergeCodexChatSessionsFromServer(snapshots, { activeSessionId: codexChatActiveSessionId || null })
    } catch {
      // Keep local chat state; server sync retries on next interval.
    }
  }, [
    codexChatActiveSessionId,
    isCodexChatRunning,
    mergeCodexChatSessionsFromServer,
    normalizeAttachmentRefs,
    parseTimestampMs,
    userId,
    workspaceId,
  ])

  React.useEffect(() => {
    return () => {
      if (realtimeRefreshTimerRef.current !== null) {
        window.clearTimeout(realtimeRefreshTimerRef.current)
      }
    }
  }, [realtimeRefreshTimerRef])

  React.useEffect(() => {
    if (!workspaceId || !userId) return
    void refreshChatFromServer()
  }, [refreshChatFromServer, userId, workspaceId])

  React.useEffect(() => {
    if (!showCodexChat || !workspaceId || !userId) return
    const id = window.setInterval(() => {
      void refreshChatFromServer()
    }, 8000)
    return () => {
      window.clearInterval(id)
    }
  }, [refreshChatFromServer, showCodexChat, userId, workspaceId])

  React.useEffect(() => {
    if (!userId || !workspaceId) return
    const streamUrl = `/api/notifications/stream?workspace_id=${encodeURIComponent(workspaceId || '')}`
    const es = new EventSource(streamUrl)

    const onNotification = (evt: MessageEvent) => {
      try {
        const incoming = JSON.parse(evt.data) as Notification
        qc.setQueryData(['notifications', userId], (current: Notification[] | undefined) => {
          const base = current ?? []
          const idx = base.findIndex((n: Notification) => n.id === incoming.id)
          if (idx >= 0) {
            const next = [...base]
            next[idx] = incoming
            return next
          }
          return [incoming, ...base]
        })
        scheduleRealtimeRefresh()
      } catch {
        qc.invalidateQueries({ queryKey: ['notifications', userId] })
        scheduleRealtimeRefresh()
      }
    }

    const onTaskEvent = (evt: MessageEvent) => {
      let payload: { created_at?: string; action?: string; project_id?: string } = {}
      try {
        payload = JSON.parse(evt.data) as { created_at?: string; action?: string; project_id?: string }
      } catch {
        payload = {}
      }
      if (showCodexChat) {
        setCodexChatLastTaskEventAt(payload.created_at ? Date.parse(payload.created_at) : Date.now())
      }
      const action = String(payload.action || '').trim()
      const projectId = String(payload.project_id || '').trim()
      if (
        action === PROJECT_EMBEDDING_INDEX_UPDATED &&
        tab === 'projects' &&
        userId &&
        selectedProjectId &&
        projectId === selectedProjectId
      ) {
        qc.invalidateQueries({ queryKey: ['bootstrap', userId] })
        return
      }
      scheduleRealtimeRefresh()
    }

    const onLicenseEvent = () => {
      qc.invalidateQueries({ queryKey: ['license-status', userId] })
    }

    es.addEventListener('notification', onNotification as EventListener)
    es.addEventListener('task_event', onTaskEvent as EventListener)
    es.addEventListener('license_event', onLicenseEvent as EventListener)

    return () => {
      es.removeEventListener('notification', onNotification as EventListener)
      es.removeEventListener('task_event', onTaskEvent as EventListener)
      es.removeEventListener('license_event', onLicenseEvent as EventListener)
      es.close()
    }
  }, [qc, scheduleRealtimeRefresh, selectedProjectId, setCodexChatLastTaskEventAt, showCodexChat, tab, userId, workspaceId])

  React.useEffect(() => {
    if (!isCodexChatRunning || !codexChatRunStartedAt) return
    const id = window.setInterval(() => {
      setCodexChatElapsedSeconds(Math.max(0, Math.floor((Date.now() - codexChatRunStartedAt) / 1000)))
    }, 1000)
    return () => window.clearInterval(id)
  }, [codexChatRunStartedAt, isCodexChatRunning, setCodexChatElapsedSeconds])

  React.useEffect(() => {
    if (!showCodexChat || !codexChatHistoryRef.current) return
    const historyEl = codexChatHistoryRef.current
    const syncScrollLock = () => {
      shouldStickChatToBottomRef.current = isChatNearBottom(historyEl)
    }
    syncScrollLock()
    historyEl.addEventListener('scroll', syncScrollLock, { passive: true })
    return () => {
      historyEl.removeEventListener('scroll', syncScrollLock)
    }
  }, [codexChatHistoryRef, isChatNearBottom, showCodexChat])

  React.useEffect(() => {
    if (!showCodexChat || !codexChatHistoryRef.current) return
    if (!shouldStickChatToBottomRef.current) return
    codexChatHistoryRef.current.scrollTop = codexChatHistoryRef.current.scrollHeight
  }, [codexChatHistoryRef, codexChatTurns, isCodexChatRunning, showCodexChat])
}
