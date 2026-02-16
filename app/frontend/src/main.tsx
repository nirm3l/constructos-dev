import React from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addProjectMember,
  addComment,
  archiveTask,
  completeTask,
  createProject,
  createProjectRule,
  deleteComment,
  createTask,
  createNote,
  deleteAttachment,
  deleteNote,
  attachmentDownloadUrl,
  deleteProject,
  deleteProjectRule,
  getTaskAutomationStatus,
  getBootstrap,
  getNotifications,
  getProjectBoard,
  getProjectRules,
  getProjectTags,
  getNotes,
  getTasks,
  listActivity,
  listComments,
  markNotificationRead,
  patchNote,
  patchMyPreferences,
  patchProject,
  patchProjectRule,
  patchTask,
  pinNote,
  restoreNote,
  restoreTask,
  reopenTask,
  removeProjectMember,
  runAgentChat,
  runTaskWithCodex,
  uploadAttachment,
  unpinNote,
  archiveNote
} from './api'
import type { AttachmentRef, ExternalRef, Notification, Note, ProjectRule, Task, TaskAutomationStatus } from './types'
import { MarkdownView } from './markdown/MarkdownView'
import './styles.css'

const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000001'

type Tab = 'today' | 'tasks' | 'notes' | 'projects' | 'search' | 'profile'
type ChatRole = 'user' | 'assistant'
type ChatTurn = { id: string; role: ChatRole; content: string; createdAt: number }
type DraftProjectRule = { id: string; title: string; body: string }

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

function parseUrlTab(raw: string | null): Tab | null {
  if (!raw) return null
  return TAB_ORDER.includes(raw as Tab) ? (raw as Tab) : null
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

function pickSingleTimeMeta(createdAt: string | null | undefined, updatedAt: string | null | undefined): { label: 'Created' | 'Updated'; value: string } | null {
  const created = createdAt || null
  const updated = updatedAt || null
  if (updated && created && updated !== created) return { label: 'Updated', value: updated }
  if (created) return { label: 'Created', value: created }
  if (updated) return { label: 'Updated', value: updated }
  return null
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

function parseExternalRefsText(raw: string): ExternalRef[] {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [urlPart, titlePart, sourcePart] = line.split('|').map((x) => x.trim())
      const item: ExternalRef = { url: urlPart || '' }
      if (titlePart) item.title = titlePart
      if (sourcePart) item.source = sourcePart
      return item
    })
    .filter((item) => item.url)
}

function externalRefsToText(items: ExternalRef[] | undefined | null): string {
  return (items ?? [])
    .map((item) => [item.url, item.title, item.source].filter(Boolean).join(' | '))
    .join('\n')
}

function removeExternalRefByIndex(raw: string, index: number): string {
  const parsed = parseExternalRefsText(raw)
  if (index < 0 || index >= parsed.length) return raw
  parsed.splice(index, 1)
  return externalRefsToText(parsed)
}

function parseAttachmentRefsText(raw: string): AttachmentRef[] {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [pathPart, namePart, mimePart, sizePart] = line.split('|').map((x) => x.trim())
      const item: AttachmentRef = { path: pathPart || '' }
      if (namePart) item.name = namePart
      if (mimePart) item.mime_type = mimePart
      if (sizePart) {
        const n = Number(sizePart)
        if (Number.isFinite(n) && n >= 0) item.size_bytes = Math.floor(n)
      }
      return item
    })
    .filter((item) => item.path)
}

function attachmentRefsToText(items: AttachmentRef[] | undefined | null): string {
  return (items ?? [])
    .map((item) => [item.path, item.name, item.mime_type, item.size_bytes != null ? String(item.size_bytes) : ''].filter(Boolean).join(' | '))
    .join('\n')
}

function removeAttachmentByPath(raw: string, path: string): string {
  const filtered = parseAttachmentRefsText(raw).filter((item) => item.path !== path)
  return attachmentRefsToText(filtered)
}

function ExternalRefList({
  refs,
  onRemoveIndex
}: {
  refs: ExternalRef[] | undefined | null
  onRemoveIndex?: (index: number) => void
}) {
  if (!refs || refs.length === 0) return null
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      {refs.map((ref, idx) => {
        const label = ref.title || ref.url
        return (
          <span key={`${ref.url}-${idx}`} className="row" style={{ gap: 6 }}>
            <a
              className="status-chip"
              href={ref.url}
              target="_blank"
              rel="noreferrer"
              title={ref.source ? `${label} (${ref.source})` : label}
            >
              {ref.source ? `${label} · ${ref.source}` : label}
            </a>
            {onRemoveIndex && (
              <button
                type="button"
                className="action-icon danger-ghost"
                onClick={() => onRemoveIndex(idx)}
                title="Remove link"
                aria-label="Remove link"
              >
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            )}
          </span>
        )
      })}
    </div>
  )
}

function ExternalRefEditor({
  refs,
  onAdd,
  onRemoveIndex,
}: {
  refs: ExternalRef[]
  onAdd: (ref: ExternalRef) => void
  onRemoveIndex: (index: number) => void
}) {
  const [url, setUrl] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [source, setSource] = React.useState('')
  return (
    <div style={{ marginTop: 8 }}>
      <ExternalRefList refs={refs} onRemoveIndex={onRemoveIndex} />
      <div className="row wrap" style={{ gap: 8, marginTop: 6 }}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          style={{ minWidth: 240 }}
        />
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          style={{ minWidth: 180 }}
        />
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Source (optional)"
          style={{ minWidth: 140 }}
        />
        <button
          className="status-chip"
          type="button"
          onClick={() => {
            const cleaned = url.trim()
            if (!cleaned) return
            onAdd({
              url: cleaned,
              ...(title.trim() ? { title: title.trim() } : {}),
              ...(source.trim() ? { source: source.trim() } : {}),
            })
            setUrl('')
            setTitle('')
            setSource('')
          }}
        >
          Add link
        </button>
      </div>
    </div>
  )
}

function AttachmentRefList({
  refs,
  workspaceId,
  userId,
  onRemovePath
}: {
  refs: AttachmentRef[] | undefined | null
  workspaceId: string
  userId: string
  onRemovePath?: (path: string) => void
}) {
  if (!refs || refs.length === 0) return null
  return (
    <div className="row wrap" style={{ gap: 6 }}>
      {refs.map((ref, idx) => (
        <span key={`${ref.path}-${idx}`} className="row" style={{ gap: 6 }}>
          <a
            className="status-chip"
            title={ref.path}
            href={attachmentDownloadUrl({ user_id: userId, workspace_id: workspaceId, path: ref.path })}
            target="_blank"
            rel="noreferrer"
          >
            {ref.name || ref.path}
          </a>
          {onRemovePath && (
            <button
              type="button"
              className="action-icon danger-ghost"
              onClick={() => onRemovePath(ref.path)}
              title="Remove file"
              aria-label="Remove file"
            >
              <Icon path="M6 6l12 12M18 6 6 18" />
            </button>
          )}
        </span>
      ))}
    </div>
  )
}

function toErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  if (typeof err === 'string' && err.trim()) return err.trim()
  return fallback
}

