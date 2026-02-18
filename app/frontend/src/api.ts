import type {
  BootstrapPayload,
  AgentChatResponse,
  GraphContextPack,
  GraphProjectOverview,
  GraphProjectSubgraph,
  Notification,
  Note,
  NotesPage,
  AttachmentRef,
  AppVersionPayload,
  ExternalRef,
  Project,
  ProjectBoard,
  ProjectMembersPage,
  ProjectRule,
  ProjectRulesPage,
  Specification,
  SpecificationBulkTaskCreateResponse,
  SpecificationsPage,
  ProjectTags,
  Task,
  TaskActivity,
  TaskAutomationStatus,
  TaskComment,
  TasksPage,
} from './types'

function formatApiError(raw: string, status: number): string {
  const fallback = `Request failed (${status})`
  const text = String(raw || '').trim()
  if (!text) return fallback
  try {
    const parsed = JSON.parse(text) as unknown
    const payload = parsed as Record<string, unknown>
    const detail = payload?.detail ?? payload?.message ?? payload?.error ?? parsed
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item === 'string') return item.trim()
          if (item && typeof item === 'object') {
            const o = item as Record<string, unknown>
            const msg = typeof o.msg === 'string' ? o.msg.trim() : ''
            const loc = Array.isArray(o.loc)
              ? o.loc.map((x) => String(x)).filter(Boolean).join('.')
              : ''
            return loc && msg ? `${loc}: ${msg}` : msg
          }
          return ''
        })
        .filter(Boolean)
      if (messages.length) return messages.join(' | ')
    }
  } catch {
    // Not JSON; fall back to plain text below.
  }
  return text
}

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    q.set(k, String(v))
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

