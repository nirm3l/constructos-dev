export type User = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent'
  timezone: string
  theme: 'light' | 'dark'
}

export type ExternalRef = {
  url: string
  title?: string
  source?: string
}

export type AttachmentRef = {
  path: string
  name?: string
  mime_type?: string
  size_bytes?: number
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
  external_refs: ExternalRef[]
  attachment_refs: AttachmentRef[]
  created_by: string
  created_at: string | null
  updated_at: string | null
}

export type Task = {
  id: string
  workspace_id: string
  project_id: string
  specification_id: string | null
  title: string
  description: string
  status: string
  priority: string
  due_date: string | null
  assignee_id: string | null
  labels: string[]
  subtasks: Array<Record<string, unknown>>
  attachments: Array<Record<string, unknown>>
  external_refs: ExternalRef[]
  attachment_refs: AttachmentRef[]
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
  created_by: string
  order_index: number
}

export type Notification = {
  id: string
  message: string
  is_read: boolean
  created_at: string | null
  workspace_id?: string | null
  project_id?: string | null
  task_id?: string | null
  note_id?: string | null
  specification_id?: string | null
}

export type AppVersionPayload = {
  backend_version: string
  backend_build: string | null
  deployed_at_utc: string
}

export type BootstrapPayload = {
  current_user: User
  workspaces: Workspace[]
  memberships: Array<{ workspace_id: string; role: string }>
  projects: Project[]
  users: Array<{ id: string; username: string; full_name: string; user_type: 'human' | 'agent' }>
  project_members: Array<{ project_id: string; user_id: string; role: string }>
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

export type GraphProjectOverview = {
  project_id: string
  project_name: string
  counts: {
    tasks: number
    notes: number
    specifications: number
    project_rules: number
  }
  top_tags: Array<{
    tag: string
    usage: number
  }>
  top_relationships: Array<{
    relationship: string
    count: number
  }>
}

export type GraphContextNeighbor = {
  entity_type: string
  entity_id: string
  title: string
  path_types: string[]
}

export type GraphContextResource = {
  entity_type: string
  entity_id: string
  title: string
  degree: number
}

export type GraphContextPack = {
  project_id: string
  focus_entity_type: string | null
  focus_entity_id: string | null
  overview: GraphProjectOverview
  focus_neighbors: GraphContextNeighbor[]
  connected_resources: GraphContextResource[]
  markdown: string
}

export type ProjectMember = {
  project_id: string
  user_id: string
  role: string
  user: {
    id: string
    username: string
    full_name: string
    user_type: 'human' | 'agent'
  }
}

export type ProjectMembersPage = {
  project_id: string
  items: ProjectMember[]
  total: number
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
  specification_id: string | null
  title: string
  body: string
  tags: string[]
  external_refs: ExternalRef[]
  attachment_refs: AttachmentRef[]
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

export type Specification = {
  id: string
  workspace_id: string
  project_id: string
  title: string
  body: string
  status: 'Draft' | 'Ready' | 'In progress' | 'Implemented' | 'Archived'
  tags: string[]
  external_refs: ExternalRef[]
  attachment_refs: AttachmentRef[]
  archived: boolean
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type SpecificationsPage = {
  items: Specification[]
  total: number
  limit: number
  offset: number
}

export type SpecificationBulkTaskResult = {
  index: number
  title: string
  ok: boolean
  task_id?: string
  error?: string
}

export type SpecificationBulkTaskCreateResponse = {
  items: Task[]
  results: SpecificationBulkTaskResult[]
  created: number
  failed: number
  total: number
}
