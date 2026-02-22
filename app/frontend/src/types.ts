export type User = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent'
  timezone: string
  theme: 'light' | 'dark'
}

export type AuthUser = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent'
  timezone: string
  theme: 'light' | 'dark'
  must_change_password: boolean
  memberships: Array<{ workspace_id: string; role: string }>
}

export type AuthMePayload = {
  ok: boolean
  user: AuthUser
}

export type AdminWorkspaceUser = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent' | 'bot' | string
  role: string
  is_active: boolean
  must_change_password: boolean
  can_reset_password?: boolean
  can_deactivate?: boolean
}

export type AdminUsersPage = {
  workspace_id: string
  items: AdminWorkspaceUser[]
  total: number
}

export type AdminUserCreateResponse = {
  workspace_id: string
  user: {
    id: string
    username: string
    full_name: string
    user_type: 'human' | 'agent'
    role: string
    must_change_password: boolean
    is_active: boolean
  }
  temporary_password: string
}

export type AdminUserResetPasswordResponse = {
  ok: boolean
  user_id: string
  temporary_password: string
}

export type AdminUserRoleUpdateResponse = {
  ok: boolean
  workspace_id: string
  user_id: string
  role: string
}

export type AdminUserDeactivateResponse = {
  ok: boolean
  workspace_id: string
  user_id: string
  is_active: boolean
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
  embedding_enabled: boolean
  embedding_model: string | null
  context_pack_evidence_top_k: number | null
  embedding_index_status: 'not_indexed' | 'indexing' | 'ready' | 'stale'
  created_by: string
  created_at: string | null
  updated_at: string | null
  template_binding?: ProjectTemplateBinding | null
}

export type ProjectTemplate = {
  key: string
  name: string
  version: string
  description: string
  default_custom_statuses: string[]
  default_embedding_enabled: boolean
  default_context_pack_evidence_top_k: number | null
  seed_counts: {
    specifications: number
    tasks: number
    rules: number
    skills?: number
    graph_nodes?: number
    graph_edges?: number
  }
}

export type ProjectTemplatesPage = {
  items: ProjectTemplate[]
}

export type ProjectFromTemplateResponse = {
  project: Project
  template: {
    key: string
    name: string
    version: string
  }
  binding: {
    project_id: string
    workspace_id: string
    template_key: string
    template_version: string
    applied_by: string
    applied_at: string | null
    parameters: Record<string, unknown>
  }
  seed_summary: {
    specification_count: number
    rule_count: number
    task_count: number
    skill_count?: number
    skill_skip_count?: number
  }
  seeded_entity_ids: {
    specification_ids: string[]
    rule_ids: string[]
    task_ids: string[]
    project_skill_ids?: string[]
    project_skill_rule_ids?: string[]
  }
  skill_seed_report?: {
    skipped: Array<Record<string, unknown>>
  }
}

export type ProjectFromTemplatePreviewResponse = {
  mode: 'preview'
  template: {
    key: string
    name: string
    version: string
    description: string
  }
  project_blueprint: {
    workspace_id: string
    project_id: string | null
    name: string
    description: string
    custom_statuses: string[]
    member_user_ids: string[]
    effective_member_user_ids: string[]
    embedding_enabled: boolean
    embedding_model: string | null
    context_pack_evidence_top_k: number | null
  }
  binding_preview: {
    workspace_id: string
    project_id: string | null
    template_key: string
    template_version: string
    applied_by: string
    parameters: Record<string, unknown>
  }
  seed_summary: {
    specification_count: number
    rule_count: number
    task_count: number
    skill_count?: number
    graph_node_count: number
    graph_edge_count: number
  }
  seed_blueprint: {
    specifications: Array<Record<string, unknown>>
    tasks: Array<Record<string, unknown>>
    rules: Array<Record<string, unknown>>
    skills?: Array<Record<string, unknown>>
    graph: {
      nodes: Array<Record<string, unknown>>
      edges: Array<Record<string, unknown>>
    }
  }
  graph_scaffold_summary: {
    template_node_id: string
    template_version_node_id: string
    project_relation_types: string[]
    graph_node_count: number
    graph_edge_count: number
  }
  project_conflict: {
    status: 'none' | 'active' | 'deleted' | 'name_missing' | string
    can_create: boolean
  }
}