export async function api<T>(path: string, userId: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const commandId = method === 'GET' ? undefined : (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`)
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
      ...(commandId ? { 'X-Command-Id': commandId } : {}),
      ...(init?.headers ?? {})
    }
  })
  if (!res.ok) {
    const raw = await res.text()
    throw new Error(formatApiError(raw, res.status))
  }
  return (await res.json()) as T
}

async function uploadApi<T>(path: string, userId: string, body: FormData): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'X-User-Id': userId },
    body
  })
  if (!res.ok) {
    const raw = await res.text()
    throw new Error(formatApiError(raw, res.status))
  }
  return (await res.json()) as T
}

export const getBootstrap = (userId: string) => api<BootstrapPayload>('/api/bootstrap', userId)

export async function getAppVersion(): Promise<AppVersionPayload> {
  const res = await fetch('/api/version')
  if (!res.ok) {
    const raw = await res.text()
    throw new Error(formatApiError(raw, res.status))
  }
  return (await res.json()) as AppVersionPayload
}

export const getTasks = (
  userId: string,
  workspaceId: string,
  params?: {
    view?: string
    project_id: string
    q?: string
    status?: string
    priority?: string
    specification_id?: string
    tags?: string[]
    archived?: boolean
    limit?: number
    offset?: number
  }
) =>
  api<TasksPage>(
    `/api/tasks${queryString({
      workspace_id: workspaceId,
      archived: params?.archived ?? false,
      view: params?.view,
      project_id: params?.project_id,
      q: params?.q,
      status: params?.status,
      priority: params?.priority,
      specification_id: params?.specification_id,
      tags: params?.tags?.join(',') || undefined,
      limit: params?.limit ?? 100,
      offset: params?.offset ?? 0
    })}`,
    userId
  )

export const createTask = (
  userId: string,
  payload: {
    title: string
    workspace_id: string
    project_id: string
    specification_id?: string | null
    due_date?: string | null
    labels?: string[]
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
  }
) => api<Task>('/api/tasks', userId, { method: 'POST', body: JSON.stringify(payload) })

export const completeTask = (userId: string, taskId: string) =>
  api<Task>(`/api/tasks/${taskId}/complete`, userId, { method: 'POST' })

export const reopenTask = (userId: string, taskId: string) =>
  api<Task>(`/api/tasks/${taskId}/reopen`, userId, { method: 'POST' })

export const archiveTask = (userId: string, taskId: string) =>
  api<Task>(`/api/tasks/${taskId}/archive`, userId, { method: 'POST' })

export const restoreTask = (userId: string, taskId: string) =>
  api<Task>(`/api/tasks/${taskId}/restore`, userId, { method: 'POST' })

export const patchTask = (
  userId: string,
  taskId: string,
  payload: Partial<
    Pick<
      Task,
      | 'description'
      | 'status'
      | 'due_date'
      | 'project_id'
      | 'title'
      | 'priority'
      | 'labels'
      | 'recurring_rule'
      | 'task_type'
      | 'scheduled_instruction'
      | 'scheduled_at_utc'
      | 'schedule_timezone'
      | 'specification_id'
      | 'external_refs'
      | 'attachment_refs'
    >
  >
) => api<Task>(`/api/tasks/${taskId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const listComments = (userId: string, taskId: string) => api<TaskComment[]>(`/api/tasks/${taskId}/comments`, userId)
export const addComment = (userId: string, taskId: string, body: string) =>
  api<TaskComment>(`/api/tasks/${taskId}/comments`, userId, { method: 'POST', body: JSON.stringify({ body }) })
export const deleteComment = (userId: string, taskId: string, commentId: number) =>
  api<{ ok: true }>(`/api/tasks/${taskId}/comments/${commentId}/delete`, userId, { method: 'POST' })
export const listActivity = (userId: string, taskId: string) => api<TaskActivity[]>(`/api/tasks/${taskId}/activity`, userId)
export const runTaskWithCodex = (userId: string, taskId: string, instruction: string) =>
  api<{ ok: boolean; task_id: string; automation_state: string; requested_at: string }>(
    `/api/tasks/${taskId}/automation/run`,
    userId,
    { method: 'POST', body: JSON.stringify({ instruction }) }
  )
export const getTaskAutomationStatus = (userId: string, taskId: string) =>
  api<TaskAutomationStatus>(`/api/tasks/${taskId}/automation`, userId)

export const runAgentChat = (
  userId: string,
  payload: {
    workspace_id: string
    instruction: string
    project_id?: string | null
    session_id?: string | null
    history?: Array<{ role: 'user' | 'assistant'; content: string }>
    allow_mutations?: boolean
  }
) =>
  api<AgentChatResponse>('/api/agents/chat', userId, {
    method: 'POST',
    body: JSON.stringify(payload)
  })

export const getNotifications = (userId: string) => api<Notification[]>('/api/notifications', userId)

export const markNotificationRead = (userId: string, id: string) =>
  api<{ ok: true }>(`/api/notifications/${id}/read`, userId, { method: 'POST' })

export const createProject = (
  userId: string,
  payload: {
    workspace_id: string
    name: string
    description?: string
    custom_statuses?: string[]
    member_user_ids?: string[]
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
  }
) =>
  api<Project>('/api/projects', userId, { method: 'POST', body: JSON.stringify(payload) })

export const patchProject = (
  userId: string,
  projectId: string,
  payload: Partial<Pick<Project, 'name' | 'description' | 'custom_statuses' | 'external_refs' | 'attachment_refs'>>
) => api<Project>(`/api/projects/${projectId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const deleteProject = (userId: string, projectId: string) =>
  api<{ ok: true }>(`/api/projects/${projectId}`, userId, { method: 'DELETE' })

export const getProjectBoard = (
  userId: string,
  projectId: string,
  params?: {
    tags?: string[]
  }
) =>
  api<ProjectBoard>(
    `/api/projects/${projectId}/board${queryString({
      tags: params?.tags?.join(',') || undefined,
    })}`,
    userId
  )

export const getProjectTags = (userId: string, projectId: string) =>
  api<ProjectTags>(`/api/projects/${projectId}/tags`, userId)

export const getProjectGraphOverview = (userId: string, projectId: string, topLimit = 8) =>
  api<GraphProjectOverview>(
    `/api/projects/${projectId}/knowledge-graph/overview${queryString({
      top_limit: topLimit,
    })}`,
    userId
  )

export const getProjectGraphContextPack = (
  userId: string,
  projectId: string,
  params?: {
    focus_entity_type?: string
    focus_entity_id?: string
    limit?: number
  }
) =>
  api<GraphContextPack>(
    `/api/projects/${projectId}/knowledge-graph/context-pack${queryString({
      focus_entity_type: params?.focus_entity_type,
      focus_entity_id: params?.focus_entity_id,
      limit: params?.limit ?? 20,
    })}`,
    userId
  )

export const getProjectGraphSubgraph = (
  userId: string,
  projectId: string,
  params?: {
    limit_nodes?: number
    limit_edges?: number
  }
) =>
  api<GraphProjectSubgraph>(
    `/api/projects/${projectId}/knowledge-graph/subgraph${queryString({
      limit_nodes: params?.limit_nodes ?? 48,
      limit_edges: params?.limit_edges ?? 160,
    })}`,
    userId
  )

export const getProjectMembers = (userId: string, projectId: string) =>
  api<ProjectMembersPage>(`/api/projects/${projectId}/members`, userId)

export const addProjectMember = (
  userId: string,
  projectId: string,
  payload: { user_id: string; role?: string }
) => api<{ ok: boolean; project_id: string; user_id: string; role: string }>(`/api/projects/${projectId}/members`, userId, { method: 'POST', body: JSON.stringify(payload) })

export const removeProjectMember = (userId: string, projectId: string, memberUserId: string) =>
  api<{ ok: boolean; project_id: string; user_id: string }>(`/api/projects/${projectId}/members/${memberUserId}/remove`, userId, { method: 'POST' })

export const getProjectRules = (
  userId: string,
  workspaceId: string,
  params: { project_id: string; q?: string; limit?: number; offset?: number }
) =>
  api<ProjectRulesPage>(
    `/api/project-rules${queryString({
      workspace_id: workspaceId,
      project_id: params.project_id,
      q: params.q,
      limit: params.limit ?? 100,
      offset: params.offset ?? 0,
    })}`,
    userId
  )

export const createProjectRule = (
  userId: string,
  payload: { workspace_id: string; project_id: string; title: string; body?: string }
) => api<ProjectRule>('/api/project-rules', userId, { method: 'POST', body: JSON.stringify(payload) })

export const patchProjectRule = (
  userId: string,
  ruleId: string,
  payload: Partial<Pick<ProjectRule, 'title' | 'body'>>
) => api<ProjectRule>(`/api/project-rules/${ruleId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const deleteProjectRule = (userId: string, ruleId: string) =>
  api<{ ok: true }>(`/api/project-rules/${ruleId}/delete`, userId, { method: 'POST' })

export const patchMyPreferences = (
  userId: string,
  payload: { theme?: 'light' | 'dark'; timezone?: string; notifications_enabled?: boolean }
) => api<{ id: string; theme: string; timezone: string; notifications_enabled: boolean }>('/api/me/preferences', userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const getNotes = (
  userId: string,
  workspaceId: string,
  params?: {
    project_id: string
    task_id?: string | null
    specification_id?: string | null
    q?: string
    tags?: string[]
    archived?: boolean
    pinned?: boolean | null
    limit?: number
    offset?: number
  }
) =>
  api<NotesPage>(
    `/api/notes${queryString({
      workspace_id: workspaceId,
      project_id: params?.project_id,
      task_id: params?.task_id ?? undefined,
      specification_id: params?.specification_id ?? undefined,
      q: params?.q,
      tags: params?.tags?.join(',') || undefined,
      archived: params?.archived ?? false,
      pinned: params?.pinned ?? undefined,
      limit: params?.limit ?? 100,
      offset: params?.offset ?? 0
    })}`,
    userId
  )

export const createNote = (
  userId: string,
  payload: {
    title: string
    workspace_id: string
    project_id: string
    task_id?: string | null
    specification_id?: string | null
    body?: string
    tags?: string[]
    pinned?: boolean
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
  }
) => api<Note>('/api/notes', userId, { method: 'POST', body: JSON.stringify(payload) })

export const patchNote = (
  userId: string,
  noteId: string,
  payload: Partial<
    Pick<Note, 'title' | 'body' | 'tags' | 'pinned' | 'archived' | 'project_id' | 'task_id' | 'specification_id' | 'external_refs' | 'attachment_refs'>
  >
) => api<Note>(`/api/notes/${noteId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const getSpecifications = (
  userId: string,
  workspaceId: string,
  params: {
    project_id: string
    q?: string
    status?: string
    tags?: string[]
    archived?: boolean
    limit?: number
    offset?: number
  }
) =>
  api<SpecificationsPage>(
    `/api/specifications${queryString({
      workspace_id: workspaceId,
      project_id: params.project_id,
      q: params.q,
      status: params.status,
      tags: params.tags?.join(',') || undefined,
      archived: params.archived ?? false,
      limit: params.limit ?? 100,
      offset: params.offset ?? 0,
    })}`,
    userId
  )

export const createSpecification = (
  userId: string,
  payload: {
    workspace_id: string
    project_id: string
    title: string
    body?: string
    status?: Specification['status']
    tags?: string[]
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
  }
) => api<Specification>('/api/specifications', userId, { method: 'POST', body: JSON.stringify(payload) })

export const patchSpecification = (
  userId: string,
  specificationId: string,
  payload: Partial<Pick<Specification, 'title' | 'body' | 'status' | 'tags' | 'external_refs' | 'attachment_refs' | 'archived'>>
) => api<Specification>(`/api/specifications/${specificationId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const createSpecificationTask = (
  userId: string,
  specificationId: string,
  payload: {
    title: string
    description?: string
    priority?: string
    due_date?: string | null
    assignee_id?: string | null
    labels?: string[]
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
    recurring_rule?: string | null
    task_type?: 'manual' | 'scheduled_instruction'
    scheduled_instruction?: string | null
    scheduled_at_utc?: string | null
    schedule_timezone?: string | null
  }
) => api<Task>(`/api/specifications/${specificationId}/tasks`, userId, { method: 'POST', body: JSON.stringify(payload) })

export const bulkCreateSpecificationTasks = (
  userId: string,
  specificationId: string,
  payload: {
    titles: string[]
    description?: string
    priority?: string
    due_date?: string | null
    assignee_id?: string | null
    labels?: string[]
  }
) =>
  api<SpecificationBulkTaskCreateResponse>(`/api/specifications/${specificationId}/tasks/bulk`, userId, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const createSpecificationNote = (
  userId: string,
  specificationId: string,
  payload: {
    title: string
    body?: string
    tags?: string[]
    pinned?: boolean
    external_refs?: ExternalRef[]
    attachment_refs?: AttachmentRef[]
  }
) => api<Note>(`/api/specifications/${specificationId}/notes`, userId, { method: 'POST', body: JSON.stringify(payload) })

export const linkTaskToSpecification = (userId: string, specificationId: string, taskId: string) =>
  api<Task>(`/api/specifications/${specificationId}/tasks/${taskId}/link`, userId, { method: 'POST' })

export const unlinkTaskFromSpecification = (userId: string, specificationId: string, taskId: string) =>
  api<Task>(`/api/specifications/${specificationId}/tasks/${taskId}/unlink`, userId, { method: 'POST' })

export const linkNoteToSpecification = (userId: string, specificationId: string, noteId: string) =>
  api<Note>(`/api/specifications/${specificationId}/notes/${noteId}/link`, userId, { method: 'POST' })

export const unlinkNoteFromSpecification = (userId: string, specificationId: string, noteId: string) =>
  api<Note>(`/api/specifications/${specificationId}/notes/${noteId}/unlink`, userId, { method: 'POST' })

export const archiveSpecification = (userId: string, specificationId: string) =>
  api<{ ok: true }>(`/api/specifications/${specificationId}/archive`, userId, { method: 'POST' })
export const restoreSpecification = (userId: string, specificationId: string) =>
  api<{ ok: true }>(`/api/specifications/${specificationId}/restore`, userId, { method: 'POST' })
export const deleteSpecification = (userId: string, specificationId: string) =>
  api<{ ok: true }>(`/api/specifications/${specificationId}/delete`, userId, { method: 'POST' })

export const archiveNote = (userId: string, noteId: string) =>
  api<{ ok: true }>(`/api/notes/${noteId}/archive`, userId, { method: 'POST' })
export const restoreNote = (userId: string, noteId: string) =>
  api<{ ok: true }>(`/api/notes/${noteId}/restore`, userId, { method: 'POST' })
export const pinNote = (userId: string, noteId: string) =>
  api<{ ok: true }>(`/api/notes/${noteId}/pin`, userId, { method: 'POST' })
export const unpinNote = (userId: string, noteId: string) =>
  api<{ ok: true }>(`/api/notes/${noteId}/unpin`, userId, { method: 'POST' })
export const deleteNote = (userId: string, noteId: string) =>
  api<{ ok: true }>(`/api/notes/${noteId}/delete`, userId, { method: 'POST' })

export const uploadAttachment = async (
  userId: string,
  payload: {
    workspace_id: string
    project_id?: string | null
    task_id?: string | null
    note_id?: string | null
    file: File
  }
) => {
  const form = new FormData()
  form.set('workspace_id', payload.workspace_id)
  if (payload.project_id) form.set('project_id', payload.project_id)
  if (payload.task_id) form.set('task_id', payload.task_id)
  if (payload.note_id) form.set('note_id', payload.note_id)
  form.set('file', payload.file)
  return uploadApi<AttachmentRef>('/api/attachments/upload', userId, form)
}

export const attachmentDownloadUrl = (payload: { user_id: string; workspace_id: string; path: string }): string =>
  `/api/attachments/download${queryString({
    user_id: payload.user_id,
    workspace_id: payload.workspace_id,
    path: payload.path
  })}`

export const deleteAttachment = (userId: string, payload: { workspace_id: string; path: string }) =>
  api<{ ok: true }>('/api/attachments/delete', userId, { method: 'POST', body: JSON.stringify(payload) })
