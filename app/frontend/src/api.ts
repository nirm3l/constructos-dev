import type {
  BootstrapPayload,
  AgentChatResponse,
  Notification,
  Project,
  ProjectBoard,
  Task,
  TaskActivity,
  TaskAutomationStatus,
  TaskComment,
  TasksPage
} from './types'

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
    throw new Error(await res.text())
  }
  return (await res.json()) as T
}

export const getBootstrap = (userId: string) => api<BootstrapPayload>('/api/bootstrap', userId)

export const getTasks = (
  userId: string,
  workspaceId: string,
  params?: {
    view?: string
    project_id?: string | null
    q?: string
    status?: string
    priority?: string
    archived?: boolean
  }
) =>
  api<TasksPage>(
    `/api/tasks${queryString({
      workspace_id: workspaceId,
      archived: params?.archived ?? false,
      view: params?.view,
      project_id: params?.project_id ?? undefined,
      q: params?.q,
      status: params?.status,
      priority: params?.priority,
      limit: 100,
      offset: 0
    })}`,
    userId
  )

export const createTask = (
  userId: string,
  payload: { title: string; workspace_id: string; project_id: string | null; due_date?: string | null }
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
      | 'task_type'
      | 'scheduled_instruction'
      | 'scheduled_at_utc'
      | 'schedule_timezone'
    >
  >
) => api<Task>(`/api/tasks/${taskId}`, userId, { method: 'PATCH', body: JSON.stringify(payload) })

export const listComments = (userId: string, taskId: string) => api<TaskComment[]>(`/api/tasks/${taskId}/comments`, userId)
export const addComment = (userId: string, taskId: string, body: string) =>
  api<TaskComment>(`/api/tasks/${taskId}/comments`, userId, { method: 'POST', body: JSON.stringify({ body }) })
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

export const createProject = (userId: string, payload: { workspace_id: string; name: string }) =>
  api<Project>('/api/projects', userId, { method: 'POST', body: JSON.stringify(payload) })

export const getProjectBoard = (userId: string, projectId: string) =>
  api<ProjectBoard>(`/api/projects/${projectId}/board`, userId)

export const patchMyPreferences = (
  userId: string,
  payload: { theme?: 'light' | 'dark'; timezone?: string; notifications_enabled?: boolean }
) => api<{ id: string; theme: string; timezone: string; notifications_enabled: boolean }>('/api/me/preferences', userId, { method: 'PATCH', body: JSON.stringify(payload) })
