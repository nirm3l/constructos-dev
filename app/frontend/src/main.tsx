import React from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addComment,
  archiveTask,
  completeTask,
  createProject,
  createTask,
  getTaskAutomationStatus,
  getBootstrap,
  getNotifications,
  getProjectBoard,
  getTasks,
  listActivity,
  listComments,
  markNotificationRead,
  patchMyPreferences,
  patchTask,
  restoreTask,
  reopenTask,
  runAgentChat,
  runTaskWithCodex
} from './api'
import type { Notification, Task, TaskAutomationStatus } from './types'
import './styles.css'

const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000001'

type Tab = 'inbox' | 'today' | 'projects' | 'search' | 'mario' | 'profile'
type ChatRole = 'user' | 'assistant'
type ChatTurn = { id: string; role: ChatRole; content: string; createdAt: number }

const TAB_ORDER: Tab[] = ['inbox', 'today', 'projects', 'search', 'mario', 'profile']

// Lazy import: keep main bundle small for non-Mario usage.
const MarioView = React.lazy(() => import('./mario/MarioView').then((m) => ({ default: m.MarioView })))

function normalizeStoredUserId(raw: string | null): string {
  if (!raw || raw === '1' || raw === '2') return DEFAULT_USER_ID
  return raw
}

function parseStoredTab(raw: string | null): Tab {
  if (raw && TAB_ORDER.includes(raw as Tab)) return raw as Tab
  return 'inbox'
}

function toLocalDateTimeInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day}T${hh}:${mm}`
}

function toReadableDate(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function formatActivitySummary(
  action: string,
  details: Record<string, unknown>,
  actorName: string
): { title: string; detail: string } {
  const keys = Object.keys(details)
  switch (action) {
    case 'TaskCreated':
      return {
        title: `${actorName} created the task`,
        detail: `Title: ${String(details.title ?? '') || '(none)'}`,
      }
    case 'TaskUpdated':
      return {
        title: `${actorName} updated the task`,
        detail: `Changed: ${keys.join(', ') || 'fields'}`,
      }
    case 'TaskCompleted':
      return {
        title: `${actorName} completed the task`,
        detail: `Completed at: ${toReadableDate(details.completed_at) || 'n/a'}`,
      }
    case 'TaskReopened':
      return {
        title: `${actorName} reopened the task`,
        detail: `Status: ${String(details.status ?? 'To do')}`,
      }
    case 'TaskArchived':
      return { title: `${actorName} archived the task`, detail: 'Task moved to archive' }
    case 'TaskRestored':
      return { title: `${actorName} restored the task`, detail: 'Task restored from archive' }
    case 'TaskCommentAdded':
      return {
        title: `${actorName} added a comment`,
        detail: String(details.body ?? '').slice(0, 180) || '(empty comment)',
      }
    case 'TaskAutomationRequested':
      return {
        title: `${actorName} requested Codex run`,
        detail: String(details.instruction ?? '(no instruction)'),
      }
    case 'TaskAutomationStarted':
      return {
        title: 'Codex run started',
        detail: `Started at: ${toReadableDate(details.started_at) || 'n/a'}`,
      }
    case 'TaskAutomationCompleted':
      return {
        title: 'Codex run completed',
        detail: String(details.summary ?? 'Completed'),
      }
    case 'TaskAutomationFailed':
      return {
        title: 'Codex run failed',
        detail: String(details.error ?? details.summary ?? 'Unknown error'),
      }
    case 'TaskScheduleConfigured':
      return {
        title: `${actorName} configured schedule`,
        detail: `At: ${toReadableDate(details.scheduled_at_utc)} | TZ: ${String(details.schedule_timezone ?? 'UTC')}`,
      }
    case 'TaskScheduleQueued':
      return {
        title: 'Scheduled run queued',
        detail: `Queued at: ${toReadableDate(details.queued_at) || 'n/a'}`,
      }
    case 'TaskScheduleStarted':
      return {
        title: 'Scheduled run started',
        detail: `Started at: ${toReadableDate(details.started_at) || 'n/a'}`,
      }
    case 'TaskScheduleCompleted':
      return {
        title: 'Scheduled run completed',
        detail: String(details.summary ?? `Completed at ${toReadableDate(details.completed_at)}`),
      }
    case 'TaskScheduleFailed':
      return {
        title: 'Scheduled run failed',
        detail: String(details.error ?? 'Unknown error'),
      }
    default:
      return {
        title: `${actorName} triggered ${action}`,
        detail: keys.length ? `Details: ${keys.join(', ')}` : 'No details',
      }
  }
}

function activityTone(action: string): 'ok' | 'warn' | 'error' | 'neutral' {
  if (action.includes('Failed')) return 'error'
  if (action.includes('Completed')) return 'ok'
  if (action.includes('Queued') || action.includes('Started') || action.includes('Requested')) return 'warn'
  return 'neutral'
}

function Icon({ path }: { path: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

const queryClient = new QueryClient()

function App() {
  const [userId] = React.useState<string>(() => normalizeStoredUserId(localStorage.getItem('user_id')))
  const [tab, setTab] = React.useState<Tab>(() => parseStoredTab(localStorage.getItem('ui_tab')))
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light')
  const [taskTitle, setTaskTitle] = React.useState('')
  const [quickDueDate, setQuickDueDate] = React.useState('')
  const [projectName, setProjectName] = React.useState('')
  const [selectedProjectId, setSelectedProjectId] = React.useState<string>('')
  const [quickProjectId, setQuickProjectId] = React.useState<string>('')
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  const [searchQ, setSearchQ] = React.useState('')
  const [searchStatus, setSearchStatus] = React.useState('')
  const [searchPriority, setSearchPriority] = React.useState('')
  const [searchArchived, setSearchArchived] = React.useState(false)
  const [commentBody, setCommentBody] = React.useState('')
  const [automationInstruction, setAutomationInstruction] = React.useState('')
  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatInstruction, setCodexChatInstruction] = React.useState('')
  const [codexChatTurns, setCodexChatTurns] = React.useState<ChatTurn[]>([])
  const [codexChatSessionId] = React.useState<string>(() => globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}`)
  const [codexChatAllowMutations, setCodexChatAllowMutations] = React.useState(false)
  const [isCodexChatRunning, setIsCodexChatRunning] = React.useState(false)
  const [codexChatRunStartedAt, setCodexChatRunStartedAt] = React.useState<number | null>(null)
  const [codexChatElapsedSeconds, setCodexChatElapsedSeconds] = React.useState(0)
  const [codexChatLastTaskEventAt, setCodexChatLastTaskEventAt] = React.useState<number | null>(null)
  const [editStatus, setEditStatus] = React.useState('To do')
  const [editDescription, setEditDescription] = React.useState('')
  const [editPriority, setEditPriority] = React.useState('Med')
  const [editDueDate, setEditDueDate] = React.useState('')
  const [editProjectId, setEditProjectId] = React.useState('')
  const [editTaskType, setEditTaskType] = React.useState<'manual' | 'scheduled_instruction'>('manual')
  const [editScheduledAtUtc, setEditScheduledAtUtc] = React.useState('')
  const [editScheduleTimezone, setEditScheduleTimezone] = React.useState('')
  const [editScheduledInstruction, setEditScheduledInstruction] = React.useState('')
  const [activityExpandedIds, setActivityExpandedIds] = React.useState<Set<number>>(new Set())
  const [activityShowRawDetails, setActivityShowRawDetails] = React.useState(false)
  const [uiError, setUiError] = React.useState<string | null>(null)
  const qc = useQueryClient()
  const realtimeRefreshTimerRef = React.useRef<number | null>(null)
  const codexChatHistoryRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    localStorage.setItem('ui_tab', tab)
  }, [tab])

  React.useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const bootstrap = useQuery({
    queryKey: ['bootstrap', userId],
    queryFn: () => getBootstrap(userId),
    retry: 1
  })

  React.useEffect(() => {
    const fromBackend = bootstrap.data?.current_user?.theme
    if (fromBackend === 'dark' || fromBackend === 'light') setTheme(fromBackend)
  }, [bootstrap.data?.current_user?.theme])

  const workspaceId = bootstrap.data?.workspaces[0]?.id ?? ''

  React.useEffect(() => {
    const firstProjectId = bootstrap.data?.projects[0]?.id ?? ''
    if (!selectedProjectId && firstProjectId) setSelectedProjectId(firstProjectId)
    if (tab === 'inbox') {
      if (quickProjectId !== '') setQuickProjectId('')
      return
    }
    if (!quickProjectId && firstProjectId) setQuickProjectId(firstProjectId)
  }, [bootstrap.data, quickProjectId, selectedProjectId, tab])

  const taskParams = React.useMemo(() => {
    if (tab === 'today') return { view: 'today' }
    if (tab === 'projects') return { project_id: selectedProjectId || undefined }
    if (tab === 'search') return { q: searchQ || undefined, status: searchStatus || undefined, priority: searchPriority || undefined, archived: searchArchived }
    return { view: 'inbox' }
  }, [tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived])

  const tasks = useQuery({
    queryKey: ['tasks', userId, workspaceId, tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived],
    queryFn: () => getTasks(userId, workspaceId, taskParams),
    enabled: Boolean(workspaceId)
  })

  const notifications = useQuery({
    queryKey: ['notifications', userId],
    queryFn: () => getNotifications(userId),
    enabled: Boolean(userId)
  })

  const scheduleRealtimeRefresh = React.useCallback(() => {
    if (realtimeRefreshTimerRef.current !== null) {
      window.clearTimeout(realtimeRefreshTimerRef.current)
    }
    realtimeRefreshTimerRef.current = window.setTimeout(() => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['bootstrap'] })
      if (selectedTaskId) {
        qc.invalidateQueries({ queryKey: ['comments', userId, selectedTaskId] })
        qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
        qc.invalidateQueries({ queryKey: ['automation-status', userId, selectedTaskId] })
      }
      realtimeRefreshTimerRef.current = null
    }, 250)
  }, [qc, selectedTaskId, userId])

  React.useEffect(() => {
    return () => {
      if (realtimeRefreshTimerRef.current !== null) {
        window.clearTimeout(realtimeRefreshTimerRef.current)
      }
    }
  }, [])

  React.useEffect(() => {
    if (!userId) return
    const streamUrl = `/api/notifications/stream?user_id=${encodeURIComponent(userId)}&workspace_id=${encodeURIComponent(workspaceId || '')}`
    const es = new EventSource(streamUrl)

    const onNotification = (evt: MessageEvent) => {
      try {
        const incoming = JSON.parse(evt.data) as Notification
        qc.setQueryData<Notification[]>(['notifications', userId], (current) => {
          const base = current ?? []
          const idx = base.findIndex((n) => n.id === incoming.id)
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
      if (showCodexChat) {
        try {
          const payload = JSON.parse(evt.data) as { created_at?: string }
          setCodexChatLastTaskEventAt(payload.created_at ? Date.parse(payload.created_at) : Date.now())
        } catch {
          setCodexChatLastTaskEventAt(Date.now())
        }
      }
      scheduleRealtimeRefresh()
    }

    es.addEventListener('notification', onNotification as EventListener)
    es.addEventListener('task_event', onTaskEvent as EventListener)

    return () => {
      es.removeEventListener('notification', onNotification as EventListener)
      es.removeEventListener('task_event', onTaskEvent as EventListener)
      es.close()
    }
  }, [qc, scheduleRealtimeRefresh, showCodexChat, userId, workspaceId])

  React.useEffect(() => {
    if (!isCodexChatRunning || !codexChatRunStartedAt) return
    const id = window.setInterval(() => {
      setCodexChatElapsedSeconds(Math.max(0, Math.floor((Date.now() - codexChatRunStartedAt) / 1000)))
    }, 1000)
    return () => window.clearInterval(id)
  }, [isCodexChatRunning, codexChatRunStartedAt])

  React.useEffect(() => {
    if (!showCodexChat || !codexChatHistoryRef.current) return
    codexChatHistoryRef.current.scrollTop = codexChatHistoryRef.current.scrollHeight
  }, [codexChatTurns, showCodexChat, isCodexChatRunning])

  const board = useQuery({
    queryKey: ['board', userId, selectedProjectId],
    queryFn: () => getProjectBoard(userId, selectedProjectId),
    enabled: Boolean(selectedProjectId && tab === 'projects')
  })

  const selectedTask = React.useMemo(() => tasks.data?.items.find((t) => t.id === selectedTaskId) ?? null, [tasks.data?.items, selectedTaskId])

  React.useEffect(() => {
    if (!selectedTask) return
    setEditStatus(selectedTask.status)
    setEditDescription(selectedTask.description)
    setEditPriority(selectedTask.priority)
    setEditDueDate(toLocalDateTimeInput(selectedTask.due_date))
    setEditProjectId(selectedTask.project_id ?? '')
    setEditTaskType((selectedTask.task_type ?? 'manual') as 'manual' | 'scheduled_instruction')
    setEditScheduledAtUtc(toLocalDateTimeInput(selectedTask.scheduled_at_utc))
    setEditScheduleTimezone(selectedTask.schedule_timezone ?? (bootstrap.data?.current_user?.timezone ?? 'UTC'))
    setEditScheduledInstruction(selectedTask.scheduled_instruction ?? '')
    setAutomationInstruction('')
  }, [bootstrap.data?.current_user?.timezone, selectedTask])

  const comments = useQuery({
    queryKey: ['comments', userId, selectedTaskId],
    queryFn: () => listComments(userId, selectedTaskId as string),
    enabled: Boolean(selectedTaskId)
  })

  const activity = useQuery({
    queryKey: ['activity', userId, selectedTaskId],
    queryFn: () => listActivity(userId, selectedTaskId as string),
    enabled: Boolean(selectedTaskId)
  })

  const automationStatus = useQuery({
    queryKey: ['automation-status', userId, selectedTaskId],
    queryFn: () => getTaskAutomationStatus(userId, selectedTaskId as string),
    enabled: Boolean(selectedTaskId),
    refetchInterval: (q) => {
      const state = (q.state.data as TaskAutomationStatus | undefined)?.automation_state
      if (state === 'queued' || state === 'running') return 2000
      return false
    }
  })

  const invalidateAll = async () => {
    await qc.invalidateQueries({ queryKey: ['tasks'] })
    await qc.invalidateQueries({ queryKey: ['board'] })
    await qc.invalidateQueries({ queryKey: ['bootstrap'] })
    await qc.invalidateQueries({ queryKey: ['notifications'] })
  }

  const createTaskMutation = useMutation({
    mutationFn: () =>
      createTask(userId, {
        title: taskTitle.trim(),
        workspace_id: workspaceId,
        project_id: quickProjectId || (tab === 'projects' ? selectedProjectId || null : null),
        due_date: quickDueDate ? new Date(quickDueDate).toISOString() : null
      }),
    onSuccess: async () => {
      setUiError(null)
      setTaskTitle('')
      setQuickDueDate('')
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Task create failed')
  })

  const completeTaskMutation = useMutation({
    mutationFn: (id: string) => completeTask(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Complete failed')
  })
  const reopenTaskMutation = useMutation({
    mutationFn: (id: string) => reopenTask(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Reopen failed')
  })
  const archiveTaskMutation = useMutation({
    mutationFn: (id: string) => archiveTask(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
      setSelectedTaskId(null)
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Archive failed')
  })
  const restoreTaskMutation = useMutation({
    mutationFn: (id: string) => restoreTask(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
      setSelectedTaskId(null)
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Restore failed')
  })

  const patchTaskMutation = useMutation({
    mutationFn: () =>
      patchTask(userId, selectedTaskId as string, {
        description: editDescription,
        status: editStatus,
        priority: editPriority,
        project_id: editProjectId || null,
        due_date: editDueDate ? new Date(editDueDate).toISOString() : null,
        task_type: editTaskType,
        scheduled_at_utc: editTaskType === 'scheduled_instruction' && editScheduledAtUtc ? new Date(editScheduledAtUtc).toISOString() : null,
        schedule_timezone: editTaskType === 'scheduled_instruction' ? (editScheduleTimezone || null) : null,
        scheduled_instruction: editTaskType === 'scheduled_instruction' ? (editScheduledInstruction.trim() || null) : null
      }),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
      setSelectedTaskId(null)
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Save failed')
  })

  const createProjectMutation = useMutation({
    mutationFn: () => createProject(userId, { workspace_id: workspaceId, name: projectName.trim() }),
    onSuccess: async () => {
      setUiError(null)
      setProjectName('')
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Project create failed')
  })

  const markReadMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Mark read failed')
  })

  const themeMutation = useMutation({
    mutationFn: (nextTheme: 'light' | 'dark') => patchMyPreferences(userId, { theme: nextTheme }),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['bootstrap'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Theme update failed')
  })

  const addCommentMutation = useMutation({
    mutationFn: () => addComment(userId, selectedTaskId as string, commentBody.trim()),
    onSuccess: async () => {
      setUiError(null)
      setCommentBody('')
      await qc.invalidateQueries({ queryKey: ['comments', userId, selectedTaskId] })
      await qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Comment failed')
  })

  const runAutomationMutation = useMutation({
    mutationFn: () => runTaskWithCodex(userId, selectedTaskId as string, automationInstruction.trim()),
    onSuccess: async () => {
      setUiError(null)
      setAutomationInstruction('')
      await qc.invalidateQueries({ queryKey: ['automation-status', userId, selectedTaskId] })
      await qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
      await qc.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Codex run failed')
  })

  const runAgentChatMutation = useMutation({
    mutationFn: (payload: { instruction: string; history: Array<{ role: 'user' | 'assistant'; content: string }> }) =>
      runAgentChat(userId, {
        workspace_id: workspaceId,
        project_id: selectedProjectId || null,
        session_id: codexChatSessionId,
        instruction: payload.instruction,
        history: payload.history,
        allow_mutations: codexChatAllowMutations
      }),
    onSuccess: async (payload) => {
      setUiError(null)
      const reply = [payload.summary, payload.comment].filter(Boolean).join('\n\n').trim()
      if (reply) {
        setCodexChatTurns((prev) => [
          ...prev,
          {
            id: globalThis.crypto?.randomUUID?.() ?? `a-${Date.now()}`,
            role: 'assistant',
            content: reply,
            createdAt: Date.now()
          }
        ])
      }
      setIsCodexChatRunning(false)
      setCodexChatRunStartedAt(null)
      setCodexChatElapsedSeconds(0)
      setCodexChatInstruction('')
      await invalidateAll()
    },
    onError: (err) => {
      setIsCodexChatRunning(false)
      setCodexChatRunStartedAt(null)
      setCodexChatElapsedSeconds(0)
      setUiError(err instanceof Error ? err.message : 'Codex chat failed')
    }
  })

  if (bootstrap.isLoading) return <div className="page"><div className="card skeleton">Loading workspace...</div></div>
  if (bootstrap.isError || !bootstrap.data) return <div className="page"><div className="notice">Unable to load bootstrap data.</div></div>

  const unreadCount = (notifications.data ?? []).filter((n) => !n.is_read).length
  const actorNames = Object.fromEntries((bootstrap.data.users ?? []).map((u) => [u.id, u.username]))

  return (
    <div className="page">
      <header className="header card">
        <div className="title-row">
          <h1 className="title">Task Management</h1>
          <div className="row">
            <span className="badge">Unread: {unreadCount}</span>
            <button className="primary" onClick={() => setShowCodexChat(true)}>Codex Chat</button>
          </div>
        </div>
        <div className="meta">User: <strong>{bootstrap.data.current_user.username}</strong> | Workspace: <strong>{bootstrap.data.workspaces[0]?.name}</strong></div>
      </header>
      {uiError && <div className="notice">{uiError}</div>}

      <section className="card">
        <h2>Quick Add</h2>
        <div className="row wrap">
          <input value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="Task title" />
          <select value={quickProjectId} onChange={(e) => setQuickProjectId(e.target.value)}>
            <option value="">Inbox</option>
            {bootstrap.data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input className="due-input" type="datetime-local" value={quickDueDate} onChange={(e) => setQuickDueDate(e.target.value)} />
          <button className="primary" disabled={!taskTitle.trim()} onClick={() => createTaskMutation.mutate()}>Add</button>
        </div>
      </section>

      {tab === 'projects' && (
        <section className="card">
          <h2>Projects</h2>
          <div className="row" style={{ marginBottom: 8 }}>
            <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}>
              {bootstrap.data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="row">
            <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="New project" />
            <button className="primary" disabled={!projectName.trim()} onClick={() => createProjectMutation.mutate()}>Create</button>
          </div>
          {board.data && (
            <div className="kanban">
              {board.data.statuses.map((status) => (
                <div key={status} className="kanban-col">
                  <div className="kanban-head">
                    <strong>{status}</strong>
                    <span className="meta">{(board.data?.lanes[status] ?? []).length}</span>
                  </div>
                  <div className="kanban-list">
                    {(board.data.lanes[status] ?? []).map((task) => (
                      <div key={task.id} className="kanban-card" onClick={() => setSelectedTaskId(task.id)} role="button">
                        <div><strong>{task.title}</strong></div>
                        <div className="meta">{task.priority}</div>
                        <div className="kanban-actions">
                          {board.data?.statuses.filter((s) => s !== status).slice(0, 3).map((nextStatus) => (
                            <button
                              key={nextStatus}
                              className="status-chip"
                              onClick={(e) => {
                                e.stopPropagation()
                                patchTask(userId, task.id, { status: nextStatus }).then(() => invalidateAll())
                              }}
                            >
                              {nextStatus}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'search' && (
        <section className="card">
          <h2>Search</h2>
          <div className="row wrap">
            <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} placeholder="Search text" />
            <select value={searchStatus} onChange={(e) => setSearchStatus(e.target.value)}>
              <option value="">Any status</option>
              <option value="To do">To do</option>
              <option value="In progress">In progress</option>
              <option value="Done">Done</option>
            </select>
            <select value={searchPriority} onChange={(e) => setSearchPriority(e.target.value)}>
              <option value="">Any priority</option>
              <option value="Low">Low</option>
              <option value="Med">Med</option>
              <option value="High">High</option>
            </select>
            <label className="row archived-toggle">
              <input type="checkbox" checked={searchArchived} onChange={(e) => setSearchArchived(e.target.checked)} />
              Archived only
            </label>
          </div>
        </section>
      )}

      {tab === 'profile' ? (
        <section className="card">
          <h2>Profile</h2>
          <p className="meta">User: {bootstrap.data.current_user.full_name}</p>
          <p className="meta">Theme: {theme}</p>
          <div className="row">
            <button onClick={() => {
              const next = theme === 'light' ? 'dark' : 'light'
              setTheme(next)
              themeMutation.mutate(next)
            }}>
              Toggle Theme
            </button>
          </div>
          <h2 style={{ marginTop: 16 }}>Notifications</h2>
          <div className="note-list">
            {notifications.data?.map((n) => (
              <div key={n.id} className="note">
                <div className="meta">{n.message}</div>
                {!n.is_read && <button onClick={() => markReadMutation.mutate(n.id)}>Read</button>}
              </div>
            ))}
          </div>
        </section>
      ) : tab === 'mario' ? (
        <section className="card">
          <h2>Super Mario (Canvas)</h2>
          <React.Suspense fallback={<div className="notice">Loading Mario...</div>}>
            <MarioView />
          </React.Suspense>
        </section>
      ) : (
        <section className="card">
          <h2>Tasks ({tasks.data?.total ?? 0})</h2>
          <div className="task-list">
            {tasks.data?.items.map((task: Task) => (
              <div key={task.id} className={`task-item ${task.task_type === 'scheduled_instruction' ? 'scheduled' : ''}`}>
                <div className="task-main" role="button" onClick={() => setSelectedTaskId(task.id)}>
                  <strong>{task.title}</strong>
                  <span className="meta">{task.status} | {task.priority} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'}</span>
                  {task.task_type === 'scheduled_instruction' && (
                    <span className="meta">
                      <span className={`badge ${task.schedule_state === 'done' ? 'done' : ''}`}>
                        Scheduled
                      </span>
                      {' '}
                      {task.scheduled_at_utc ? `for ${new Date(task.scheduled_at_utc).toLocaleString()}` : 'time not set'}
                      {' '}
                      ({task.schedule_state})
                    </span>
                  )}
                </div>
                {task.archived ? (
                  <button className="action-icon" onClick={() => restoreTaskMutation.mutate(task.id)} title="Restore" aria-label="Restore">
                    <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
                  </button>
                ) : task.status === 'Done' ? (
                  <button className="action-icon" onClick={() => reopenTaskMutation.mutate(task.id)} title="Reopen" aria-label="Reopen">
                    <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
                  </button>
                ) : (
                  <button className="action-icon" onClick={() => completeTaskMutation.mutate(task.id)} title="Complete" aria-label="Complete">
                    <Icon path="m5 13 4 4L19 7" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <nav className="bottom-tabs">
        <button className={tab === 'inbox' ? 'primary' : ''} onClick={() => setTab('inbox')} title="Inbox" aria-label="Inbox">
          <Icon path="M4 13h4l2 3h4l2-3h4M4 13V6h16v7M4 13v5h16v-5" />
          <span className="tab-label">Inbox</span>
        </button>
        <button className={tab === 'today' ? 'primary' : ''} onClick={() => setTab('today')} title="Today" aria-label="Today">
          <Icon path="M8 3v4M16 3v4M4 10h16M4 5h16v15H4z" />
          <span className="tab-label">Today</span>
        </button>
        <button className={tab === 'projects' ? 'primary' : ''} onClick={() => setTab('projects')} title="Projects" aria-label="Projects">
          <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
          <span className="tab-label">Projects</span>
        </button>
        <button className={tab === 'search' ? 'primary' : ''} onClick={() => setTab('search')} title="Search" aria-label="Search">
          <Icon path="M20 20l-3.5-3.5M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14z" />
          <span className="tab-label">Search</span>
        </button>
        <button className={tab === 'mario' ? 'primary' : ''} onClick={() => setTab('mario')} title="Mario" aria-label="Mario">
          <Icon path="M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z" />
          <span className="tab-label">Mario</span>
        </button>
        <button className={tab === 'profile' ? 'primary' : ''} onClick={() => setTab('profile')} title="Profile" aria-label="Profile">
          <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
          <span className="tab-label">Profile</span>
        </button>
      </nav>

      {selectedTask && (
        <div className="drawer open" onClick={() => setSelectedTaskId(null)}>
          <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
            <h3>{selectedTask.title}</h3>
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <select value={editStatus} onChange={(e) => setEditStatus(e.target.value)}>
                <option value="To do">To do</option>
                <option value="In progress">In progress</option>
                <option value="Done">Done</option>
              </select>
              <select value={editPriority} onChange={(e) => setEditPriority(e.target.value)}>
                <option value="Low">Low</option>
                <option value="Med">Med</option>
                <option value="High">High</option>
              </select>
              <select value={editProjectId} onChange={(e) => setEditProjectId(e.target.value)}>
                <option value="">Inbox</option>
                {bootstrap.data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <input className="due-input" type="datetime-local" value={editDueDate} onChange={(e) => setEditDueDate(e.target.value)} />
              <button className="primary" onClick={() => patchTaskMutation.mutate()}>Save</button>
              {selectedTask.status === 'Done' ? (
                <button className="action-icon" onClick={() => reopenTaskMutation.mutate(selectedTask.id)} title="Reopen" aria-label="Reopen">
                  <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
                </button>
              ) : (
                <button className="action-icon" onClick={() => completeTaskMutation.mutate(selectedTask.id)} title="Complete" aria-label="Complete">
                  <Icon path="m5 13 4 4L19 7" />
                </button>
              )}
              {selectedTask.archived ? (
                <button className="action-icon" onClick={() => restoreTaskMutation.mutate(selectedTask.id)} title="Restore" aria-label="Restore">
                  <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
                </button>
              ) : (
                <button className="action-icon" onClick={() => archiveTaskMutation.mutate(selectedTask.id)} title="Archive" aria-label="Archive">
                  <Icon path="M3 7h18M5 7l1 13h12l1-13M9 7V4h6v3" />
                </button>
              )}
            </div>
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <select value={editTaskType} onChange={(e) => setEditTaskType(e.target.value as 'manual' | 'scheduled_instruction')}>
                <option value="manual">Manual</option>
                <option value="scheduled_instruction">Scheduled instruction</option>
              </select>
              <input
                className="due-input"
                type="datetime-local"
                value={editScheduledAtUtc}
                onChange={(e) => setEditScheduledAtUtc(e.target.value)}
                disabled={editTaskType !== 'scheduled_instruction'}
              />
              <input
                value={editScheduleTimezone}
                onChange={(e) => setEditScheduleTimezone(e.target.value)}
                placeholder="Timezone (e.g. Europe/Sarajevo)"
                disabled={editTaskType !== 'scheduled_instruction'}
              />
            </div>
            <textarea
              value={editScheduledInstruction}
              onChange={(e) => setEditScheduledInstruction(e.target.value)}
              rows={3}
              style={{ width: '100%', marginBottom: 8 }}
              placeholder='Scheduled instruction (executed automatically when due)'
              disabled={editTaskType !== 'scheduled_instruction'}
            />
            {selectedTask.schedule_state && editTaskType === 'scheduled_instruction' && (
              <div className="row wrap" style={{ marginBottom: 8 }}>
                <span className="badge">Schedule: {selectedTask.schedule_state}</span>
                {selectedTask.scheduled_at_utc && <span className="meta">Scheduled for: {new Date(selectedTask.scheduled_at_utc).toLocaleString()}</span>}
                {selectedTask.last_schedule_error && <span className="meta">Last error: {selectedTask.last_schedule_error}</span>}
              </div>
            )}
            <textarea value={editDescription} onChange={(e) => setEditDescription(e.target.value)} rows={4} style={{ width: '100%' }} />
            <h4>Comments</h4>
            <div className="note-list">
              {comments.data?.map((c) => <div className="note" key={`${c.id}-${c.created_at}`}>{c.body}</div>)}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <input value={commentBody} onChange={(e) => setCommentBody(e.target.value)} placeholder="Add comment" />
              <button onClick={() => addCommentMutation.mutate()} disabled={!commentBody.trim()}>Send</button>
            </div>
            <h4>Codex Automation</h4>
            <div className="automation-box">
              <div className="row wrap" style={{ marginBottom: 8 }}>
                <span className={`badge ${automationStatus.data?.automation_state === 'completed' ? 'done' : ''}`}>
                  State: {automationStatus.data?.automation_state ?? 'idle'}
                </span>
                {automationStatus.data?.last_agent_run_at && (
                  <span className="meta">Last run: {new Date(automationStatus.data.last_agent_run_at).toLocaleString()}</span>
                )}
              </div>
              {automationStatus.data?.last_agent_comment && <div className="note">{automationStatus.data.last_agent_comment}</div>}
              {automationStatus.data?.last_agent_error && <div className="notice">Runner error: {automationStatus.data.last_agent_error}</div>}
              <div className="row wrap" style={{ marginTop: 8 }}>
                <textarea
                  value={automationInstruction}
                  onChange={(e) => setAutomationInstruction(e.target.value)}
                  placeholder='Instruction (e.g. "#complete", "update due date", "create related task")'
                  rows={4}
                  style={{ width: '100%' }}
                />
                <button
                  className="primary"
                  onClick={() => runAutomationMutation.mutate()}
                  disabled={runAutomationMutation.isPending || !selectedTaskId}
                >
                  Run with Codex
                </button>
              </div>
            </div>
            <h4>Activity</h4>
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <label className="row archived-toggle">
                <input
                  type="checkbox"
                  checked={activityShowRawDetails}
                  onChange={(e) => setActivityShowRawDetails(e.target.checked)}
                />
                Show raw details JSON
              </label>
            </div>
            <div className="note-list">
              {activity.data?.slice(0, 20).map((a) => {
                const summary = formatActivitySummary(a.action, a.details, actorNames[a.actor_id] || 'Someone')
                const fullDetail = summary.detail || ''
                const isLong = fullDetail.length > 180
                const expanded = activityExpandedIds.has(a.id)
                const visibleDetail = isLong && !expanded ? `${fullDetail.slice(0, 180)}...` : fullDetail
                const tone = activityTone(a.action)
                return (
                  <div key={a.id} className={`note activity-note ${tone}`}>
                    <div>
                      <strong>{summary.title}</strong>
                      <div className="meta">{visibleDetail}</div>
                      {isLong && (
                        <button
                          className="status-chip"
                          onClick={() =>
                            setActivityExpandedIds((prev) => {
                              const next = new Set(prev)
                              if (next.has(a.id)) next.delete(a.id)
                              else next.add(a.id)
                              return next
                            })
                          }
                        >
                          {expanded ? 'Show less' : 'Show more'}
                        </button>
                      )}
                      {activityShowRawDetails && (
                        <pre className="activity-raw-json">{JSON.stringify(a.details, null, 2)}</pre>
                      )}
                      <div className="meta">{toReadableDate(a.created_at)}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {showCodexChat && (
        <div className="drawer open" onClick={() => setShowCodexChat(false)}>
          <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
            <h3>Codex Chat</h3>
            <p className="meta">General instruction mode. Session: <code>{codexChatSessionId}</code></p>
            <div className="codex-chat-history" ref={codexChatHistoryRef}>
              {codexChatTurns.length === 0 && (
                <div className="meta">Chat je prazan. Pošalji prvu instrukciju.</div>
              )}
              {codexChatTurns.map((turn) => (
                <div key={turn.id} className={`codex-chat-bubble ${turn.role}`}>
                  <div className="codex-chat-role">{turn.role === 'user' ? 'Ti' : 'Codex'}</div>
                  <div>{turn.content}</div>
                </div>
              ))}
            </div>
            <textarea
              value={codexChatInstruction}
              onChange={(e) => setCodexChatInstruction(e.target.value)}
              rows={5}
              style={{ width: '100%', marginTop: 8 }}
              placeholder='Example: "Create 3 tasks for tomorrow in project Test2 with High priority"'
            />
            <label className="row archived-toggle" style={{ marginTop: 8 }}>
              <input
                type="checkbox"
                checked={codexChatAllowMutations}
                onChange={(e) => setCodexChatAllowMutations(e.target.checked)}
                disabled={runAgentChatMutation.isPending}
              />
              Allow task/project changes
            </label>
            <div className="row" style={{ marginTop: 8 }}>
              <button
                className="primary"
                onClick={() => {
                  const instruction = codexChatInstruction.trim()
                  if (!instruction) return
                  const nextUserTurn: ChatTurn = {
                    id: globalThis.crypto?.randomUUID?.() ?? `u-${Date.now()}`,
                    role: 'user',
                    content: instruction,
                    createdAt: Date.now()
                  }
                  const history = [...codexChatTurns, nextUserTurn]
                    .slice(-16)
                    .map((t) => ({ role: t.role, content: t.content }))
                  setCodexChatTurns((prev) => [...prev, nextUserTurn])
                  setIsCodexChatRunning(true)
                  setCodexChatRunStartedAt(Date.now())
                  setCodexChatElapsedSeconds(0)
                  runAgentChatMutation.mutate({ instruction, history })
                }}
                disabled={runAgentChatMutation.isPending || !codexChatInstruction.trim() || !workspaceId}
              >
                Send to Codex
              </button>
              <button
                onClick={() => setCodexChatTurns([])}
                disabled={runAgentChatMutation.isPending || codexChatTurns.length === 0}
              >
                Clear chat
              </button>
              <button onClick={() => setShowCodexChat(false)}>Close</button>
            </div>
            <div className="row wrap" style={{ marginTop: 8 }}>
              <span className={`badge ${runAgentChatMutation.isPending ? '' : 'done'}`}>
                {isCodexChatRunning ? 'Codex running' : 'Idle'}
              </span>
              <span className="meta">Mode: {codexChatAllowMutations ? 'Write enabled' : 'Read-only'}</span>
              {isCodexChatRunning && (
                <span className="meta codex-progress">Executing tools... {codexChatElapsedSeconds}s</span>
              )}
              {codexChatLastTaskEventAt && (
                <span className="meta">Last task event: {new Date(codexChatLastTaskEventAt).toLocaleTimeString()}</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
)
