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
  project_id: string | null
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

export type ProjectBoard = {
  project_id: string
  statuses: string[]
  lanes: Record<string, Task[]>
}
