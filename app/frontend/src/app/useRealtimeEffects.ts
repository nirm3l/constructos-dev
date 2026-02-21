import React from 'react'
import type { Notification } from '../types'

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

  React.useEffect(() => {
    return () => {
      if (realtimeRefreshTimerRef.current !== null) {
        window.clearTimeout(realtimeRefreshTimerRef.current)
      }
    }
  }, [realtimeRefreshTimerRef])

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
