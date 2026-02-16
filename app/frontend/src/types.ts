export type User = {
  id: string
  username: string
  full_name: string
  timezone: string
  theme: 'light' | 'dark'
}

export type Workspace = {
  id: string
  name: string
  type: string
}

export type Project = {
  id: string
  workspace_id: string
  name: string
  description: string
  status: string
  custom_statuses: string[]
}

export type Task = {
  id: string
  workspace_id: string
  project_id: string
  title: string
  description: string
  status: string
  priority: string
  due_date: string | null
  assignee_id: string | null
  labels: string[]
  subtasks: Array<Record<string, unknown>>
  attachments: Array<Record<string, unknown>>
  recurring_rule: string | null
  task_type: 'manual' | 'scheduled_instruction'
  scheduled_instruction: string | null
  scheduled_at_utc: string | null
  schedule_timezone: string | null
  schedule_state: 'idle' | 'queued' | 'running' | 'done' | 'failed'
  last_schedule_run_at: string | null
  last_schedule_error: string | null
  archived: boolean
  completed_at: string | null
  created_at: string | null
  updated_at: string | null
  order_index: number
}

export type Notification = {
  id: string
  message: string
  is_read: boolean
  created_at: string | null
}

export type BootstrapPayload = {
  current_user: User
  workspaces: Workspace[]
  memberships: Array<{ workspace_id: string; role: string }>
  projects: Project[]
  users: Array<{ id: string; username: string; full_name: string }>
  notifications: Notification[]
  saved_views: Array<{
    id: string
    workspace_id: string
    project_id: string | null
    user_id: string | null
    name: string
    shared: boolean
    filters: Record<string, unknown>
  }>
}

export type TasksPage = {
  items: Task[]
  total: number
  limit: number
  offset: number
}

export type TaskComment = {
  id: number | null
  task_id: string
  user_id: string
  body: string
  created_at: string | null
}

export type TaskActivity = {
  id: number
  action: string
  actor_id: string
  details: Record<string, unknown>
  created_at: string
}

export type TaskAutomationStatus = {
  task_id: string
  automation_state: 'idle' | 'queued' | 'running' | 'completed' | 'failed'
  last_agent_run_at: string | null
  last_agent_error: string | null
  last_agent_comment: string | null
  last_requested_instruction: string | null
  task_type: 'manual' | 'scheduled_instruction'
  schedule_state: 'idle' | 'queued' | 'running' | 'done' | 'failed'
  scheduled_at_utc: string | null
  scheduled_instruction: string | null
  last_schedule_run_at: string | null
  last_schedule_error: string | null
}

export type ProjectBoard = {
  project_id: string
  statuses: string[]
  lanes: Record<string, Task[]>
}

export type ProjectTags = {
  project_id: string
  tags: string[]
}

export type ProjectRule = {
  id: string
  workspace_id: string
  project_id: string
  title: string
  body: string
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type ProjectRulesPage = {
  items: ProjectRule[]
  total: number
  limit: number
  offset: number
}

export type AgentChatResponse = {
  ok: boolean
  action: 'complete' | 'comment'
  summary: string
  comment: string | null
  session_id?: string | null
}

export type Note = {
  id: string
  workspace_id: string
  project_id: string
  task_id: string | null
  title: string
  body: string
  tags: string[]
  pinned: boolean
  archived: boolean
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type NotesPage = {
  items: Note[]
  total: number
  limit: number
  offset: number
}