function stableJson(value: unknown): string {
  return JSON.stringify(value ?? null)
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
  const [quickDueDateFocused, setQuickDueDateFocused] = React.useState(false)
  const [projectName, setProjectName] = React.useState('')
  const [projectDescription, setProjectDescription] = React.useState('')
  const [projectExternalRefsText, setProjectExternalRefsText] = React.useState('')
  const [projectAttachmentRefsText, setProjectAttachmentRefsText] = React.useState('')
  const [projectDescriptionView, setProjectDescriptionView] = React.useState<'write' | 'preview'>('write')
  const [showProjectCreateForm, setShowProjectCreateForm] = React.useState(false)
  const [showProjectEditForm, setShowProjectEditForm] = React.useState(false)
  const [editProjectName, setEditProjectName] = React.useState('')
  const [editProjectDescription, setEditProjectDescription] = React.useState('')
  const [editProjectExternalRefsText, setEditProjectExternalRefsText] = React.useState('')
  const [editProjectAttachmentRefsText, setEditProjectAttachmentRefsText] = React.useState('')
  const [createProjectMemberIds, setCreateProjectMemberIds] = React.useState<string[]>([])
  const [editProjectMemberIds, setEditProjectMemberIds] = React.useState<string[]>([])
  const [editProjectDescriptionView, setEditProjectDescriptionView] = React.useState<'write' | 'preview'>('write')
  const [projectRuleQ, setProjectRuleQ] = React.useState('')
  const [selectedProjectRuleId, setSelectedProjectRuleId] = React.useState<string | null>(null)
  const [projectRuleTitle, setProjectRuleTitle] = React.useState('')
  const [projectRuleBody, setProjectRuleBody] = React.useState('')
  const [projectRuleView, setProjectRuleView] = React.useState<'write' | 'preview'>('write')
  const [draftProjectRules, setDraftProjectRules] = React.useState<DraftProjectRule[]>([])
  const [selectedDraftProjectRuleId, setSelectedDraftProjectRuleId] = React.useState<string | null>(null)
  const [draftProjectRuleTitle, setDraftProjectRuleTitle] = React.useState('')
  const [draftProjectRuleBody, setDraftProjectRuleBody] = React.useState('')
  const [draftProjectRuleView, setDraftProjectRuleView] = React.useState<'write' | 'preview'>('write')
  const [selectedProjectId, setSelectedProjectId] = React.useState<string>(() =>
    parseStoredProjectId(localStorage.getItem('ui_selected_project_id'))
  )
  const [quickProjectId, setQuickProjectId] = React.useState<string>('')
  const [quickTaskTags, setQuickTaskTags] = React.useState<string[]>([])
  const [quickTaskExternalRefsText, setQuickTaskExternalRefsText] = React.useState('')
  const [quickTaskAttachmentRefsText, setQuickTaskAttachmentRefsText] = React.useState('')
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
  const [editNoteExternalRefsText, setEditNoteExternalRefsText] = React.useState('')
  const [editNoteAttachmentRefsText, setEditNoteAttachmentRefsText] = React.useState('')
  const [showTagPicker, setShowTagPicker] = React.useState(false)
  const [tagPickerQuery, setTagPickerQuery] = React.useState('')
  const [noteEditorView, setNoteEditorView] = React.useState<'write' | 'preview'>('preview')
  const [commentBody, setCommentBody] = React.useState('')
  const [expandedCommentIds, setExpandedCommentIds] = React.useState<Set<string>>(new Set())
  const [automationInstruction, setAutomationInstruction] = React.useState('')
  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatProjectId, setCodexChatProjectId] = React.useState<string>('')
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
  const [editTaskExternalRefsText, setEditTaskExternalRefsText] = React.useState('')
  const [editTaskAttachmentRefsText, setEditTaskAttachmentRefsText] = React.useState('')
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
  const [scrollToNewestComment, setScrollToNewestComment] = React.useState(false)
  const [uiError, setUiError] = React.useState<string | null>(null)
  const [uiInfo, setUiInfo] = React.useState<string | null>(null)
  const [taskEditorError, setTaskEditorError] = React.useState<string | null>(null)
  const qc = useQueryClient()
  const realtimeRefreshTimerRef = React.useRef<number | null>(null)
  const codexChatHistoryRef = React.useRef<HTMLDivElement | null>(null)
  const commentInputRef = React.useRef<HTMLTextAreaElement | null>(null)
  const commentsListRef = React.useRef<HTMLDivElement | null>(null)
  const quickTaskFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const taskFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const noteFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const editProjectFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const fabIdleTimerRef = React.useRef<number | null>(null)
  const openNextSelectedNoteInWriteRef = React.useRef(false)
  const projectDescriptionRef = React.useRef<HTMLTextAreaElement | null>(null)
  const editProjectDescriptionRef = React.useRef<HTMLTextAreaElement | null>(null)
  const urlInitAppliedRef = React.useRef(false)

  const autoResizeTextarea = React.useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) return
    const minHeight = 96
    const maxHeight = 280
    el.style.height = 'auto'
    const next = Math.max(minHeight, Math.min(el.scrollHeight, maxHeight))
    el.style.height = `${next}px`
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [])

  React.useEffect(() => {
    localStorage.setItem('ui_tab', tab)
  }, [tab])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    const urlTab = parseUrlTab(params.get('tab'))
    if (urlTab) setTab(urlTab)
    const projectId = params.get('project')
    if (projectId) setSelectedProjectId(projectId)
    const taskId = params.get('task')
    if (taskId) {
      setSelectedTaskId(taskId)
      setTab('tasks')
    }
    const noteId = params.get('note')
    if (noteId) {
      setSelectedNoteId(noteId)
      setTab('notes')
    }
  }, [])

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
    if (tab !== 'projects') {
      setShowProjectCreateForm(false)
      setShowProjectEditForm(false)
    }
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
  const workspaceUsers = React.useMemo(
    () => [...(bootstrap.data?.users ?? [])].sort((a, b) => a.full_name.localeCompare(b.full_name)),
    [bootstrap.data?.users]
  )
  const projectMemberCounts = React.useMemo(() => {
    const counts: Record<string, number> = {}
    for (const pm of bootstrap.data?.project_members ?? []) {
      counts[pm.project_id] = (counts[pm.project_id] ?? 0) + 1
    }
    return counts
  }, [bootstrap.data?.project_members])
  const selectedProject = React.useMemo(
    () => bootstrap.data?.projects.find((p) => p.id === selectedProjectId) ?? null,
    [bootstrap.data?.projects, selectedProjectId]
  )

  React.useEffect(() => {
    const firstProjectId = bootstrap.data?.projects[0]?.id ?? ''
    const validSelected = Boolean(selectedProjectId && (bootstrap.data?.projects ?? []).some((p) => p.id === selectedProjectId))
    if ((!selectedProjectId || !validSelected) && firstProjectId) setSelectedProjectId(firstProjectId)
  }, [bootstrap.data, selectedProjectId])

  React.useEffect(() => {
    if (!bootstrap.data || urlInitAppliedRef.current) return
    urlInitAppliedRef.current = true
    const params = new URLSearchParams(window.location.search)
    const urlProject = params.get('project')
    if (urlProject && !(bootstrap.data.projects ?? []).some((p) => p.id === urlProject)) {
      params.delete('project')
      params.delete('task')
      params.delete('note')
      const next = params.toString()
      window.history.replaceState(null, '', next ? `?${next}` : window.location.pathname)
    }
  }, [bootstrap.data])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    params.set('tab', tab)
    if (selectedProjectId) params.set('project', selectedProjectId)
    else params.delete('project')
    if (selectedTaskId) params.set('task', selectedTaskId)
    else params.delete('task')
    if (selectedNoteId) params.set('note', selectedNoteId)
    else params.delete('note')
    const next = params.toString()
    window.history.replaceState(null, '', next ? `?${next}` : window.location.pathname)
  }, [tab, selectedProjectId, selectedTaskId, selectedNoteId])

  React.useEffect(() => {
    if (!showProjectCreateForm) return
    if (createProjectMemberIds.length > 0) return
    if (!bootstrap.data?.current_user?.id) return
    setCreateProjectMemberIds([bootstrap.data.current_user.id])
  }, [showProjectCreateForm, createProjectMemberIds.length, bootstrap.data?.current_user?.id])

  React.useEffect(() => {
    if (!showProjectEditForm || !selectedProjectId) return
    const ids = (bootstrap.data?.project_members ?? [])
      .filter((pm) => pm.project_id === selectedProjectId)
      .map((pm) => pm.user_id)
    const uniqueIds = Array.from(new Set(ids))
    setEditProjectMemberIds(uniqueIds)
    const project = (bootstrap.data?.projects ?? []).find((p) => p.id === selectedProjectId)
    if (!project) return
  }, [showProjectEditForm, selectedProjectId, bootstrap.data?.project_members, bootstrap.data?.projects])

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
  const projectTags = useQuery({
    queryKey: ['project-tags', userId, selectedProjectId],
    queryFn: () => getProjectTags(userId, selectedProjectId),
    enabled: Boolean(selectedProjectId)
  })
  const projectRules = useQuery({
    queryKey: ['project-rules', userId, workspaceId, selectedProjectId, projectRuleQ],
    queryFn: () =>
      getProjectRules(userId, workspaceId, {
        project_id: selectedProjectId,
        q: projectRuleQ || undefined,
      }),
    enabled: Boolean(workspaceId && selectedProjectId) && tab === 'projects'
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
  const projectRuleCountQueries = useQueries({
    queries: (bootstrap.data?.projects ?? []).map((project) => ({
      queryKey: ['project-rule-count', userId, workspaceId, project.id],
      queryFn: () => getProjectRules(userId, workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
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
  const selectedProjectRule = React.useMemo(
    () => projectRules.data?.items.find((r) => r.id === selectedProjectRuleId) ?? null,
    [projectRules.data?.items, selectedProjectRuleId]
  )

  const taskTagSuggestions = React.useMemo(() => {
    return (projectTags.data?.tags ?? []).slice(0, 40)
  }, [projectTags.data?.tags])
  const noteTagSuggestions = React.useMemo(() => {
    return (projectTags.data?.tags ?? []).slice(0, 24)
  }, [projectTags.data?.tags])
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
  const toggleCreateProjectMember = React.useCallback((userIdToToggle: string) => {
    const id = String(userIdToToggle || '').trim()
    if (!id) return
    setCreateProjectMemberIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])
  const toggleEditProjectMember = React.useCallback((userIdToToggle: string) => {
    const id = String(userIdToToggle || '').trim()
    if (!id) return
    setEditProjectMemberIds((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [])

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

  const selectedProjectMemberIds = React.useMemo(
    () =>
      Array.from(
        new Set(
          (bootstrap.data?.project_members ?? [])
            .filter((pm) => pm.project_id === selectedProjectId)
            .map((pm) => pm.user_id)
        )
      ).sort(),
    [bootstrap.data?.project_members, selectedProjectId]
  )

  const projectIsDirty = React.useMemo(() => {
    if (!showProjectEditForm || !selectedProject) return false
    return (
      editProjectName.trim() !== (selectedProject.name ?? '').trim() ||
      editProjectDescription !== (selectedProject.description ?? '') ||
      stableJson(parseExternalRefsText(editProjectExternalRefsText)) !== stableJson(selectedProject.external_refs ?? []) ||
      stableJson(parseAttachmentRefsText(editProjectAttachmentRefsText)) !== stableJson(selectedProject.attachment_refs ?? []) ||
      stableJson(Array.from(new Set(editProjectMemberIds.filter(Boolean))).sort()) !== stableJson(selectedProjectMemberIds)
    )
  }, [
    editProjectAttachmentRefsText,
    editProjectDescription,
    editProjectExternalRefsText,
    editProjectMemberIds,
    editProjectName,
    selectedProject,
    selectedProjectMemberIds,
    showProjectEditForm,
  ])

  const noteIsDirty = React.useMemo(() => {
    if (!selectedNote) return false
    return (
      (editNoteTitle.trim() || 'Untitled') !== (selectedNote.title?.trim() || 'Untitled') ||
      editNoteBody !== (selectedNote.body ?? '') ||
      stableJson(parseCommaTags(editNoteTags)) !== stableJson(selectedNote.tags ?? []) ||
      stableJson(parseExternalRefsText(editNoteExternalRefsText)) !== stableJson(selectedNote.external_refs ?? []) ||
      stableJson(parseAttachmentRefsText(editNoteAttachmentRefsText)) !== stableJson(selectedNote.attachment_refs ?? [])
    )
  }, [editNoteAttachmentRefsText, editNoteBody, editNoteExternalRefsText, editNoteTags, editNoteTitle, selectedNote])

  const taskIsDirty = React.useMemo(() => {
    if (!selectedTask) return false
    const current = {
      description: editDescription,
      status: editStatus,
      priority: editPriority,
      project_id: editProjectId || selectedTask.project_id,
      labels: editTaskTags,
      due_date: editDueDate || '',
      task_type: editTaskType,
      scheduled_at_utc: editScheduledAtUtc || '',
      schedule_timezone: editTaskType === 'scheduled_instruction' ? (editScheduleTimezone || '') : '',
      scheduled_instruction: editTaskType === 'scheduled_instruction' ? editScheduledInstruction : '',
      recurring_rule:
        editTaskType === 'scheduled_instruction' && editRecurringEvery.trim()
          ? `every:${Math.max(1, Number(editRecurringEvery) || 1)}${editRecurringUnit}`
          : '',
      external_refs: parseExternalRefsText(editTaskExternalRefsText),
      attachment_refs: parseAttachmentRefsText(editTaskAttachmentRefsText),
    }
    const original = {
      description: selectedTask.description ?? '',
      status: selectedTask.status ?? 'To do',
      priority: selectedTask.priority ?? 'Med',
      project_id: selectedTask.project_id ?? '',
      labels: selectedTask.labels ?? [],
      due_date: toLocalDateTimeInput(selectedTask.due_date),
      task_type: selectedTask.task_type ?? 'manual',
      scheduled_at_utc: toLocalDateTimeInput(selectedTask.scheduled_at_utc),
      schedule_timezone:
        (selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? (selectedTask.schedule_timezone ?? '') : '',
      scheduled_instruction:
        (selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? (selectedTask.scheduled_instruction ?? '') : '',
      recurring_rule:
        (selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? String(selectedTask.recurring_rule ?? '') : '',
      external_refs: selectedTask.external_refs ?? [],
      attachment_refs: selectedTask.attachment_refs ?? [],
    }
    return stableJson(current) !== stableJson(original)
  }, [
    editDescription,
    editDueDate,
    editPriority,
    editProjectId,
    editRecurringEvery,
    editRecurringUnit,
    editScheduledAtUtc,
    editScheduledInstruction,
    editScheduleTimezone,
    editStatus,
    editTaskAttachmentRefsText,
    editTaskExternalRefsText,
    editTaskTags,
    editTaskType,
    selectedTask,
  ])

  const confirmDiscardChanges = React.useCallback(() => {
    if (typeof window === 'undefined') return true
    return window.confirm('You have unsaved changes. Discard them?')
  }, [])

  const closeTaskEditor = React.useCallback(() => {
    if (taskIsDirty && !confirmDiscardChanges()) return false
    setSelectedTaskId(null)
    setTaskEditorError(null)
    return true
  }, [confirmDiscardChanges, taskIsDirty])

  const openTaskEditor = React.useCallback((taskId: string) => {
    if (selectedTaskId === taskId) return true
    if (selectedTaskId && taskIsDirty && !confirmDiscardChanges()) return false
    setSelectedTaskId(taskId)
    setTaskEditorError(null)
    return true
  }, [confirmDiscardChanges, selectedTaskId, taskIsDirty])

  const toggleNoteEditor = React.useCallback((noteId: string) => {
    if (selectedNoteId === noteId) {
      if (noteIsDirty && !confirmDiscardChanges()) return false
      setSelectedNoteId(null)
      return true
    }
    if (selectedNoteId && noteIsDirty && !confirmDiscardChanges()) return false
    setSelectedNoteId(noteId)
    return true
  }, [confirmDiscardChanges, noteIsDirty, selectedNoteId])

  const toggleProjectEditor = React.useCallback((projectId: string) => {
    if (selectedProjectId === projectId) {
      if (showProjectEditForm) {
        if (projectIsDirty && !confirmDiscardChanges()) return false
        setShowProjectEditForm(false)
        return true
      }
      setShowProjectCreateForm(false)
      setShowProjectEditForm(true)
      return true
    }
    if (showProjectEditForm && projectIsDirty && !confirmDiscardChanges()) return false
    setSelectedProjectId(projectId)
    setShowProjectEditForm(false)
    return true
  }, [confirmDiscardChanges, projectIsDirty, selectedProjectId, showProjectEditForm])

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
    setEditTaskExternalRefsText(externalRefsToText(selectedTask.external_refs))
    setEditTaskAttachmentRefsText(attachmentRefsToText(selectedTask.attachment_refs))
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
    setTaskEditorError(null)
    // Helpful default: focus comment box when opening a task.
    window.setTimeout(() => commentInputRef.current?.focus(), 0)
  }, [bootstrap.data?.current_user?.timezone, selectedTask?.id])

  React.useEffect(() => {
    if (!taskEditorError) return
    setTaskEditorError(null)
  }, [editTaskType, editScheduledInstruction, editScheduledAtUtc, editScheduleTimezone, editRecurringEvery, editRecurringUnit])

  // Notes uses an accordion: do not auto-open a note.

  React.useEffect(() => {
    if (!selectedNote) return
    setEditNoteTitle(selectedNote.title ?? '')
    setEditNoteBody(selectedNote.body ?? '')
    setEditNoteTags((selectedNote.tags ?? []).join(', '))
    setEditNoteExternalRefsText(externalRefsToText(selectedNote.external_refs))
    setEditNoteAttachmentRefsText(attachmentRefsToText(selectedNote.attachment_refs))
    setTagPickerQuery('')
    setShowTagPicker(false)
    const hasBody = Boolean((selectedNote.body ?? '').trim())
    setNoteEditorView(openNextSelectedNoteInWriteRef.current || !hasBody ? 'write' : 'preview')
    openNextSelectedNoteInWriteRef.current = false
  }, [selectedNote?.id])

  const comments = useQuery({
    queryKey: ['comments', userId, selectedTaskId],
    queryFn: () => listComments(userId, selectedTaskId as string),
    enabled: Boolean(selectedTaskId)
  })

  React.useEffect(() => {
    if (!scrollToNewestComment || comments.isFetching) return
    const list = commentsListRef.current
    if (!list) return
    list.scrollTo({ top: 0, behavior: 'smooth' })
    const newest = list.querySelector('.comment-item') as HTMLElement | null
    if (newest) newest.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    setScrollToNewestComment(false)
  }, [scrollToNewestComment, comments.isFetching, comments.data])

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
    await qc.invalidateQueries({ queryKey: ['project-tags'] })
    await qc.invalidateQueries({ queryKey: ['board'] })
    await qc.invalidateQueries({ queryKey: ['bootstrap'] })
    await qc.invalidateQueries({ queryKey: ['notifications'] })
    await qc.invalidateQueries({ queryKey: ['project-rules'] })
  }

  const uploadAttachmentRef = React.useCallback(
    async (file: File, scope: { project_id?: string | null; task_id?: string | null; note_id?: string | null }) => {
      const projectId = scope.project_id ?? undefined
      const taskId = scope.task_id ?? undefined
      const noteId = scope.note_id ?? undefined
      if (!workspaceId) throw new Error('Workspace is missing')
      if (!projectId && !taskId && !noteId) throw new Error('Select project/task/note before upload')
      const ref = await uploadAttachment(userId, {
        workspace_id: workspaceId,
        project_id: projectId,
        task_id: taskId,
        note_id: noteId,
        file,
      })
      setUiError(null)
      return ref
    },
    [userId, workspaceId]
  )

  const removeUploadedAttachment = React.useCallback(
    async (path: string) => {
      if (!workspaceId) throw new Error('Workspace is missing')
      try {
        await deleteAttachment(userId, { workspace_id: workspaceId, path })
      } catch (err) {
        const message = toErrorMessage(err, '')
        // Idempotent delete: stale refs can point to files already removed on disk.
        if (!/attachment not found/i.test(message)) throw err
      }
      setUiError(null)
    },
    [userId, workspaceId]
  )

  const buildShareUrl = React.useCallback(
    (payload: { tab?: Tab; projectId?: string; taskId?: string; noteId?: string }) => {
      const u = new URL(window.location.href)
      u.searchParams.set('tab', payload.tab ?? tab)
      if (payload.projectId) u.searchParams.set('project', payload.projectId)
      else u.searchParams.delete('project')
      if (payload.taskId) u.searchParams.set('task', payload.taskId)
      else u.searchParams.delete('task')
      if (payload.noteId) u.searchParams.set('note', payload.noteId)
      else u.searchParams.delete('note')
      return u.toString()
    },
    [tab]
  )

  const copyShareLink = React.useCallback(async (payload: { tab?: Tab; projectId?: string; taskId?: string; noteId?: string }) => {
    try {
      const text = buildShareUrl(payload)
      const canUseClipboardApi = typeof navigator !== 'undefined' && !!navigator.clipboard?.writeText
      if (canUseClipboardApi) {
        await navigator.clipboard.writeText(text)
      } else if (typeof document !== 'undefined') {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.setAttribute('readonly', 'true')
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        ta.style.pointerEvents = 'none'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('Clipboard copy is not supported in this browser context')
      } else {
        throw new Error('Clipboard copy is not available')
      }
      setUiInfo('Link copied to clipboard')
      setTimeout(() => setUiInfo(null), 1800)
    } catch (err) {
      setUiError(toErrorMessage(err, 'Copy link failed'))
    }
  }, [buildShareUrl])

  const syncProjectMembers = React.useCallback(async (projectId: string, desiredMemberIds: string[]) => {
    const currentMemberIds = Array.from(
      new Set(
        (bootstrap.data?.project_members ?? [])
          .filter((pm) => pm.project_id === projectId)
          .map((pm) => pm.user_id)
      )
    )
    const currentSet = new Set(currentMemberIds)
    const desiredSet = new Set(desiredMemberIds)
    const toAdd = desiredMemberIds.filter((uid) => !currentSet.has(uid))
    const toRemove = currentMemberIds.filter((uid) => !desiredSet.has(uid))
    if (toAdd.length > 0 || toRemove.length > 0) {
      await Promise.all([
        ...toAdd.map((uid) => addProjectMember(userId, projectId, { user_id: uid })),
        ...toRemove.map((uid) => removeProjectMember(userId, projectId, uid)),
      ])
    }
  }, [bootstrap.data?.project_members, userId])

  const saveProjectNow = React.useCallback(async () => {
    if (!selectedProjectId) throw new Error('No project selected')
    const name = editProjectName.trim()
    if (!name) throw new Error('Project name is required')
    const memberIds = Array.from(new Set(editProjectMemberIds.filter(Boolean))).sort()
    await patchProject(userId, selectedProjectId, {
      name,
      description: editProjectDescription,
      external_refs: parseExternalRefsText(editProjectExternalRefsText),
      attachment_refs: parseAttachmentRefsText(editProjectAttachmentRefsText),
    })
    await syncProjectMembers(selectedProjectId, memberIds)
    await qc.invalidateQueries({ queryKey: ['bootstrap'] })
  }, [
    editProjectAttachmentRefsText,
    editProjectDescription,
    editProjectExternalRefsText,
    editProjectMemberIds,
    editProjectName,
    qc,
    selectedProjectId,
    syncProjectMembers,
    userId,
  ])

  const saveNoteNow = React.useCallback(async () => {
    if (!selectedNoteId) throw new Error('No note selected')
    const payload = {
      title: editNoteTitle.trim() || 'Untitled',
      body: editNoteBody,
      tags: parseCommaTags(editNoteTags),
      external_refs: parseExternalRefsText(editNoteExternalRefsText),
      attachment_refs: parseAttachmentRefsText(editNoteAttachmentRefsText),
    }
    await patchNote(userId, selectedNoteId, payload)
    await qc.invalidateQueries({ queryKey: ['notes'] })
    await qc.invalidateQueries({ queryKey: ['project-tags'] })
  }, [editNoteAttachmentRefsText, editNoteBody, editNoteExternalRefsText, editNoteTags, editNoteTitle, qc, selectedNoteId, userId])

  const buildTaskPatchPayload = React.useCallback(() => {
    if (!selectedTaskId) throw new Error('No task selected')
    const recurringRule =
      editTaskType === 'scheduled_instruction' && editRecurringEvery.trim()
        ? `every:${Math.max(1, Number(editRecurringEvery) || 1)}${editRecurringUnit}`
        : null
    const payload = {
      description: editDescription,
      status: editStatus,
      priority: editPriority,
      project_id: editProjectId || selectedTask?.project_id,
      labels: editTaskTags,
      external_refs: parseExternalRefsText(editTaskExternalRefsText),
      attachment_refs: parseAttachmentRefsText(editTaskAttachmentRefsText),
      due_date: editDueDate ? new Date(editDueDate).toISOString() : null,
      task_type: editTaskType,
      scheduled_at_utc: editTaskType === 'scheduled_instruction' && editScheduledAtUtc ? new Date(editScheduledAtUtc).toISOString() : null,
      schedule_timezone: editTaskType === 'scheduled_instruction' ? (editScheduleTimezone || null) : null,
      scheduled_instruction: editTaskType === 'scheduled_instruction' ? (editScheduledInstruction.trim() || null) : null,
      recurring_rule: recurringRule,
    }
    return { payload }
  }, [
    editTaskAttachmentRefsText,
    editDescription,
    editDueDate,
    editPriority,
    editProjectId,
    editRecurringEvery,
    editRecurringUnit,
    editScheduledAtUtc,
    editScheduledInstruction,
    editScheduleTimezone,
    editStatus,
    editTaskTags,
    editTaskType,
    editTaskExternalRefsText,
    selectedTask?.project_id,
    selectedTaskId,
  ])

  const saveTaskNow = React.useCallback(async () => {
    if (!selectedTaskId) throw new Error('No task selected')
    if (editTaskType === 'scheduled_instruction' && !editScheduledInstruction.trim()) {
      throw new Error('Add scheduled instruction to save.')
    }
    const { payload } = buildTaskPatchPayload()
    await patchTask(userId, selectedTaskId, payload)
    await qc.invalidateQueries({ queryKey: ['tasks'] })
    await qc.invalidateQueries({ queryKey: ['board'] })
  }, [buildTaskPatchPayload, editScheduledInstruction, editTaskType, qc, selectedTaskId, userId])

  const saveProjectMutation = useMutation({
    mutationFn: () => saveProjectNow(),
    onSuccess: () => {
      setUiError(null)
    },
    onError: (err) => setUiError(toErrorMessage(err, 'Project save failed')),
  })

  const saveNoteMutation = useMutation({
    mutationFn: () => saveNoteNow(),
    onSuccess: () => {
      setUiError(null)
    },
    onError: (err) => setUiError(toErrorMessage(err, 'Note save failed')),
  })

  const saveTaskMutation = useMutation({
    mutationFn: () => saveTaskNow(),
    onSuccess: () => {
      setUiError(null)
      setTaskEditorError(null)
    },
    onError: (err) => {
      const message = toErrorMessage(err, 'Task save failed')
      setUiError(message)
      setTaskEditorError(message)
    },
  })

  const createTaskMutation = useMutation({
    mutationFn: () =>
      createTask(userId, {
        title: taskTitle.trim(),
        workspace_id: workspaceId,
        project_id: quickProjectId || selectedProjectId,
        due_date: quickDueDate ? new Date(quickDueDate).toISOString() : null,
        labels: quickTaskTags,
        external_refs: parseExternalRefsText(quickTaskExternalRefsText),
        attachment_refs: parseAttachmentRefsText(quickTaskAttachmentRefsText),
      }),
    onSuccess: async () => {
      setUiError(null)
      setTaskTitle('')
      setQuickDueDate('')
      setQuickTaskTags([])
      setQuickTaskExternalRefsText('')
      setQuickTaskAttachmentRefsText('')
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

  const createProjectMutation = useMutation({
    mutationFn: () =>
      createProject(userId, {
        workspace_id: workspaceId,
        name: projectName.trim(),
        description: projectDescription,
        external_refs: parseExternalRefsText(projectExternalRefsText),
        attachment_refs: parseAttachmentRefsText(projectAttachmentRefsText),
        member_user_ids: Array.from(new Set(createProjectMemberIds)),
      }),
    onSuccess: async (createdProject) => {
      setUiError(null)
      if (draftProjectRules.length > 0) {
        const creations = draftProjectRules.map((rule) =>
          createProjectRule(userId, {
            workspace_id: workspaceId,
            project_id: createdProject.id,
            title: rule.title,
            body: rule.body,
          })
        )
        try {
          await Promise.all(creations)
        } catch (err) {
          setUiError(toErrorMessage(err, 'Project created, but some rules failed to save'))
        }
      }
      setProjectName('')
      setProjectDescription('')
      setProjectExternalRefsText('')
      setProjectAttachmentRefsText('')
      setProjectDescriptionView('write')
      setCreateProjectMemberIds([])
      setDraftProjectRules([])
      setSelectedDraftProjectRuleId(null)
      setDraftProjectRuleTitle('')
      setDraftProjectRuleBody('')
      setDraftProjectRuleView('write')
      setShowProjectCreateForm(false)
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

  const createProjectRuleMutation = useMutation({
    mutationFn: () =>
      createProjectRule(userId, {
        workspace_id: workspaceId,
        project_id: selectedProjectId,
        title: projectRuleTitle.trim(),
        body: projectRuleBody,
      }),
    onSuccess: async (rule) => {
      setUiError(null)
      setSelectedProjectRuleId(rule.id)
      await qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Rule create failed')
  })

  const patchProjectRuleMutation = useMutation({
    mutationFn: () =>
      patchProjectRule(userId, selectedProjectRuleId as string, {
        title: projectRuleTitle.trim(),
        body: projectRuleBody,
      }),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Rule update failed')
  })

  const deleteProjectRuleMutation = useMutation({
    mutationFn: (ruleId: string) => deleteProjectRule(userId, ruleId),
    onSuccess: async () => {
      setUiError(null)
      setSelectedProjectRuleId(null)
      setProjectRuleTitle('')
      setProjectRuleBody('')
      await qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Rule delete failed')
  })

  const createNoteMutation = useMutation({
    mutationFn: () =>
      createNote(userId, {
        title: 'Untitled',
        workspace_id: workspaceId,
        project_id: selectedProjectId,
        body: '',
        external_refs: [],
        attachment_refs: [],
      }),
    onSuccess: async (note) => {
      setUiError(null)
      setTab('notes')
      openNextSelectedNoteInWriteRef.current = true
      setSelectedNoteId(note.id)
      setShowTagPicker(true)
      setTagPickerQuery('')
      await invalidateAll()
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Note create failed')
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
      setScrollToNewestComment(true)
      await qc.invalidateQueries({ queryKey: ['comments', userId, selectedTaskId] })
      await qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Comment failed')
  })
  const deleteCommentMutation = useMutation({
    mutationFn: (commentId: number) => deleteComment(userId, selectedTaskId as string, commentId),
    onSuccess: async () => {
      setUiError(null)
      await qc.invalidateQueries({ queryKey: ['comments', userId, selectedTaskId] })
      await qc.invalidateQueries({ queryKey: ['activity', userId, selectedTaskId] })
    },
    onError: (err) => setUiError(err instanceof Error ? err.message : 'Delete comment failed')
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
    mutationFn: (payload: { instruction: string; history: Array<{ role: 'user' | 'assistant'; content: string }>; projectId: string | null }) =>
      runAgentChat(userId, {
        workspace_id: workspaceId,
        project_id: payload.projectId,
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

  React.useEffect(() => {
    if (!selectedProject) {
      setEditProjectName('')
      setEditProjectDescription('')
      setEditProjectExternalRefsText('')
      setEditProjectAttachmentRefsText('')
      setEditProjectDescriptionView('write')
      setShowProjectEditForm(false)
      setSelectedProjectRuleId(null)
      setProjectRuleTitle('')
      setProjectRuleBody('')
      setProjectRuleView('write')
      return
    }
    setEditProjectName(selectedProject.name ?? '')
    setEditProjectDescription(selectedProject.description ?? '')
    setEditProjectExternalRefsText(externalRefsToText(selectedProject.external_refs))
    setEditProjectAttachmentRefsText(attachmentRefsToText(selectedProject.attachment_refs))
    const hasDescription = Boolean((selectedProject.description ?? '').trim())
    setEditProjectDescriptionView(hasDescription ? 'preview' : 'write')
    setSelectedProjectRuleId(null)
    setProjectRuleTitle('')
    setProjectRuleBody('')
    setProjectRuleView('write')
  }, [selectedProject?.id])

  React.useEffect(() => {
    if (!showProjectCreateForm) return
    const hasDescription = Boolean(projectDescription.trim())
    setProjectDescriptionView(hasDescription ? 'preview' : 'write')
  }, [showProjectCreateForm])

  React.useEffect(() => {
    if (!selectedProjectRule) return
    setProjectRuleTitle(selectedProjectRule.title ?? '')
    setProjectRuleBody(selectedProjectRule.body ?? '')
    setProjectRuleView('write')
  }, [selectedProjectRule?.id])

  React.useEffect(() => {
    if (!selectedDraftProjectRuleId) return
    const selected = draftProjectRules.find((r) => r.id === selectedDraftProjectRuleId)
    if (!selected) return
    setDraftProjectRuleTitle(selected.title)
    setDraftProjectRuleBody(selected.body)
    setDraftProjectRuleView('write')
  }, [selectedDraftProjectRuleId, draftProjectRules])

  React.useEffect(() => {
    if (!showProjectCreateForm || projectDescriptionView !== 'write') return
    autoResizeTextarea(projectDescriptionRef.current)
  }, [autoResizeTextarea, projectDescription, projectDescriptionView, showProjectCreateForm])

  React.useEffect(() => {
    if (!showProjectEditForm || editProjectDescriptionView !== 'write') return
    autoResizeTextarea(editProjectDescriptionRef.current)
  }, [autoResizeTextarea, editProjectDescription, editProjectDescriptionView, showProjectEditForm])

  if (bootstrap.isLoading) return <div className="page"><div className="card skeleton">Loading workspace...</div></div>
  if (bootstrap.isError || !bootstrap.data) return <div className="page"><div className="notice">Unable to load bootstrap data.</div></div>

  const unreadCount = (notifications.data ?? []).filter((n) => !n.is_read).length
  const actorNames = Object.fromEntries((bootstrap.data.users ?? []).map((u) => [u.id, u.username]))
  const projectNames = Object.fromEntries((bootstrap.data.projects ?? []).map((p) => [p.id, p.name]))
  const selectedTaskTimeMeta = pickSingleTimeMeta(selectedTask?.created_at, selectedTask?.updated_at)
  const selectedNoteTimeMeta = pickSingleTimeMeta(selectedNote?.created_at, selectedNote?.updated_at)
  const selectedProjectTimeMeta = pickSingleTimeMeta(selectedProject?.created_at, selectedProject?.updated_at)
  const selectedTaskCreator = selectedTask?.created_by ? actorNames[selectedTask.created_by] || selectedTask.created_by : 'Unknown'
  const selectedNoteCreator = selectedNote?.created_by ? actorNames[selectedNote.created_by] || selectedNote.created_by : 'Unknown'
  const selectedProjectCreator = selectedProject?.created_by ? actorNames[selectedProject.created_by] || selectedProject.created_by : 'Unknown'

  return (
    <div className="page">
      <header className="header card">
        <div className="title-row">
          <div className="brand" role="banner">
            <div className="brand-mark" aria-hidden="true">m</div>
            <div className="brand-stack">
              <div className="brand-name">m4tr1x</div>
              <div className="brand-sub">c0d3 w1th m3m0ry</div>
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
      {uiError && (
        <div className="notice notice-global" role="alert">
          <span>{uiError}</span>
          <button className="action-icon" onClick={() => setUiError(null)} title="Dismiss" aria-label="Dismiss">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      )}
      {uiInfo && (
        <div className="notice notice-global" role="status">
          <span>{uiInfo}</span>
          <button className="action-icon" onClick={() => setUiInfo(null)} title="Dismiss" aria-label="Dismiss">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      )}

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
                <div className="quickadd-project-field">
                  <span className="meta quickadd-project-label">Project</span>
			              <select
                    className="quickadd-project-select"
                    value={quickProjectId}
                    onChange={(e) => setQuickProjectId(e.target.value)}
                    aria-label="Project"
                  >
			                  {(bootstrap.data?.projects ?? []).map((p) => (
		                  <option key={p.id} value={p.id}>
		                    {p.name}
		                  </option>
		                ))}
			              </select>
                </div>
	              <div className={`quickadd-due ${quickDueDate ? 'has-value' : ''} ${quickDueDateFocused ? 'focused' : ''}`}>
	                <span className="quickadd-due-placeholder">Due Date</span>
	                <input
	                  id="quick-task-due-date"
	                  className={`due-input ${!quickDueDate && !quickDueDateFocused ? 'due-input-empty' : ''}`}
	                  type="datetime-local"
	                  value={quickDueDate}
	                  onChange={(e) => setQuickDueDate(e.target.value)}
	                  onFocus={() => setQuickDueDateFocused(true)}
	                  onBlur={() => setQuickDueDateFocused(false)}
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
                <div className="meta" style={{ marginTop: 8 }}>External links</div>
                <ExternalRefEditor
                  refs={parseExternalRefsText(quickTaskExternalRefsText)}
                  onRemoveIndex={(idx) => setQuickTaskExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
                  onAdd={(ref) =>
                    setQuickTaskExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
                  }
                />
                <div className="meta" style={{ marginTop: 8 }}>File attachments</div>
                <div className="row" style={{ marginTop: 6 }}>
                  <button
                    className="status-chip"
                    type="button"
                    onClick={() => quickTaskFileInputRef.current?.click()}
                  >
                    Upload file
                  </button>
                  <input
                    ref={quickTaskFileInputRef}
                    type="file"
                    style={{ display: 'none' }}
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      e.currentTarget.value = ''
                      if (!file) return
                      try {
                        const ref = await uploadAttachmentRef(file, { project_id: quickProjectId || selectedProjectId })
                        setQuickTaskAttachmentRefsText((prev) => attachmentRefsToText([...parseAttachmentRefsText(prev), ref]))
                      } catch (err) {
                        setUiError(toErrorMessage(err, 'Upload failed'))
                      }
                    }}
                  />
                </div>
                <AttachmentRefList
                  refs={parseAttachmentRefsText(quickTaskAttachmentRefsText)}
                  workspaceId={workspaceId}
                  userId={userId}
                  onRemovePath={(path) => {
                    removeUploadedAttachment(path)
                      .then(() => setQuickTaskAttachmentRefsText((prev) => removeAttachmentByPath(prev, path)))
                      .catch((err) => setUiError(toErrorMessage(err, 'Remove file failed')))
                  }}
                />
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
		              <button
                        className="primary tag-picker-create"
                        onClick={() => {
                          toggleQuickTaskTag(quickTaskTagQuery)
                          setQuickTaskTagQuery('')
                          setShowQuickTaskTagPicker(false)
                        }}
                        title="Create tag"
                        aria-label="Create tag"
                      >
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
                      <div key={task.id} className="kanban-card" onClick={() => openTaskEditor(task.id)} role="button">
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
                  <div className="task-main" role="button" onClick={() => openTaskEditor(task.id)}>
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
	            <div className="row" style={{ gap: 8 }}>
	                <button
	                  className="primary"
	                  onClick={() => {
	                    if (showProjectEditForm && projectIsDirty && !confirmDiscardChanges()) return
	                    setShowProjectEditForm(false)
	                    setShowProjectCreateForm((v) => !v)
	                  }}
	                  title={showProjectCreateForm ? 'Close create' : 'New project'}
	                  aria-label={showProjectCreateForm ? 'Close create' : 'New project'}
	              >
	                <Icon path={showProjectCreateForm ? 'M6 6l12 12M18 6L6 18' : 'M12 5v14M5 12h14'} />
	              </button>
	            </div>
	          </div>
          {showProjectCreateForm && (
            <div style={{ marginBottom: 10 }}>
              <h3 style={{ margin: '0 0 8px 0' }}>Create project</h3>
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
                <button className="primary" disabled={!projectName.trim()} onClick={() => createProjectMutation.mutate()}>
                  <Icon path="M12 5v14M5 12h14" />
                </button>
              </div>
              <div className="row" style={{ justifyContent: 'flex-end', marginBottom: 8 }}>
                <div className="seg" role="tablist" aria-label="Project description editor view">
                  <button
                    className={`seg-btn ${projectDescriptionView === 'write' ? 'active' : ''}`}
                    onClick={() => setProjectDescriptionView('write')}
                    type="button"
                  >
                    Edit
                  </button>
                  <button
                    className={`seg-btn ${projectDescriptionView === 'preview' ? 'active' : ''}`}
                    onClick={() => setProjectDescriptionView('preview')}
                    type="button"
                  >
                    Preview
                  </button>
                </div>
              </div>
              {projectDescriptionView === 'write' ? (
                <textarea
                  ref={projectDescriptionRef}
                  value={projectDescription}
                  onChange={(e) => setProjectDescription(e.target.value)}
                  placeholder="Project description (Markdown)"
                  style={{ width: '100%', minHeight: 96, maxHeight: 280, resize: 'none', overflowY: 'hidden' }}
                />
              ) : (
                <MarkdownView value={projectDescription} />
              )}
              <div className="rules-studio" style={{ marginTop: 10, marginBottom: 14 }}>
                <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                  <h3 style={{ margin: 0 }}>Project Rules (Draft: {draftProjectRules.length})</h3>
                  <div className="meta">These rules are created with the new project.</div>
                </div>
                <div className="rules-layout">
                  <div className="rules-list">
                    {draftProjectRules.length === 0 ? (
                      <div className="notice">No draft rules yet.</div>
                    ) : (
                      draftProjectRules.map((rule) => {
                        const isSelected = selectedDraftProjectRuleId === rule.id
                        return (
                          <div
                            key={rule.id}
                            className={`task-item rule-item ${isSelected ? 'selected' : ''}`}
                            onClick={() => setSelectedDraftProjectRuleId(rule.id)}
                            role="button"
                          >
                            <div className="task-main">
                              <div className="task-title">
                                <strong>{rule.title || 'Untitled rule'}</strong>
                                {isSelected && <span className="badge">Editing</span>}
                              </div>
                              <div className="meta">{(rule.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                  <div className="rules-editor">
                    <div className="row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                      <input
                        value={draftProjectRuleTitle}
                        onChange={(e) => setDraftProjectRuleTitle(e.target.value)}
                        placeholder="Rule title"
                      />
                      <button
                        className="status-chip"
                        onClick={() => {
                          setSelectedDraftProjectRuleId(null)
                          setDraftProjectRuleTitle('')
                          setDraftProjectRuleBody('')
                          setDraftProjectRuleView('write')
                        }}
                        title="New rule"
                        aria-label="New rule"
                      >
                        New rule
                      </button>
                    </div>
                    <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                      <div className="seg" role="tablist" aria-label="Draft project rule editor view">
                        <button
                          className={`seg-btn ${draftProjectRuleView === 'write' ? 'active' : ''}`}
                          onClick={() => setDraftProjectRuleView('write')}
                          type="button"
                        >
                          Write
                        </button>
                        <button
                          className={`seg-btn ${draftProjectRuleView === 'preview' ? 'active' : ''}`}
                          onClick={() => setDraftProjectRuleView('preview')}
                          type="button"
                        >
                          Preview
                        </button>
                      </div>
                      <div className="row" style={{ gap: 8 }}>
                        <button
                          className="primary"
                          disabled={!draftProjectRuleTitle.trim()}
                          onClick={() => {
                            const title = draftProjectRuleTitle.trim()
                            if (!title) return
                            if (selectedDraftProjectRuleId) {
                              setDraftProjectRules((prev) =>
                                prev.map((item) =>
                                  item.id === selectedDraftProjectRuleId
                                    ? { ...item, title, body: draftProjectRuleBody }
                                    : item
                                )
                              )
                            } else {
                              const newId = globalThis.crypto?.randomUUID?.() ?? `draft-rule-${Date.now()}`
                              setDraftProjectRules((prev) => [...prev, { id: newId, title, body: draftProjectRuleBody }])
                              setSelectedDraftProjectRuleId(newId)
                            }
                          }}
                          title={selectedDraftProjectRuleId ? 'Update draft rule' : 'Add draft rule'}
                          aria-label={selectedDraftProjectRuleId ? 'Update draft rule' : 'Add draft rule'}
                        >
                          <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                        </button>
                        {selectedDraftProjectRuleId && (
                          <button
                            className="action-icon danger-ghost"
                            onClick={() => {
                              if (!selectedDraftProjectRuleId) return
                              setDraftProjectRules((prev) => prev.filter((item) => item.id !== selectedDraftProjectRuleId))
                              setSelectedDraftProjectRuleId(null)
                              setDraftProjectRuleTitle('')
                              setDraftProjectRuleBody('')
                            }}
                            title="Remove draft rule"
                            aria-label="Remove draft rule"
                          >
                            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                          </button>
                        )}
                      </div>
                    </div>
                    {draftProjectRuleView === 'write' ? (
                      <textarea
                        value={draftProjectRuleBody}
                        onChange={(e) => setDraftProjectRuleBody(e.target.value)}
                        placeholder="Rule details (Markdown)"
                        style={{ width: '100%', minHeight: 140 }}
                      />
                    ) : (
                      <MarkdownView value={draftProjectRuleBody} />
                    )}
                  </div>
                </div>
              </div>
              <div className="meta" style={{ marginTop: 10 }}>External links</div>
              <ExternalRefEditor
                refs={parseExternalRefsText(projectExternalRefsText)}
                onRemoveIndex={(idx) => setProjectExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
                onAdd={(ref) =>
                  setProjectExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
                }
              />
              <div className="meta" style={{ marginTop: 8 }}>
                File attachments are available after project is created.
              </div>
              <div style={{ marginTop: 10 }}>
                <div className="meta" style={{ marginBottom: 6 }}>Assign users to project</div>
                <div className="row wrap" style={{ gap: 6 }}>
                  {workspaceUsers.map((u) => {
                    const selected = createProjectMemberIds.includes(u.id)
                    return (
                      <button
                        key={`create-member-${u.id}`}
                        type="button"
                        className={`status-chip ${selected ? 'active' : ''}`}
                        onClick={() => toggleCreateProjectMember(u.id)}
                        aria-pressed={selected}
                        title={`${u.full_name} (${u.user_type})`}
                      >
                        {u.full_name} · {u.user_type}
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
	          <div className="task-list">
	            {bootstrap.data.projects.map((project, idx) => {
	              const isSelected = selectedProjectId === project.id
              const isOpen = isSelected && showProjectEditForm && selectedProject?.id === project.id
	              const taskCount = projectTaskCountQueries[idx]?.data?.total
	              const noteCount = projectNoteCountQueries[idx]?.data?.total
	              const ruleCount = projectRuleCountQueries[idx]?.data?.total
	              return (
	                <div key={project.id} className={`task-item project-item ${isOpen ? 'open selected' : isSelected ? 'selected' : ''}`}>
	                  <div className="task-main" role="button" onClick={() => toggleProjectEditor(project.id)}>
	                    <div className="task-title">
	                      <strong>{project.name}</strong>
	                    </div>
                    <span className="meta">Status: {project.status || 'active'}</span>
                    <div className="meta">{project.description || '(no description)'}</div>
                    <div className="meta">
                      {[
                        typeof taskCount === 'number' && taskCount > 0 ? `Tasks: ${taskCount}` : '',
                        typeof noteCount === 'number' && noteCount > 0 ? `Notes: ${noteCount}` : '',
                        typeof ruleCount === 'number' && ruleCount > 0 ? `Rules: ${ruleCount}` : '',
                        (projectMemberCounts[project.id] ?? 0) > 0 ? `Members: ${projectMemberCounts[project.id] ?? 0}` : '',
                      ]
                        .filter(Boolean)
                        .join(' | ')}
                    </div>
	                    <ExternalRefList refs={project.external_refs} />
	                    <AttachmentRefList refs={project.attachment_refs} workspaceId={workspaceId} userId={userId} />
                      {isOpen && selectedProject && (
                        <div style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
                          <div className="row wrap resource-meta-row" style={{ marginBottom: 8 }}>
                            <div className="meta">Created by: {selectedProjectCreator}</div>
                            {selectedProjectTimeMeta && <div className="meta">{selectedProjectTimeMeta.label}: {toUserDateTime(selectedProjectTimeMeta.value, userTimezone)}</div>}
                          </div>
                          <div className="row" style={{ marginBottom: 10 }}>
                            <input value={editProjectName} onChange={(e) => setEditProjectName(e.target.value)} placeholder="Project name" />
                            {projectIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
                            <button
                              className="primary"
                              onClick={() => saveProjectMutation.mutate()}
                              disabled={saveProjectMutation.isPending || !editProjectName.trim() || !projectIsDirty}
                              title="Save project"
                              aria-label="Save project"
                            >
                              Save
                            </button>
                          </div>
                          <div className="row" style={{ justifyContent: 'flex-end', marginBottom: 8 }}>
                            <div className="seg" role="tablist" aria-label="Edit project description editor view">
                              <button
                                className={`seg-btn ${editProjectDescriptionView === 'write' ? 'active' : ''}`}
                                onClick={() => setEditProjectDescriptionView('write')}
                                type="button"
                              >
                                Edit
                              </button>
                              <button
                                className={`seg-btn ${editProjectDescriptionView === 'preview' ? 'active' : ''}`}
                                onClick={() => setEditProjectDescriptionView('preview')}
                                type="button"
                              >
                                Preview
                              </button>
                            </div>
                          </div>
                          {editProjectDescriptionView === 'write' ? (
                            <textarea
                              ref={editProjectDescriptionRef}
                              value={editProjectDescription}
                              onChange={(e) => setEditProjectDescription(e.target.value)}
                              placeholder="Project description (Markdown)"
                              style={{ width: '100%', minHeight: 96, maxHeight: 280, resize: 'none', overflowY: 'hidden' }}
                            />
                          ) : (
                            <MarkdownView value={editProjectDescription} />
                          )}
                          <div className="rules-studio" style={{ marginTop: 10, marginBottom: 14 }}>
                            <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                              <h3 style={{ margin: 0 }}>Project Rules ({projectRules.data?.total ?? 0})</h3>
                              <div className="row" style={{ gap: 8 }}>
                                <input
                                  value={projectRuleQ}
                                  onChange={(e) => setProjectRuleQ(e.target.value)}
                                  placeholder="Search rules"
                                  style={{ minWidth: 180 }}
                                />
                              </div>
                            </div>
                            <div className="rules-layout">
                              <div className="rules-list">
                                {(projectRules.data?.items ?? []).length === 0 ? (
                                  <div className="notice">No rules yet for this project.</div>
                                ) : (
                                  (projectRules.data?.items ?? []).map((rule: ProjectRule) => {
                                    const isSelected = selectedProjectRuleId === rule.id
                                    return (
                                      <div
                                        key={rule.id}
                                        className={`task-item rule-item ${isSelected ? 'selected' : ''}`}
                                        onClick={() => setSelectedProjectRuleId(rule.id)}
                                        role="button"
                                      >
                                        <div className="task-main">
                                          <div className="task-title">
                                            <strong>{rule.title || 'Untitled rule'}</strong>
                                            {isSelected && <span className="badge">Editing</span>}
                                          </div>
                                          <div className="meta">{(rule.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                                          <div className="meta">Updated: {toUserDateTime(rule.updated_at, userTimezone)}</div>
                                        </div>
                                      </div>
                                    )
                                  })
                                )}
                              </div>
                              <div className="rules-editor">
                                <div className="row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                                  <input
                                    value={projectRuleTitle}
                                    onChange={(e) => setProjectRuleTitle(e.target.value)}
                                    placeholder="Rule title"
                                  />
                                  <button
                                    className="status-chip"
                                    onClick={() => {
                                      setSelectedProjectRuleId(null)
                                      setProjectRuleTitle('')
                                      setProjectRuleBody('')
                                      setProjectRuleView('write')
                                    }}
                                    title="New rule"
                                    aria-label="New rule"
                                  >
                                    New rule
                                  </button>
                                </div>
                                <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                                  <div className="seg" role="tablist" aria-label="Project rule editor view">
                                    <button
                                      className={`seg-btn ${projectRuleView === 'write' ? 'active' : ''}`}
                                      onClick={() => setProjectRuleView('write')}
                                      type="button"
                                    >
                                      Write
                                    </button>
                                    <button
                                      className={`seg-btn ${projectRuleView === 'preview' ? 'active' : ''}`}
                                      onClick={() => setProjectRuleView('preview')}
                                      type="button"
                                    >
                                      Preview
                                    </button>
                                  </div>
                                  <div className="row" style={{ gap: 8 }}>
                                    <button
                                      className="primary"
                                      disabled={!projectRuleTitle.trim() || createProjectRuleMutation.isPending || patchProjectRuleMutation.isPending}
                                      onClick={() => {
                                        if (selectedProjectRuleId) patchProjectRuleMutation.mutate()
                                        else createProjectRuleMutation.mutate()
                                      }}
                                      title={selectedProjectRuleId ? 'Update rule' : 'Create rule'}
                                      aria-label={selectedProjectRuleId ? 'Update rule' : 'Create rule'}
                                    >
                                      <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                                    </button>
                                    {selectedProjectRuleId && (
                                      <button
                                        className="action-icon danger-ghost"
                                        disabled={deleteProjectRuleMutation.isPending}
                                        onClick={() => {
                                          if (!selectedProjectRuleId) return
                                          if (!window.confirm('Delete this rule?')) return
                                          deleteProjectRuleMutation.mutate(selectedProjectRuleId)
                                        }}
                                        title="Delete rule"
                                        aria-label="Delete rule"
                                      >
                                        <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                                      </button>
                                    )}
                                  </div>
                                </div>
                                {projectRuleView === 'write' ? (
                                  <textarea
                                    value={projectRuleBody}
                                    onChange={(e) => setProjectRuleBody(e.target.value)}
                                    placeholder="Rule details (Markdown)"
                                    style={{ width: '100%', minHeight: 140 }}
                                  />
                                ) : (
                                  <MarkdownView value={projectRuleBody} />
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="meta" style={{ marginTop: 10 }}>External links</div>
                          <ExternalRefEditor
                            refs={parseExternalRefsText(editProjectExternalRefsText)}
                            onRemoveIndex={(idx) => setEditProjectExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
                            onAdd={(ref) =>
                              setEditProjectExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
                            }
                          />
                          <div className="meta" style={{ marginTop: 8 }}>File attachments</div>
                          <div className="row" style={{ marginTop: 6 }}>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => editProjectFileInputRef.current?.click()}
                            >
                              Upload file
                            </button>
                            <input
                              ref={editProjectFileInputRef}
                              type="file"
                              style={{ display: 'none' }}
                              onChange={async (e) => {
                                const file = e.target.files?.[0]
                                e.currentTarget.value = ''
                                if (!file || !selectedProject) return
                                try {
                                  const ref = await uploadAttachmentRef(file, { project_id: selectedProject.id })
                                  setEditProjectAttachmentRefsText((prev) => attachmentRefsToText([...parseAttachmentRefsText(prev), ref]))
                                } catch (err) {
                                  setUiError(toErrorMessage(err, 'Upload failed'))
                                }
                              }}
                            />
                          </div>
                          <AttachmentRefList
                            refs={parseAttachmentRefsText(editProjectAttachmentRefsText)}
                            workspaceId={workspaceId}
                            userId={userId}
                            onRemovePath={(path) => {
                              setEditProjectAttachmentRefsText((prev) => removeAttachmentByPath(prev, path))
                            }}
                          />
                          <div style={{ marginTop: 10 }}>
                            <div className="meta" style={{ marginBottom: 6 }}>Assigned users</div>
                            <div className="row wrap" style={{ gap: 6 }}>
                              {workspaceUsers.map((u) => {
                                const selected = editProjectMemberIds.includes(u.id)
                                return (
                                  <button
                                    key={`edit-member-${u.id}`}
                                    type="button"
                                    className={`status-chip ${selected ? 'active' : ''}`}
                                    onClick={() => toggleEditProjectMember(u.id)}
                                    aria-pressed={selected}
                                    title={`${u.full_name} (${u.user_type})`}
                                  >
                                    {u.full_name} · {u.user_type}
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        </div>
                      )}
	                  </div>
                  <div className="project-item-actions">
                    <button
                      className="action-icon"
                      type="button"
                      onClick={() => copyShareLink({ tab: 'projects', projectId: project.id })}
                      title="Copy project link"
                      aria-label="Copy project link"
                    >
                      <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                    </button>
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
                            className={`status-chip tag-filter-chip ${noteTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
                            onClick={() => toggleNoteFilterTag(tag)}
                            aria-pressed={noteTags.includes(tag.toLowerCase())}
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
                    const displayTitle = isSelected ? editNoteTitle || 'Untitled' : n.title || 'Untitled'
		                return (
		                  <div
		                    key={n.id}
		                    className={`note-row ${isOpen ? 'open selected' : ''}`}
		                    onClick={() => {
                          const changed = toggleNoteEditor(n.id)
                          if (!changed) return
		                      setShowTagPicker(false)
		                      setTagPickerQuery('')
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
		                      <strong>{displayTitle}</strong>
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
                          {((n.external_refs?.length ?? 0) > 0 || (n.attachment_refs?.length ?? 0) > 0) && (
                            <div className="row wrap" style={{ gap: 6 }} onClick={(e) => e.stopPropagation()}>
                              <ExternalRefList refs={n.external_refs} />
                              <AttachmentRefList refs={n.attachment_refs} workspaceId={workspaceId} userId={userId} />
                            </div>
                          )}

		                    {isOpen && isSelected && selectedNote && (
		                      <div className="note-accordion" onClick={(e) => e.stopPropagation()} role="region" aria-label="Note editor">
				                        <div className="note-editor-head">
			                          <input
			                            className="note-title-input"
			                            value={editNoteTitle}
			                            onChange={(e) => setEditNoteTitle(e.target.value)}
			                            placeholder="Title"
			                          />
			                          <div className="note-actions">
                            {noteIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
                            <button
                              className="action-icon primary"
                              onClick={() => saveNoteMutation.mutate()}
                              disabled={saveNoteMutation.isPending || !noteIsDirty}
                              title="Save note"
                              aria-label="Save note"
                            >
                              <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                            </button>
                            <button
                              className="action-icon"
                              onClick={() => copyShareLink({ tab: 'notes', projectId: selectedNote.project_id, noteId: selectedNote.id })}
                              title="Copy note link"
                              aria-label="Copy note link"
                            >
                              <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
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
                        <div className="row wrap resource-meta-row" style={{ marginBottom: 8 }}>
                          <div className="meta">Created by: {selectedNoteCreator}</div>
                          {selectedNoteTimeMeta && <div className="meta">{selectedNoteTimeMeta.label}: {toUserDateTime(selectedNoteTimeMeta.value, userTimezone)}</div>}
                        </div>
		                        </div>

			                        <div className="row" style={{ justifyContent: 'flex-end' }}>
			                          <div className="seg" role="tablist" aria-label="Note editor view">
			                            <button className={`seg-btn ${noteEditorView === 'write' ? 'active' : ''}`} onClick={() => setNoteEditorView('write')} type="button">
			                              Edit
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
	                        <div className="meta" style={{ marginTop: 8 }}>External links</div>
	                        <ExternalRefEditor
	                          refs={parseExternalRefsText(editNoteExternalRefsText)}
                          onRemoveIndex={(idx) => setEditNoteExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
                          onAdd={(ref) =>
                            setEditNoteExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
                          }
                        />
                        <div className="meta" style={{ marginTop: 8 }}>File attachments</div>
                        <div className="row" style={{ marginTop: 6 }}>
                          <button
                            className="status-chip"
                            type="button"
                            onClick={() => noteFileInputRef.current?.click()}
                          >
                            Upload file
                          </button>
                          <input
                            ref={noteFileInputRef}
                            type="file"
                            style={{ display: 'none' }}
                            onChange={async (e) => {
                              const file = e.target.files?.[0]
                              e.currentTarget.value = ''
                              if (!file || !selectedNote) return
                              try {
                                const ref = await uploadAttachmentRef(file, { project_id: selectedNote.project_id, note_id: selectedNote.id })
                                setEditNoteAttachmentRefsText((prev) => attachmentRefsToText([...parseAttachmentRefsText(prev), ref]))
                              } catch (err) {
                                setUiError(toErrorMessage(err, 'Upload failed'))
                              }
                            }}
                          />
                        </div>
                        <AttachmentRefList
                          refs={parseAttachmentRefsText(editNoteAttachmentRefsText)}
                          workspaceId={workspaceId}
                          userId={userId}
	                          onRemovePath={(path) => {
	                            setEditNoteAttachmentRefsText((prev) => removeAttachmentByPath(prev, path))
	                          }}
	                        />
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
		                              onClick={() => {
                                addNoteTag(tagPickerQuery)
                                setShowTagPicker(false)
                              }}
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
                  className={`status-chip tag-filter-chip ${searchTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
                  onClick={() => toggleSearchTag(tag)}
                  aria-pressed={searchTags.includes(tag.toLowerCase())}
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
                <div className="task-main" role="button" onClick={() => openTaskEditor(task.id)}>
                  <div className="task-title">
                    <strong>{task.title}</strong>
                  </div>
		                  <span className="meta">
		                    {task.status} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'}
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
        <button className={tab === 'notes' ? 'primary' : ''} onClick={() => setTab('notes')} title="Notes" aria-label="Notes">
          <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
          <span className="tab-label">Notes</span>
        </button>
      </nav>

		      <button
		        className={`fab fab-task ${fabHidden ? 'fab-hide' : ''}`}
		        onClick={() => {
              setQuickProjectId(selectedProjectId || bootstrap.data?.projects?.[0]?.id || '')
              setQuickTaskExternalRefsText('')
              setQuickTaskAttachmentRefsText('')
              setShowQuickAdd(true)
            }}
		        title="New Task"
		        aria-label="New Task"
		      >
	        <Icon path="M12 5v14M5 12h14" />
	      </button>
	
		      <button
		        className={`fab ${isCodexChatRunning ? 'busy' : ''} ${fabHidden ? 'fab-hide' : ''}`}
		        onClick={() => {
              setCodexChatProjectId(selectedProjectId || '')
              setShowCodexChat(true)
            }}
		        title="Codex Chat"
		        aria-label="Codex Chat"
		      >
	        <Icon path="M4 4h16v11H7l-3 3V4z" />
	        <span>{isCodexChatRunning ? `Chat (${codexChatElapsedSeconds}s)` : 'Chat'}</span>
	      </button>

	      {selectedTask && (
	        <div className="drawer open" onClick={() => closeTaskEditor()}>
	          <div className="drawer-body task-drawer-body" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div className="task-header-main">
                <h3 className="drawer-title">{selectedTask.title}</h3>
              </div>
              <div className="row task-header-actions">
                {taskIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
                <button
                  className="action-icon primary"
                  onClick={() => saveTaskMutation.mutate()}
                  disabled={saveTaskMutation.isPending || !taskIsDirty}
                  title="Save task"
                  aria-label="Save task"
                >
                  <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                </button>
                <button
                  className="action-icon"
                  onClick={() => copyShareLink({ tab: 'tasks', projectId: selectedTask.project_id, taskId: selectedTask.id })}
                  title="Copy task link"
                  aria-label="Copy task link"
                >
                  <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                </button>
                <span className="action-separator" aria-hidden="true" />
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
                <span className="action-separator" aria-hidden="true" />
                <button className="action-icon" onClick={() => closeTaskEditor()} title="Close" aria-label="Close">
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              </div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <div className="meta">Task ID: <code>{selectedTask.id}</code></div>
              <div className="meta">
                Created by: {selectedTaskCreator}
                {selectedTaskTimeMeta ? ` | ${selectedTaskTimeMeta.label}: ${toUserDateTime(selectedTaskTimeMeta.value, userTimezone)}` : ''}
              </div>
            </div>
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
	            </div>
	            <textarea
	              value={editDescription}
	              onChange={(e) => setEditDescription(e.target.value)}
	              rows={4}
	              style={{ width: '100%', marginBottom: 10 }}
	            />
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
	            </div>
	            {taskEditorError && (
	              <div className="notice" role="alert" style={{ marginBottom: 8 }}>
	                {taskEditorError}
	              </div>
	            )}
	            {editTaskType === 'scheduled_instruction' && (
	              <>
	                <div className="row wrap" style={{ marginBottom: 8 }}>
	                  <input
	                    className="due-input"
	                    type="datetime-local"
	                    value={editScheduledAtUtc}
	                    onChange={(e) => setEditScheduledAtUtc(e.target.value)}
	                  />
	                  <input
	                    value={editScheduleTimezone}
	                    onChange={(e) => setEditScheduleTimezone(e.target.value)}
	                    placeholder="Timezone (e.g. Europe/Sarajevo)"
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
	                    style={{ width: 140 }}
	                  />
	                  <select
	                    value={editRecurringUnit}
	                    onChange={(e) => setEditRecurringUnit(e.target.value as 'm' | 'h' | 'd')}
	                  >
	                    <option value="m">minutes</option>
	                    <option value="h">hours</option>
	                    <option value="d">days</option>
	                  </select>
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
	                </div>
	                <textarea
	                  value={editScheduledInstruction}
	                  onChange={(e) => setEditScheduledInstruction(e.target.value)}
	                  rows={3}
	                  style={{ width: '100%', marginBottom: 8 }}
	                  placeholder='Scheduled (executed automatically when due)'
	                />
	              </>
	            )}
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
            <div className="meta" style={{ marginBottom: 6 }}>External links</div>
            <ExternalRefEditor
              refs={parseExternalRefsText(editTaskExternalRefsText)}
              onRemoveIndex={(idx) => setEditTaskExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
              onAdd={(ref) =>
                setEditTaskExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
              }
            />
            <div className="meta" style={{ marginBottom: 6 }}>File attachments</div>
            <div className="row" style={{ marginBottom: 8 }}>
              <button
                className="status-chip"
                type="button"
                onClick={() => taskFileInputRef.current?.click()}
              >
                Upload file
              </button>
              <input
                ref={taskFileInputRef}
                type="file"
                style={{ display: 'none' }}
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  e.currentTarget.value = ''
                  if (!file || !selectedTask) return
                  try {
                    const ref = await uploadAttachmentRef(file, { project_id: editProjectId || selectedTask.project_id, task_id: selectedTask.id })
                    setEditTaskAttachmentRefsText((prev) => attachmentRefsToText([...parseAttachmentRefsText(prev), ref]))
                  } catch (err) {
                    const message = toErrorMessage(err, 'Upload failed')
                    setUiError(message)
                    setTaskEditorError(message)
                  }
                }}
              />
            </div>
            <AttachmentRefList
              refs={parseAttachmentRefsText(editTaskAttachmentRefsText)}
              workspaceId={workspaceId}
              userId={userId}
              onRemovePath={(path) => {
                setEditTaskAttachmentRefsText((prev) => removeAttachmentByPath(prev, path))
              }}
            />
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
	                    <button
                        className="primary tag-picker-create"
                        onClick={() => {
                          toggleTaskTag(taskTagPickerQuery)
                          setTaskTagPickerQuery('')
                          setShowTaskTagPicker(false)
                        }}
                        title="Create tag"
                        aria-label="Create tag"
                      >
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
            <div ref={commentsListRef} className="note-list comment-list">
              {comments.isLoading && <div className="meta">Loading comments...</div>}
              {comments.data?.map((c) => (
                <div className="note comment-item" key={`${c.id}-${c.created_at}`}>
                  {(() => {
                    const body = c.body || ''
                    const commentId = c.id
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
                            <div className="row" style={{ gap: 6 }}>
                              <span className="meta">{c.created_at ? new Date(c.created_at).toLocaleString() : ''}</span>
                              {typeof commentId === 'number' && (
                                <button
                                  className="action-icon danger-ghost comment-delete-btn"
                                  title="Delete comment"
                                  aria-label="Delete comment"
                                  disabled={deleteCommentMutation.isPending}
                                  onClick={() => {
                                    if (!window.confirm('Delete this comment?')) return
                                    deleteCommentMutation.mutate(commentId)
                                  }}
                                >
                                  <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                                </button>
                              )}
                            </div>
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
            <p className="meta">
              General instruction mode. Session: <code>{codexChatSessionId}</code>
            </p>
            <div className="codex-chat-context">
              <label className="meta codex-chat-context-label" htmlFor="codex-chat-project-context">Project</label>
              <select
                className="codex-chat-context-select"
                id="codex-chat-project-context"
                value={codexChatProjectId}
                onChange={(e) => setCodexChatProjectId(e.target.value)}
                disabled={runAgentChatMutation.isPending}
              >
                <option value="">No project</option>
                {(bootstrap.data?.projects ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="codex-chat-history" ref={codexChatHistoryRef}>
              {codexChatTurns.length === 0 && (
                <div className="meta">Chat is empty. Send your first instruction.</div>
              )}
              {codexChatTurns.map((turn) => (
                <div key={turn.id} className={`codex-chat-bubble ${turn.role}`}>
                  <div className="codex-chat-role">{turn.role === 'user' ? 'You' : 'Codex'}</div>
                  {turn.role === 'assistant' ? <MarkdownView value={turn.content} /> : <div>{turn.content}</div>}
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
	                  runAgentChatMutation.mutate({
                      instruction,
                      history,
                      projectId: codexChatProjectId.trim() ? codexChatProjectId : null,
                    })
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
