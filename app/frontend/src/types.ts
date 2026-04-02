export type User = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent'
  timezone: string
  theme: 'light' | 'dark'
  agent_chat_model?: string
  agent_chat_reasoning_effort?: ChatReasoningEffort | string
  onboarding_quick_tour_completed?: boolean
  onboarding_advanced_tour_completed?: boolean
}

export type AuthUser = {
  id: string
  username: string
  full_name: string
  user_type: 'human' | 'agent'
  timezone: string
  theme: 'light' | 'dark'
  agent_chat_model?: string
  agent_chat_reasoning_effort?: ChatReasoningEffort | string
  onboarding_quick_tour_completed?: boolean
  onboarding_advanced_tour_completed?: boolean
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
  can_update_role?: boolean
  background_agent_model?: string | null
  background_agent_provider?: 'codex' | 'claude' | 'opencode' | string | null
  background_agent_available?: boolean
  background_agent_reasoning_effort?: string | null
  background_agent_model_is_fallback?: boolean | null
  background_agent_reasoning_is_fallback?: boolean | null
  is_background_execution_selected?: boolean
  can_configure_background_execution?: boolean
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

export type AdminUserAgentRuntimeUpdateResponse = {
  ok: boolean
  workspace_id: string
  user_id: string
  provider: 'codex' | 'claude' | 'opencode' | string
  model: string
  reasoning_effort?: string | null
  is_background_execution_selected: boolean
}

export type DoctorRunCheck = {
  id: string
  label: string
  status: 'passed' | 'warning' | 'failed' | string
  details?: Record<string, unknown> | null
}

export type DoctorRunSummary = {
  project_id?: string | null
  project_link?: string | null
  queued_task_id?: string | null
  checks?: DoctorRunCheck[]
  counts?: {
    passed?: number
    warning?: number
    failed?: number
  } | null
  [key: string]: unknown
}

export type DoctorRun = {
  id: string
  workspace_id: string
  project_id?: string | null
  fixture_version: string
  status: 'pending' | 'running' | 'passed' | 'warning' | 'failed' | string
  summary: DoctorRunSummary
  started_at: string | null
  finished_at: string | null
  triggered_by?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export type WorkspaceDoctorStatus = {
  workspace_id: string
  plugin_key: string
  supported: boolean
  enabled: boolean
  fixture_version: string
  project?: {
    id: string
    name: string
    status: string
    link: string
  } | null
  seeded: boolean
  runner_enabled: boolean
  checks: {
    team_mode_enabled: boolean
    git_delivery_enabled: boolean
    seeded_team_task_count: number
    task_count: number
  }
  last_seeded_at: string | null
  last_run_at: string | null
  last_run_status: string | null
  last_run?: DoctorRun | null
  recent_runs: DoctorRun[]
  setup?: Record<string, unknown> | null
}

export type WorkspaceDoctorRunResponse = {
  workspace_id: string
  run: DoctorRun
  status: WorkspaceDoctorStatus
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

export type TaskExecutionTriggerManual = {
  kind: 'manual'
  enabled?: boolean
}

export type TaskExecutionTriggerSchedule = {
  kind: 'schedule'
  enabled?: boolean
  scheduled_at_utc: string
  schedule_timezone?: string
  recurring_rule?: string
  run_on_statuses?: string[]
}

export type TaskExecutionTriggerStatusChange = {
  kind: 'status_change'
  enabled?: boolean
  scope: 'self' | 'external'
  match_mode?: 'any' | 'all'
  from_statuses?: string[]
  to_statuses?: string[]
  selector?: {
    task_ids?: string[]
    project_id?: string
    specification_id?: string
    assignee_id?: string
    labels_any?: string[]
  }
  cooldown_seconds?: number
}

export type TaskExecutionTrigger =
  | TaskExecutionTriggerManual
  | TaskExecutionTriggerSchedule
  | TaskExecutionTriggerStatusChange

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
  automation_max_parallel_tasks: number
  chat_index_mode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' | string
  chat_attachment_ingestion_mode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' | string
  vector_index_distill_enabled: boolean
  event_storming_enabled: boolean
  embedding_index_status: 'not_indexed' | 'indexing' | 'ready' | 'stale'
  embedding_index_progress_pct: number | null
  embedding_indexed_entities: number
  embedding_index_expected_entities: number
  embedding_indexed_chunks: number
  created_by: string
  created_at: string | null
  updated_at: string | null
  setup_profile?: ProjectSetupProfile | null
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
  assigned_agent_code: string | null
  labels: string[]
  subtasks: Array<Record<string, unknown>>
  attachments: Array<Record<string, unknown>>
  external_refs: ExternalRef[]
  attachment_refs: AttachmentRef[]
  linked_note_count?: number
  instruction: string | null
  execution_triggers: TaskExecutionTrigger[]
  task_relationships?: Array<Record<string, unknown>>
  delivery_mode?: 'deployable_slice' | 'merged_increment' | string | null
  recurring_rule: string | null
  task_type: 'manual' | 'scheduled_instruction'
  scheduled_instruction: string | null
  scheduled_at_utc: string | null
  schedule_timezone: string | null
  schedule_state: 'idle' | 'queued' | 'running' | 'done' | 'failed'
  automation_state?: 'idle' | 'queued' | 'running' | 'completed' | 'failed'
  review_required?: boolean
  review_status?: string | null
  review_requested_at?: string | null
  reviewed_at?: string | null
  reviewed_by_user_id?: string | null
  review_source_assignee_id?: string | null
  review_source_assigned_agent_code?: string | null
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
  notification_type?: string | null
  severity?: 'info' | 'warning' | 'critical' | string | null
  dedupe_key?: string | null
  payload?: Record<string, unknown> | null
  source_event?: string | null
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
  notifications?: Notification[]
}

export type LicenseStatusResponse = {
  ok: boolean
  license: LicenseStatus
}

export type LicenseAutoUpdateResponse = {
  ok: boolean
  queued: boolean
  running: boolean
  run_id: string | null
  started_at: string | null
  log_path: string | null
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

export type FeedbackKind = 'general' | 'feature_request' | 'question' | 'other'

export type FeedbackCreateRequest = {
  title: string
  description: string
  feedback_type: FeedbackKind
  context?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export type FeedbackCreateResponse = {
  ok: boolean
  created: boolean
  feedback: Record<string, unknown>
}

export type AppVersionPayload = {
  backend_version: string
  backend_build: string | null
  deployed_at_utc: string
}

export type ArchitectureInventorySummary = {
  generated_at: string
  counts: Record<string, number>
  internal_docs: {
    existing_docs_count: number
    reading_order_count: number
    missing_from_reading_order_count: number
    unreferenced_docs_count: number
    missing_from_reading_order: string[]
    unreferenced_docs: string[]
  }
  audit: {
    ok: boolean
    error_count: number
    warning_count: number
    errors: string[]
    warnings: string[]
  }
  cache_ttl_seconds: number
  cache_hit: boolean
  cache_status: {
    key: string
    has_payload: boolean
    hit_count: number
    miss_count: number
    expires_in_seconds: number
  }
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
  agent_chat_context_limit_tokens_default?: number
  agent_chat_default_model?: string
  agent_chat_default_reasoning_effort?: ChatReasoningEffort | string
  agent_chat_available_models?: string[]
  agent_chat_available_mcp_servers?: AgentChatMcpServer[]
  architecture_inventory_summary?: ArchitectureInventorySummary
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
  last_agent_progress: string | null
  last_agent_stream_status: string | null
  last_agent_stream_updated_at: string | null
  last_agent_run_id: string | null
  last_agent_error: string | null
  last_agent_comment: string | null
  last_agent_usage?: Record<string, unknown> | null
  last_agent_prompt_mode?: 'full' | 'resume' | string | null
  last_agent_prompt_segment_chars?: Record<string, number> | null
  last_agent_codex_session_id?: string | null
  last_agent_codex_resume_attempted?: boolean | null
  last_agent_codex_resume_succeeded?: boolean | null
  last_agent_codex_resume_fallback_used?: boolean | null
  last_requested_instruction: string | null
  last_requested_source: 'manual' | 'schedule' | 'status_change' | 'lead_handoff' | string | null
  last_requested_source_task_id?: string | null
  last_requested_reason?: string | null
  last_requested_trigger_link?: string | null
  last_requested_correlation_id?: string | null
  last_requested_trigger_task_id: string | null
  last_requested_from_status: string | null
  last_requested_to_status: string | null
  last_requested_triggered_at: string | null
  last_dispatch_decision?: Record<string, unknown> | null
  last_ignored_request_source?: 'status_change' | string | null
  last_ignored_request_source_task_id?: string | null
  last_ignored_request_reason?: string | null
  last_ignored_request_trigger_link?: string | null
  last_ignored_request_correlation_id?: string | null
  last_ignored_request_trigger_task_id?: string | null
  last_ignored_request_from_status?: string | null
  last_ignored_request_to_status?: string | null
  last_ignored_request_triggered_at?: string | null
  last_lead_handoff_token?: string | null
  last_lead_handoff_at?: string | null
  last_lead_handoff_refs?: Array<Record<string, unknown>> | null
  team_mode_phase?: string | null
  instruction: string | null
  execution_triggers: TaskExecutionTrigger[]
  task_relationships?: Array<Record<string, unknown>>
  task_type: 'manual' | 'scheduled_instruction'
  schedule_state: 'idle' | 'queued' | 'running' | 'done' | 'failed'
  scheduled_at_utc: string | null
  scheduled_instruction: string | null
  last_schedule_run_at: string | null
  last_schedule_error: string | null
  execution_gates?: Array<{
    id: string
    label: string
    status: 'pass' | 'fail' | 'waiting' | 'not_applicable' | string
    blocking: boolean
    message?: string | null
  }>
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
  total_entities: number
  counts: {
    tasks: number
    notes: number
    specifications: number
    project_rules: number
    comments: number
  }
  entity_type_counts: Array<{
    entity_type: string
    count: number
  }>
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
  starter_alignment?: number
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

export type ProjectStarterDefinition = {
  key: string
  label: string
  description: string
  positioning_text: string
  recommended_use_cases: string[]
  default_custom_statuses: string[]
  retrieval_hints: string[]
  question_set: string[]
  setup_tags: string[]
  facet_defaults: string[]
  artifact_counts: {
    specifications: number
    tasks: number
    rules: number
  }
}

export type ProjectStarterCatalog = {
  items: ProjectStarterDefinition[]
  facets: string[]
}

export type ProjectSetupProfile = {
  primary_starter_key: string
  facet_keys: string[]
  starter_version: string
  retrieval_hints?: string[]
  applied_by: string
  applied_at: string | null
}

export type GraphContextPack = {
  project_id: string
  focus: GraphContextFocus | null
  mode: 'graph-only' | 'graph+vector'
  structure: GraphContextStructure
  evidence: GraphContextEvidence[]
  setup_profile?: ProjectSetupProfile
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
  review_status?: 'candidate' | 'approved' | 'rejected' | string
  inference_method?: string
  confidence?: number
}

export type GraphProjectSubgraph = {
  project_id: string
  project_name: string
  node_count: number
  edge_count: number
  nodes: GraphSubgraphNode[]
  edges: GraphSubgraphEdge[]
}

export type TaskDependencyGraphNode = {
  entity_type: 'Task' | string
  entity_id: string
  title: string
  status: string
  priority: string
  automation_state: string
  role: string
  assigned_agent_code?: string | null
  assignee_id?: string | null
  specification_id?: string | null
  team_mode_phase?: string | null
  team_mode_blocking_gate?: string | null
  last_requested_source?: string | null
  last_requested_source_task_id?: string | null
  last_requested_triggered_at?: string | null
  last_activity_at?: string | null
  inbound_count: number
  outbound_count: number
  runtime_inbound_count: number
  runtime_outbound_count: number
  structural_inbound_count: number
  structural_outbound_count: number
  status_trigger_inbound_count: number
  status_trigger_outbound_count: number
}

export type TaskDependencyGraphEdgeChannel = {
  kind: 'relationship' | 'status_trigger' | 'runtime_request' | string
  label: string
  source: string
  statuses?: string[]
  to_statuses?: string[]
  scope?: string | null
  match_mode?: string | null
  count?: number
  latest_at?: string | null
  correlation_ids?: string[]
  active?: boolean
}

export type TaskDependencyGraphRuntimeEvent = {
  at?: string | null
  source: string
  reason?: string | null
  trigger_link?: string | null
  correlation_id?: string | null
  active?: boolean
}

export type TaskDependencyGraphEventDetail = {
  project_id: string
  source_task_id: string
  source_task_title: string
  target_task_id: string
  target_task_title: string
  source: string
  requested_at?: string | null
  correlation_id?: string | null
  trigger_link?: string | null
  reason?: string | null
  origin_chat_session_id?: string | null
  origin_prompt_markdown?: string | null
  origin_prompt_at?: string | null
  origin_classifier?: Record<string, unknown> | null
  runtime_classifier?: Record<string, unknown> | null
  request_markdown?: string | null
  response_markdown?: string | null
  response_status?: string | null
  response_at?: string | null
  response_summary?: string | null
  response_error?: string | null
  response_comment_body?: string | null
  response_comment_at?: string | null
}

export type TaskDependencyGraphEdge = {
  source_entity_id: string
  target_entity_id: string
  relationship: string
  structural: boolean
  trigger_dependency: boolean
  runtime_dependency: boolean
  active_runtime: boolean
  runtime_requests_total: number
  lead_handoffs_total: number
  latest_runtime_at?: string | null
  latest_runtime_source?: string | null
  relationship_kinds?: string[]
  trigger_conditions?: Array<Record<string, unknown>>
  runtime_sources?: Record<string, number>
  channels: TaskDependencyGraphEdgeChannel[]
  runtime_events?: TaskDependencyGraphRuntimeEvent[]
}

export type ProjectTaskDependencyGraph = {
  project_id: string
  project_name: string
  node_count: number
  edge_count: number
  counts: {
    tasks: number
    structural_edges: number
    status_trigger_edges: number
    runtime_edges: number
    active_runtime_edges: number
    running_tasks: number
    queued_tasks: number
    blocked_tasks: number
    done_tasks: number
  }
  relationship_counts?: Record<string, number>
  runtime_source_counts?: Record<string, number>
  nodes: TaskDependencyGraphNode[]
  edges: TaskDependencyGraphEdge[]
}

export type ProjectDockerComposeRuntimePublisher = {
  url?: string | null
  target_port?: number | null
  published_port?: number | null
  protocol?: string | null
}

export type ProjectDockerComposeRuntimeContainer = {
  name: string
  service: string
  state: string
  status: string
  health?: string | null
  image?: string | null
  command?: string | null
  exit_code?: number | null
  publishers: ProjectDockerComposeRuntimePublisher[]
}

export type ProjectDockerComposeRuntimeLogEvent = {
  project_id: string
  project_name: string
  container_name: string
  timestamp?: string | null
  message: string
}

export type ProjectDockerComposeRuntimeSnapshot = {
  project_id: string
  project_name: string
  enabled: boolean
  stack: string
  port?: number | null
  health_path?: string | null
  require_http_200: boolean
  has_runtime: boolean
  error?: string | null
  stderr?: string | null
  containers: ProjectDockerComposeRuntimeContainer[]
  health?: Record<string, unknown>
}

export type ProjectGitRepositoryBranch = {
  name: string
  commit_sha?: string | null
  committed_at?: string | null
  author_name?: string | null
  subject?: string | null
  is_current: boolean
  is_default: boolean
  merged_to_main: boolean
}

export type ProjectGitRepositorySummary = {
  project_id: string
  project_name: string
  available: boolean
  repo_root: string
  current_branch?: string | null
  default_branch?: string | null
  branch_count: number
  branches_preview: ProjectGitRepositoryBranch[]
}

export type ProjectGitRepositoryBranchesResponse = {
  project_id: string
  project_name: string
  branches: ProjectGitRepositoryBranch[]
}

export type ProjectGitRepositoryTreeEntry = {
  name: string
  path: string
  kind: 'directory' | 'file'
  object_id: string
  mode: string
}

export type ProjectGitRepositoryTreeResponse = {
  project_id: string
  project_name: string
  ref: string
  path: string
  entries: ProjectGitRepositoryTreeEntry[]
}

export type ProjectGitRepositoryFileResponse = {
  project_id: string
  project_name: string
  ref: string
  path: string
  size_bytes?: number | null
  encoding?: string | null
  previewable: boolean
  truncated: boolean
  binary: boolean
  content?: string | null
}

export type ProjectGitRepositoryDiffFile = {
  path: string
  old_path?: string | null
  status: 'added' | 'modified' | 'deleted' | 'renamed' | 'copied' | 'type_changed' | 'unmerged' | string
  status_code?: string | null
  additions?: number | null
  deletions?: number | null
  binary?: boolean
}

export type ProjectGitRepositoryDiffResponse = {
  project_id: string
  project_name: string
  base_ref: string
  head_ref: string
  compare_mode: 'merge_base' | string
  merge_base?: string | null
  path: string
  context_lines: number
  files_changed: number
  insertions: number
  deletions: number
  patch: string
  patch_truncated: boolean
  files: ProjectGitRepositoryDiffFile[]
}

export type GraphLayoutPosition = {
  entity_id: string
  x: number
  y: number
}

export type GraphAiLayoutResult = {
  project_id: string
  project_name: string
  graph_signature: string
  strategy: string
  positions: GraphLayoutPosition[]
}

export type EventStormingOverview = {
  project_id: string
  project_name: string
  component_counts: Record<string, number>
  artifact_link_count: number
  event_storming_enabled: boolean
  context_frame?: {
    mode?: 'full' | 'delta' | string | null
    revision?: string | null
    updated_at?: string | null
  }
  processing: {
    artifact_total: number
    processed: number
    queued: number
    running: number
    failed: number
    done: number
    progress_pct: number
  }
}

export type EventStormingSubgraph = {
  project_id: string
  project_name: string
  node_count: number
  edge_count: number
  nodes: GraphSubgraphNode[]
  edges: GraphSubgraphEdge[]
}

export type ProjectPolicyCheckResult = {
  project_id: string
  active?: boolean
  kickoff_required?: boolean
  kickoff_hint?: string
  checks: Record<string, boolean | string | number | null>
  available_checks?: string[]
  check_descriptions?: Record<string, string>
  required_checks?: string[]
  required_failed_checks?: string[]
  plugin_policy?: Record<string, unknown>
  plugin_policy_source?: string
  counts?: Record<string, number>
  ok: boolean
}

export type ProjectPolicyCheckCatalogItem = {
  id: string
  label?: string
  description?: string
  default_required?: boolean
}

export type ProjectPolicyChecksVerifyResponse = {
  project_id: string
  team_mode?: ProjectPolicyCheckResult
  team_mode_runtime?: {
    active: boolean
    parallel_limit?: number
    agents: Array<{
      id: string
      name: string
      authority_role: string
      executor_user_id?: string | null
      status: 'busy' | 'idle' | string
      busy_task_ids: string[]
      busy_task_count: number
    }>
    tasks: Array<{
      id: string
      title: string
      status: string
      semantic_status?: string
      role: string
      phase?: string
      priority?: string
      automation_state: string
      assigned_agent_code?: string
      dispatch_slot?: string
      has_instruction?: boolean
      dispatch_ready?: boolean
      dependency_ready?: boolean
      dependency_reason?: string | null
      runtime_state?: 'active' | 'runnable' | 'blocked' | 'waiting' | 'missing_instruction' | 'out_of_scope' | string
      blocker_reason?: string | null
      runnable?: boolean
      selected_for_dispatch?: boolean
      selected_for_kickoff?: boolean
      last_requested_source?: string | null
      last_agent_run_at?: string | null
    }>
    summary?: {
      tasks_total?: number
      team_tasks_total?: number
      active_tasks_total?: number
      runnable_tasks_total?: number
      blocked_tasks_total?: number
      waiting_tasks_total?: number
      missing_instruction_total?: number
      active_agents_total?: number
      idle_agents_total?: number
      by_role?: Record<string, { total?: number; active?: number; runnable?: number; blocked?: number }>
      role_agents?: Record<string, { configured?: number; busy?: number; idle?: number }>
    }
    dispatch?: {
      ok?: boolean
      mode?: string
      queue_task_ids?: string[]
      selected_by_role?: Record<string, string[]>
      counts?: {
        busy_total?: number
        available_slots?: number
        candidates?: Record<string, number>
      }
      blocked_reasons?: string[]
    }
    kickoff?: {
      ok?: boolean
      kickoff_task_ids?: string[]
      kickoff_task_ids_by_role?: Record<string, string[]>
      parallel_limit?: number
      blocked_reasons?: string[]
    }
  }
  delivery?: ProjectPolicyCheckResult & {
    runtime_deploy_health?: Record<string, unknown>
  }
  execution_gates?: {
    tasks: Array<{
      task_id: string
      title: string
      status: string
      gates_total: number
      blocking_total: number
      pass: number
      fail: number
      waiting: number
      not_applicable: number
    }>
    totals: {
      tasks_with_gates: number
      gates_total: number
      blocking_total: number
      pass: number
      fail: number
      waiting: number
      not_applicable: number
    }
  }
  workflow_communication?: {
    events: Array<{
      delivery?: 'requested' | 'ignored' | string
      task_id: string
      title: string
      status: string
      source: string
      source_task_id?: string | null
      reason?: string | null
      trigger_link?: string | null
      correlation_id?: string | null
      lead_handoff_token?: string | null
      dispatch_decision?: Record<string, unknown> | null
      requested_at?: string | null
    }>
    totals: Record<string, number>
    events_total: number
  }
  catalog?: Record<string, ProjectPolicyCheckCatalogItem[] | undefined>
  ok: boolean
} & Record<string, unknown>

export type ProjectPluginConfig = {
  workspace_id: string
  project_id: string
  plugin_key: 'team_mode' | 'git_delivery' | 'docker_compose' | string
  enabled: boolean
  version: number
  schema_version: number
  config: Record<string, unknown>
  compiled_policy: Record<string, unknown>
  last_validation_errors?: Array<Record<string, unknown>>
  last_validated_at?: string | null
  exists?: boolean
  created?: boolean
}

export type ProjectPluginConfigValidation = {
  workspace_id: string
  project_id: string
  plugin_key: 'team_mode' | 'git_delivery' | 'docker_compose' | string
  schema_version: number
  errors: Array<Record<string, unknown>>
  warnings: string[]
  blocking: boolean
  normalized_config: Record<string, unknown>
  compiled_policy: Record<string, unknown>
}

export type ProjectPluginConfigDiff = {
  workspace_id: string
  project_id: string
  plugin_key: 'team_mode' | 'git_delivery' | 'docker_compose' | string
  current_version: number
  exists: boolean
  blocking: boolean
  errors: Array<Record<string, unknown>>
  warnings: string[]
  config_changes: Array<Record<string, unknown>>
  compiled_policy_changes: Array<Record<string, unknown>>
  current_config: Record<string, unknown>
  next_config: Record<string, unknown>
  current_compiled_policy: Record<string, unknown>
  next_compiled_policy: Record<string, unknown>
  changed: boolean
}

export type ProjectCapabilities = {
  workspace_id: string
  project_id: string
  enabled_plugin_keys: string[]
  plugins: Array<{
    plugin_key: string
    exists: boolean
    enabled: boolean
    version: number
    schema_version: number
  }>
  capabilities: {
    team_mode: boolean
    git_delivery: boolean
    docker_compose: boolean
  }
}

export type EventStormingLinkReviewResult = {
  project_id: string
  entity_type: string
  entity_id: string
  component_id: string
  review_status: 'candidate' | 'approved' | 'rejected' | string
  inference_method: string
  confidence: number
  updated_at: string
}

export type EventStormingEntityLinks = {
  project_id: string
  entity_type: string
  entity_id: string
  items: Array<{
    component_id: string
    component_type: string
    component_title: string
    confidence: number
    review_status: 'candidate' | 'approved' | 'rejected' | string
    inference_method: string
    updated_at: string
  }>
}

export type EventStormingComponentLinks = {
  project_id: string
  component_id: string
  component_type: string
  component_title: string
  items: Array<{
    entity_id: string
    entity_type: string
    entity_title: string
    confidence: number
    review_status: 'candidate' | 'approved' | 'rejected' | string
    inference_method: string
    updated_at: string
  }>
}

export type ProjectKnowledgeSearchItem = {
  rank: number
  entity_type: string
  entity_id: string
  source_type: string
  snippet: string
  vector_similarity: number | null
  graph_score: number
  starter_alignment?: number
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
  setup_profile?: ProjectSetupProfile
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
  codex_session_id?: string | null
  usage?: AgentChatUsage | null
  resume_attempted?: boolean
  resume_succeeded?: boolean
  resume_fallback_used?: boolean
}

export type AgentAuthProvider = 'codex' | 'claude' | 'opencode'
export type AgentAuthEffectiveSource = 'system_override' | 'host_mount' | 'runtime_builtin' | 'none'
export type CodexAuthLoginMethod = 'browser' | 'device_code'
export type ClaudeAuthLoginMethod = 'claudeai' | 'console'

export type AgentAuthLoginSession = {
  id: string
  status: 'pending' | 'succeeded' | 'failed' | 'cancelled'
  started_at: string
  updated_at: string
  login_method?: CodexAuthLoginMethod | ClaudeAuthLoginMethod | string | null
  verification_uri?: string | null
  local_callback_url?: string | null
  user_code?: string | null
  error?: string | null
  output_excerpt?: string[]
}

export type AgentAuthStatus = {
  provider?: AgentAuthProvider | string
  provider_label?: string | null
  configured: boolean
  effective_source: AgentAuthEffectiveSource
  host_auth_available: boolean
  override_available: boolean
  override_updated_at?: string | null
  scope?: 'system' | string
  target_actor_user_id?: string | null
  target_actor_username?: string | null
  target_actor_full_name?: string | null
  selected_login_method?: CodexAuthLoginMethod | ClaudeAuthLoginMethod | string | null
  supported_login_methods?: Array<CodexAuthLoginMethod | ClaudeAuthLoginMethod | string>
  login_session?: AgentAuthLoginSession | null
}

export type CodexAuthStatus = AgentAuthStatus
export type ClaudeAuthStatus = AgentAuthStatus

export type ChatMcpServer = string
export type ChatReasoningEffort = 'low' | 'medium' | 'high' | 'xhigh'

export type AgentChatMcpServer = {
  name: string
  display_name: string
  enabled: boolean
  disabled_reason?: string | null
  auth_status?: string | null
}

export type AgentChatUsage = {
  input_tokens: number
  cached_input_tokens?: number
  output_tokens: number
  context_limit_tokens?: number
  graph_context_frame_mode?: 'full' | 'delta' | string
  graph_context_frame_revision?: string
  prompt_mode?: 'full' | 'resume' | string
  prompt_segment_chars?: Record<string, number>
  codex_resume_attempted?: boolean
  codex_resume_succeeded?: boolean
  codex_resume_fallback_used?: boolean
}

export type ChatSessionRecord = {
  id: string
  aggregate_id: string
  workspace_id: string
  project_id: string | null
  title: string
  is_archived: boolean
  codex_session_id: string | null
  mcp_servers: string[]
  session_attachment_refs: AttachmentRef[]
  usage: AgentChatUsage | null
  last_message_at: string | null
  last_message_preview: string
  last_task_event_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type ChatMessageRecord = {
  id: string
  session_id: string
  workspace_id: string
  project_id: string | null
  role: 'user' | 'assistant' | string
  content: string
  order_index: number
  attachment_refs: AttachmentRef[]
  usage: Record<string, unknown> | null
  is_deleted: boolean
  created_at: string | null
  updated_at: string | null
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
  status: 'Draft' | 'Ready' | 'In Progress' | 'Implemented' | 'Archived'
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
