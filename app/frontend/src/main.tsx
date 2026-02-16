import React from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addComment,
  archiveTask,
  completeTask,
  createProject,
  createTask,
  createNote,
  deleteNote,
  deleteProject,
  getTaskAutomationStatus,
  getBootstrap,
  getNotifications,
  getProjectBoard,
  getNotes,
  getTasks,
  listActivity,
  listComments,
  markNotificationRead,
  patchNote,
  patchMyPreferences,
  patchTask,
  pinNote,
  restoreNote,
  restoreTask,
  reopenTask,
  runAgentChat,
  runTaskWithCodex,
  unpinNote,
  archiveNote
} from './api'
import type { Notification, Note, Task, TaskAutomationStatus } from './types'
import { MarkdownView } from './markdown/MarkdownView'
import './styles.css'

const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000001'

type Tab = 'today' | 'tasks' | 'notes' | 'projects' | 'search' | 'profile'
type ChatRole = 'user' | 'assistant'
type ChatTurn = { id: string; role: ChatRole; content: string; createdAt: number }

const TAB_ORDER: Tab[] = ['today', 'tasks', 'notes', 'projects', 'search', 'profile']

function normalizeStoredUserId(raw: string | null): string {
  if (!raw || raw === '1' || raw === '2') return DEFAULT_USER_ID
  return raw
}

function parseStoredTab(raw: string | null): Tab {
  if (raw && TAB_ORDER.includes(raw as Tab)) return raw as Tab
  return 'tasks'
}

function parseStoredProjectId(raw: string | null): string {
  if (!raw) return ''
  return raw
}

function parseStoredProjectsMode(raw: string | null): 'board' | 'list' {
  if (raw === 'list') return 'list'
  return 'board'
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

function toUserDateTime(iso: unknown, timezone: string | undefined): string {
  if (typeof iso !== 'string' || !iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: timezone || 'UTC',
    }).format(d)
  } catch {
    return d.toLocaleString()
  }
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

function priorityTone(priority: string): 'low' | 'med' | 'high' {
  const p = String(priority || '').trim().toLowerCase()
  if (p === 'high') return 'high'
  if (p === 'low') return 'low'
  return 'med'
}