export type Task = {
  id: string
  workspace_id: string
  project_id: string
  task_group_id: string | null
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

export type LicenseStatus = {
  installation_id: string
  status: 'active' | 'trial' | 'grace' | 'expired' | 'unlicensed' | string
  plan_code: string | null
  enforcement_enabled: boolean
  write_access: boolean
  trial_ends_at: string | null
  grace_ends_at: string | null
  last_validated_at: string | null
  token_expires_at: string | null
  metadata: Record<string, unknown>
}

export type LicenseStatusResponse = {
  ok: boolean
  license: LicenseStatus
}

export type LicenseActivationSeatUsage = {
  active_installations: number
  max_installations: number
  customer_ref: string
}

export type LicenseActivationResponse = {
  ok: boolean
  license: LicenseStatus
  seat_usage: LicenseActivationSeatUsage | null
}

export type BugReportSeverity = 'low' | 'medium' | 'high' | 'critical'

export type BugReportCreateRequest = {
  title: string
  description: string
  steps_to_reproduce?: string | null
  expected_behavior?: string | null
  actual_behavior?: string | null
  severity: BugReportSeverity
  context?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type BugReportCreateResponse = {
  ok: boolean
  created: boolean
  queued: boolean
  queue_id: number | null
  report_id: string | null
  bug_report: Record<string, unknown>
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
  embedding_allowed_models: string[]
  embedding_default_model: string
  vector_store_enabled: boolean
  context_pack_evidence_top_k_default: number
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

export type ProjectTagStat = {
  tag: string
  usage_count: number
}

export type ProjectTags = {
  project_id: string
  tags: string[]
  tag_stats?: ProjectTagStat[]
}

export type GraphProjectOverview = {
  project_id: string
  project_name: string
  counts: {
    tasks: number
    notes: number
    specifications: number
    project_rules: number
    comments: number
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

export type GraphDependencyPath = {
  to_entity_type: string
  to_entity_id: string
  hops: number
  relationships: string[]
  path: string[]
}

export type GraphContextStructure = {
  overview: GraphProjectOverview
  focus_neighbors: GraphContextNeighbor[]
  dependency_paths: GraphDependencyPath[]
}

export type GraphContextFocus = {
  entity_type: string
  entity_id: string
}

export type GraphContextEvidence = {
  evidence_id: string
  entity_type: string
  entity_id: string
  source_type: string
  snippet: string
  vector_similarity: number | null
  graph_score: number
  template_alignment?: number
  final_score: number
  graph_path: string[]
  updated_at: string | null
  why_selected: string
}

export type GraphSummary = {
  executive: string
  key_points: Array<{
    claim: string
    evidence_ids: string[]
  }>
  gaps: string[]
}

export type ProjectTemplateBinding = {
  template_key: string
  template_version: string
  applied_by: string
  applied_at: string | null
}

export type GraphContextPack = {
  project_id: string
  focus: GraphContextFocus | null
  mode: 'graph-only' | 'graph+vector'
  structure: GraphContextStructure
  evidence: GraphContextEvidence[]
  template?: ProjectTemplateBinding
  summary?: GraphSummary
  gaps?: string[]
  markdown: string
}

export type GraphSubgraphNode = {
  entity_type: string
  entity_id: string
  title: string
  degree: number
}

export type GraphSubgraphEdge = {
  source_entity_id: string
  target_entity_id: string
  relationship: string
}

export type GraphProjectSubgraph = {
  project_id: string
  project_name: string
  node_count: number
  edge_count: number
  nodes: GraphSubgraphNode[]
  edges: GraphSubgraphEdge[]
}

export type ProjectKnowledgeSearchItem = {
  rank: number
  entity_type: string
  entity_id: string
  source_type: string
  snippet: string
  vector_similarity: number | null
  graph_score: number
  template_alignment?: number
  final_score: number
  graph_path: string[]
  updated_at: string | null
  why_selected?: string
}

export type ProjectKnowledgeSearchResult = {
  project_id: string
  query: string
  mode: 'graph-only' | 'graph+vector' | 'vector-only' | 'empty'
  focus?: GraphContextFocus
  template?: ProjectTemplateBinding
  gaps?: string[]
  items: ProjectKnowledgeSearchItem[]
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

export type ProjectSkill = {
  id: string
  workspace_id: string
  project_id: string
  skill_key: string
  name: string
  summary: string
  source_type: string
  source_locator: string
  source_version: string | null
  trust_level: 'verified' | 'reviewed' | 'untrusted' | string
  mode: 'advisory' | 'enforced' | string
  generated_rule_id: string | null
  manifest: Record<string, unknown>
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type ProjectSkillsPage = {
  items: ProjectSkill[]
  total: number
  limit: number
  offset: number
}

export type WorkspaceSkill = {
  id: string
  workspace_id: string
  skill_key: string
  name: string
  summary: string
  source_type: string
  source_locator: string
  source_version: string | null
  trust_level: 'verified' | 'reviewed' | 'untrusted' | string
  mode: 'advisory' | 'enforced' | string
  is_seeded: boolean
  manifest: Record<string, unknown>
  created_by: string
  updated_by: string
  created_at: string | null
  updated_at: string | null
}

export type WorkspaceSkillsPage = {
  items: WorkspaceSkill[]
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
  usage?: AgentChatUsage | null
}

export type AgentChatUsage = {
  input_tokens: number
  cached_input_tokens?: number
  output_tokens: number
  context_limit_tokens?: number
}

export type Note = {
  id: string
  workspace_id: string
  project_id: string
  note_group_id: string | null
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

export type TaskGroup = {
  id: string
  workspace_id: string
  project_id: string
  name: string
  description: string
  color: string | null
  order_index: number
  created_at: string | null
  updated_at: string | null
}

export type TaskGroupsPage = {
  items: TaskGroup[]
  total: number
  limit: number
  offset: number
}

export type NoteGroup = {
  id: string
  workspace_id: string
  project_id: string
  name: string
  description: string
  color: string | null
  order_index: number
  created_at: string | null
  updated_at: string | null
}

export type NoteGroupsPage = {
  items: NoteGroup[]
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