function Icon({ path }: { path: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

function parseCommaTags(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const t of String(raw || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)) {
    const key = t.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(t)
  }
  return out
}

function tagHue(tag: string): number {
  // Deterministic hash -> hue for consistent chip coloring.
  let h = 0
  const s = String(tag || '')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  // Avoid harsh reds by snapping into a cool palette.
  const palette = [150, 170, 190, 205, 220, 235, 250, 265]
  return palette[h % palette.length] ?? 205
}

const queryClient = new QueryClient()

function App() {
  const [userId] = React.useState<string>(() => normalizeStoredUserId(localStorage.getItem('user_id')))
  const [tab, setTab] = React.useState<Tab>(() => parseStoredTab(localStorage.getItem('ui_tab')))
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light')
  const [taskTitle, setTaskTitle] = React.useState('')
  const [quickDueDate, setQuickDueDate] = React.useState('')
  const [projectName, setProjectName] = React.useState('')
  const [selectedProjectId, setSelectedProjectId] = React.useState<string>(() =>
    parseStoredProjectId(localStorage.getItem('ui_selected_project_id'))
  )
  const [quickProjectId, setQuickProjectId] = React.useState<string>('')
  const [quickTaskTags, setQuickTaskTags] = React.useState<string[]>([])
  const [showQuickTaskTagPicker, setShowQuickTaskTagPicker] = React.useState(false)
  const [quickTaskTagQuery, setQuickTaskTagQuery] = React.useState('')
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  const [selectedNoteId, setSelectedNoteId] = React.useState<string | null>(null)
  const [searchQ, setSearchQ] = React.useState('')
  const [searchStatus, setSearchStatus] = React.useState('')
  const [searchPriority, setSearchPriority] = React.useState('')
  const [searchTags, setSearchTags] = React.useState<string[]>([])
  const [searchArchived, setSearchArchived] = React.useState(false)
  const [noteQ, setNoteQ] = React.useState('')
  const [noteTags, setNoteTags] = React.useState<string[]>([])
  const [noteArchived, setNoteArchived] = React.useState(false)
  const [notePinnedFilter, setNotePinnedFilter] = React.useState<'any' | 'pinned' | 'unpinned'>('any')
  const [editNoteTitle, setEditNoteTitle] = React.useState('')
  const [editNoteBody, setEditNoteBody] = React.useState('')
  const [editNoteTags, setEditNoteTags] = React.useState('')
  const [showTagPicker, setShowTagPicker] = React.useState(false)
  const [tagPickerQuery, setTagPickerQuery] = React.useState('')
  const [noteEditorView, setNoteEditorView] = React.useState<'write' | 'preview'>('preview')
  const [commentBody, setCommentBody] = React.useState('')
  const [expandedCommentIds, setExpandedCommentIds] = React.useState<Set<string>>(new Set())
  const [automationInstruction, setAutomationInstruction] = React.useState('')
  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatInstruction, setCodexChatInstruction] = React.useState('')
  const [codexChatTurns, setCodexChatTurns] = React.useState<ChatTurn[]>([])
  const [codexChatSessionId] = React.useState<string>(() => globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}`)
  const [isCodexChatRunning, setIsCodexChatRunning] = React.useState(false)
  const [codexChatRunStartedAt, setCodexChatRunStartedAt] = React.useState<number | null>(null)
  const [codexChatElapsedSeconds, setCodexChatElapsedSeconds] = React.useState(0)
  const [codexChatLastTaskEventAt, setCodexChatLastTaskEventAt] = React.useState<number | null>(null)
  const [fabHidden, setFabHidden] = React.useState(false)
  const [showNotificationsPanel, setShowNotificationsPanel] = React.useState(false)
  const [showQuickAdd, setShowQuickAdd] = React.useState(false)
  const [projectsMode, setProjectsMode] = React.useState<'board' | 'list'>(() =>
    parseStoredProjectsMode(localStorage.getItem('ui_projects_mode'))
  )
  const [editStatus, setEditStatus] = React.useState('To do')
  const [editDescription, setEditDescription] = React.useState('')
  const [editPriority, setEditPriority] = React.useState('Med')
  const [editDueDate, setEditDueDate] = React.useState('')
  const [editProjectId, setEditProjectId] = React.useState('')
  const [editTaskTags, setEditTaskTags] = React.useState<string[]>([])
  const [showTaskTagPicker, setShowTaskTagPicker] = React.useState(false)
  const [taskTagPickerQuery, setTaskTagPickerQuery] = React.useState('')
  const [editTaskType, setEditTaskType] = React.useState<'manual' | 'scheduled_instruction'>('manual')
  const [editScheduledAtUtc, setEditScheduledAtUtc] = React.useState('')
  const [editScheduleTimezone, setEditScheduleTimezone] = React.useState('')
  const [editScheduledInstruction, setEditScheduledInstruction] = React.useState('')
  const [editRecurringEvery, setEditRecurringEvery] = React.useState('')
  const [editRecurringUnit, setEditRecurringUnit] = React.useState<'m' | 'h' | 'd'>('h')
  const [activityExpandedIds, setActivityExpandedIds] = React.useState<Set<number>>(new Set())
  const [activityShowRawDetails, setActivityShowRawDetails] = React.useState(false)
  const [uiError, setUiError] = React.useState<string | null>(null)
  const qc = useQueryClient()
  const realtimeRefreshTimerRef = React.useRef<number | null>(null)
  const codexChatHistoryRef = React.useRef<HTMLDivElement | null>(null)
  const commentInputRef = React.useRef<HTMLTextAreaElement | null>(null)
  const fabIdleTimerRef = React.useRef<number | null>(null)

  React.useEffect(() => {
    localStorage.setItem('ui_tab', tab)
  }, [tab])

  React.useEffect(() => {
    localStorage.setItem('ui_selected_project_id', selectedProjectId)
  }, [selectedProjectId])

  React.useEffect(() => {
    let raf = 0
    const onAnyScroll = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        setFabHidden(true)
        if (fabIdleTimerRef.current) window.clearTimeout(fabIdleTimerRef.current)
        fabIdleTimerRef.current = window.setTimeout(() => setFabHidden(false), 650)
      })
    }
    // Capture scroll events from ANY scroll container (not just window).
    document.addEventListener('scroll', onAnyScroll, { passive: true, capture: true })
    return () => {
      if (raf) cancelAnimationFrame(raf)
      document.removeEventListener('scroll', onAnyScroll, { capture: true } as any)
      if (fabIdleTimerRef.current) window.clearTimeout(fabIdleTimerRef.current)
    }
  }, [])

  React.useEffect(() => {
    localStorage.setItem('ui_projects_mode', projectsMode)
  }, [projectsMode])

  React.useEffect(() => {
    if (tab === 'notes') setSelectedTaskId(null)
  }, [tab])

  React.useEffect(() => {
    setShowNotificationsPanel(false)
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
  const userTimezone = bootstrap.data?.current_user?.timezone
  const selectedProject = React.useMemo(
    () => bootstrap.data?.projects.find((p) => p.id === selectedProjectId) ?? null,
    [bootstrap.data?.projects, selectedProjectId]
  )

  React.useEffect(() => {
    const firstProjectId = bootstrap.data?.projects[0]?.id ?? ''
    const validSelected = Boolean(selectedProjectId && (bootstrap.data?.projects ?? []).some((p) => p.id === selectedProjectId))
    if ((!selectedProjectId || !validSelected) && firstProjectId) setSelectedProjectId(firstProjectId)
    if (!quickProjectId && firstProjectId) setQuickProjectId(firstProjectId)
  }, [bootstrap.data, quickProjectId, selectedProjectId])

  const taskParams = React.useMemo(() => {
    if (!selectedProjectId) return null
    if (tab === 'today') return { project_id: selectedProjectId, view: 'today' }
    if (tab === 'tasks') return { project_id: selectedProjectId, tags: searchTags }
    if (tab === 'search') {
      return {
        project_id: selectedProjectId,
        q: searchQ || undefined,
        status: searchStatus || undefined,
        priority: searchPriority || undefined,
        tags: searchTags,
        archived: searchArchived,
      }
    }
    return null
  }, [tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived, searchTags])

  const tasks = useQuery({
    queryKey: ['tasks', userId, workspaceId, tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived, searchTags.join(',')],
    queryFn: () => getTasks(userId, workspaceId, taskParams as { project_id: string; view?: string; q?: string; status?: string; priority?: string; tags?: string[]; archived?: boolean }),
    enabled: Boolean(workspaceId && taskParams) && (tab === 'today' || tab === 'tasks' || tab === 'search')
  })

  const notesPinnedParam = React.useMemo(() => {
    if (notePinnedFilter === 'pinned') return true
    if (notePinnedFilter === 'unpinned') return false
    return null
  }, [notePinnedFilter])

  const notes = useQuery({
    queryKey: ['notes', userId, workspaceId, selectedProjectId, noteQ, noteArchived, notePinnedFilter, noteTags.join(',')],
    queryFn: () =>
      getNotes(userId, workspaceId, {
        project_id: selectedProjectId,
        q: noteQ || undefined,
        tags: noteTags,
        archived: noteArchived,
        pinned: notesPinnedParam
      }),
    enabled: Boolean(workspaceId && selectedProjectId) && tab === 'notes'
  })
  const projectTaskCountQueries = useQueries({
    queries: (bootstrap.data?.projects ?? []).map((project) => ({
      queryKey: ['project-task-count', userId, workspaceId, project.id],
      queryFn: () => getTasks(userId, workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
      enabled: Boolean(workspaceId && tab === 'projects')
    }))
  })
  const projectNoteCountQueries = useQueries({
    queries: (bootstrap.data?.projects ?? []).map((project) => ({
      queryKey: ['project-note-count', userId, workspaceId, project.id],
      queryFn: () => getNotes(userId, workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
      enabled: Boolean(workspaceId && tab === 'projects')
    }))
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
    enabled: Boolean(selectedProjectId && tab === 'tasks' && projectsMode === 'board')
  })

  const selectedTask = React.useMemo(() => tasks.data?.items.find((t) => t.id === selectedTaskId) ?? null, [tasks.data?.items, selectedTaskId])
  const selectedNote = React.useMemo(() => notes.data?.items.find((n) => n.id === selectedNoteId) ?? null, [notes.data?.items, selectedNoteId])

  const taskTagSuggestions = React.useMemo(() => {
    const counts = new Map<string, number>()
    for (const t of tasks.data?.items ?? []) {
      for (const label of t.labels ?? []) {
        const k = String(label || '').trim()
        if (!k) continue
        counts.set(k, (counts.get(k) ?? 0) + 1)
      }
    }
    // If board is loaded, include tags from kanban items too.
    for (const laneTasks of Object.values(board.data?.lanes ?? {})) {
      for (const t of laneTasks ?? []) {
        for (const label of (t as any).labels ?? []) {
          const k = String(label || '').trim()
          if (!k) continue
          counts.set(k, (counts.get(k) ?? 0) + 1)
        }
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 40)
      .map(([t]) => t)
  }, [board.data?.lanes, tasks.data?.items])
  const noteTagSuggestions = React.useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of notes.data?.items ?? []) {
      for (const t of n.tags ?? []) {
        const k = String(t || '').trim()
        if (!k) continue
        counts.set(k, (counts.get(k) ?? 0) + 1)
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 24)
      .map(([t]) => t)
  }, [notes.data?.items])
  const toggleSearchTag = React.useCallback((tag: string) => {
    const cleaned = String(tag || '').trim().toLowerCase()
    if (!cleaned) return
    setSearchTags((prev) => (prev.includes(cleaned) ? prev.filter((t) => t !== cleaned) : [...prev, cleaned]))
  }, [])
  const toggleNoteFilterTag = React.useCallback((tag: string) => {
    const cleaned = String(tag || '').trim().toLowerCase()
    if (!cleaned) return
    setNoteTags((prev) => (prev.includes(cleaned) ? prev.filter((t) => t !== cleaned) : [...prev, cleaned]))
  }, [])

  const addNoteTag = React.useCallback(
    (raw: string) => {
      const cleaned = String(raw || '').trim().replace(/,+$/, '')
      if (!cleaned) return
      const current = parseCommaTags(editNoteTags)
      const next = parseCommaTags([...current, cleaned].join(', '))
      setEditNoteTags(next.join(', '))
      setTagPickerQuery('')
    },
    [editNoteTags]
  )

  const currentNoteTags = React.useMemo(() => parseCommaTags(editNoteTags), [editNoteTags])
  const currentNoteTagsLower = React.useMemo(() => new Set(currentNoteTags.map((t) => t.toLowerCase())), [currentNoteTags])
  const toggleNoteTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = currentNoteTagsLower.has(lower)
      const next = exists ? currentNoteTags.filter((t) => t.toLowerCase() !== lower) : [...currentNoteTags, cleaned]
      setEditNoteTags(parseCommaTags(next.join(', ')).join(', '))
    },
    [currentNoteTags, currentNoteTagsLower]
  )
  const allNoteTags = React.useMemo(() => {
    const set = new Set<string>()
    const out: string[] = []
    for (const t of [...noteTagSuggestions, ...currentNoteTags]) {
      const cleaned = String(t || '').trim()
      if (!cleaned) continue
      const key = cleaned.toLowerCase()
      if (set.has(key)) continue
      set.add(key)
      out.push(cleaned)
    }
    return out
  }, [currentNoteTags, noteTagSuggestions])
  const filteredNoteTags = React.useMemo(() => {
    const q = tagPickerQuery.trim().toLowerCase()
    const base = q ? allNoteTags.filter((t) => t.toLowerCase().includes(q)) : allNoteTags
    return base.slice(0, 40)
  }, [allNoteTags, tagPickerQuery])
  const canCreateTag = React.useMemo(() => {
    const q = tagPickerQuery.trim()
    if (!q) return false
    return !allNoteTags.some((t) => t.toLowerCase() === q.toLowerCase())
  }, [allNoteTags, tagPickerQuery])

  const toggleTaskTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = editTaskTags.some((t) => t.toLowerCase() === lower)
      const next = exists ? editTaskTags.filter((t) => t.toLowerCase() !== lower) : [...editTaskTags, cleaned]
      setEditTaskTags(parseCommaTags(next.join(', ')))
    },
    [editTaskTags]
  )
  const toggleQuickTaskTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const exists = quickTaskTags.some((t) => t.toLowerCase() === lower)
      const next = exists ? quickTaskTags.filter((t) => t.toLowerCase() !== lower) : [...quickTaskTags, cleaned]
      setQuickTaskTags(parseCommaTags(next.join(', ')))
    },
    [quickTaskTags]
  )

  const filteredTaskTags = React.useMemo(() => {
    const q = taskTagPickerQuery.trim().toLowerCase()
    const base = q ? taskTagSuggestions.filter((t) => t.toLowerCase().includes(q)) : taskTagSuggestions
    return base.slice(0, 50)
  }, [taskTagPickerQuery, taskTagSuggestions])
  const taskTagsLower = React.useMemo(() => new Set(editTaskTags.map((t) => t.toLowerCase())), [editTaskTags])
  const canCreateTaskTag = React.useMemo(() => {
    const q = taskTagPickerQuery.trim()
    if (!q) return false
    return !taskTagSuggestions.some((t) => t.toLowerCase() === q.toLowerCase())
  }, [taskTagPickerQuery, taskTagSuggestions])

  const filteredQuickTaskTags = React.useMemo(() => {
    const q = quickTaskTagQuery.trim().toLowerCase()
    const base = q ? taskTagSuggestions.filter((t) => t.toLowerCase().includes(q)) : taskTagSuggestions
    return base.slice(0, 50)
  }, [quickTaskTagQuery, taskTagSuggestions])
  const quickTaskTagsLower = React.useMemo(() => new Set(quickTaskTags.map((t) => t.toLowerCase())), [quickTaskTags])
  const canCreateQuickTaskTag = React.useMemo(() => {
    const q = quickTaskTagQuery.trim()
    if (!q) return false
    return !taskTagSuggestions.some((t) => t.toLowerCase() === q.toLowerCase())
  }, [quickTaskTagQuery, taskTagSuggestions])

  React.useEffect(() => {
    if (!selectedTask) return
    setEditStatus(selectedTask.status)
    setEditDescription(selectedTask.description)
    setEditPriority(selectedTask.priority)
    setEditDueDate(toLocalDateTimeInput(selectedTask.due_date))
    setEditProjectId(selectedTask.project_id)
    setEditTaskTags(selectedTask.labels ?? [])
    setShowTaskTagPicker(false)
    setTaskTagPickerQuery('')
    setEditTaskType((selectedTask.task_type ?? 'manual') as 'manual' | 'scheduled_instruction')
    setEditScheduledAtUtc(toLocalDateTimeInput(selectedTask.scheduled_at_utc))
    setEditScheduleTimezone(selectedTask.schedule_timezone ?? (bootstrap.data?.current_user?.timezone ?? 'UTC'))
    setEditScheduledInstruction(selectedTask.scheduled_instruction ?? '')
	    ;(() => {
	      const raw = String(selectedTask.recurring_rule ?? '').trim()
	      const m = raw.match(/^(?:every:)?\s*(\d+)\s*([mhd])\s*$/i)
	      if (!m) {
	        setEditRecurringEvery('')
	        setEditRecurringUnit('h')
	        return
	      }
	      setEditRecurringEvery(String(m[1] || ''))
	      const unit = String(m[2] || 'h').toLowerCase()
	      setEditRecurringUnit(unit === 'm' || unit === 'h' || unit === 'd' ? unit : 'h')
	    })()
    setAutomationInstruction('')
    setCommentBody('')
    setExpandedCommentIds(new Set())
    // Helpful default: focus comment box when opening a task.
    window.setTimeout(() => commentInputRef.current?.focus(), 0)
  }, [bootstrap.data?.current_user?.timezone, selectedTask])

  // Notes uses an accordion: do not auto-open a note.

  React.useEffect(() => {
    if (!selectedNote) return
    setEditNoteTitle(selectedNote.title ?? '')
    setEditNoteBody(selectedNote.body ?? '')
    setEditNoteTags((selectedNote.tags ?? []).join(', '))
    setTagPickerQuery('')
    setShowTagPicker(false)
    setNoteEditorView('preview')
  }, [selectedNote])

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
    await qc.invalidateQueries({ queryKey: ['notes'] })
    await qc.invalidateQueries({ queryKey: ['board'] })
    await qc.invalidateQueries({ queryKey: ['bootstrap'] })
    await qc.invalidateQueries({ queryKey: ['notifications'] })
  }

  const createTaskMutation = useMutation({
    mutationFn: () =>
      createTask(userId, {
        title: taskTitle.trim(),
        workspace_id: workspaceId,
        project_id: quickProjectId || selectedProjectId,
        due_date: quickDueDate ? new Date(quickDueDate).toISOString() : null,
        labels: quickTaskTags
      }),
    onSuccess: async () => {
      setUiError(null)
      setTaskTitle('')
      setQuickDueDate('')
      setQuickTaskTags([])
      setShowQuickTaskTagPicker(false)
      setQuickTaskTagQuery('')
      setShowQuickAdd(false)
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
        project_id: editProjectId || selectedTask?.project_id,
        labels: editTaskTags,
        due_date: editDueDate ? new Date(editDueDate).toISOString() : null,
        task_type: editTaskType,
        scheduled_at_utc: editTaskType === 'scheduled_instruction' && editScheduledAtUtc ? new Date(editScheduledAtUtc).toISOString() : null,
        schedule_timezone: editTaskType === 'scheduled_instruction' ? (editScheduleTimezone || null) : null,
        scheduled_instruction: editTaskType === 'scheduled_instruction' ? (editScheduledInstruction.trim() || null) : null,
        recurring_rule:
          editTaskType === 'scheduled_instruction' && editRecurringEvery.trim()
            ? `every:${Math.max(1, Number(editRecurringEvery) || 1)}${editRecurringUnit}`
            : null
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

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: string) => deleteProject(userId, projectId),
    onSuccess: async () => {
      setUiError(null)
      await invalidateAll()
      // If selected project was deleted, bootstrap effect will select first remaining.
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Project delete failed')
  })

  const createNoteMutation = useMutation({
    mutationFn: () =>
      createNote(userId, {
        title: 'Untitled',
        workspace_id: workspaceId,
        project_id: selectedProjectId,
        body: ''
      }),
    onSuccess: async (note) => {
      setUiError(null)
      setTab('notes')
      setSelectedNoteId(note.id)
      setShowTagPicker(true)
      setTagPickerQuery('')
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Note create failed')
  })

  const patchNoteMutation = useMutation({
    mutationFn: () =>
      patchNote(userId, selectedNoteId as string, {
        title: editNoteTitle.trim() || 'Untitled',
        body: editNoteBody,
        tags: editNoteTags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean)
      }),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Note save failed')
  })

  const pinNoteMutation = useMutation({
    mutationFn: (id: string) => pinNote(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Pin failed')
  })

  const unpinNoteMutation = useMutation({
    mutationFn: (id: string) => unpinNote(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Unpin failed')
  })

  const archiveNoteMutation = useMutation({
    mutationFn: (id: string) => archiveNote(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Archive note failed')
  })

  const restoreNoteMutation = useMutation({
    mutationFn: (id: string) => restoreNote(userId, id),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Restore note failed')
  })

  const deleteNoteMutation = useMutation({
    mutationFn: (id: string) => deleteNote(userId, id),
    onSuccess: async () => {
      setUiError(null)
      setSelectedNoteId(null)
      await qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Delete note failed')
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
        project_id: selectedProjectId,
        session_id: codexChatSessionId,
        instruction: payload.instruction,
        history: payload.history,
        // Always allow normal (write-enabled) mode; no read-only toggle in UI.
        allow_mutations: true
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
      // If Codex reports a failure, surface it in UI as well (in addition to the chat bubble).
      if (payload.ok === false) {
        setUiError(payload.summary || payload.comment || 'Codex request failed')
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
      const msg = err instanceof Error ? err.message : 'Codex chat failed'
      setUiError(msg)
      // Also show the error inline in chat; otherwise it feels like "nothing happened".
      setCodexChatTurns((prev) => [
        ...prev,
        {
          id: globalThis.crypto?.randomUUID?.() ?? `aerr-${Date.now()}`,
          role: 'assistant',
          content: `Error: ${msg}`,
          createdAt: Date.now()
        }
      ])
    }
  })

  if (bootstrap.isLoading) return <div className="page"><div className="card skeleton">Loading workspace...</div></div>
  if (bootstrap.isError || !bootstrap.data) return <div className="page"><div className="notice">Unable to load bootstrap data.</div></div>

  const unreadCount = (notifications.data ?? []).filter((n) => !n.is_read).length
  const actorNames = Object.fromEntries((bootstrap.data.users ?? []).map((u) => [u.id, u.username]))
  const projectNames = Object.fromEntries((bootstrap.data.projects ?? []).map((p) => [p.id, p.name]))

  return (
    <div className="page">
      <header className="header card">
        <div className="title-row">
          <div className="brand" role="banner">
            <div className="brand-mark" aria-hidden="true">m</div>
            <div className="brand-stack">
              <div className="brand-name">m4tr1x</div>
              <div className="brand-sub">tasks + notes</div>
            </div>
          </div>

          <div className="brand-meta" aria-label="Context">
            <div className="brand-meta-row">
              <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
              <span className="brand-meta-text">
                <strong>{bootstrap.data.current_user.username}</strong>
              </span>
            </div>
            <div className="brand-meta-row">
              <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
              <span className="brand-meta-text">
                <strong>{bootstrap.data.workspaces[0]?.name}</strong>
              </span>
            </div>
          </div>

          <div className="top-actions">
            <button onClick={() => setTab('profile')} title="Profile" aria-label="Profile">
              <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
            </button>
            <button
              className={showNotificationsPanel ? 'primary' : ''}
              onClick={() => setShowNotificationsPanel((v) => !v)}
              title="Notifications"
              aria-label="Notifications"
            >
              <Icon path="M12 22a2 2 0 0 0 2-2H10a2 2 0 0 0 2 2zm6-6V11a6 6 0 1 0-12 0v5L4 18v1h16v-1l-2-2z" />
              {unreadCount > 0 && <span className="notif-dot">{Math.min(99, unreadCount)}</span>}
            </button>
          </div>
        </div>
        <div className="header-lower">
          <div className="top-search-wrap" role="search">
            <Icon path="M20 20l-3.5-3.5M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14z" />
            <input
              className="top-search"
              value={searchQ}
              onChange={(e) => {
                setSearchQ(e.target.value)
                if (tab !== 'search') setTab('search')
              }}
              placeholder="Search tasks..."
            />
          </div>
          <div className="header-project-scope">
            <span className="meta">Project</span>
            <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}>
              {bootstrap.data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="action-icon" onClick={() => setTab('projects')} title="Manage projects" aria-label="Manage projects">
              <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
            </button>
          </div>
        </div>
        {showNotificationsPanel && (
          <div className="header-panel">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="row" style={{ gap: 10 }}>
                <strong>Notifications</strong>
                <span className="meta">{unreadCount} unread</span>
              </div>
              <button className="action-icon" onClick={() => setShowNotificationsPanel(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <div className="notifications-list" style={{ marginTop: 10 }}>
              {(notifications.data ?? []).length === 0 ? (
                <div className="meta">No notifications.</div>
              ) : (
                (notifications.data ?? []).map((n) => (
                  <div key={n.id} className={`notif ${n.is_read ? 'read' : 'unread'}`}>
                    <div className="notif-dotline" aria-hidden="true" />
                    <div className="notif-main">
                      <div className="notif-message">{n.message}</div>
                      <div className="notif-actions">
                        {!n.is_read && (
                          <button className="status-chip" onClick={() => markReadMutation.mutate(n.id)}>
                            Mark read
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </header>
      {uiError && <div className="notice">{uiError}</div>}

	      {showQuickAdd && (
	        <div className="drawer open" onClick={() => setShowQuickAdd(false)}>
	          <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
	            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
	              <h3 style={{ margin: 0 }}>New Task</h3>
	              <button className="action-icon" onClick={() => setShowQuickAdd(false)} title="Close" aria-label="Close">
	                <Icon path="M6 6l12 12M18 6 6 18" />
	              </button>
	            </div>
		            <div className="quickadd-form">
	              <input
	                className="quickadd-title"
	                value={taskTitle}
	                onChange={(e) => setTaskTitle(e.target.value)}
	                onKeyDown={(e) => {
		                  if (e.key === 'Enter' && !e.shiftKey) {
		                    const title = taskTitle.trim()
		                    if (!title || !quickProjectId || createTaskMutation.isPending) return
		                    createTaskMutation.mutate()
		                  }
	                }}
	                placeholder="Task title"
	                autoFocus
	              />
		              <select value={quickProjectId} onChange={(e) => setQuickProjectId(e.target.value)}>
		                {bootstrap.data.projects.map((p) => (
	                  <option key={p.id} value={p.id}>
	                    {p.name}
	                  </option>
	                ))}
	              </select>
	              <div className={`quickadd-due ${quickDueDate ? 'has-value' : ''}`}>
	                <span className="quickadd-due-placeholder">Due date</span>
	                <input
	                  className="due-input"
	                  type="datetime-local"
	                  value={quickDueDate}
	                  onChange={(e) => setQuickDueDate(e.target.value)}
	                  aria-label="Due date"
	                />
	              </div>
		              <button
		                className="action-icon primary quickadd-create"
			                disabled={!taskTitle.trim() || !quickProjectId || createTaskMutation.isPending}
		                onClick={() => createTaskMutation.mutate()}
		                title="Create task"
		                aria-label="Create task"
		              >
		                <Icon path="M12 5v14M5 12h14" />
		              </button>
		            </div>
		            <div className="tag-bar" aria-label="Task tags" style={{ marginTop: 10 }}>
		              <div className="tag-chiplist">
		                {quickTaskTags.length === 0 ? (
		                  <span className="meta">No tags</span>
		                ) : (
		                  quickTaskTags.map((t) => (
		                    <span
		                      key={t}
		                      className="tag-chip"
		                      style={{
		                        background: `linear-gradient(135deg, hsl(${tagHue(t)}, 70%, 92%), hsl(${tagHue(t)}, 70%, 86%))`,
		                        borderColor: `hsl(${tagHue(t)}, 70%, 74%)`,
		                        color: `hsl(${tagHue(t)}, 55%, 22%)`
		                      }}
		                    >
		                      <span className="tag-text">{t}</span>
		                    </span>
		                  ))
		                )}
		              </div>
		              <button
		                className="action-icon"
		                onClick={() => setShowQuickTaskTagPicker(true)}
		                title="Edit tags"
		                aria-label="Edit tags"
		              >
		                <Icon path="M3 12h8m-8 6h12m-12-12h18" />
		              </button>
		            </div>
		            <div className="meta" style={{ marginTop: 10 }}>
		              Tip: you can also ask Codex Chat to create tasks in bulk.
		            </div>
		          </div>
		        </div>
		      )}

		      {showQuickTaskTagPicker && (
		        <div className="drawer open" onClick={() => setShowQuickTaskTagPicker(false)}>
		          <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
		            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
		              <h3 style={{ margin: 0 }}>Task Tags</h3>
		              <button className="action-icon" onClick={() => setShowQuickTaskTagPicker(false)} title="Close" aria-label="Close">
		                <Icon path="M6 6l12 12M18 6 6 18" />
		              </button>
		            </div>
		            <input
		              value={quickTaskTagQuery}
		              onChange={(e) => setQuickTaskTagQuery(e.target.value)}
		              placeholder="Search or create tag"
		              autoFocus
		            />
		            <div className="tag-picker-list" role="listbox" aria-label="Tag list">
		              {filteredQuickTaskTags.map((t) => {
		                const selected = quickTaskTagsLower.has(t.toLowerCase())
		                return (
		                  <button
		                    key={t}
		                    className={`tag-picker-item ${selected ? 'selected' : ''}`}
		                    onClick={() => toggleQuickTaskTag(t)}
		                    aria-label={selected ? `Remove tag ${t}` : `Add tag ${t}`}
		                    title={selected ? 'Remove tag' : 'Add tag'}
		                  >
		                    <span className="tag-picker-check" aria-hidden="true">
		                      <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
		                    </span>
		                    <span className="tag-picker-name">{t}</span>
		                  </button>
		                )
		              })}
		              {filteredQuickTaskTags.length === 0 && <div className="meta">No tags found.</div>}
		            </div>
		            {canCreateQuickTaskTag && (
		              <button className="primary tag-picker-create" onClick={() => toggleQuickTaskTag(quickTaskTagQuery)} title="Create tag" aria-label="Create tag">
		                Create "{quickTaskTagQuery.trim()}"
		              </button>
		            )}
		          </div>
		        </div>
		      )}

      {tab === 'tasks' && (
        <section className="card">
          <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Tasks</h2>
            <div className="seg" role="tablist" aria-label="Task view mode">
              <button
                className={`seg-btn ${projectsMode === 'board' ? 'active' : ''}`}
                onClick={() => setProjectsMode('board')}
                role="tab"
                aria-selected={projectsMode === 'board'}
              >
                <Icon path="M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z" />
                Board
              </button>
              <button
                className={`seg-btn ${projectsMode === 'list' ? 'active' : ''}`}
                onClick={() => setProjectsMode('list')}
                role="tab"
                aria-selected={projectsMode === 'list'}
              >
                <Icon path="M4 6h16M4 12h16M4 18h16" />
                List
              </button>
            </div>
          </div>
          <div className="row wrap" style={{ marginBottom: 8 }}>
            {taskTagSuggestions.slice(0, 10).map((tag) => (
              <button
                key={`project-tag-${tag}`}
                className={`status-chip ${searchTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
                onClick={() => toggleSearchTag(tag)}
              >
                #{tag}
              </button>
            ))}
          </div>

          {projectsMode === 'board' && board.data && (
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
                        <div className="kanban-title">
                          <strong>{task.title}</strong>
                          <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
                            {task.priority}
                          </span>
                        </div>
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

          {projectsMode === 'list' && (
            <div className="task-list" style={{ marginTop: 12 }}>
              {(tasks.data?.items ?? []).map((task: Task) => (
                <div key={task.id} className={`task-item ${task.task_type === 'scheduled_instruction' ? 'scheduled' : ''}`}>
                  <div className="task-main" role="button" onClick={() => setSelectedTaskId(task.id)}>
                    <div className="task-title">
                      <strong>{task.title}</strong>
                    </div>
	                  <span className="meta">{task.status} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'}</span>
	                  {(task.labels ?? []).length > 0 && (
	                    <div className="task-tags">
                      {(task.labels ?? []).map((t) => (
	                        <span
	                          key={t}
	                          className="tag-mini"
	                          style={{
	                            backgroundColor: `hsl(${tagHue(t)}, 70%, 92%)`,
	                            borderColor: `hsl(${tagHue(t)}, 70%, 78%)`,
	                            color: `hsl(${tagHue(t)}, 55%, 28%)`
	                          }}
	                        >
	                          {t}
	                        </span>
	                      ))}
	                    </div>
	                  )}
	                  <div className="task-badges">
	                    <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
	                      {task.priority}
	                    </span>
	                    {task.task_type === 'scheduled_instruction' && (
	                        <span className={`badge ${task.schedule_state === 'done' ? 'done' : ''}`} title="Scheduled task">
	                          Scheduled
	                        </span>
	                      )}
	                    </div>
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
              {(tasks.data?.items ?? []).length === 0 && <div className="notice" style={{ marginTop: 10 }}>No tasks in this project.</div>}
            </div>
          )}
        </section>
      )}

      {tab === 'projects' && (
        <section className="card">
          <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Projects ({bootstrap.data.projects.length})</h2>
          </div>
          <div className="row" style={{ marginBottom: 10 }}>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  const name = projectName.trim()
                  if (!name) return
                  createProjectMutation.mutate()
                }
              }}
              placeholder="New project"
            />
            <button className="primary" disabled={!projectName.trim()} onClick={() => createProjectMutation.mutate()}>Create</button>
          </div>
          <div className="task-list">
            {bootstrap.data.projects.map((project, idx) => {
              const isSelected = selectedProjectId === project.id
              const taskCount = projectTaskCountQueries[idx]?.data?.total
              const noteCount = projectNoteCountQueries[idx]?.data?.total
              return (
                <div key={project.id} className="task-item">
                  <div className="task-main" role="button" onClick={() => setSelectedProjectId(project.id)}>
                    <div className="task-title">
                      <strong>{project.name}</strong>
                      {isSelected && <span className="badge">Selected</span>}
                    </div>
                    <span className="meta">Status: {project.status || 'active'}</span>
                    <div className="meta">{project.description || '(no description)'}</div>
                    <div className="meta">
                      Tasks: {taskCount ?? '...'} | Notes: {noteCount ?? '...'}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      if (!window.confirm(`Delete ${project.name}? This permanently deletes project resources.`)) return
                      deleteProjectMutation.mutate(project.id)
                    }}
                    disabled={deleteProjectMutation.isPending}
                    title="Delete project"
                    aria-label="Delete project"
                    className="action-icon danger-ghost"
                  >
                    <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                  </button>
                </div>
              )
            })}
          </div>
        </section>
      )}

		      {tab === 'notes' && (
		        <section className="card">
		          <h2>Notes ({notes.data?.total ?? 0})</h2>
		          <div className="notes-shell">
		            <div className="notes-toolbar">
		              <div className="notes-search">
		                <input value={noteQ} onChange={(e) => setNoteQ(e.target.value)} placeholder="Search notes" />
		              </div>
		              <div className="notes-filters">
		                <select value={notePinnedFilter} onChange={(e) => setNotePinnedFilter(e.target.value as 'any' | 'pinned' | 'unpinned')}>
		                  <option value="any">Any pin</option>
		                  <option value="pinned">Pinned</option>
		                  <option value="unpinned">Unpinned</option>
		                </select>
			                <label className="row archived-toggle">
			                  <input type="checkbox" checked={noteArchived} onChange={(e) => setNoteArchived(e.target.checked)} />
			                  Archived only
			                </label>
                      <div className="row wrap">
                        {noteTagSuggestions.slice(0, 8).map((tag) => (
                          <button
                            key={`note-filter-${tag}`}
                            className={`status-chip ${noteTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
                            onClick={() => toggleNoteFilterTag(tag)}
                          >
                            #{tag}
                          </button>
                        ))}
                      </div>
			                <button className="action-icon primary" onClick={() => createNoteMutation.mutate()} title="New note" aria-label="New note">
			                  <Icon path="M12 5v14M5 12h14" />
			                </button>
			              </div>
		            </div>

		            <div className="task-list">
		              {notes.isLoading && <div className="notice">Loading notes...</div>}
		              {notes.data?.items.map((n: Note) => {
		                const isOpen = selectedNoteId === n.id
		                const isSelected = selectedNote?.id === n.id
		                return (
		                  <div
		                    key={n.id}
		                    className={`note-row ${isOpen ? 'open selected' : ''}`}
		                    onClick={() => {
		                      setShowTagPicker(false)
		                      setTagPickerQuery('')
		                      setSelectedNoteId((prev) => (prev === n.id ? null : n.id))
		                    }}
		                    role="button"
		                  >
		                    <div className="note-title">
		                      {n.pinned && (
		                        <span className="badge icon-badge" title="Pinned" aria-label="Pinned">
		                          <Icon path="M6 2h12v20l-6-4-6 4V2z" />
		                        </span>
		                      )}
		                      {n.archived && <span className="badge">Archived</span>}
                          {selectedProject && <span className="badge">Project: {selectedProject.name}</span>}
		                      <strong>{n.title || 'Untitled'}</strong>
		                    </div>
		                    {(n.tags ?? []).length > 0 && (
		                      <div className="note-tags">
                        {(n.tags ?? []).map((t) => (
		                          <span
		                            key={t}
		                            className="tag-mini"
		                            style={{
		                              backgroundColor: `hsl(${tagHue(t)}, 70%, 92%)`,
		                              borderColor: `hsl(${tagHue(t)}, 70%, 78%)`,
		                              color: `hsl(${tagHue(t)}, 55%, 28%)`
		                            }}
		                          >
		                            {t}
		                          </span>
		                        ))}
		                      </div>
		                    )}
		                    <div className="note-snippet">{(n.body || '').replace(/\\s+/g, ' ').slice(0, 160) || '(empty)'}</div>
			                    <div className="meta">
                            Created: {toUserDateTime(n.created_at, userTimezone)} | Updated: {toUserDateTime(n.updated_at, userTimezone)}
                          </div>

		                    {isOpen && isSelected && selectedNote && (
		                      <div className="note-accordion" onClick={(e) => e.stopPropagation()} role="region" aria-label="Note editor">
				                        <div className="note-editor-head">
			                          <input
			                            className="note-title-input"
			                            value={editNoteTitle}
			                            onChange={(e) => setEditNoteTitle(e.target.value)}
			                            onKeyDown={(e) => {
			                              if (e.key === 'Enter' && !e.shiftKey) {
			                                if (!selectedNoteId || patchNoteMutation.isPending) return
			                                patchNoteMutation.mutate()
			                              }
			                            }}
			                            placeholder="Title"
			                          />
		                          <div className="note-actions">
		                            <button
		                              className="action-icon primary"
		                              onClick={() => patchNoteMutation.mutate()}
		                              disabled={!selectedNoteId}
		                              title="Save"
		                              aria-label="Save"
		                            >
		                              <Icon path="m5 13 4 4L19 7" />
		                            </button>
		                            {selectedNote.pinned ? (
		                              <button className="action-icon" onClick={() => unpinNoteMutation.mutate(selectedNote.id)} title="Unpin" aria-label="Unpin">
		                                <Icon path="M6 2h12v20l-6-4-6 4V2z" />
		                              </button>
		                            ) : (
		                              <button className="action-icon" onClick={() => pinNoteMutation.mutate(selectedNote.id)} title="Pin" aria-label="Pin">
		                                <Icon path="M6 2h12v20l-6-4-6 4V2z" />
		                              </button>
		                            )}
		                            {selectedNote.archived ? (
		                              <button className="action-icon" onClick={() => restoreNoteMutation.mutate(selectedNote.id)} title="Restore" aria-label="Restore">
		                                <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
		                              </button>
		                            ) : (
		                              <button className="action-icon" onClick={() => archiveNoteMutation.mutate(selectedNote.id)} title="Archive" aria-label="Archive">
		                                <Icon path="M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6" />
		                              </button>
		                            )}
		                            <button className="action-icon danger-ghost" onClick={() => deleteNoteMutation.mutate(selectedNote.id)} title="Delete" aria-label="Delete">
		                              <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
		                            </button>
				                        </div>
                        <div className="meta" style={{ marginBottom: 8 }}>Created: {toUserDateTime(selectedNote.created_at, userTimezone)}</div>
		                        </div>

		                        <div className="tag-bar" aria-label="Tags">
		                          <div className="tag-chiplist">
		                            {currentNoteTags.length === 0 ? (
		                              <span className="meta">No tags</span>
		                            ) : (
		                              currentNoteTags.map((t) => (
		                                <span
		                                  key={t}
		                                  className="tag-chip"
		                                  style={{
		                                    background: `linear-gradient(135deg, hsl(${tagHue(t)}, 70%, 92%), hsl(${tagHue(t)}, 70%, 86%))`,
		                                    borderColor: `hsl(${tagHue(t)}, 70%, 74%)`,
		                                    color: `hsl(${tagHue(t)}, 55%, 22%)`
		                                  }}
		                                >
		                                  <span className="tag-text">{t}</span>
		                                </span>
		                              ))
		                            )}
		                          </div>
		                          <button className="action-icon" onClick={() => setShowTagPicker(true)} title="Edit tags" aria-label="Edit tags">
		                            <Icon path="M3 12h8m-8 6h12m-12-12h18" />
		                          </button>
		                        </div>

		                        <div className="row" style={{ justifyContent: 'space-between' }}>
		                          <div className="seg" role="tablist" aria-label="Note editor view">
		                            <button className={`seg-btn ${noteEditorView === 'write' ? 'active' : ''}`} onClick={() => setNoteEditorView('write')} type="button">
		                              Write
		                            </button>
		                            <button className={`seg-btn ${noteEditorView === 'preview' ? 'active' : ''}`} onClick={() => setNoteEditorView('preview')} type="button">
		                              Preview
		                            </button>
		                          </div>
		                        </div>

		                        {noteEditorView === 'write' ? (
		                          <textarea value={editNoteBody} onChange={(e) => setEditNoteBody(e.target.value)} placeholder="Write Markdown..." />
		                        ) : (
		                          <MarkdownView value={editNoteBody} />
		                        )}
		                      </div>
		                    )}

		                    {showTagPicker && isSelected && (
		                      <div className="drawer open" onClick={() => setShowTagPicker(false)}>
		                        <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
		                          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
		                            <h3 style={{ margin: 0 }}>Tags</h3>
		                            <button className="action-icon" onClick={() => setShowTagPicker(false)} title="Close" aria-label="Close">
		                              <Icon path="M6 6l12 12M18 6 6 18" />
		                            </button>
		                          </div>
		                          <input
		                            value={tagPickerQuery}
		                            onChange={(e) => setTagPickerQuery(e.target.value)}
		                            placeholder="Search or create tag"
		                            autoFocus
		                          />
		                          <div className="tag-picker-list" role="listbox" aria-label="Tag list">
		                            {filteredNoteTags.map((t) => {
		                              const selected = currentNoteTagsLower.has(t.toLowerCase())
		                              return (
		                                <button
		                                  key={t}
		                                  className={`tag-picker-item ${selected ? 'selected' : ''}`}
		                                  onClick={() => toggleNoteTag(t)}
		                                  aria-label={selected ? `Remove tag ${t}` : `Add tag ${t}`}
		                                  title={selected ? 'Remove tag' : 'Add tag'}
		                                >
		                                  <span className="tag-picker-check" aria-hidden="true">
		                                    <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
		                                  </span>
		                                  <span className="tag-picker-name">{t}</span>
		                                </button>
		                              )
		                            })}
		                            {filteredNoteTags.length === 0 && <div className="meta">No tags found.</div>}
		                          </div>
		                          {canCreateTag && (
		                            <button
		                              className="primary tag-picker-create"
		                              onClick={() => addNoteTag(tagPickerQuery)}
		                              title="Create tag"
		                              aria-label="Create tag"
		                            >
		                              Create "{tagPickerQuery.trim()}"
		                            </button>
		                          )}
		                        </div>
		                      </div>
		                    )}
		                  </div>
		                )
		              })}
		            </div>
		          </div>
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
            <div className="row wrap">
              {taskTagSuggestions.slice(0, 10).map((tag) => (
                <button
                  key={`search-tag-${tag}`}
                  className={`status-chip ${searchTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
                  onClick={() => toggleSearchTag(tag)}
                >
                  #{tag}
                </button>
              ))}
            </div>
            <button onClick={() => setTab('tasks')}>Close</button>
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
        </section>
      ) : tab !== 'tasks' && tab !== 'projects' && tab !== 'notes' ? (
        <section className="card">
          <h2>Tasks ({tasks.data?.total ?? 0})</h2>
          <div className="task-list">
            {tasks.data?.items.map((task: Task) => (
              <div key={task.id} className={`task-item ${task.task_type === 'scheduled_instruction' ? 'scheduled' : ''}`}>
                <div className="task-main" role="button" onClick={() => setSelectedTaskId(task.id)}>
                  <div className="task-title">
                    <strong>{task.title}</strong>
                  </div>
		                  <span className="meta">
		                    {task.status} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'} | Created: {toUserDateTime(task.created_at, userTimezone)}
		                    {tab === 'search' && (
                      <>
                        {' '}| Project: {projectNames[task.project_id] || task.project_id}
                      </>
                    )}
	                  </span>
	                  {(task.labels ?? []).length > 0 && (
	                    <div className="task-tags">
                      {(task.labels ?? []).map((t) => (
	                        <span
	                          key={t}
	                          className="tag-mini"
	                          style={{
	                            backgroundColor: `hsl(${tagHue(t)}, 70%, 92%)`,
	                            borderColor: `hsl(${tagHue(t)}, 70%, 78%)`,
	                            color: `hsl(${tagHue(t)}, 55%, 28%)`
	                          }}
	                        >
	                          {t}
	                        </span>
	                      ))}
	                    </div>
	                  )}
	                  {task.task_type === 'scheduled_instruction' && (
	                    <span className="meta">
	                      Scheduled {task.scheduled_at_utc ? `for ${new Date(task.scheduled_at_utc).toLocaleString()}` : 'time not set'} (
                      {task.schedule_state})
                    </span>
                  )}
	                  <div className="task-badges">
	                    <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
	                      {task.priority}
	                    </span>
	                    {task.task_type === 'scheduled_instruction' && (
	                      <span className={`badge ${task.schedule_state === 'done' ? 'done' : ''}`} title="Scheduled task">
	                        Scheduled
	                      </span>
	                    )}
	                  </div>
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
      ) : null}

      <nav className="bottom-tabs">
        <button className={tab === 'today' ? 'primary' : ''} onClick={() => setTab('today')} title="Today" aria-label="Today">
          <Icon path="M8 3v4M16 3v4M4 10h16M4 5h16v15H4z" />
          <span className="tab-label">Today</span>
        </button>
        <button className={tab === 'tasks' ? 'primary' : ''} onClick={() => setTab('tasks')} title="Tasks" aria-label="Tasks">
          <Icon path="M4 6h16M4 12h10M4 18h13" />
          <span className="tab-label">Tasks</span>
        </button>
        <button className={tab === 'projects' ? 'primary' : ''} onClick={() => setTab('projects')} title="Projects" aria-label="Projects">
          <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
          <span className="tab-label">Projects</span>
        </button>
        <button className={tab === 'notes' ? 'primary' : ''} onClick={() => setTab('notes')} title="Notes" aria-label="Notes">
          <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
          <span className="tab-label">Notes</span>
        </button>
      </nav>

	      <button
	        className={`fab fab-task ${fabHidden ? 'fab-hide' : ''}`}
	        onClick={() => setShowQuickAdd(true)}
	        title="New Task"
	        aria-label="New Task"
	      >
	        <Icon path="M12 5v14M5 12h14" />
	      </button>
	
	      <button
	        className={`fab ${isCodexChatRunning ? 'busy' : ''} ${fabHidden ? 'fab-hide' : ''}`}
	        onClick={() => setShowCodexChat(true)}
	        title="Codex Chat"
	        aria-label="Codex Chat"
	      >
	        <Icon path="M4 4h16v11H7l-3 3V4z" />
	        <span>{isCodexChatRunning ? `Chat (${codexChatElapsedSeconds}s)` : 'Chat'}</span>
	      </button>

	      {selectedTask && (
	        <div className="drawer open" onClick={() => setSelectedTaskId(null)}>
	          <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
            <div className="row wrap" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
              <h3 style={{ margin: 0 }}>{selectedTask.title}</h3>
              <button className="action-icon" onClick={() => setSelectedTaskId(null)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <div className="meta" style={{ marginTop: 4 }}>Created: {toUserDateTime(selectedTask.created_at, userTimezone)}</div>
            <div className="row wrap" style={{ marginTop: 8, marginBottom: 10 }}>
              <button
                className="pill"
                onClick={() => {
                  setSelectedProjectId(selectedTask.project_id)
                  setTab('tasks')
                }}
                title="Open project"
                aria-label="Open project"
              >
                <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
                <span>{projectNames[selectedTask.project_id] || selectedTask.project_id}</span>
              </button>
              {selectedTask.due_date && (
                <span className="pill subtle" title="Due date" aria-label="Due date">
                  <Icon path="M8 3v4M16 3v4M4 10h16M4 5h16v15H4z" />
                  <span>{new Date(selectedTask.due_date).toLocaleString()}</span>
                </span>
              )}
            </div>
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
	                {bootstrap.data.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
	              </select>
              <input className="due-input" type="datetime-local" value={editDueDate} onChange={(e) => setEditDueDate(e.target.value)} />
              <button className="primary action-icon" onClick={() => patchTaskMutation.mutate()} title="Save" aria-label="Save">
                <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
              </button>
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
	            <div className="tag-bar" aria-label="Task tags" style={{ marginBottom: 10 }}>
	              <div className="tag-chiplist">
	                {editTaskTags.length === 0 ? (
	                  <span className="meta">No tags</span>
	                ) : (
	                  editTaskTags.map((t) => (
	                    <span
	                      key={t}
	                      className="tag-chip"
	                      style={{
	                        background: `linear-gradient(135deg, hsl(${tagHue(t)}, 70%, 92%), hsl(${tagHue(t)}, 70%, 86%))`,
	                        borderColor: `hsl(${tagHue(t)}, 70%, 74%)`,
	                        color: `hsl(${tagHue(t)}, 55%, 22%)`
	                      }}
	                    >
	                      <span className="tag-text">{t}</span>
	                    </span>
	                  ))
	                )}
	              </div>
	              <button className="action-icon" onClick={() => setShowTaskTagPicker(true)} title="Edit tags" aria-label="Edit tags">
	                <Icon path="M3 12h8m-8 6h12m-12-12h18" />
	              </button>
	            </div>
	            <div className="row wrap" style={{ marginBottom: 8 }}>
	              <select value={editTaskType} onChange={(e) => setEditTaskType(e.target.value as 'manual' | 'scheduled_instruction')}>
	                <option value="manual">Manual</option>
	                <option value="scheduled_instruction">Scheduled</option>
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
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <input
                type="number"
                min={1}
                inputMode="numeric"
                value={editRecurringEvery}
                onChange={(e) => setEditRecurringEvery(e.target.value)}
                placeholder="Repeat every"
                disabled={editTaskType !== 'scheduled_instruction'}
                style={{ width: 140 }}
              />
              <select
                value={editRecurringUnit}
                onChange={(e) => setEditRecurringUnit(e.target.value as 'm' | 'h' | 'd')}
                disabled={editTaskType !== 'scheduled_instruction'}
              >
                <option value="m">minutes</option>
                <option value="h">hours</option>
                <option value="d">days</option>
              </select>
              {editTaskType === 'scheduled_instruction' && (
                <button
                  className="action-icon"
                  onClick={() => {
                    setEditRecurringEvery('')
                    setEditRecurringUnit('h')
                  }}
                  title="Clear repeat"
                  aria-label="Clear repeat"
                >
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              )}
            </div>
            <textarea
              value={editScheduledInstruction}
              onChange={(e) => setEditScheduledInstruction(e.target.value)}
              rows={3}
              style={{ width: '100%', marginBottom: 8 }}
              placeholder='Scheduled (executed automatically when due)'
              disabled={editTaskType !== 'scheduled_instruction'}
            />
            {selectedTask.schedule_state && editTaskType === 'scheduled_instruction' && (
              <div className="row wrap" style={{ marginBottom: 8 }}>
                <span className="badge">Schedule: {selectedTask.schedule_state}</span>
                <span className={`prio prio-${priorityTone(selectedTask.priority)}`} title="Priority">
                  {selectedTask.priority}
                </span>
                {selectedTask.scheduled_at_utc && <span className="meta">Scheduled for: {new Date(selectedTask.scheduled_at_utc).toLocaleString()}</span>}
                {selectedTask.recurring_rule && <span className="meta">Repeats: {String(selectedTask.recurring_rule)}</span>}
                {selectedTask.last_schedule_error && <span className="meta">Last error: {selectedTask.last_schedule_error}</span>}
              </div>
            )}
	            <textarea value={editDescription} onChange={(e) => setEditDescription(e.target.value)} rows={4} style={{ width: '100%' }} />
	            {showTaskTagPicker && (
	              <div className="drawer open" onClick={() => setShowTaskTagPicker(false)}>
	                <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
	                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
	                    <h3 style={{ margin: 0 }}>Task Tags</h3>
	                    <button className="action-icon" onClick={() => setShowTaskTagPicker(false)} title="Close" aria-label="Close">
	                      <Icon path="M6 6l12 12M18 6 6 18" />
	                    </button>
	                  </div>
	                  <input
	                    value={taskTagPickerQuery}
	                    onChange={(e) => setTaskTagPickerQuery(e.target.value)}
	                    placeholder="Search or create tag"
	                    autoFocus
	                  />
	                  <div className="tag-picker-list" role="listbox" aria-label="Tag list">
	                    {filteredTaskTags.map((t) => {
	                      const selected = taskTagsLower.has(t.toLowerCase())
	                      return (
	                        <button
	                          key={t}
	                          className={`tag-picker-item ${selected ? 'selected' : ''}`}
	                          onClick={() => toggleTaskTag(t)}
	                          aria-label={selected ? `Remove tag ${t}` : `Add tag ${t}`}
	                          title={selected ? 'Remove tag' : 'Add tag'}
	                        >
	                          <span className="tag-picker-check" aria-hidden="true">
	                            <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
	                          </span>
	                          <span className="tag-picker-name">{t}</span>
	                        </button>
	                      )
	                    })}
	                    {filteredTaskTags.length === 0 && <div className="meta">No tags found.</div>}
	                  </div>
	                  {canCreateTaskTag && (
	                    <button className="primary tag-picker-create" onClick={() => toggleTaskTag(taskTagPickerQuery)} title="Create tag" aria-label="Create tag">
	                      Create "{taskTagPickerQuery.trim()}"
	                    </button>
	                  )}
	                </div>
	              </div>
	            )}
	            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginTop: 10 }}>
	              <h4 style={{ margin: 0 }}>Comments</h4>
	              <span className="meta">{comments.data?.length ?? 0}</span>
	            </div>
            <div className="note-list comment-list">
              {comments.isLoading && <div className="meta">Loading comments...</div>}
              {comments.data?.map((c) => (
                <div className="note comment-item" key={`${c.id}-${c.created_at}`}>
                  {(() => {
                    const body = c.body || ''
                    const commentKey = `${c.id ?? 'null'}-${c.created_at ?? ''}-${c.user_id}`
                    const expanded = expandedCommentIds.has(commentKey)
                    const isLong = body.length > 520 || body.split('\n').length > 14
                    const author = actorNames[c.user_id] || 'Someone'
                    const avatar = (author || 'S').trim().slice(0, 1).toUpperCase()
                    return (
                      <>
                        <div className="comment-gutter" aria-hidden="true">
                          <div className="comment-avatar">{avatar}</div>
                        </div>
                        <div className="comment-main">
                          <div className="comment-head">
                            <strong className="comment-author">{author}</strong>
                            <span className="meta">{c.created_at ? new Date(c.created_at).toLocaleString() : ''}</span>
                          </div>
                          <div className={`comment-body ${isLong && !expanded ? 'collapsed' : ''}`}>
                            <MarkdownView value={body} />
                          </div>
                          {isLong && (
                            <div className="comment-actions">
                              <button
                                className="status-chip"
                                onClick={() =>
                                  setExpandedCommentIds((prev) => {
                                    const next = new Set(prev)
                                    if (next.has(commentKey)) next.delete(commentKey)
                                    else next.add(commentKey)
                                    return next
                                  })
                                }
                              >
                                {expanded ? 'Show less' : 'Show more'}
                              </button>
                            </div>
                          )}
                        </div>
                      </>
                    )
                  })()}
                </div>
              ))}
              {!comments.isLoading && (comments.data ?? []).length === 0 && <div className="meta">No comments yet.</div>}
            </div>
	            <div className="comment-composer">
	              <div className="comment-help meta">
	                Markdown supported. Use <code>@username</code> to mention. Press <code>Enter</code> to send, <code>Shift</code> + <code>Enter</code> for a new line.
	              </div>
	              <textarea
	                ref={commentInputRef}
	                value={commentBody}
	                onChange={(e) => setCommentBody(e.target.value)}
	                onKeyDown={(e) => {
	                  if (e.key === 'Enter' && !e.shiftKey) {
	                    e.preventDefault()
	                    const body = commentBody.trim()
	                    if (!body || addCommentMutation.isPending) return
	                    addCommentMutation.mutate()
	                  }
	                }}
	                rows={3}
	                placeholder="Write a comment..."
	                disabled={addCommentMutation.isPending}
	              />
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="meta">{commentBody.trim().length ? `${commentBody.trim().length} chars` : ''}</span>
                <button
                  className="primary"
                  onClick={() => addCommentMutation.mutate()}
                  disabled={!commentBody.trim() || addCommentMutation.isPending}
                >
                  {addCommentMutation.isPending ? 'Sending...' : 'Send'}
                </button>
              </div>
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
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
              <h3 style={{ margin: 0 }}>Codex Chat</h3>
              <button className="action-icon" onClick={() => setShowCodexChat(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <p className="meta">General instruction mode. Session: <code>{codexChatSessionId}</code></p>
            <div className="codex-chat-history" ref={codexChatHistoryRef}>
              {codexChatTurns.length === 0 && (
                <div className="meta">Chat is empty. Send your first instruction.</div>
              )}
              {codexChatTurns.map((turn) => (
                <div key={turn.id} className={`codex-chat-bubble ${turn.role}`}>
                  <div className="codex-chat-role">{turn.role === 'user' ? 'You' : 'Codex'}</div>
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
            <div className="codex-chat-toolbar">
              <button
                className="action-icon"
                onClick={() => setCodexChatTurns([])}
                disabled={runAgentChatMutation.isPending || codexChatTurns.length === 0}
                title="Clear chat"
                aria-label="Clear chat"
              >
                <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
              </button>
              <span className={`codex-chat-status ${isCodexChatRunning ? 'codex-progress' : ''}`}>
                {isCodexChatRunning ? `Executing tools... ${codexChatElapsedSeconds}s` : ''}
              </span>
              <button
                className="action-icon primary"
	                onClick={() => {
	                  const instruction = codexChatInstruction.trim()
	                  if (!instruction) return
	                  // Clear immediately so the input doesn't "stick" while Codex runs.
	                  setCodexChatInstruction('')
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
                title="Send to Codex"
                aria-label="Send to Codex"
              >
                <Icon path="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z" />
              </button>
            </div>
            {codexChatLastTaskEventAt && (
              <div className="row wrap" style={{ marginTop: 8 }}>
                <span className="meta">Last task event: {new Date(codexChatLastTaskEventAt).toLocaleTimeString()}</span>
              </div>
            )}
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
