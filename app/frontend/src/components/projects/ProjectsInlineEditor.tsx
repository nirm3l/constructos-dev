import React from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Select from '@radix-ui/react-select'
import * as Accordion from '@radix-ui/react-accordion'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import {
  applyProjectPluginConfig,
  createProjectRule,
  deleteProjectRule,
  diffProjectPluginConfig,
  getProjectDockerComposeRuntime,
  getProjectEventStormingOverview,
  getProjectGitRepositorySummary,
  getProjectCapabilities,
  getProjectMembers,
  getProjectPolicyChecksVerification,
  getProjectPluginConfig,
  patchProjectRule,
  setProjectPluginEnabled,
  validateProjectPluginConfig,
} from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import type {
  AgentChatUsage,
  AttachmentRef,
  EventStormingOverview,
  GraphContextPack,
  GraphProjectOverview,
  Project,
  ProjectDockerComposeRuntimeSnapshot,
  ProjectGitRepositorySummary,
  ProjectPolicyChecksVerifyResponse,
  ProjectCapabilities,
  ProjectPluginConfig,
  ProjectPluginConfigDiff,
  ProjectPluginConfigValidation,
  ProjectMembersPage,
  ProjectRule,
  ProjectRulesPage,
  ProjectSkill,
  ProjectSkillsPage,
  WorkspaceSkill,
  WorkspaceSkillsPage,
} from '../../types'
import type { ProjectGitRepositoryTarget } from '../../utils/gitRepositoryLinks'
import { parseProjectGitRepositoryExternalRef } from '../../utils/gitRepositoryLinks'
import {
  AttachmentRefList,
  ExternalRefEditor,
  Icon,
  MarkdownModeToggle,
  MarkdownSplitPane,
} from '../shared/uiHelpers'
import { ProjectContextSnapshotPanel } from './ProjectContextSnapshotPanel'
import { ProjectDockerComposeRuntimeDialog } from './ProjectDockerComposeRuntimeDialog'
import { ProjectGitRepositoryDialog } from './ProjectGitRepositoryDialog'
import {
  attachmentRefsToText,
  externalRefsToText,
  parseAttachmentRefsText,
  parseExternalRefsText,
  removeAttachmentByPath,
  removeExternalRefByIndex,
  toErrorMessage,
} from '../../utils/ui'

type ProjectMutation = {
  isPending: boolean
  mutate: (...args: any[]) => void
  mutateAsync?: (...args: any[]) => Promise<unknown>
}

type WorkspaceUser = {
  id: string
  full_name: string
  user_type: string
}

type CodexResumeStateLike = {
  attempted?: boolean
  succeeded?: boolean
  fallbackUsed?: boolean
} | null

type ProjectPluginKey = 'team_mode' | 'git_delivery' | 'docker_compose'
type TeamModeRole = 'Developer' | 'QA' | 'Lead'
type ProjectEditorTab =
  | 'overview'
  | 'checks'
  | 'team-mode'
  | 'git-delivery'
  | 'docker-compose'
  | 'rules'
  | 'skills'
  | 'resources'
  | 'context'
type StagedRuleCreate = { clientId: string; title: string; body: string }
type StagedSkillImportUrl = {
  clientId: string
  source_url: string
  skill_key?: string
  mode?: 'advisory' | 'enforced'
  trust_level?: 'verified' | 'reviewed' | 'untrusted'
}
type StagedSkillImportFile = {
  clientId: string
  file: File
  skill_key?: string
  mode?: 'advisory' | 'enforced'
  trust_level?: 'verified' | 'reviewed' | 'untrusted'
}

function pluginLabel(value: ProjectPluginKey): string {
  if (value === 'team_mode') return 'Team Mode'
  if (value === 'git_delivery') return 'Git Delivery'
  return 'Docker Compose'
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return '{}'
  }
}

function prettyCompact(value: unknown): string {
  try {
    const raw = JSON.stringify(value)
    if (!raw) return 'null'
    return raw.length > 160 ? `${raw.slice(0, 157)}...` : raw
  } catch {
    return String(value)
  }
}

const TEAM_MODE_ROLES: TeamModeRole[] = ['Developer', 'QA', 'Lead']
const PROJECT_EDITOR_TAB_VALUES: readonly ProjectEditorTab[] = [
  'overview',
  'checks',
  'team-mode',
  'git-delivery',
  'docker-compose',
  'rules',
  'skills',
  'resources',
  'context',
]

function resolveProjectEditorTabFromUrl(): ProjectEditorTab | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  const raw = String(params.get('project_editor_tab') || '').trim()
  if (!raw) return null
  return (PROJECT_EDITOR_TAB_VALUES as readonly string[]).includes(raw) ? (raw as ProjectEditorTab) : null
}

function buildTeamModeStarterConfig(args: {
  statuses: string[]
}): Record<string, unknown> {
  const statuses = args.statuses.length ? args.statuses : ['To do', 'Dev', 'QA', 'Lead', 'Done', 'Blocked']
  const statusSet = new Set(statuses)
  const hasCanonicalFlow = ['To do', 'Dev', 'Lead', 'QA', 'Done', 'Blocked'].every((status) => statusSet.has(status))
  const transitions = hasCanonicalFlow
    ? [
        { from: 'To do', to: 'Dev', allowed_roles: ['Developer', 'Lead'] },
        { from: 'Dev', to: 'Lead', allowed_roles: ['Developer'] },
        { from: 'Lead', to: 'QA', allowed_roles: ['Lead'] },
        { from: 'QA', to: 'Done', allowed_roles: ['QA'] },
        { from: 'To do', to: 'Blocked', allowed_roles: ['Developer', 'QA', 'Lead'] },
        { from: 'Dev', to: 'Blocked', allowed_roles: ['Developer', 'Lead'] },
        { from: 'Lead', to: 'Blocked', allowed_roles: ['Lead'] },
        { from: 'QA', to: 'Blocked', allowed_roles: ['QA', 'Lead'] },
        { from: 'Blocked', to: 'Dev', allowed_roles: ['Developer', 'Lead'] },
        { from: 'Blocked', to: 'Lead', allowed_roles: ['Lead'] },
        { from: 'Blocked', to: 'QA', allowed_roles: ['QA', 'Lead'] },
      ]
    : [
        statuses.length >= 2 ? { from: statuses[0], to: statuses[1], allowed_roles: ['Developer'] } : null,
        statuses.length >= 3 ? { from: statuses[1], to: statuses[2], allowed_roles: ['Lead'] } : null,
        statuses.length >= 4 ? { from: statuses[2], to: statuses[3], allowed_roles: ['QA'] } : null,
      ].filter(Boolean)
  return {
    required_checks: {
      team_mode: ['role_coverage_present', 'required_topology_present', 'lead_oversight_not_done_before_delivery_complete'],
    },
    team: {
      agents: [
        { id: 'dev-a', name: 'Developer A', authority_role: 'Developer' },
        { id: 'dev-b', name: 'Developer B', authority_role: 'Developer' },
        { id: 'qa-a', name: 'QA A', authority_role: 'QA' },
        { id: 'lead-a', name: 'Lead A', authority_role: 'Lead' },
      ],
    },
    workflow: {
      statuses,
      transitions,
    },
    governance: {
      merge_authority_roles: ['Lead'],
      task_move_authority_roles: ['Developer', 'QA', 'Lead'],
    },
    automation: {
      lead_recurring_max_minutes: 5,
    },
  }
}

function isTeamModeMinimalDefaultConfig(config: unknown): boolean {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return false
  const root = config as Record<string, unknown>
  const team = root.team && typeof root.team === 'object' && !Array.isArray(root.team)
    ? (root.team as Record<string, unknown>)
    : {}
  const workflow = root.workflow && typeof root.workflow === 'object' && !Array.isArray(root.workflow)
    ? (root.workflow as Record<string, unknown>)
    : {}
  const members = Array.isArray(team.members)
    ? team.members.filter((item) => item && typeof item === 'object')
    : []
  const agents = Array.isArray(team.agents)
    ? team.agents.filter((item) => item && typeof item === 'object')
    : []
  const transitions = Array.isArray(workflow.transitions)
    ? workflow.transitions.filter((item) => item && typeof item === 'object')
    : []
  return members.length === 0 && agents.length === 0 && transitions.length === 0
}

const GIT_DELIVERY_STARTER_CONFIG: Record<string, unknown> = {
  required_checks: {
    delivery: [
      'repo_context_present',
      'git_contract_ok',
    ],
  },
  execution: {
    require_dev_tests: false,
  },
}

const DOCKER_COMPOSE_STARTER_CONFIG: Record<string, unknown> = {
  compose_project_name: 'constructos-app',
  workspace_root: '/workspace',
  allowed_services: ['task-app', 'mcp-tools'],
  protected_services: ['license-control-plane', 'license-control-plane-backup'],
  runtime_deploy_health: {
    required: false,
    stack: 'constructos-ws-default',
    port: null,
    health_path: '/health',
    require_http_200: true,
  },
}

function parseJsonObject(rawText: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(rawText || '{}') as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

function isEmptyObject(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return true
  return Object.keys(value as Record<string, unknown>).length === 0
}

function roleLabel(value: string): string {
  const normalized = String(value || '').trim()
  if (normalized === 'DeveloperAgent') return 'Developer'
  if (normalized === 'QAAgent') return 'QA'
  if (normalized === 'TeamLeadAgent') return 'Lead'
  if (normalized === 'Developer') return 'Developer'
  if (normalized === 'QA') return 'QA'
  if (normalized === 'Lead') return 'Lead'
  return normalized || 'Unknown'
}

function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip.Provider delayDuration={120}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button type="button" className="project-plugin-tooltip-trigger" aria-label={text}>
            <Icon path="M12 16v-4m0-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
            {text}
            <Tooltip.Arrow className="header-tooltip-arrow" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}

function csvToList(value: string): string[] {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function listToCsv(value: unknown): string {
  if (!Array.isArray(value)) return ''
  return value
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .join(', ')
}

export function ProjectsInlineEditor({
  project,
  selectedProject,
  projectIsDirty,
  editProjectName,
  setEditProjectName,
  editProjectCustomStatusesText,
  setEditProjectCustomStatusesText,
  editProjectEmbeddingEnabled,
  setEditProjectEmbeddingEnabled,
  editProjectEmbeddingModel,
  setEditProjectEmbeddingModel,
  editProjectContextPackEvidenceTopKText,
  setEditProjectContextPackEvidenceTopKText,
  editProjectAutomationMaxParallelTasksText,
  setEditProjectAutomationMaxParallelTasksText,
  editProjectChatIndexMode,
  setEditProjectChatIndexMode,
  editProjectChatAttachmentIngestionMode,
  setEditProjectChatAttachmentIngestionMode,
  editProjectEventStormingEnabled,
  setEditProjectEventStormingEnabled,
  embeddingAllowedModels,
  embeddingDefaultModel,
  vectorStoreEnabled,
  contextPackEvidenceTopKDefault,
  contextLimitTokensDefault,
  codexChatProjectId,
  codexChatTurns,
  codexChatUsage,
  codexChatResumeState,
  saveProjectMutation,
  deleteProjectMutation,
  editProjectDescriptionView,
  setEditProjectDescriptionView,
  editProjectDescriptionRef,
  editProjectDescription,
  setEditProjectDescription,
  projectRules,
  projectSkills,
  projectGraphOverview,
  projectGraphContextPack,
  projectEventStormingOverview,
  workspaceSkills,
  selectedProjectRuleId,
  setSelectedProjectRuleId,
  projectRuleTitle,
  setProjectRuleTitle,
  projectRuleBody,
  setProjectRuleBody,
  projectRuleView,
  setProjectRuleView,
  createProjectRuleMutation,
  patchProjectRuleMutation,
  deleteProjectRuleMutation,
  importProjectSkillMutation,
  importProjectSkillFileMutation,
  patchProjectSkillMutation,
  applyProjectSkillMutation,
  deleteProjectSkillMutation,
  attachWorkspaceSkillToProjectMutation,
  toUserDateTime,
  userTimezone,
  editProjectExternalRefsText,
  setEditProjectExternalRefsText,
  editProjectFileInputRef,
  uploadAttachmentRef,
  setUiError,
  editProjectAttachmentRefsText,
  setEditProjectAttachmentRefsText,
  workspaceId,
  userId,
  workspaceUsers,
  editProjectMemberIds,
  toggleEditProjectMember,
  selectedProjectCreator,
  selectedProjectTimeMeta,
  onUnsavedChange,
}: {
  project: Project
  selectedProject: Project
  projectIsDirty: boolean
  editProjectName: string
  setEditProjectName: React.Dispatch<React.SetStateAction<string>>
  editProjectCustomStatusesText: string
  setEditProjectCustomStatusesText: React.Dispatch<React.SetStateAction<string>>
  editProjectEmbeddingEnabled: boolean
  setEditProjectEmbeddingEnabled: React.Dispatch<React.SetStateAction<boolean>>
  editProjectEmbeddingModel: string
  setEditProjectEmbeddingModel: React.Dispatch<React.SetStateAction<string>>
  editProjectContextPackEvidenceTopKText: string
  setEditProjectContextPackEvidenceTopKText: React.Dispatch<React.SetStateAction<string>>
  editProjectAutomationMaxParallelTasksText: string
  setEditProjectAutomationMaxParallelTasksText: React.Dispatch<React.SetStateAction<string>>
  editProjectChatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'
  setEditProjectChatIndexMode: React.Dispatch<React.SetStateAction<'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'>>
  editProjectChatAttachmentIngestionMode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
  setEditProjectChatAttachmentIngestionMode: React.Dispatch<
    React.SetStateAction<'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'>
  >
  editProjectEventStormingEnabled: boolean
  setEditProjectEventStormingEnabled: React.Dispatch<React.SetStateAction<boolean>>
  embeddingAllowedModels: string[]
  embeddingDefaultModel: string
  vectorStoreEnabled: boolean
  contextPackEvidenceTopKDefault: number
  contextLimitTokensDefault: number
  codexChatProjectId: string
  codexChatTurns: Array<{ role?: string; content?: string }>
  codexChatUsage?: AgentChatUsage | null
  codexChatResumeState?: CodexResumeStateLike
  saveProjectMutation: ProjectMutation
  deleteProjectMutation: ProjectMutation
  editProjectDescriptionView: 'write' | 'preview' | 'split'
  setEditProjectDescriptionView: React.Dispatch<React.SetStateAction<'write' | 'preview' | 'split'>>
  editProjectDescriptionRef: React.RefObject<HTMLTextAreaElement | null>
  editProjectDescription: string
  setEditProjectDescription: React.Dispatch<React.SetStateAction<string>>
  projectRules: { data?: ProjectRulesPage }
  projectSkills: { data?: ProjectSkillsPage; isLoading?: boolean; isFetching?: boolean }
  projectGraphOverview?: { data?: GraphProjectOverview }
  projectGraphContextPack?: { data?: GraphContextPack }
  projectEventStormingOverview?: {
    data?: EventStormingOverview
    isLoading?: boolean
    isFetching?: boolean
    isError?: boolean
    error?: unknown
  }
  workspaceSkills: { data?: WorkspaceSkillsPage; isLoading?: boolean; isFetching?: boolean }
  selectedProjectRuleId: string | null
  setSelectedProjectRuleId: React.Dispatch<React.SetStateAction<string | null>>
  projectRuleTitle: string
  setProjectRuleTitle: React.Dispatch<React.SetStateAction<string>>
  projectRuleBody: string
  setProjectRuleBody: React.Dispatch<React.SetStateAction<string>>
  projectRuleView: 'write' | 'preview' | 'split'
  setProjectRuleView: React.Dispatch<React.SetStateAction<'write' | 'preview' | 'split'>>
  createProjectRuleMutation: ProjectMutation
  patchProjectRuleMutation: ProjectMutation
  deleteProjectRuleMutation: ProjectMutation
  importProjectSkillMutation: ProjectMutation
  importProjectSkillFileMutation: ProjectMutation
  patchProjectSkillMutation: ProjectMutation
  applyProjectSkillMutation: ProjectMutation
  deleteProjectSkillMutation: ProjectMutation
  attachWorkspaceSkillToProjectMutation: ProjectMutation
  toUserDateTime: (iso: unknown, timezone: string | undefined) => string
  userTimezone: string | undefined
  editProjectExternalRefsText: string
  setEditProjectExternalRefsText: React.Dispatch<React.SetStateAction<string>>
  editProjectFileInputRef: React.RefObject<HTMLInputElement | null>
  uploadAttachmentRef: (file: File, opts: { project_id: string; task_id?: string; note_id?: string }) => Promise<AttachmentRef>
  setUiError: React.Dispatch<React.SetStateAction<string | null>>
  editProjectAttachmentRefsText: string
  setEditProjectAttachmentRefsText: React.Dispatch<React.SetStateAction<string>>
  workspaceId: string
  userId: string
  workspaceUsers: WorkspaceUser[]
  editProjectMemberIds: string[]
  toggleEditProjectMember: (userIdToToggle: string) => void
  selectedProjectCreator: string
  selectedProjectTimeMeta: { label: 'Created' | 'Updated'; value: string } | null
  onUnsavedChange?: (hasUnsavedChanges: boolean) => void
}) {
  const modelOptions = React.useMemo(
    () =>
      Array.from(
        new Set(
          (embeddingAllowedModels ?? [])
            .map((model) => String(model || '').trim())
            .filter(Boolean)
        )
      ),
    [embeddingAllowedModels]
  )
  const defaultModel = React.useMemo(() => {
    const normalized = String(embeddingDefaultModel || '').trim()
    if (normalized && modelOptions.includes(normalized)) return normalized
    return modelOptions[0] ?? ''
  }, [embeddingDefaultModel, modelOptions])
  const selectedModel = React.useMemo(() => {
    const current = String(editProjectEmbeddingModel || '').trim()
    if (current && modelOptions.includes(current)) return current
    return defaultModel
  }, [defaultModel, editProjectEmbeddingModel, modelOptions])
  const embeddingStatus = String(selectedProject.embedding_index_status || 'not_indexed')
  const embeddingStatusLabel =
    embeddingStatus === 'ready'
      ? 'Ready'
      : embeddingStatus === 'indexing'
        ? 'Indexing'
        : embeddingStatus === 'stale'
          ? 'Stale'
          : 'Not indexed'
  const embeddingIndexedEntities = Math.max(0, Number(selectedProject.embedding_indexed_entities ?? 0))
  const embeddingExpectedEntities = Math.max(0, Number(selectedProject.embedding_index_expected_entities ?? 0))
  const embeddingIndexedChunks = Math.max(0, Number(selectedProject.embedding_indexed_chunks ?? 0))
  const rawEmbeddingProgressPct = selectedProject.embedding_index_progress_pct
  const embeddingProgressPct =
    typeof rawEmbeddingProgressPct === 'number' && Number.isFinite(rawEmbeddingProgressPct)
      ? Math.max(0, Math.min(100, Math.round(rawEmbeddingProgressPct)))
      : null
  const embeddingStatusBadgeLabel = React.useMemo(() => {
    let label = `Index: ${embeddingStatusLabel}`
    if (embeddingStatus !== 'indexing') return label
    if (embeddingExpectedEntities > 0) {
      const computedPct =
        embeddingProgressPct == null
          ? Math.round((embeddingIndexedEntities / embeddingExpectedEntities) * 100)
          : embeddingProgressPct
      label += ` ${embeddingIndexedEntities}/${embeddingExpectedEntities} (${Math.max(0, Math.min(100, computedPct))}%)`
      return label
    }
    label += ` ${embeddingIndexedChunks} chunks`
    return label
  }, [
    embeddingExpectedEntities,
    embeddingIndexedChunks,
    embeddingIndexedEntities,
    embeddingProgressPct,
    embeddingStatus,
    embeddingStatusLabel,
  ])
  const vectorAvailable = Boolean(vectorStoreEnabled)
  const chatPolicyDisabled = !editProjectEmbeddingEnabled
  const effectiveChatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' = chatPolicyDisabled
    ? 'OFF'
    : editProjectChatIndexMode
  const chatAttachmentDisabled = chatPolicyDisabled || effectiveChatIndexMode === 'OFF'
  const queryClient = useQueryClient()
  const inlineEventStormingOverviewQuery = useQuery({
    queryKey: ['project-event-storming-overview', userId, project.id],
    queryFn: () => getProjectEventStormingOverview(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const eventStormingOverview = inlineEventStormingOverviewQuery.data ?? projectEventStormingOverview?.data
  const teamModePluginQuery = useQuery<ProjectPluginConfig>({
    queryKey: ['project-plugin-config', userId, project.id, 'team_mode'],
    queryFn: () => getProjectPluginConfig(userId, project.id, 'team_mode'),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const projectMembersQuery = useQuery<ProjectMembersPage>({
    queryKey: ['project-members-inline', userId, project.id],
    queryFn: () => getProjectMembers(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const gitDeliveryPluginQuery = useQuery<ProjectPluginConfig>({
    queryKey: ['project-plugin-config', userId, project.id, 'git_delivery'],
    queryFn: () => getProjectPluginConfig(userId, project.id, 'git_delivery'),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const dockerComposePluginQuery = useQuery<ProjectPluginConfig>({
    queryKey: ['project-plugin-config', userId, project.id, 'docker_compose'],
    queryFn: () => getProjectPluginConfig(userId, project.id, 'docker_compose'),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const gitRepositorySummaryQuery = useQuery<ProjectGitRepositorySummary>({
    queryKey: ['project-git-repository-summary', userId, project.id],
    queryFn: () => getProjectGitRepositorySummary(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id && gitDeliveryPluginQuery.data?.enabled),
    retry: false,
  })
  const dockerComposeRuntimeQuery = useQuery<ProjectDockerComposeRuntimeSnapshot>({
    queryKey: ['project-docker-compose-runtime', userId, project.id],
    queryFn: () => getProjectDockerComposeRuntime(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id && dockerComposePluginQuery.data?.enabled),
    refetchInterval: dockerComposePluginQuery.data?.enabled ? 15000 : false,
  })
  const projectCapabilitiesQuery = useQuery<ProjectCapabilities>({
    queryKey: ['project-capabilities', userId, project.id],
    queryFn: () => getProjectCapabilities(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const shouldShowProjectChecks = Boolean(teamModePluginQuery.data?.enabled || gitDeliveryPluginQuery.data?.enabled)
  const capabilityByPluginKey = React.useMemo(() => {
    const out: Record<string, { enabled: boolean; version: number }> = {}
    for (const item of projectCapabilitiesQuery.data?.plugins || []) {
      const key = String(item?.plugin_key || '').trim()
      if (!key) continue
      out[key] = {
        enabled: Boolean(item.enabled),
        version: Number(item.version || 0),
      }
    }
    return out
  }, [projectCapabilitiesQuery.data?.plugins])
  const projectChecksQuery = useQuery<ProjectPolicyChecksVerifyResponse>({
    queryKey: ['project-checks-verify', userId, project.id],
    queryFn: () => getProjectPolicyChecksVerification(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id && shouldShowProjectChecks),
    refetchInterval: 20_000,
  })
  const [dockerRuntimeDialogOpen, setDockerRuntimeDialogOpen] = React.useState(false)
  const [gitRepositoryDialogOpen, setGitRepositoryDialogOpen] = React.useState(false)
  const [gitRepositoryDialogTarget, setGitRepositoryDialogTarget] = React.useState<ProjectGitRepositoryTarget | null>(null)
  const openGitRepositoryFromRef = React.useCallback((ref: { url: string; title?: string; source?: string }) => {
    const target = parseProjectGitRepositoryExternalRef(ref)
    if (!target) return false
    setGitRepositoryDialogTarget(target)
    setGitRepositoryDialogOpen(true)
    return true
  }, [])
  const validatePluginConfigMutation = useMutation({
    mutationFn: (params: { pluginKey: ProjectPluginKey; draftConfig: Record<string, unknown> }) =>
      validateProjectPluginConfig(userId, project.id, params.pluginKey, {
        draft_config: params.draftConfig,
      }),
  })
  const applyPluginConfigMutation = useMutation({
    mutationFn: (params: {
      pluginKey: ProjectPluginKey
      config: Record<string, unknown>
      expectedVersion?: number
      enabled?: boolean
    }) =>
      applyProjectPluginConfig(userId, project.id, params.pluginKey, {
        config: params.config,
        expected_version: params.expectedVersion,
        enabled: params.enabled,
      }),
  })
  const setPluginEnabledMutation = useMutation({
    mutationFn: (params: { pluginKey: ProjectPluginKey; enabled: boolean }) =>
      setProjectPluginEnabled(userId, project.id, params.pluginKey, {
        enabled: params.enabled,
      }),
  })
  const diffPluginConfigMutation = useMutation({
    mutationFn: (params: { pluginKey: ProjectPluginKey; draftConfig: Record<string, unknown> }) =>
      diffProjectPluginConfig(userId, project.id, params.pluginKey, {
        draft_config: params.draftConfig,
      }),
  })
  const eventStormingFrameModeRaw = String(eventStormingOverview?.context_frame?.mode || '').trim().toLowerCase()
  const eventStormingFrameMode = eventStormingFrameModeRaw === 'full' || eventStormingFrameModeRaw === 'delta'
    ? eventStormingFrameModeRaw.toUpperCase()
    : null
  const eventStormingFrameRevision = String(eventStormingOverview?.context_frame?.revision || '').trim()
  const eventStormingFrameRevisionShort = eventStormingFrameRevision ? eventStormingFrameRevision.slice(0, 8) : null
  const eventStormingFrameUpdatedAtRaw = String(eventStormingOverview?.context_frame?.updated_at || '').trim()
  const eventStormingFrameUpdatedAtLabel = eventStormingFrameUpdatedAtRaw
    ? new Date(eventStormingFrameUpdatedAtRaw).toLocaleString()
    : null
  const eventStormingOverviewLoading = Boolean(
    inlineEventStormingOverviewQuery.isLoading ||
      inlineEventStormingOverviewQuery.isFetching ||
      (!inlineEventStormingOverviewQuery.data &&
        (projectEventStormingOverview?.isLoading || projectEventStormingOverview?.isFetching))
  )
  const eventStormingOverviewError = Boolean(
    inlineEventStormingOverviewQuery.isError ||
      (!inlineEventStormingOverviewQuery.data && projectEventStormingOverview?.isError)
  )
  const eventStormingProcessing = eventStormingOverview?.processing ?? {
    artifact_total: 0,
    processed: 0,
    queued: 0,
    running: 0,
    failed: 0,
    done: 0,
    progress_pct: 0,
  }
  const eventStormingProgressPct = Math.max(0, Math.min(100, Number(eventStormingProcessing.progress_pct || 0)))
  const eventStormingComponentStats = React.useMemo(() => {
    const counts = eventStormingOverview?.component_counts ?? {}
    return [
      { key: 'BoundedContext', label: 'Bounded Context', color: '#14b8a6', count: Number(counts.BoundedContext || 0) },
      { key: 'Aggregate', label: 'Aggregate', color: '#f59e0b', count: Number(counts.Aggregate || 0) },
      { key: 'Command', label: 'Command', color: '#2563eb', count: Number(counts.Command || 0) },
      { key: 'DomainEvent', label: 'Domain Event', color: '#ea580c', count: Number(counts.DomainEvent || 0) },
      { key: 'Policy', label: 'Policy', color: '#8b5cf6', count: Number(counts.Policy || 0) },
      { key: 'ReadModel', label: 'Read Model', color: '#64748b', count: Number(counts.ReadModel || 0) },
    ]
  }, [eventStormingOverview?.component_counts])
  const projectChecksSnapshot = projectChecksQuery.data
  const gateScopeEntries = React.useMemo<
    Array<{
      scopeKey: string
      scopeTitle: string
      active: boolean
      checks: Record<string, boolean | string | number | null>
      requiredChecks: string[]
      failedChecks: string[]
      checkDescriptions: Record<string, string>
      availableChecks: Array<{ id: string; description?: string }>
      gatePolicySource: string
      gatePolicy?: Record<string, unknown>
    }>
  >(() => {
    if (!projectChecksSnapshot || typeof projectChecksSnapshot !== 'object') return []
    const payload = projectChecksSnapshot as Record<string, unknown>
    const catalogRaw =
      payload.catalog && typeof payload.catalog === 'object'
        ? (payload.catalog as Record<string, unknown>)
        : ({} as Record<string, unknown>)

    const scopeKeys = Object.keys(payload).filter(
      (key) => !['project_id', 'catalog', 'ok'].includes(String(key || '').trim().toLowerCase())
    )
    return scopeKeys
      .map((scopeKey) => {
        const scopeRaw = payload[scopeKey]
        if (!scopeRaw || typeof scopeRaw !== 'object') return null
        const scope = scopeRaw as Record<string, unknown>
        const activeValue = scope.active
        const scopeActive = typeof activeValue === 'boolean' ? activeValue : true
        if (!scopeActive) return null
        const checksRaw = scope.checks
        const checks =
          checksRaw && typeof checksRaw === 'object'
            ? (checksRaw as Record<string, boolean | string | number | null>)
            : ({} as Record<string, boolean | string | number | null>)
        if (Object.keys(checks).length === 0) return null

        const requiredChecks = Array.isArray(scope.required_checks)
          ? scope.required_checks.map((item) => String(item || '').trim()).filter(Boolean)
          : []
        const failedChecks = Array.isArray(scope.required_failed_checks)
          ? scope.required_failed_checks.map((item) => String(item || '').trim()).filter(Boolean)
          : []
        const baseDescriptions =
          scope.check_descriptions && typeof scope.check_descriptions === 'object'
            ? (scope.check_descriptions as Record<string, string>)
            : {}

        const policyRaw = scope.plugin_policy
        const policy =
          policyRaw && typeof policyRaw === 'object'
            ? (policyRaw as Record<string, unknown>)
            : undefined
        const policyAvailableRaw =
          policy?.available_checks && typeof policy.available_checks === 'object'
            ? (policy.available_checks as Record<string, unknown>)
            : {}
        const policyScopeDescriptionsRaw = policyAvailableRaw[scopeKey]
        const policyScopeDescriptions =
          policyScopeDescriptionsRaw && typeof policyScopeDescriptionsRaw === 'object'
            ? (policyScopeDescriptionsRaw as Record<string, unknown>)
            : {}
        const policyDescriptions: Record<string, string> = {}
        for (const [key, value] of Object.entries(policyScopeDescriptions)) {
          const id = String(key || '').trim()
          const description = String(value || '').trim()
          if (!id || !description) continue
          policyDescriptions[id] = description
        }
        const checkDescriptions = {
          ...baseDescriptions,
          ...policyDescriptions,
        }

        const catalogForScopeRaw = catalogRaw[scopeKey]
        const catalogForScope = Array.isArray(catalogForScopeRaw)
          ? (catalogForScopeRaw as Array<{ id: string; description?: string }>)
          : []
        const availableChecks = catalogForScope.length
          ? catalogForScope
          : (Array.isArray(scope.available_checks) ? scope.available_checks : [])
              .map((id) => ({ id: String(id || '').trim() }))
              .filter((item) => Boolean(item.id))

        const scopeTitle = scopeKey
          .split('_')
          .map((token) => (token ? token.charAt(0).toUpperCase() + token.slice(1) : token))
          .join(' ')

        return {
          scopeKey,
          scopeTitle,
          active: scopeActive,
          checks,
          requiredChecks,
          failedChecks,
          checkDescriptions,
          availableChecks,
          gatePolicySource: String(scope.plugin_policy_source || '').trim() || 'default',
          gatePolicy: policy,
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
  }, [projectChecksSnapshot])
  const gatePolicyPayload = React.useMemo(() => {
    for (const scope of gateScopeEntries) {
      if (scope.gatePolicy && Object.keys(scope.gatePolicy).length > 0) return scope.gatePolicy
    }
    return undefined
  }, [gateScopeEntries])
  const runtimeScopeMap = React.useMemo(() => {
    const map = new Map<string, (typeof gateScopeEntries)[number]>()
    for (const scope of gateScopeEntries) map.set(scope.scopeKey, scope)
    return map
  }, [gateScopeEntries])
  const gateConfigScopes = React.useMemo<
    Array<{
      scopeKey: string
      scopeTitle: string
      requiredChecks: string[]
      diagnosticChecks: string[]
      availableDescriptions: Record<string, string>
      runtimeScope?: (typeof gateScopeEntries)[number]
    }>
  >(() => {
    const toTitle = (scopeKey: string) =>
      scopeKey
        .split('_')
        .map((token) => (token ? token.charAt(0).toUpperCase() + token.slice(1) : token))
        .join(' ')

    const requiredChecksRaw =
      gatePolicyPayload &&
      typeof gatePolicyPayload.required_checks === 'object' &&
      gatePolicyPayload.required_checks !== null
        ? (gatePolicyPayload.required_checks as Record<string, unknown>)
        : {}
    const availableChecksRaw =
      gatePolicyPayload &&
      typeof gatePolicyPayload.available_checks === 'object' &&
      gatePolicyPayload.available_checks !== null
        ? (gatePolicyPayload.available_checks as Record<string, unknown>)
        : {}
    const scopeKeys = Object.keys(requiredChecksRaw)
    if (scopeKeys.length === 0) {
      return gateScopeEntries.map((scope) => ({
        scopeKey: scope.scopeKey,
        scopeTitle: scope.scopeTitle,
        requiredChecks: scope.requiredChecks,
        diagnosticChecks: Object.keys(scope.checkDescriptions)
          .map((item) => String(item || '').trim())
          .filter((item) => Boolean(item) && !scope.requiredChecks.includes(item)),
        availableDescriptions: scope.checkDescriptions,
        runtimeScope: scope,
      }))
    }
    return scopeKeys
      .map((scopeKey) => {
      const runtimeScope = runtimeScopeMap.get(scopeKey)
      if (!runtimeScope) return null
      const requiredChecks = Array.isArray(requiredChecksRaw[scopeKey])
        ? (requiredChecksRaw[scopeKey] as unknown[])
            .map((item) => String(item || '').trim())
            .filter(Boolean)
        : []
      const availableScopeRaw = availableChecksRaw[scopeKey]
      const availableDescriptions: Record<string, string> = {}
      if (availableScopeRaw && typeof availableScopeRaw === 'object') {
        for (const [checkId, descriptionRaw] of Object.entries(availableScopeRaw as Record<string, unknown>)) {
          const normalizedId = String(checkId || '').trim()
          const normalizedDescription = String(descriptionRaw || '').trim()
          if (!normalizedId || !normalizedDescription) continue
          availableDescriptions[normalizedId] = normalizedDescription
        }
      }
      return {
        scopeKey,
        scopeTitle: toTitle(scopeKey),
        requiredChecks,
        diagnosticChecks: Array.from(
          new Set(
            [
              ...Object.keys(availableDescriptions),
              ...Object.keys(runtimeScope.checkDescriptions || {}),
              ...Object.keys(runtimeScope.checks || {}),
            ]
              .map((item) => String(item || '').trim())
              .filter((item) => Boolean(item) && !requiredChecks.includes(item))
          )
        ),
        availableDescriptions,
        runtimeScope,
      }
    })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
  }, [gatePolicyPayload, gateScopeEntries, runtimeScopeMap])
  const gateSummary = React.useMemo(() => {
    return gateConfigScopes.reduce(
      (acc, scope) => {
        const runtimeFailed = new Set(scope.runtimeScope?.failedChecks ?? [])
        for (const checkId of scope.requiredChecks) {
          if (runtimeFailed.has(checkId)) acc.failed += 1
        }
        if (!scope.runtimeScope) acc.unknown += scope.requiredChecks.length
        acc.required += scope.requiredChecks.length
        return acc
      },
      { failed: 0, required: 0, unknown: 0 }
    )
  }, [gateConfigScopes])
  const gatePolicySource = React.useMemo(
    () => gateScopeEntries.find((scope) => scope.gatePolicySource !== 'default')?.gatePolicySource || 'default',
    [gateScopeEntries]
  )
  const teamModeVerificationScope = React.useMemo(
    () => gateConfigScopes.find((scope) => scope.scopeKey === 'team_mode'),
    [gateConfigScopes]
  )
  const deliveryVerificationScope = React.useMemo(
    () => gateConfigScopes.find((scope) => scope.scopeKey === 'delivery'),
    [gateConfigScopes]
  )
  const deliveryKickoffRequired = Boolean(projectChecksSnapshot?.delivery?.kickoff_required)
  const deliveryKickoffHint = String(projectChecksSnapshot?.delivery?.kickoff_hint || '').trim()
  const deliveryRuntimeDeployHealth = React.useMemo(() => {
    const raw = projectChecksSnapshot?.delivery?.runtime_deploy_health
    if (!raw || typeof raw !== 'object') return null
    const value = raw as Record<string, unknown>
    const stack = String(value.stack || '').trim() || 'constructos-ws-default'
    const healthPathRaw = String(value.health_path || '').trim() || '/health'
    const healthPath = healthPathRaw.startsWith('/') ? healthPathRaw : `/${healthPathRaw}`
    const rawPort = value.port
    let port: number | null = null
    if (typeof rawPort === 'number' && Number.isFinite(rawPort)) {
      port = rawPort
    } else if (typeof rawPort === 'string' && rawPort.trim()) {
      const parsed = Number(rawPort)
      if (Number.isFinite(parsed)) port = parsed
    }
    const endpoint = port != null ? `http://gateway:${port}${healthPath}` : null
    return {
      stack,
      port,
      healthPath,
      endpoint,
      ok: Boolean(value.ok),
      skipped: Boolean(value.skipped),
      required: !Boolean(value.skipped),
      stackRunning: Boolean(value.stack_running),
      portMapped: Boolean(value.port_mapped),
      http200: Boolean(value.http_200),
    }
  }, [projectChecksSnapshot?.delivery?.runtime_deploy_health])
  const deliveryKickoffSummaryLine = React.useMemo(() => {
    if (deliveryKickoffRequired) {
      return `Kickoff state: waiting (Lead-first kickoff has not been requested yet).`
    }
    return 'Kickoff state: started (Lead-first orchestration active; QA runs after explicit Lead handoff).'
  }, [deliveryKickoffRequired])
  const executionGateSnapshot = React.useMemo(() => {
    const raw = projectChecksSnapshot?.execution_gates
    if (!raw || typeof raw !== 'object') return null
    const totalsRaw = raw.totals && typeof raw.totals === 'object' ? (raw.totals as Record<string, unknown>) : {}
    const tasksRaw = Array.isArray(raw.tasks) ? raw.tasks : []
    const totals = {
      tasks_with_gates: Number(totalsRaw.tasks_with_gates || 0),
      gates_total: Number(totalsRaw.gates_total || 0),
      blocking_total: Number(totalsRaw.blocking_total || 0),
      pass: Number(totalsRaw.pass || 0),
      fail: Number(totalsRaw.fail || 0),
      waiting: Number(totalsRaw.waiting || 0),
      not_applicable: Number(totalsRaw.not_applicable || 0),
    }
    const tasks = tasksRaw
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const row = item as Record<string, unknown>
        const task_id = String(row.task_id || '').trim()
        if (!task_id) return null
        return {
          task_id,
          title: String(row.title || '').trim() || task_id,
          status: String(row.status || '').trim(),
          gates_total: Number(row.gates_total || 0),
          blocking_total: Number(row.blocking_total || 0),
          pass: Number(row.pass || 0),
          fail: Number(row.fail || 0),
          waiting: Number(row.waiting || 0),
          not_applicable: Number(row.not_applicable || 0),
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
    return { totals, tasks }
  }, [projectChecksSnapshot?.execution_gates])
  const workflowCommunicationSnapshot = React.useMemo(() => {
    const raw = projectChecksSnapshot?.workflow_communication
    if (!raw || typeof raw !== 'object') return null
    const value = raw as Record<string, unknown>
    const totalsRaw = value.totals && typeof value.totals === 'object' ? (value.totals as Record<string, unknown>) : {}
    const eventsRaw = Array.isArray(value.events) ? value.events : []
    const totals: Record<string, number> = {}
    for (const [key, count] of Object.entries(totalsRaw)) {
      const normalizedKey = String(key || '').trim()
      if (!normalizedKey) continue
      totals[normalizedKey] = Number(count || 0)
    }
    const events = eventsRaw
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const row = item as Record<string, unknown>
        const taskId = String(row.task_id || '').trim()
        const source = String(row.source || '').trim()
        if (!taskId || !source) return null
        return {
          delivery: String(row.delivery || '').trim() || 'requested',
          task_id: taskId,
          title: String(row.title || '').trim() || taskId,
          status: String(row.status || '').trim(),
          source,
          source_task_id: String(row.source_task_id || '').trim() || null,
          reason: String(row.reason || '').trim() || null,
          trigger_link: String(row.trigger_link || '').trim() || null,
          correlation_id: String(row.correlation_id || '').trim() || null,
          lead_handoff_token: String(row.lead_handoff_token || '').trim() || null,
          dispatch_decision:
            row.dispatch_decision && typeof row.dispatch_decision === 'object'
              ? (row.dispatch_decision as Record<string, unknown>)
              : null,
          requested_at: String(row.requested_at || '').trim() || null,
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
    return {
      totals,
      events,
      events_total: Number(value.events_total || events.length || 0),
    }
  }, [projectChecksSnapshot?.workflow_communication])
  const effectiveEventStormingEnabled = Boolean(editProjectEventStormingEnabled ?? true)
  const projectExternalRefs = React.useMemo(
    () => parseExternalRefsText(editProjectExternalRefsText),
    [editProjectExternalRefsText]
  )
  const projectAttachmentRefs = React.useMemo(
    () => parseAttachmentRefsText(editProjectAttachmentRefsText),
    [editProjectAttachmentRefsText]
  )
  const templateBinding = selectedProject.template_binding
  const [selectedProjectSkillId, setSelectedProjectSkillId] = React.useState<string | null>(null)
  const [skillImportSourceUrl, setSkillImportSourceUrl] = React.useState('')
  const skillImportFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const [projectEditorTab, setProjectEditorTab] = React.useState<ProjectEditorTab>(
    () => resolveProjectEditorTabFromUrl() || 'overview'
  )
  const [skillImportKey, setSkillImportKey] = React.useState('')
  const [skillImportMode, setSkillImportMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [skillImportTrustLevel, setSkillImportTrustLevel] = React.useState<'verified' | 'reviewed' | 'untrusted'>(
    'reviewed'
  )
  const [skillEditorName, setSkillEditorName] = React.useState('')
  const [skillEditorSummary, setSkillEditorSummary] = React.useState('')
  const [skillEditorContent, setSkillEditorContent] = React.useState('')
  const [skillEditorMode, setSkillEditorMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [skillEditorTrustLevel, setSkillEditorTrustLevel] = React.useState<'verified' | 'reviewed' | 'untrusted'>(
    'reviewed'
  )
  const [skillContentView, setSkillContentView] = React.useState<'write' | 'preview' | 'split'>('split')
  const [showCatalogPicker, setShowCatalogPicker] = React.useState(false)
  const [catalogSearchQ, setCatalogSearchQ] = React.useState('')
  const [removeProjectPromptOpen, setRemoveProjectPromptOpen] = React.useState(false)
  const [deleteRulePrompt, setDeleteRulePrompt] = React.useState<{ id: string; title: string } | null>(null)
  const [deleteSkillPrompt, setDeleteSkillPrompt] = React.useState<{ id: string; name: string } | null>(null)
  const [teamModeConfigText, setTeamModeConfigText] = React.useState('{}')
  const [gitDeliveryConfigText, setGitDeliveryConfigText] = React.useState('{}')
  const [dockerComposeConfigText, setDockerComposeConfigText] = React.useState('{}')
  const [teamModePersistedText, setTeamModePersistedText] = React.useState('{}')
  const [gitDeliveryPersistedText, setGitDeliveryPersistedText] = React.useState('{}')
  const [dockerComposePersistedText, setDockerComposePersistedText] = React.useState('{}')
  const [teamModeLocalEditLock, setTeamModeLocalEditLock] = React.useState(false)
  const [gitDeliveryLocalEditLock, setGitDeliveryLocalEditLock] = React.useState(false)
  const [dockerComposeLocalEditLock, setDockerComposeLocalEditLock] = React.useState(false)
  const teamModeHydratedKeyRef = React.useRef<string>('')
  const gitDeliveryHydratedKeyRef = React.useRef<string>('')
  const dockerComposeHydratedKeyRef = React.useRef<string>('')
  const [pluginUiStatus, setPluginUiStatus] = React.useState<
    Partial<Record<ProjectPluginKey, { tone: 'ok' | 'error' | 'warning'; text: string }>>
  >({})
  const [pluginValidationByKey, setPluginValidationByKey] = React.useState<
    Partial<Record<ProjectPluginKey, ProjectPluginConfigValidation>>
  >({})
  const [pluginDiffByKey, setPluginDiffByKey] = React.useState<Partial<Record<ProjectPluginKey, ProjectPluginConfigDiff>>>({})
  const [globalSaveStatus, setGlobalSaveStatus] = React.useState<{ tone: 'ok' | 'error' | 'warning'; text: string } | null>(null)
  const [stagedRuleCreates, setStagedRuleCreates] = React.useState<StagedRuleCreate[]>([])
  const [stagedRulePatches, setStagedRulePatches] = React.useState<Record<string, { title: string; body: string }>>({})
  const [stagedRuleDeletes, setStagedRuleDeletes] = React.useState<string[]>([])
  const [rulesSavePending, setRulesSavePending] = React.useState(false)
  const [stagedSkillImportUrls, setStagedSkillImportUrls] = React.useState<StagedSkillImportUrl[]>([])
  const [stagedSkillImportFiles, setStagedSkillImportFiles] = React.useState<StagedSkillImportFile[]>([])
  const [stagedSkillAttachIds, setStagedSkillAttachIds] = React.useState<string[]>([])
  const [stagedSkillApplyIds, setStagedSkillApplyIds] = React.useState<string[]>([])
  const [stagedSkillDeleteIds, setStagedSkillDeleteIds] = React.useState<string[]>([])
  const ruleCreateSeqRef = React.useRef(1)
  const stagedSkillSeqRef = React.useRef(1)
  const teamModeConfigDirty = React.useMemo(
    () => String(teamModeConfigText || '').trim() !== String(teamModePersistedText || '').trim(),
    [teamModeConfigText, teamModePersistedText]
  )
  const gitDeliveryConfigDirty = React.useMemo(
    () => String(gitDeliveryConfigText || '').trim() !== String(gitDeliveryPersistedText || '').trim(),
    [gitDeliveryConfigText, gitDeliveryPersistedText]
  )
  const dockerComposeConfigDirty = React.useMemo(
    () => String(dockerComposeConfigText || '').trim() !== String(dockerComposePersistedText || '').trim(),
    [dockerComposeConfigText, dockerComposePersistedText]
  )
  const sourceProjectRules = React.useMemo(() => projectRules.data?.items ?? [], [projectRules.data?.items])
  const sourceRuleById = React.useMemo(() => {
    const out = new Map<string, ProjectRule>()
    for (const rule of sourceProjectRules) {
      const id = String(rule.id || '').trim()
      if (!id) continue
      out.set(id, rule)
    }
    return out
  }, [sourceProjectRules])
  const stagedRuleCreateById = React.useMemo(() => {
    const out = new Map<string, StagedRuleCreate>()
    for (const item of stagedRuleCreates) out.set(item.clientId, item)
    return out
  }, [stagedRuleCreates])
  const stagedRuleDeleteSet = React.useMemo(() => new Set(stagedRuleDeletes), [stagedRuleDeletes])
  const rulesListItems = React.useMemo(() => {
    const items: Array<{
      id: string
      title: string
      body: string
      updatedAt?: string | null
      isNew: boolean
      isPatched: boolean
    }> = []
    for (const rule of sourceProjectRules) {
      const id = String(rule.id || '').trim()
      if (!id || stagedRuleDeleteSet.has(id)) continue
      const patch = stagedRulePatches[id]
      items.push({
        id,
        title: patch ? patch.title : String(rule.title || ''),
        body: patch ? patch.body : String(rule.body || ''),
        updatedAt: String(rule.updated_at || ''),
        isNew: false,
        isPatched: Boolean(patch),
      })
    }
    for (const draft of stagedRuleCreates) {
      items.push({
        id: draft.clientId,
        title: draft.title,
        body: draft.body,
        updatedAt: null,
        isNew: true,
        isPatched: true,
      })
    }
    return items
  }, [sourceProjectRules, stagedRuleCreates, stagedRuleDeleteSet, stagedRulePatches])
  const rulesDirty = React.useMemo(
    () => stagedRuleCreates.length > 0 || stagedRuleDeletes.length > 0 || Object.keys(stagedRulePatches).length > 0,
    [stagedRuleCreates.length, stagedRuleDeletes.length, stagedRulePatches]
  )
  const selectedRuleListItem = React.useMemo(
    () => rulesListItems.find((item) => item.id === selectedProjectRuleId) ?? null,
    [rulesListItems, selectedProjectRuleId]
  )
  const currentRuleEditorDirty = React.useMemo(() => {
    if (!selectedProjectRuleId) return false
    if (!selectedRuleListItem) {
      return Boolean(String(projectRuleTitle || '').trim() || String(projectRuleBody || '').trim())
    }
    return (
      String(projectRuleTitle || '') !== String(selectedRuleListItem.title || '') ||
      String(projectRuleBody || '') !== String(selectedRuleListItem.body || '')
    )
  }, [projectRuleBody, projectRuleTitle, selectedProjectRuleId, selectedRuleListItem])
  const skillsDirty = React.useMemo(
    () =>
      stagedSkillImportUrls.length > 0 ||
      stagedSkillImportFiles.length > 0 ||
      stagedSkillAttachIds.length > 0 ||
      stagedSkillApplyIds.length > 0 ||
      stagedSkillDeleteIds.length > 0,
    [stagedSkillApplyIds.length, stagedSkillAttachIds.length, stagedSkillDeleteIds.length, stagedSkillImportFiles.length, stagedSkillImportUrls.length]
  )
  const teamModeStarterConfig = React.useMemo(
    () =>
      buildTeamModeStarterConfig({
        statuses: csvToList(editProjectCustomStatusesText),
      }),
    [editProjectCustomStatusesText]
  )

  React.useEffect(() => {
    setTeamModeLocalEditLock(false)
    setGitDeliveryLocalEditLock(false)
    setDockerComposeLocalEditLock(false)
    setGlobalSaveStatus(null)
    setStagedRuleCreates([])
    setStagedRulePatches({})
    setStagedRuleDeletes([])
    setRulesSavePending(false)
    setStagedSkillImportUrls([])
    setStagedSkillImportFiles([])
    setStagedSkillAttachIds([])
    setStagedSkillApplyIds([])
    setStagedSkillDeleteIds([])
    ruleCreateSeqRef.current = 1
    stagedSkillSeqRef.current = 1
  }, [project.id])

  React.useEffect(() => {
    if (!teamModePluginQuery.data) return
    const shouldUseStarter =
      teamModePluginQuery.data.exists === false ||
      Number(teamModePluginQuery.data.version || 0) < 1 ||
      isEmptyObject(teamModePluginQuery.data.config) ||
      (Number(teamModePluginQuery.data.version || 0) === 1 && isTeamModeMinimalDefaultConfig(teamModePluginQuery.data.config))
    const next = shouldUseStarter ? teamModeStarterConfig : teamModePluginQuery.data.config
    const currentProjectPrefix = `${project.id}:`
    if (
      teamModeLocalEditLock &&
      teamModeConfigDirty &&
      teamModeHydratedKeyRef.current.startsWith(currentProjectPrefix)
    ) {
      return
    }
    const hydrationKey = `${project.id}:${Number(teamModePluginQuery.data.version || 0)}:${prettyJson(next)}`
    if (teamModeHydratedKeyRef.current === hydrationKey) return
    const serialized = prettyJson(next)
    setTeamModeConfigText(serialized)
    setTeamModePersistedText(serialized)
    setTeamModeLocalEditLock(false)
    teamModeHydratedKeyRef.current = hydrationKey
  }, [project.id, teamModePluginQuery.data, teamModeStarterConfig, teamModeConfigDirty, teamModeLocalEditLock])

  React.useEffect(() => {
    if (!gitDeliveryPluginQuery.data) return
    const next = isEmptyObject(gitDeliveryPluginQuery.data.config)
      ? GIT_DELIVERY_STARTER_CONFIG
      : gitDeliveryPluginQuery.data.config
    const currentProjectPrefix = `${project.id}:`
    if (
      gitDeliveryLocalEditLock &&
      gitDeliveryConfigDirty &&
      gitDeliveryHydratedKeyRef.current.startsWith(currentProjectPrefix)
    ) {
      return
    }
    const hydrationKey = `${project.id}:${Number(gitDeliveryPluginQuery.data.version || 0)}:${prettyJson(next)}`
    if (gitDeliveryHydratedKeyRef.current === hydrationKey) return
    const serialized = prettyJson(next)
    setGitDeliveryConfigText(serialized)
    setGitDeliveryPersistedText(serialized)
    setGitDeliveryLocalEditLock(false)
    gitDeliveryHydratedKeyRef.current = hydrationKey
  }, [project.id, gitDeliveryPluginQuery.data, gitDeliveryConfigDirty, gitDeliveryLocalEditLock])

  React.useEffect(() => {
    if (!dockerComposePluginQuery.data) return
    const next = isEmptyObject(dockerComposePluginQuery.data.config)
      ? DOCKER_COMPOSE_STARTER_CONFIG
      : dockerComposePluginQuery.data.config
    const currentProjectPrefix = `${project.id}:`
    if (
      dockerComposeLocalEditLock &&
      dockerComposeConfigDirty &&
      dockerComposeHydratedKeyRef.current.startsWith(currentProjectPrefix)
    ) {
      return
    }
    const hydrationKey = `${project.id}:${Number(dockerComposePluginQuery.data.version || 0)}:${prettyJson(next)}`
    if (dockerComposeHydratedKeyRef.current === hydrationKey) return
    const serialized = prettyJson(next)
    setDockerComposeConfigText(serialized)
    setDockerComposePersistedText(serialized)
    setDockerComposeLocalEditLock(false)
    dockerComposeHydratedKeyRef.current = hydrationKey
  }, [project.id, dockerComposePluginQuery.data, dockerComposeConfigDirty, dockerComposeLocalEditLock])

  const parsePluginConfigText = React.useCallback((pluginKey: ProjectPluginKey, rawText: string): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(rawText || '{}') as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: 'error', text: 'Config must be a JSON object.' },
        }))
        return null
      }
      return parsed as Record<string, unknown>
    } catch (err) {
      setPluginUiStatus((prev) => ({
        ...prev,
        [pluginKey]: { tone: 'error', text: toErrorMessage(err, 'Invalid JSON payload.') },
      }))
      return null
    }
  }, [])

  const teamModeDraft = React.useMemo(() => parseJsonObject(teamModeConfigText), [teamModeConfigText])
  const gitDeliveryDraft = React.useMemo(() => parseJsonObject(gitDeliveryConfigText), [gitDeliveryConfigText])
  const dockerComposeDraft = React.useMemo(() => parseJsonObject(dockerComposeConfigText), [dockerComposeConfigText])

  const patchTeamModeDraft = React.useCallback(
    (updater: (draft: Record<string, unknown>) => Record<string, unknown>) => {
      if (!teamModeDraft) {
        setPluginUiStatus((prev) => ({
          ...prev,
          team_mode: { tone: 'error', text: 'Team Mode JSON is invalid.' },
        }))
        return
      }
      setTeamModeLocalEditLock(true)
      setGlobalSaveStatus(null)
      setTeamModeConfigText(prettyJson(updater({ ...teamModeDraft })))
    },
    [teamModeDraft]
  )

  const patchGitDeliveryDraft = React.useCallback(
    (updater: (draft: Record<string, unknown>) => Record<string, unknown>) => {
      if (!gitDeliveryDraft) {
        setPluginUiStatus((prev) => ({
          ...prev,
          git_delivery: { tone: 'error', text: 'Git Delivery JSON is invalid.' },
        }))
        return
      }
      setGitDeliveryLocalEditLock(true)
      setGlobalSaveStatus(null)
      setGitDeliveryConfigText(prettyJson(updater({ ...gitDeliveryDraft })))
    },
    [gitDeliveryDraft]
  )

  const patchDockerComposeDraft = React.useCallback(
    (updater: (draft: Record<string, unknown>) => Record<string, unknown>) => {
      if (!dockerComposeDraft) {
        setPluginUiStatus((prev) => ({
          ...prev,
          docker_compose: { tone: 'error', text: 'Docker Compose JSON is invalid.' },
        }))
        return
      }
      setDockerComposeLocalEditLock(true)
      setGlobalSaveStatus(null)
      setDockerComposeConfigText(prettyJson(updater({ ...dockerComposeDraft })))
    },
    [dockerComposeDraft]
  )

  const teamModeQuick = React.useMemo(() => {
    const team = (teamModeDraft?.team as Record<string, unknown> | undefined) || {}
    const workflow = (teamModeDraft?.workflow as Record<string, unknown> | undefined) || {}
    const governance = (teamModeDraft?.governance as Record<string, unknown> | undefined) || {}
    const automation = (teamModeDraft?.automation as Record<string, unknown> | undefined) || {}
    const leadRecurringRaw = automation.lead_recurring_max_minutes
    const leadRecurring = Number.isFinite(Number(leadRecurringRaw)) ? Number(leadRecurringRaw) : 5
    const transitions = Array.isArray(workflow.transitions)
      ? workflow.transitions
          .filter((item) => item && typeof item === 'object')
          .map((item) => item as Record<string, unknown>)
      : []
    const mergeRoles = Array.isArray(governance.merge_authority_roles)
      ? governance.merge_authority_roles.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    const agents = Array.isArray(team.agents)
      ? team.agents
          .filter((item) => item && typeof item === 'object')
          .map((item) => item as Record<string, unknown>)
      : []
    return {
      statusesCsv: listToCsv(workflow.statuses),
      leadRecurring,
      transitions,
      mergeRoles,
      agents,
      teamRoles: [...TEAM_MODE_ROLES],
    }
  }, [teamModeDraft])

  const gitDeliveryQuick = React.useMemo(() => {
    const requiredChecks = (gitDeliveryDraft?.required_checks as Record<string, unknown> | undefined) || {}
    const execution = (gitDeliveryDraft?.execution as Record<string, unknown> | undefined) || {}
    const deliveryChecks = Array.isArray(requiredChecks.delivery)
      ? requiredChecks.delivery.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    return {
      deliveryChecks,
      requireDevTests: Boolean(execution.require_dev_tests),
    }
  }, [gitDeliveryDraft])

  const dockerComposeQuick = React.useMemo(() => {
    const runtime = (dockerComposeDraft?.runtime_deploy_health as Record<string, unknown> | undefined) || {}
    const portRaw = runtime.port
    const port = portRaw == null || String(portRaw).trim() === '' ? '' : String(portRaw)
    return {
      runtimeRequired: Boolean(runtime.required),
      runtimeStack: String(runtime.stack || ''),
      runtimePort: port,
      runtimeHealthPath: String(runtime.health_path || ''),
      runtimeRequireHttp200: runtime.require_http_200 == null ? true : Boolean(runtime.require_http_200),
    }
  }, [dockerComposeDraft])

  const teamModePolicySummary = React.useMemo(() => {
    const compiled = (teamModePluginQuery.data?.compiled_policy as Record<string, unknown> | undefined) || {}
    const required = (compiled.required_checks as Record<string, unknown> | undefined) || {}
    const available = (compiled.available_checks as Record<string, unknown> | undefined) || {}
    const teamModeRequired = Array.isArray(required.team_mode)
      ? required.team_mode.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    const teamModeAvailable = available.team_mode && typeof available.team_mode === 'object'
      ? Object.entries(available.team_mode as Record<string, unknown>)
          .map(([id, description]) => ({
            id: String(id || '').trim(),
            description: String(description || '').trim(),
          }))
          .filter((item) => Boolean(item.id))
          .sort((a, b) => a.id.localeCompare(b.id))
      : []
    const automation = (compiled.team_mode as Record<string, unknown> | undefined) || {}
    const recurring = Number.isFinite(Number(automation.lead_recurring_max_minutes))
      ? Number(automation.lead_recurring_max_minutes)
      : null
    return {
      teamModeRequired,
      teamModeAvailable,
      recurring,
      raw: compiled,
    }
  }, [teamModePluginQuery.data?.compiled_policy])

  const gitDeliveryPolicySummary = React.useMemo(() => {
    const compiled = (gitDeliveryPluginQuery.data?.compiled_policy as Record<string, unknown> | undefined) || {}
    const required = (compiled.required_checks as Record<string, unknown> | undefined) || {}
    const available = (compiled.available_checks as Record<string, unknown> | undefined) || {}
    const deliveryRequired = Array.isArray(required.delivery)
      ? required.delivery.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    const deliveryAvailable = available.delivery && typeof available.delivery === 'object'
      ? Object.entries(available.delivery as Record<string, unknown>)
          .map(([id, description]) => ({
            id: String(id || '').trim(),
            description: String(description || '').trim(),
          }))
          .filter((item) => Boolean(item.id))
          .sort((a, b) => a.id.localeCompare(b.id))
      : []
    return {
      deliveryRequired,
      deliveryAvailable,
      raw: compiled,
    }
  }, [gitDeliveryPluginQuery.data?.compiled_policy])

  const dockerPolicySummary = React.useMemo(() => {
    const compiled = (dockerComposePluginQuery.data?.compiled_policy as Record<string, unknown> | undefined) || {}
    const runtime = (compiled.runtime_deploy_health as Record<string, unknown> | undefined) || {}
    return {
      runtimeRequired: Boolean(runtime.required),
      runtimeStack: String(runtime.stack || 'constructos-ws-default'),
      runtimePort: runtime.port == null ? 'auto' : String(runtime.port),
      runtimeHealthPath: String(runtime.health_path || '/health'),
      raw: compiled,
    }
  }, [dockerComposePluginQuery.data?.compiled_policy])

  const renderPluginDiffDetails = React.useCallback((diff?: ProjectPluginConfigDiff) => {
    if (!diff) return null
    const configChanges = Array.isArray(diff.config_changes) ? diff.config_changes : []
    const compiledChanges = Array.isArray(diff.compiled_policy_changes) ? diff.compiled_policy_changes : []
    return (
      <div className="plugin-diff-panel">
        {configChanges.length === 0 && compiledChanges.length === 0 ? (
          <div className="meta">No effective changes.</div>
        ) : null}
        {configChanges.length > 0 ? (
          <div className="plugin-diff-scope">
            <div className="meta" style={{ fontWeight: 700 }}>Config changes</div>
            <div className="plugin-diff-list">
              {configChanges.map((change, idx) => {
                const entry = (change || {}) as Record<string, unknown>
                const op = String(entry.op || 'replace')
                const path = String(entry.path || '/')
                return (
                  <div key={`diff-config-${idx}`} className="plugin-diff-item">
                    <div className="plugin-diff-item-head">
                      <code>{path}</code>
                      <span className="badge">{op}</span>
                    </div>
                    {'before' in entry ? <div className="meta">before: {prettyCompact(entry.before)}</div> : null}
                    {'after' in entry ? <div className="meta">after: {prettyCompact(entry.after)}</div> : null}
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
        {compiledChanges.length > 0 ? (
          <details className="plugin-diff-scope">
            <summary>Compiled policy changes ({compiledChanges.length})</summary>
            <div className="plugin-diff-list" style={{ marginTop: 6 }}>
              {compiledChanges.map((change, idx) => {
                const entry = (change || {}) as Record<string, unknown>
                const op = String(entry.op || 'replace')
                const path = String(entry.path || '/')
                return (
                  <div key={`diff-compiled-${idx}`} className="plugin-diff-item">
                    <div className="plugin-diff-item-head">
                      <code>{path}</code>
                      <span className="badge">{op}</span>
                    </div>
                    {'before' in entry ? <div className="meta">before: {prettyCompact(entry.before)}</div> : null}
                    {'after' in entry ? <div className="meta">after: {prettyCompact(entry.after)}</div> : null}
                  </div>
                )
              })}
            </div>
          </details>
        ) : null}
        {diff.errors?.length ? (
          <div className="meta">
            Errors: {diff.errors.map((err) => JSON.stringify(err)).join('; ')}
          </div>
        ) : null}
      </div>
    )
  }, [])

  const boardStatusesList = React.useMemo(() => csvToList(editProjectCustomStatusesText), [editProjectCustomStatusesText])
  const teamModeRequiredChecksSelected = React.useMemo(() => {
    const requiredChecks = (teamModeDraft?.required_checks as Record<string, unknown> | undefined) || {}
    const selected = Array.isArray(requiredChecks.team_mode)
      ? requiredChecks.team_mode.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    return selected.length ? selected : teamModePolicySummary.teamModeRequired
  }, [teamModeDraft, teamModePolicySummary.teamModeRequired])
  const gitDeliveryRequiredChecksSelected = React.useMemo(() => {
    return gitDeliveryQuick.deliveryChecks.length ? gitDeliveryQuick.deliveryChecks : gitDeliveryPolicySummary.deliveryRequired
  }, [gitDeliveryQuick.deliveryChecks, gitDeliveryPolicySummary.deliveryRequired])
  const teamModeRequiredCheckSet = React.useMemo(
    () => new Set(teamModeRequiredChecksSelected),
    [teamModeRequiredChecksSelected]
  )
  const teamModeCheckDescriptionById = React.useMemo(() => {
    const out: Record<string, string> = {}
    for (const option of teamModePolicySummary.teamModeAvailable) out[option.id] = option.description || ''
    return out
  }, [teamModePolicySummary.teamModeAvailable])

  const setTeamModeRequiredChecks = React.useCallback(
    (nextChecks: string[]) => {
      patchTeamModeDraft((draft) => {
        const requiredChecks = ((draft.required_checks as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        return {
          ...draft,
          required_checks: {
            ...requiredChecks,
            team_mode: nextChecks,
          },
        }
      })
    },
    [patchTeamModeDraft]
  )

  const setGitDeliveryRequireDevTests = React.useCallback(
    (nextValue: boolean) => {
      patchGitDeliveryDraft((draft) => {
        const execution = ((draft.execution as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        return {
          ...draft,
          execution: {
            ...execution,
            require_dev_tests: Boolean(nextValue),
          },
        }
      })
    },
    [patchGitDeliveryDraft]
  )

  const upsertTeamAgent = React.useCallback(
    (index: number, patch: Record<string, unknown>) => {
      patchTeamModeDraft((draft) => {
        const team = ((draft.team as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        const agents = Array.isArray(team.agents)
          ? team.agents
              .filter((item) => item && typeof item === 'object')
              .map((item) => ({ ...(item as Record<string, unknown>) }))
          : []
        const target = (agents[index] || {}) as Record<string, unknown>
        agents[index] = { ...target, ...patch }
        return {
          ...draft,
          team: {
            ...team,
            agents,
          },
        }
      })
    },
    [patchTeamModeDraft]
  )

  const addTeamAgent = React.useCallback(() => {
    patchTeamModeDraft((draft) => {
      const team = ((draft.team as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
      const agents = Array.isArray(team.agents)
        ? team.agents
            .filter((item) => item && typeof item === 'object')
            .map((item) => ({ ...(item as Record<string, unknown>) }))
        : []
      const nextIndex = agents.length + 1
      agents.push({
        id: `agent-${nextIndex}`,
        name: `Agent ${nextIndex}`,
        authority_role: 'Developer',
        executor_user_id: '',
      })
      return {
        ...draft,
        team: {
          ...team,
          agents,
        },
      }
    })
  }, [patchTeamModeDraft])

  const removeTeamAgent = React.useCallback(
    (index: number) => {
      patchTeamModeDraft((draft) => {
        const team = ((draft.team as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        const agents = Array.isArray(team.agents)
          ? team.agents
              .filter((item) => item && typeof item === 'object')
              .map((item) => ({ ...(item as Record<string, unknown>) }))
          : []
        agents.splice(index, 1)
        return {
          ...draft,
          team: {
            ...team,
            agents,
          },
        }
      })
    },
    [patchTeamModeDraft]
  )

  const upsertTransition = React.useCallback(
    (index: number, patch: Record<string, unknown>) => {
      patchTeamModeDraft((draft) => {
        const workflow = ((draft.workflow as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        const transitions = Array.isArray(workflow.transitions)
          ? workflow.transitions
              .filter((item) => item && typeof item === 'object')
              .map((item) => ({ ...(item as Record<string, unknown>) }))
          : []
        const target = (transitions[index] || {}) as Record<string, unknown>
        transitions[index] = { ...target, ...patch }
        return {
          ...draft,
          workflow: {
            ...workflow,
            transitions,
          },
        }
      })
    },
    [patchTeamModeDraft]
  )

  const removeTransition = React.useCallback(
    (index: number) => {
      patchTeamModeDraft((draft) => {
        const workflow = ((draft.workflow as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
        const transitions = Array.isArray(workflow.transitions)
          ? workflow.transitions
              .filter((item) => item && typeof item === 'object')
              .map((item) => ({ ...(item as Record<string, unknown>) }))
          : []
        transitions.splice(index, 1)
        return {
          ...draft,
          workflow: {
            ...workflow,
            transitions,
          },
        }
      })
    },
    [patchTeamModeDraft]
  )

  const addTransition = React.useCallback(() => {
    patchTeamModeDraft((draft) => {
      const workflow = ((draft.workflow as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
      const transitions = Array.isArray(workflow.transitions) ? [...workflow.transitions] : []
      const statuses = Array.isArray(workflow.statuses)
        ? workflow.statuses.map((item) => String(item || '').trim()).filter(Boolean)
        : []
      const fallback = statuses[0] || 'Dev'
      transitions.push({
        from: fallback,
        to: fallback,
        allowed_roles: ['Developer'],
      })
      return {
        ...draft,
        workflow: {
          ...workflow,
          transitions,
        },
      }
    })
  }, [patchTeamModeDraft])

  const runValidatePluginConfig = React.useCallback(
    async (pluginKey: ProjectPluginKey, rawText: string) => {
      const parsed = parsePluginConfigText(pluginKey, rawText)
      if (!parsed) return
      try {
        const response = await validatePluginConfigMutation.mutateAsync({
          pluginKey,
          draftConfig: parsed,
        })
        setPluginValidationByKey((prev) => ({ ...prev, [pluginKey]: response }))
        const warningCount = Array.isArray(response.warnings) ? response.warnings.length : 0
        const message = response.blocking
          ? `${response.errors.length} validation error(s)`
          : warningCount > 0
            ? `Valid with ${warningCount} warning(s)`
            : 'Config is valid.'
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: response.blocking ? 'error' : warningCount > 0 ? 'warning' : 'ok', text: message },
        }))
      } catch (err) {
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: 'error', text: toErrorMessage(err, 'Validation failed.') },
        }))
      }
    },
    [parsePluginConfigText, validatePluginConfigMutation]
  )

  const runDiffPluginConfig = React.useCallback(
    async (pluginKey: ProjectPluginKey, rawText: string) => {
      const parsed = parsePluginConfigText(pluginKey, rawText)
      if (!parsed) return
      try {
        const response = await diffPluginConfigMutation.mutateAsync({
          pluginKey,
          draftConfig: parsed,
        })
        setPluginDiffByKey((prev) => ({ ...prev, [pluginKey]: response }))
        const changeCount =
          Number(response.config_changes?.length || 0) + Number(response.compiled_policy_changes?.length || 0)
        const message = response.blocking
          ? `${response.errors.length} diff validation error(s)`
          : changeCount > 0
            ? `${changeCount} change(s) detected`
            : 'No changes.'
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: response.blocking ? 'error' : changeCount > 0 ? 'warning' : 'ok', text: message },
        }))
      } catch (err) {
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: 'error', text: toErrorMessage(err, 'Diff failed.') },
        }))
      }
    },
    [diffPluginConfigMutation, parsePluginConfigText]
  )

  const runSetPluginEnabled = React.useCallback(
    async (pluginKey: ProjectPluginKey, enabled: boolean) => {
      try {
        await setPluginEnabledMutation.mutateAsync({ pluginKey, enabled })
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['project-plugin-config', userId, project.id, pluginKey] }),
          queryClient.invalidateQueries({ queryKey: ['project-checks-verify', userId, project.id] }),
          queryClient.invalidateQueries({ queryKey: ['project-capabilities', userId, project.id] }),
        ])
        setPluginUiStatus((prev) => {
          const next = { ...prev }
          delete next[pluginKey]
          return next
        })
        setGlobalSaveStatus({
          tone: 'ok',
          text: `${pluginLabel(pluginKey)} ${enabled ? 'enabled' : 'disabled'}.`,
        })
      } catch (err) {
        setPluginUiStatus((prev) => ({
          ...prev,
          [pluginKey]: { tone: 'error', text: toErrorMessage(err, 'Failed to update plugin state.') },
        }))
        setGlobalSaveStatus({
          tone: 'error',
          text: `${pluginLabel(pluginKey)}: ${toErrorMessage(err, 'Failed to update plugin state.')}`,
        })
      }
    },
    [project.id, queryClient, setPluginEnabledMutation, userId]
  )

  const savePluginConfigOrThrow = React.useCallback(
    async (pluginKey: ProjectPluginKey, rawText: string, currentVersion: number | undefined, enabled: boolean | undefined) => {
      const parsed = parsePluginConfigText(pluginKey, rawText)
      if (!parsed) throw new Error('Invalid JSON payload.')
      const normalizedExpectedVersion =
        Number.isFinite(Number(currentVersion)) && Number(currentVersion) >= 1 ? Number(currentVersion) : undefined
      const saved = await applyPluginConfigMutation.mutateAsync({
        pluginKey,
        config: parsed,
        expectedVersion: normalizedExpectedVersion,
        enabled,
      })
      if (pluginKey === 'team_mode') {
        const persisted = prettyJson((saved?.config as Record<string, unknown> | undefined) || parsed)
        setTeamModeConfigText(persisted)
        setTeamModePersistedText(persisted)
        setTeamModeLocalEditLock(false)
        const hydratedVersion = Number(saved?.version || currentVersion || 0)
        teamModeHydratedKeyRef.current = `${project.id}:${hydratedVersion}:${persisted}`
      } else if (pluginKey === 'git_delivery') {
        const persisted = prettyJson((saved?.config as Record<string, unknown> | undefined) || parsed)
        setGitDeliveryConfigText(persisted)
        setGitDeliveryPersistedText(persisted)
        setGitDeliveryLocalEditLock(false)
        const hydratedVersion = Number(saved?.version || currentVersion || 0)
        gitDeliveryHydratedKeyRef.current = `${project.id}:${hydratedVersion}:${persisted}`
      } else if (pluginKey === 'docker_compose') {
        const persisted = prettyJson((saved?.config as Record<string, unknown> | undefined) || parsed)
        setDockerComposeConfigText(persisted)
        setDockerComposePersistedText(persisted)
        setDockerComposeLocalEditLock(false)
        const hydratedVersion = Number(saved?.version || currentVersion || 0)
        dockerComposeHydratedKeyRef.current = `${project.id}:${hydratedVersion}:${persisted}`
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project-plugin-config', userId, project.id, pluginKey] }),
        queryClient.invalidateQueries({ queryKey: ['project-checks-verify', userId, project.id] }),
        queryClient.invalidateQueries({ queryKey: ['project-capabilities', userId, project.id] }),
        queryClient.invalidateQueries({ queryKey: ['project-members-inline', userId, project.id] }),
        queryClient.invalidateQueries({ queryKey: ['bootstrap', userId] }),
      ])
      setPluginDiffByKey((prev) => ({ ...prev, [pluginKey]: undefined }))
      setPluginUiStatus((prev) => ({
        ...prev,
        [pluginKey]: { tone: 'ok', text: 'Configuration saved.' },
      }))
    },
    [applyPluginConfigMutation, parsePluginConfigText, project.id, queryClient, userId]
  )

  const legacyRuleMutationsPending = Boolean(
    createProjectRuleMutation.isPending || patchProjectRuleMutation.isPending || deleteProjectRuleMutation.isPending
  )
  const saveAllPending = Boolean(
    saveProjectMutation.isPending ||
    applyPluginConfigMutation.isPending ||
    rulesSavePending ||
    legacyRuleMutationsPending ||
    importProjectSkillMutation.isPending ||
    importProjectSkillFileMutation.isPending ||
    applyProjectSkillMutation.isPending ||
    attachWorkspaceSkillToProjectMutation.isPending ||
    deleteProjectSkillMutation.isPending
  )
  const unsavedSections = React.useMemo(() => {
    const sections: string[] = []
    if (projectIsDirty) sections.push('Overview')
    if (teamModeConfigDirty) sections.push('Team Mode')
    if (gitDeliveryConfigDirty) sections.push('Git Delivery')
    if (dockerComposeConfigDirty) sections.push('Docker Compose')
    if (rulesDirty || currentRuleEditorDirty) sections.push('Rules')
    if (skillsDirty) sections.push('Skills')
    return sections
  }, [projectIsDirty, teamModeConfigDirty, gitDeliveryConfigDirty, dockerComposeConfigDirty, rulesDirty, currentRuleEditorDirty, skillsDirty])
  const hasAnyUnsavedChanges = unsavedSections.length > 0
  const showProjectSaveBar = hasAnyUnsavedChanges || saveAllPending || Boolean(globalSaveStatus)

  React.useEffect(() => {
    if (typeof onUnsavedChange !== 'function') return
    onUnsavedChange(hasAnyUnsavedChanges)
  }, [hasAnyUnsavedChanges, onUnsavedChange])

  React.useEffect(() => {
    return () => {
      if (typeof onUnsavedChange === 'function') onUnsavedChange(false)
    }
  }, [onUnsavedChange])

  const runSaveAllChanges = React.useCallback(async () => {
    if (!hasAnyUnsavedChanges) return
    setGlobalSaveStatus(null)
    const failedSections: string[] = []
    const savedSections: string[] = []
    if (projectIsDirty) {
      try {
        if (typeof saveProjectMutation.mutateAsync === 'function') {
          await saveProjectMutation.mutateAsync()
        } else {
          await new Promise<void>((resolve, reject) => {
            saveProjectMutation.mutate(undefined, {
              onSuccess: () => resolve(),
              onError: (err: unknown) => reject(err),
            })
          })
        }
        savedSections.push('Overview')
      } catch {
        failedSections.push('Overview')
      }
    }
    if (teamModeConfigDirty) {
      try {
        await savePluginConfigOrThrow('team_mode', teamModeConfigText, teamModePluginQuery.data?.version, teamModePluginQuery.data?.enabled)
        savedSections.push('Team Mode')
      } catch {
        failedSections.push('Team Mode')
      }
    }
    if (gitDeliveryConfigDirty) {
      try {
        await savePluginConfigOrThrow(
          'git_delivery',
          gitDeliveryConfigText,
          gitDeliveryPluginQuery.data?.version,
          gitDeliveryPluginQuery.data?.enabled
        )
        savedSections.push('Git Delivery')
      } catch {
        failedSections.push('Git Delivery')
      }
    }
    if (dockerComposeConfigDirty) {
      try {
        await savePluginConfigOrThrow(
          'docker_compose',
          dockerComposeConfigText,
          dockerComposePluginQuery.data?.version,
          dockerComposePluginQuery.data?.enabled
        )
        savedSections.push('Docker Compose')
      } catch {
        failedSections.push('Docker Compose')
      }
    }
    if (rulesDirty || currentRuleEditorDirty) {
      try {
        setRulesSavePending(true)
        const effectiveDeletes = [...stagedRuleDeletes]
        const effectivePatches: Record<string, { title: string; body: string }> = { ...stagedRulePatches }
        const effectiveCreates = [...stagedRuleCreates]
        if (currentRuleEditorDirty) {
          const selectedId = String(selectedProjectRuleId || '').trim()
          const editorTitle = String(projectRuleTitle || '')
          const editorBody = String(projectRuleBody || '')
          if (!selectedId) {
            if (editorTitle.trim() || editorBody.trim()) {
              const clientId = `local-rule-save-${Date.now()}`
              effectiveCreates.push({ clientId, title: editorTitle, body: editorBody })
            }
          } else if (selectedId.startsWith('local-rule-')) {
            const index = effectiveCreates.findIndex((item) => item.clientId === selectedId)
            if (index >= 0) {
              effectiveCreates[index] = { clientId: selectedId, title: editorTitle, body: editorBody }
            } else if (editorTitle.trim() || editorBody.trim()) {
              effectiveCreates.push({ clientId: selectedId, title: editorTitle, body: editorBody })
            }
          } else {
            const source = sourceRuleById.get(selectedId)
            if (source) {
              const sourceTitle = String(source.title || '')
              const sourceBody = String(source.body || '')
              const deleteIndex = effectiveDeletes.indexOf(selectedId)
              if (deleteIndex >= 0) effectiveDeletes.splice(deleteIndex, 1)
              if (editorTitle === sourceTitle && editorBody === sourceBody) {
                delete effectivePatches[selectedId]
              } else {
                effectivePatches[selectedId] = { title: editorTitle, body: editorBody }
              }
            }
          }
        }
        const deleteIds = [...effectiveDeletes]
        const patchEntries = Object.entries(effectivePatches).filter(([ruleId]) => !deleteIds.includes(ruleId))
        const createEntries = [...effectiveCreates]
        for (const ruleId of deleteIds) {
          await deleteProjectRule(userId, ruleId)
        }
        for (const [ruleId, patch] of patchEntries) {
          await patchProjectRule(userId, ruleId, {
            title: String(patch.title || '').trim(),
            body: String(patch.body || ''),
          })
        }
        const createdByClientId = new Map<string, ProjectRule>()
        for (const draft of createEntries) {
          const created = await createProjectRule(userId, {
            workspace_id: workspaceId,
            project_id: project.id,
            title: String(draft.title || '').trim(),
            body: String(draft.body || ''),
          })
          createdByClientId.set(draft.clientId, created)
        }
        await queryClient.invalidateQueries({ queryKey: ['project-rules'] })
        setStagedRuleCreates([])
        setStagedRulePatches({})
        setStagedRuleDeletes([])
        const selectedId = String(selectedProjectRuleId || '').trim()
        if (selectedId && selectedId.startsWith('local-rule-')) {
          const created = createdByClientId.get(selectedId)
          if (created?.id) {
            setSelectedProjectRuleId(created.id)
            setProjectRuleTitle(String(created.title || ''))
            setProjectRuleBody(String(created.body || ''))
          } else {
            setSelectedProjectRuleId(null)
            setProjectRuleTitle('')
            setProjectRuleBody('')
          }
        } else if (selectedId && deleteIds.includes(selectedId)) {
          setSelectedProjectRuleId(null)
          setProjectRuleTitle('')
          setProjectRuleBody('')
        }
        savedSections.push('Rules')
      } catch {
        failedSections.push('Rules')
      } finally {
        setRulesSavePending(false)
      }
    }
    if (skillsDirty) {
      try {
        const runSkillMutation = async <T,>(mutation: ProjectMutation, payload: unknown): Promise<T> => {
          if (typeof mutation.mutateAsync === 'function') {
            return mutation.mutateAsync(payload) as Promise<T>
          }
          return await new Promise<T>((resolve, reject) => {
            mutation.mutate(payload, {
              onSuccess: (value: T) => resolve(value),
              onError: (err: unknown) => reject(err),
            })
          })
        }
        for (const projectSkillId of stagedSkillDeleteIds) {
          await runSkillMutation(deleteProjectSkillMutation, {
            skillId: projectSkillId,
            delete_linked_rule: true,
          })
          if (selectedProjectSkillId === projectSkillId) setSelectedProjectSkillId(null)
        }
        const importedSkillIds: string[] = []
        for (const staged of stagedSkillImportUrls) {
          const imported = await runSkillMutation<ProjectSkill>(importProjectSkillMutation, {
            source_url: staged.source_url,
            skill_key: staged.skill_key,
            mode: staged.mode,
            trust_level: staged.trust_level,
          })
          const skillId = String((imported as ProjectSkill | undefined)?.id || '').trim()
          if (skillId) importedSkillIds.push(skillId)
        }
        for (const staged of stagedSkillImportFiles) {
          const imported = await runSkillMutation<ProjectSkill>(importProjectSkillFileMutation, {
            file: staged.file,
            skill_key: staged.skill_key,
            mode: staged.mode,
            trust_level: staged.trust_level,
          })
          const skillId = String((imported as ProjectSkill | undefined)?.id || '').trim()
          if (skillId) importedSkillIds.push(skillId)
        }
        for (const workspaceSkillId of stagedSkillAttachIds) {
          const attached = await runSkillMutation<ProjectSkill>(attachWorkspaceSkillToProjectMutation, {
            skillId: workspaceSkillId,
          })
          const attachedSkillId = String((attached as ProjectSkill | undefined)?.id || '').trim()
          if (attachedSkillId) importedSkillIds.push(attachedSkillId)
        }
        const deletedSkillIdSet = new Set(stagedSkillDeleteIds)
        const applyQueue = Array.from(new Set([...stagedSkillApplyIds, ...importedSkillIds]))
          .filter((projectSkillId) => !deletedSkillIdSet.has(projectSkillId))
        for (const projectSkillId of applyQueue) {
          await runSkillMutation(applyProjectSkillMutation, { skillId: projectSkillId })
        }
        setStagedSkillImportUrls([])
        setStagedSkillImportFiles([])
        setStagedSkillAttachIds([])
        setStagedSkillApplyIds([])
        setStagedSkillDeleteIds([])
        savedSections.push('Skills')
      } catch {
        failedSections.push('Skills')
      }
    }
    if (failedSections.length > 0) {
      setGlobalSaveStatus({
        tone: savedSections.length > 0 ? 'warning' : 'error',
        text: savedSections.length > 0
          ? `Partially saved. Failed: ${failedSections.join(', ')}.`
          : `Save failed for: ${failedSections.join(', ')}.`,
      })
      return
    }
    setGlobalSaveStatus({
      tone: 'ok',
      text: savedSections.length > 0 ? `Saved: ${savedSections.join(', ')}.` : 'No changes to save.',
    })
  }, [
    dockerComposeConfigDirty,
    dockerComposeConfigText,
    dockerComposePluginQuery.data?.enabled,
    dockerComposePluginQuery.data?.version,
    gitDeliveryConfigDirty,
    gitDeliveryConfigText,
    gitDeliveryPluginQuery.data?.enabled,
    gitDeliveryPluginQuery.data?.version,
    hasAnyUnsavedChanges,
    projectIsDirty,
    savePluginConfigOrThrow,
    saveProjectMutation,
    currentRuleEditorDirty,
    project.id,
    queryClient,
    rulesDirty,
    rulesSavePending,
    skillsDirty,
    selectedProjectRuleId,
    setProjectRuleBody,
    setProjectRuleTitle,
    setSelectedProjectRuleId,
    stagedRuleCreates,
    stagedRuleDeletes,
    stagedRulePatches,
    stagedSkillApplyIds,
    stagedSkillAttachIds,
    stagedSkillDeleteIds,
    stagedSkillImportFiles,
    stagedSkillImportUrls,
    sourceRuleById,
    applyProjectSkillMutation,
    attachWorkspaceSkillToProjectMutation,
    deleteProjectSkillMutation,
    importProjectSkillFileMutation,
    importProjectSkillMutation,
    teamModeConfigDirty,
    teamModeConfigText,
    teamModePluginQuery.data?.enabled,
    teamModePluginQuery.data?.version,
    selectedProjectSkillId,
    setSelectedProjectSkillId,
    userId,
    workspaceId,
  ])

  React.useEffect(() => {
    if (!globalSaveStatus) return
    setGlobalSaveStatus(null)
  }, [
    dockerComposeConfigText,
    editProjectDescription,
    editProjectEmbeddingEnabled,
    editProjectEmbeddingModel,
    editProjectEventStormingEnabled,
    editProjectName,
    editProjectCustomStatusesText,
    gitDeliveryConfigText,
    projectRuleBody,
    projectRuleTitle,
    rulesDirty,
    skillsDirty,
    selectedProjectRuleId,
    teamModeConfigText,
  ])
  React.useEffect(() => {
    if (!globalSaveStatus || globalSaveStatus.tone !== 'ok') return
    const timer = window.setTimeout(() => {
      setGlobalSaveStatus((current) => {
        if (!current || current.tone !== 'ok') return current
        return null
      })
    }, 3000)
    return () => window.clearTimeout(timer)
  }, [globalSaveStatus])

  const skillItems = projectSkills.data?.items ?? []
  const workspaceSkillItems = workspaceSkills.data?.items ?? []
  const stagedSkillDeleteSet = React.useMemo(
    () => new Set(stagedSkillDeleteIds.map((id) => String(id || '').trim()).filter(Boolean)),
    [stagedSkillDeleteIds]
  )
  const stagedSkillPreviewItems = React.useMemo(
    () => [
      ...stagedSkillImportUrls.map((item) => ({
        id: item.clientId,
        name: item.skill_key || item.source_url || 'Imported skill',
        source: item.source_url,
        mode: item.mode || 'advisory',
        trust: item.trust_level || 'reviewed',
        kind: 'import_url' as const,
      })),
      ...stagedSkillImportFiles.map((item) => ({
        id: item.clientId,
        name: item.skill_key || item.file.name || 'Imported skill file',
        source: item.file.name,
        mode: item.mode || 'advisory',
        trust: item.trust_level || 'reviewed',
        kind: 'import_file' as const,
      })),
      ...stagedSkillAttachIds.map((workspaceSkillId) => {
        const match = workspaceSkillItems.find((entry) => String(entry.id || '').trim() === String(workspaceSkillId || '').trim())
        return {
          id: `attach:${workspaceSkillId}`,
          name: String(match?.name || match?.skill_key || workspaceSkillId),
          source: String(match?.source_locator || '(workspace catalog)'),
          mode: String(match?.mode || 'advisory'),
          trust: String(match?.trust_level || 'reviewed'),
          kind: 'attach' as const,
        }
      }),
    ],
    [stagedSkillAttachIds, stagedSkillImportFiles, stagedSkillImportUrls, workspaceSkillItems]
  )
  const hasSkillRows = stagedSkillPreviewItems.length > 0 || skillItems.length > 0
  const activeProjectRuleIds = React.useMemo(() => {
    const ids = new Set<string>()
    for (const item of projectRules.data?.items ?? []) {
      const id = String(item?.id || '').trim()
      if (id) ids.add(id)
    }
    return ids
  }, [projectRules.data?.items])
  const skillByGeneratedRuleId = React.useMemo(() => {
    const out = new Map<
      string,
      {
        skillId: string
        skillName: string
        skillKey: string
      }
    >()
    for (const skill of skillItems) {
      const generatedRuleId = String(skill.generated_rule_id || '').trim()
      if (!generatedRuleId || out.has(generatedRuleId)) continue
      out.set(generatedRuleId, {
        skillId: String(skill.id || '').trim(),
        skillName: String(skill.name || '').trim(),
        skillKey: String(skill.skill_key || '').trim(),
      })
    }
    return out
  }, [skillItems])
  const selectedProjectSkill = React.useMemo(
    () => skillItems.find((item: ProjectSkill) => item.id === selectedProjectSkillId) ?? null,
    [selectedProjectSkillId, skillItems]
  )
  React.useEffect(() => {
    if (!selectedProjectSkillId) return
    if (!stagedSkillDeleteSet.has(selectedProjectSkillId)) return
    setSelectedProjectSkillId(null)
  }, [selectedProjectSkillId, stagedSkillDeleteSet])
  const selectedRuleLinkedSkill = React.useMemo(() => {
    if (!selectedProjectRuleId) return null
    return skillByGeneratedRuleId.get(selectedProjectRuleId) ?? null
  }, [selectedProjectRuleId, skillByGeneratedRuleId])

  const openLinkedRule = React.useCallback((ruleId: string | null | undefined) => {
    const normalizedRuleId = String(ruleId || '').trim()
    if (!normalizedRuleId) return
    setProjectEditorTab('rules')
    setSelectedProjectRuleId(normalizedRuleId)
    setProjectRuleView('split')
  }, [])

  const openLinkedSkill = React.useCallback((skillId: string | null | undefined) => {
    const normalizedSkillId = String(skillId || '').trim()
    if (!normalizedSkillId) return
    setProjectEditorTab('skills')
    setSelectedProjectSkillId(normalizedSkillId)
  }, [])

  const selectRuleInEditor = React.useCallback((ruleId: string, title: string, body: string) => {
    setSelectedProjectRuleId(ruleId)
    setProjectRuleTitle(title)
    setProjectRuleBody(body)
    setProjectRuleView('split')
  }, [setProjectRuleBody, setProjectRuleTitle, setProjectRuleView, setSelectedProjectRuleId])

  const stageCurrentRuleDraft = React.useCallback(() => {
    const selectedId = String(selectedProjectRuleId || '').trim()
    const title = String(projectRuleTitle || '')
    const body = String(projectRuleBody || '')
    if (!selectedId) {
      const hasAny = Boolean(title.trim() || body.trim())
      if (!hasAny) return
      const clientId = `local-rule-${ruleCreateSeqRef.current++}`
      setStagedRuleCreates((prev) => [...prev, { clientId, title, body }])
      selectRuleInEditor(clientId, title, body)
      setGlobalSaveStatus(null)
      return
    }
    if (selectedId.startsWith('local-rule-')) {
      setStagedRuleCreates((prev) =>
        prev.map((item) => (item.clientId === selectedId ? { ...item, title, body } : item))
      )
      setGlobalSaveStatus(null)
      return
    }
    const source = sourceRuleById.get(selectedId)
    if (!source) return
    const sourceTitle = String(source.title || '')
    const sourceBody = String(source.body || '')
    setStagedRuleDeletes((prev) => prev.filter((id) => id !== selectedId))
    setStagedRulePatches((prev) => {
      const next = { ...prev }
      if (title === sourceTitle && body === sourceBody) {
        delete next[selectedId]
      } else {
        next[selectedId] = { title, body }
      }
      return next
    })
    setGlobalSaveStatus(null)
  }, [projectRuleBody, projectRuleTitle, selectRuleInEditor, selectedProjectRuleId, sourceRuleById])

  const addNewRuleDraft = React.useCallback(() => {
    const clientId = `local-rule-${ruleCreateSeqRef.current++}`
    const next = { clientId, title: '', body: '' }
    setStagedRuleCreates((prev) => [...prev, next])
    selectRuleInEditor(clientId, next.title, next.body)
    setGlobalSaveStatus(null)
  }, [selectRuleInEditor])

  const stageDeleteRule = React.useCallback((ruleId: string) => {
    const normalized = String(ruleId || '').trim()
    if (!normalized) return
    if (normalized.startsWith('local-rule-')) {
      setStagedRuleCreates((prev) => prev.filter((item) => item.clientId !== normalized))
      if (selectedProjectRuleId === normalized) {
        setSelectedProjectRuleId(null)
        setProjectRuleTitle('')
        setProjectRuleBody('')
      }
      setGlobalSaveStatus(null)
      return
    }
    setStagedRuleDeletes((prev) => (prev.includes(normalized) ? prev : [...prev, normalized]))
    setStagedRulePatches((prev) => {
      if (!(normalized in prev)) return prev
      const next = { ...prev }
      delete next[normalized]
      return next
    })
    if (selectedProjectRuleId === normalized) {
      setSelectedProjectRuleId(null)
      setProjectRuleTitle('')
      setProjectRuleBody('')
    }
    setGlobalSaveStatus(null)
  }, [selectedProjectRuleId, setProjectRuleBody, setProjectRuleTitle, setSelectedProjectRuleId])

  const lastSelectedRuleIdRef = React.useRef<string | null>(null)
  React.useEffect(() => {
    const selectedId = String(selectedProjectRuleId || '').trim() || null
    if (lastSelectedRuleIdRef.current === selectedId) return
    lastSelectedRuleIdRef.current = selectedId
    if (!selectedId || !selectedRuleListItem) return
    setProjectRuleTitle(String(selectedRuleListItem.title || ''))
    setProjectRuleBody(String(selectedRuleListItem.body || ''))
  }, [selectedProjectRuleId, selectedRuleListItem, setProjectRuleBody, setProjectRuleTitle])

  React.useEffect(() => {
    if (!currentRuleEditorDirty) return
    const timer = window.setTimeout(() => {
      stageCurrentRuleDraft()
    }, 180)
    return () => window.clearTimeout(timer)
  }, [currentRuleEditorDirty, projectRuleBody, projectRuleTitle, selectedProjectRuleId, stageCurrentRuleDraft])

  React.useEffect(() => {
    if (skillItems.length === 0) {
      setSelectedProjectSkillId(null)
      return
    }
    if (!selectedProjectSkillId) return
    if (skillItems.some((item: ProjectSkill) => item.id === selectedProjectSkillId)) return
    setSelectedProjectSkillId(null)
  }, [selectedProjectSkillId, skillItems])

  const getSkillSourceContent = React.useCallback((manifest: Record<string, unknown> | undefined): string => {
    if (!manifest || typeof manifest !== 'object') return ''
    const raw = (manifest as Record<string, unknown>).source_content
    return typeof raw === 'string' ? raw : ''
  }, [])

  React.useEffect(() => {
    if (!selectedProjectSkill) {
      setSkillEditorName('')
      setSkillEditorSummary('')
      setSkillEditorContent('')
      setSkillEditorMode('advisory')
      setSkillEditorTrustLevel('reviewed')
      return
    }
    setSkillEditorName(String(selectedProjectSkill.name || ''))
    setSkillEditorSummary(String(selectedProjectSkill.summary || ''))
    setSkillEditorContent(
      getSkillSourceContent(selectedProjectSkill?.manifest as Record<string, unknown> | undefined)
    )
    setSkillEditorMode(
      String(selectedProjectSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory'
    )
    const nextTrustLevel = String(selectedProjectSkill.trust_level || '').toLowerCase()
    if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
      setSkillEditorTrustLevel(nextTrustLevel)
    } else {
      setSkillEditorTrustLevel('reviewed')
    }
  }, [getSkillSourceContent, selectedProjectSkill])

  const skillEditorDirty = React.useMemo(() => {
    if (!selectedProjectSkill) return false
    return (
      skillEditorName.trim() !== String(selectedProjectSkill.name || '').trim() ||
      skillEditorSummary !== String(selectedProjectSkill.summary || '') ||
      skillEditorContent !== getSkillSourceContent(selectedProjectSkill?.manifest as Record<string, unknown> | undefined) ||
      skillEditorMode !==
        (String(selectedProjectSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory') ||
      skillEditorTrustLevel !==
        (String(selectedProjectSkill.trust_level || '').toLowerCase() === 'verified'
          ? 'verified'
          : String(selectedProjectSkill.trust_level || '').toLowerCase() === 'untrusted'
            ? 'untrusted'
            : 'reviewed')
    )
  }, [
    selectedProjectSkill,
    getSkillSourceContent,
    skillEditorContent,
    skillEditorMode,
    skillEditorName,
    skillEditorSummary,
    skillEditorTrustLevel,
  ])
  const projectSkillKeys = React.useMemo(
    () => new Set(
      skillItems
        .filter((item: ProjectSkill) => !stagedSkillDeleteSet.has(String(item.id || '').trim()))
        .map((item: ProjectSkill) => String(item.skill_key || '').trim())
        .filter(Boolean)
    ),
    [skillItems, stagedSkillDeleteSet]
  )
  const stagedSkillAttachSet = React.useMemo(
    () => new Set(stagedSkillAttachIds.map((id) => String(id || '').trim()).filter(Boolean)),
    [stagedSkillAttachIds]
  )
  const filteredWorkspaceSkillItems = React.useMemo(() => {
    const query = String(catalogSearchQ || '').trim().toLowerCase()
    if (!query) return workspaceSkillItems
    return workspaceSkillItems.filter((item: WorkspaceSkill) => {
      const haystack = [
        String(item.name || ''),
        String(item.skill_key || ''),
        String(item.summary || ''),
        String(item.source_locator || ''),
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [catalogSearchQ, workspaceSkillItems])
  const projectRuleCount = rulesListItems.length
  const projectSkillCount = projectSkills.data?.total ?? skillItems.length
  const projectResourceCount = projectExternalRefs.length + projectAttachmentRefs.length
  React.useEffect(() => {
    const nextTabFromUrl = resolveProjectEditorTabFromUrl()
    setProjectEditorTab(nextTabFromUrl || 'overview')
    setPluginUiStatus({})
    setPluginValidationByKey({})
    setPluginDiffByKey({})
  }, [project.id])

  React.useEffect(() => {
    if (projectEditorTab === 'checks' && !shouldShowProjectChecks) {
      setProjectEditorTab('overview')
    }
  }, [projectEditorTab, shouldShowProjectChecks])

  return (
    <div
      className="project-inline-editor"
      style={{ marginTop: 10, paddingBottom: showProjectSaveBar ? undefined : 12 }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="row wrap" style={{ marginBottom: 10 }}>
        <input
          value={editProjectName}
          onChange={(e) => setEditProjectName(e.target.value)}
          placeholder="Project name"
          style={{ flex: 1, minWidth: 0 }}
        />
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              className="action-icon"
              type="button"
              title="More project actions"
              aria-label="More project actions"
            >
              <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
              <DropdownMenu.Item
                className="task-group-menu-item task-group-menu-item-danger"
                onSelect={() => {
                  setRemoveProjectPromptOpen(true)
                }}
                disabled={deleteProjectMutation.isPending}
              >
                <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                <span>Remove project</span>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      <Tabs.Root
        className="project-editor-tabs"
        value={projectEditorTab}
        onValueChange={(next) => {
          if (
            next === 'overview' ||
            next === 'checks' ||
            next === 'team-mode' ||
            next === 'git-delivery' ||
            next === 'docker-compose' ||
            next === 'rules' ||
            next === 'skills' ||
            next === 'resources' ||
            next === 'context'
          ) {
            setProjectEditorTab(next)
          }
        }}
      >
        <Tabs.List className="project-editor-tabs-list" aria-label="Project editor sections">
          <Tabs.Trigger className="project-editor-tab-trigger" value="overview">Overview</Tabs.Trigger>
          {shouldShowProjectChecks && (
            <Tabs.Trigger className="project-editor-tab-trigger" value="checks">
              <span>Checks</span>
              <span className="project-editor-tab-count">{projectChecksQuery.data?.ok ? 'OK' : '!!'}</span>
            </Tabs.Trigger>
          )}
          <Tabs.Trigger className="project-editor-tab-trigger" value="rules">
            <span>Rules</span>
            <span className="project-editor-tab-count">{projectRuleCount}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="project-editor-tab-trigger" value="skills">
            <span>Skills</span>
            <span className="project-editor-tab-count">{projectSkillCount}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="project-editor-tab-trigger" value="resources">
            <span>Resources</span>
            <span className="project-editor-tab-count">{projectResourceCount}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="project-editor-tab-trigger" value="context">Context</Tabs.Trigger>
          <span className="project-editor-tab-divider" aria-hidden="true" />
          <Tabs.Trigger className="project-editor-tab-trigger" value="team-mode">
            <span>Team Mode</span>
            <span className="project-editor-tab-count">
              {capabilityByPluginKey.team_mode?.enabled ? 'ON' : 'OFF'}
            </span>
          </Tabs.Trigger>
          <Tabs.Trigger className="project-editor-tab-trigger" value="git-delivery">
            <span>Git Delivery</span>
            <span className="project-editor-tab-count">
              {capabilityByPluginKey.git_delivery?.enabled ? 'ON' : 'OFF'}
            </span>
          </Tabs.Trigger>
          <Tabs.Trigger className="project-editor-tab-trigger" value="docker-compose">
            <span>Docker Compose</span>
            <span className="project-editor-tab-count">
              {capabilityByPluginKey.docker_compose?.enabled ? 'ON' : 'OFF'}
            </span>
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="overview" className="project-editor-tab-content">
      <div className="md-editor-surface">
        <MarkdownModeToggle
          view={editProjectDescriptionView}
          onChange={setEditProjectDescriptionView}
          ariaLabel="Edit project description editor view"
        />
        <div className="md-editor-content">
          {editProjectDescriptionView === 'write' ? (
            <textarea
              className="md-textarea"
              ref={editProjectDescriptionRef}
              value={editProjectDescription}
              onChange={(e) => setEditProjectDescription(e.target.value)}
              placeholder="Project description (Markdown)"
              style={{ width: '100%', minHeight: 96, maxHeight: 280, resize: 'none', overflowY: 'hidden' }}
            />
          ) : editProjectDescriptionView === 'split' ? (
            <MarkdownSplitPane
              left={(
                <textarea
                  className="md-textarea"
                  ref={editProjectDescriptionRef}
                  value={editProjectDescription}
                  onChange={(e) => setEditProjectDescription(e.target.value)}
                  placeholder="Project description (Markdown)"
                  style={{ width: '100%' }}
                />
              )}
              right={<MarkdownView value={editProjectDescription} />}
              ariaLabel="Resize project description editor and preview panels"
            />
          ) : (
            <MarkdownView value={editProjectDescription} />
          )}
        </div>
      </div>
      <label className="field-control" style={{ marginTop: 10, marginBottom: 10 }}>
        <span className="field-label">Board statuses (comma-separated)</span>
        <input
          value={editProjectCustomStatusesText}
          onChange={(e) => {
            const next = e.target.value
            setEditProjectCustomStatusesText(next)
            if (!teamModeDraft) return
            patchTeamModeDraft((draft) => ({
              ...draft,
              workflow: {
                ...((draft.workflow as Record<string, unknown> | undefined) || {}),
                statuses: csvToList(next),
              },
            }))
          }}
          placeholder="To do, In progress, Blocked, Ready for QA, Done"
        />
      </label>
      <div className="field-control" style={{ marginBottom: 10 }}>
        <span className="field-label">Embeddings</span>
        <div className="row wrap" style={{ gap: 10, alignItems: 'center' }}>
          <label className="row" style={{ gap: 6, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={editProjectEmbeddingEnabled}
              onChange={(e) => {
                const next = e.target.checked
                setEditProjectEmbeddingEnabled(next)
                if (next && !String(editProjectEmbeddingModel || '').trim() && defaultModel) {
                  setEditProjectEmbeddingModel(defaultModel)
                }
                if (!next) {
                  setEditProjectChatIndexMode('OFF')
                  setEditProjectChatAttachmentIngestionMode('METADATA_ONLY')
                }
              }}
            />
            <span>Embedding enabled</span>
          </label>
          <Select.Root
            value={selectedModel || '__none__'}
            disabled={!editProjectEmbeddingEnabled || modelOptions.length === 0}
            onValueChange={(value) => {
              if (value === '__none__') return
              setEditProjectEmbeddingModel(value)
            }}
          >
            <Select.Trigger
              className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
              aria-label="Project embedding model"
            >
              <Select.Value />
              <Select.Icon asChild>
                <Icon path="M6 9l6 6 6-6" />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                <Select.Viewport className="quickadd-project-viewport">
                  {modelOptions.length === 0 && (
                    <Select.Item value="__none__" className="quickadd-project-item" disabled>
                      <Select.ItemText>No models available</Select.ItemText>
                    </Select.Item>
                  )}
                  {modelOptions.map((model) => (
                    <Select.Item key={`embedding-model-${model}`} value={model} className="quickadd-project-item">
                      <Select.ItemText>{model === defaultModel ? `${model} (default)` : model}</Select.ItemText>
                    </Select.Item>
                  ))}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <span className="badge">{embeddingStatusBadgeLabel}</span>
        </div>
        <label className="field-control" style={{ marginTop: 8 }}>
          <span className="field-label">Context pack evidence top K (optional override)</span>
          <input
            type="number"
            min={1}
            max={40}
            step={1}
            value={editProjectContextPackEvidenceTopKText}
            onChange={(e) => setEditProjectContextPackEvidenceTopKText(e.target.value)}
            placeholder={String(contextPackEvidenceTopKDefault || 10)}
            inputMode="numeric"
          />
        </label>
        <label className="field-control" style={{ marginTop: 8 }}>
          <span className="field-label">Project automation max parallel tasks</span>
          <input
            type="number"
            min={1}
            max={50}
            step={1}
            value={editProjectAutomationMaxParallelTasksText}
            onChange={(e) => setEditProjectAutomationMaxParallelTasksText(e.target.value)}
            placeholder="4"
            inputMode="numeric"
          />
        </label>
        <div className="meta" style={{ marginTop: 6 }}>
          Per-project limit for concurrent automation runs. Lead kickoff dispatch is capped by this value.
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          Leave empty to use global default ({contextPackEvidenceTopKDefault || 10}).
        </div>
        {!vectorAvailable ? (
          <div className="meta" style={{ marginTop: 6 }}>
            Vector store is currently unavailable. Project retrieval runs in graph-only mode.
          </div>
        ) : !editProjectEmbeddingEnabled ? (
          <div className="meta" style={{ marginTop: 6 }}>
            Vector store is enabled globally. Enable embeddings for this project to use graph+vector retrieval.
          </div>
        ) : null}
      </div>
      <div className="field-control" style={{ marginBottom: 10 }}>
        <div className="project-chat-policy-inline">
          <span className="field-label">Chat indexing policy</span>
          <div className="project-chat-policy-controls">
            <label className="field-control project-chat-policy-select">
              <span className="field-label">Messages</span>
              <Select.Root
                value={effectiveChatIndexMode}
                disabled={chatPolicyDisabled}
                onValueChange={(next) => {
                  if (next === 'VECTOR_ONLY' || next === 'KG_AND_VECTOR') {
                    setEditProjectChatIndexMode(next)
                    return
                  }
                  setEditProjectChatIndexMode('OFF')
                }}
              >
                <Select.Trigger
                  className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
                  aria-label="Chat message indexing mode"
                >
                  <Select.Value />
                  <Select.Icon asChild>
                    <Icon path="M6 9l6 6 6-6" />
                  </Select.Icon>
                </Select.Trigger>
                <Select.Portal>
                  <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                    <Select.Viewport className="quickadd-project-viewport">
                      <Select.Item value="OFF" className="quickadd-project-item">
                        <Select.ItemText>OFF</Select.ItemText>
                      </Select.Item>
                      <Select.Item value="VECTOR_ONLY" className="quickadd-project-item">
                        <Select.ItemText>VECTOR_ONLY</Select.ItemText>
                      </Select.Item>
                      <Select.Item value="KG_AND_VECTOR" className="quickadd-project-item">
                        <Select.ItemText>KG_AND_VECTOR</Select.ItemText>
                      </Select.Item>
                    </Select.Viewport>
                  </Select.Content>
                </Select.Portal>
              </Select.Root>
            </label>
            <label className="field-control project-chat-policy-select">
              <span className="field-label">Attachments</span>
              <Select.Root
                value={editProjectChatAttachmentIngestionMode}
                disabled={chatAttachmentDisabled}
                onValueChange={(next) => {
                  if (next === 'OFF' || next === 'FULL_TEXT') {
                    setEditProjectChatAttachmentIngestionMode(next)
                    return
                  }
                  setEditProjectChatAttachmentIngestionMode('METADATA_ONLY')
                }}
              >
                <Select.Trigger
                  className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
                  aria-label="Chat attachment ingestion mode"
                >
                  <Select.Value />
                  <Select.Icon asChild>
                    <Icon path="M6 9l6 6 6-6" />
                  </Select.Icon>
                </Select.Trigger>
                <Select.Portal>
                  <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                    <Select.Viewport className="quickadd-project-viewport">
                      <Select.Item value="METADATA_ONLY" className="quickadd-project-item">
                        <Select.ItemText>METADATA_ONLY</Select.ItemText>
                      </Select.Item>
                      <Select.Item value="OFF" className="quickadd-project-item">
                        <Select.ItemText>OFF</Select.ItemText>
                      </Select.Item>
                      <Select.Item value="FULL_TEXT" className="quickadd-project-item">
                        <Select.ItemText>FULL_TEXT</Select.ItemText>
                      </Select.Item>
                    </Select.Viewport>
                  </Select.Content>
                </Select.Portal>
              </Select.Root>
            </label>
          </div>
        </div>
        {chatPolicyDisabled ? (
          <div className="meta" style={{ marginTop: 6 }}>
            Enable embeddings to configure chat indexing. While embeddings are disabled, chat indexing mode is forced to OFF.
          </div>
        ) : effectiveChatIndexMode === 'OFF' ? (
          <div className="meta" style={{ marginTop: 6 }}>
            Chat history is excluded from Knowledge Graph and vector retrieval for this project.
          </div>
        ) : effectiveChatIndexMode === 'VECTOR_ONLY' ? (
          <div className="meta" style={{ marginTop: 6 }}>
            Chat history contributes to semantic vector search only, without graph relation extraction.
          </div>
        ) : (
          <div className="meta" style={{ marginTop: 6 }}>
            Chat history contributes to both Knowledge Graph relations and semantic vector retrieval.
          </div>
        )}
      </div>
      <div className="field-control" style={{ marginBottom: 10 }}>
        <div className="event-storming-controls">
          <div className="event-storming-controls-head">
            <div className="event-storming-controls-title">Event Storming processing</div>
            <label className="event-storming-toggle">
              <input
                type="checkbox"
                checked={effectiveEventStormingEnabled}
                onChange={(e) => setEditProjectEventStormingEnabled(Boolean(e.target.checked))}
              />
              <span>Enable processing</span>
            </label>
          </div>
          {eventStormingOverviewError ? (
            <div className="meta">Projection status unavailable.</div>
          ) : eventStormingOverviewLoading ? (
            <div className="meta">Loading projection status...</div>
          ) : eventStormingOverview ? (
            <>
              <div className="event-storming-controls-grid">
                <div className="event-storming-controls-card">
                  <div className="event-storming-controls-card-title">Processing</div>
                  <div className="event-storming-progress-line">
                    <span>Artifacts</span>
                    <strong>
                      {eventStormingProcessing.processed}/{eventStormingProcessing.artifact_total} ({eventStormingProgressPct.toFixed(1)}%)
                    </strong>
                  </div>
                  <div className="event-storming-progress-track" role="presentation" aria-hidden="true">
                    <span className="event-storming-progress-fill" style={{ width: `${eventStormingProgressPct}%` }} />
                  </div>
                  <div className="event-storming-mini-stats">
                    <span className="badge">Artifact links: {eventStormingOverview.artifact_link_count}</span>
                    {eventStormingFrameMode && (
                      <span className="badge">
                        Frame: {eventStormingFrameMode}{eventStormingFrameRevisionShort ? ` · ${eventStormingFrameRevisionShort}` : ''}
                      </span>
                    )}
                    {eventStormingFrameUpdatedAtLabel && (
                      <span className="badge">Frame updated: {eventStormingFrameUpdatedAtLabel}</span>
                    )}
                    <span className="badge">Queued: {eventStormingProcessing.queued}</span>
                    <span className="badge">Running: {eventStormingProcessing.running}</span>
                    <span className="badge">Failed: {eventStormingProcessing.failed}</span>
                  </div>
                </div>
                <div className="event-storming-controls-card">
                  <div className="event-storming-controls-card-title">Detected Components</div>
                  <div className="event-storming-component-grid">
                    {eventStormingComponentStats.map((item) => (
                      <div
                        key={`project-es-count-${item.key}`}
                        className={`event-storming-component-chip ${item.count === 0 ? 'zero' : ''}`}
                        style={{ borderColor: item.color }}
                      >
                        <span>{item.label}</span>
                        <strong>{item.count}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="meta">Loading projection status...</div>
          )}
        </div>
      </div>
        </Tabs.Content>
        {shouldShowProjectChecks && (
          <Tabs.Content value="checks" className="project-editor-tab-content">
            <div className="gates-panel">
              <div className="gates-panel-head">
                <div className="gates-panel-title-row">
                  <h3 style={{ margin: 0 }}>Delivery Verification</h3>
                  <span className={`badge ${projectChecksSnapshot?.ok ? 'status-done' : 'status-blocked'}`}>
                    {projectChecksSnapshot?.ok ? 'PASS' : 'FAIL'}
                  </span>
                </div>
                <div className="gates-panel-summary">
                  <span className="badge">Scopes: {gateConfigScopes.length}</span>
                  <span className="badge">Failed required: {gateSummary.failed}</span>
                  <span className="badge">Required checks: {gateSummary.required}</span>
                  {gateSummary.unknown > 0 ? <span className="badge">Unknown: {gateSummary.unknown}</span> : null}
                </div>
                {deliveryKickoffRequired ? (
                  <div className="notice" style={{ marginTop: 8 }}>
                    <strong>Kickoff required: Yes.</strong>{' '}
                    <span>{deliveryKickoffHint || 'Execution is not started yet. Start kickoff from chat when you are ready.'}</span>
                  </div>
                ) : null}
                {executionGateSnapshot ? (
                  <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
                    <div style={{ fontWeight: 600, marginBottom: 6 }}>Execution Gates (hard runtime)</div>
                    <div className="row wrap" style={{ gap: 6 }}>
                      <span className="badge">Tasks: {executionGateSnapshot.totals.tasks_with_gates}</span>
                      <span className="badge">Total gates: {executionGateSnapshot.totals.gates_total}</span>
                      <span className="badge">Blocking: {executionGateSnapshot.totals.blocking_total}</span>
                      {executionGateSnapshot.totals.fail > 0 ? (
                        <span className="badge status-blocked">Fail: {executionGateSnapshot.totals.fail}</span>
                      ) : null}
                      {executionGateSnapshot.totals.waiting > 0 ? (
                        <span className="badge">Waiting: {executionGateSnapshot.totals.waiting}</span>
                      ) : null}
                      {executionGateSnapshot.totals.pass > 0 ? (
                        <span className="badge status-done">Pass: {executionGateSnapshot.totals.pass}</span>
                      ) : null}
                    </div>
                    {executionGateSnapshot.tasks.length > 0 ? (
                      <div className="gates-check-list" style={{ marginTop: 8 }}>
                        {executionGateSnapshot.tasks.slice(0, 12).map((row) => (
                          <div key={`exec-gate-task-${row.task_id}`} className="gates-check-row">
                            <div className="gates-check-copy">
                              <a href={`?tab=tasks&project=${selectedProject.id}&task=${row.task_id}`}>{row.title}</a>
                              <span className="meta">
                                status={row.status || 'Unknown'}; blocking={row.blocking_total}; pass={row.pass}; fail={row.fail}; waiting={row.waiting}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="meta" style={{ marginTop: 8 }}>
                        No task-level execution gates are active right now.
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
              {projectChecksQuery.isLoading ? (
                <div className="meta">Loading check verification...</div>
              ) : projectChecksQuery.isError ? (
                <div className="notice">Check verification unavailable.</div>
              ) : projectChecksSnapshot ? (
                <>
                  {gatePolicyPayload ? (
                    <div className="gates-scope-grid" style={{ marginBottom: 10 }}>
                      <section className="gates-scope-card">
                        <div className="gates-scope-head">
                          <strong>Policy Configuration</strong>
                        </div>
                        <div className="gates-check-list">
                          {Object.entries(gatePolicyPayload)
                            .filter(([key]) => !['required_checks', 'available_checks'].includes(String(key || '').trim().toLowerCase()))
                            .map(([key, value]) => (
                              <div key={`policy-config-${key}`} className="gates-check-row">
                                <div className="gates-check-copy">
                                  <code>{String(key)}</code>
                                  <span className="meta">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</span>
                                </div>
                              </div>
                            ))}
                        </div>
                      </section>
                    </div>
                  ) : null}
                  <div className="gates-scope-grid">
                    {gateConfigScopes.map((scope) => (
                      <section key={`scope-card-${scope.scopeKey}`} className="gates-scope-card">
                        <div className="gates-scope-head">
                          <strong>{scope.scopeTitle}</strong>
                          {scope.runtimeScope ? (
                            <span className={`badge ${scope.runtimeScope.failedChecks.length === 0 ? 'status-done' : 'status-blocked'}`}>
                              {scope.runtimeScope.failedChecks.length === 0
                                ? 'Ready'
                                : `${scope.runtimeScope.failedChecks.length} failed`}
                            </span>
                          ) : (
                            <span className="badge">Not evaluated</span>
                          )}
                        </div>
                        <div className="gates-check-list">
                          {scope.requiredChecks.map((checkId) => {
                            const runtimeFailed = scope.runtimeScope?.failedChecks ?? []
                            const failed = runtimeFailed.includes(checkId)
                            const description = String(
                              scope.runtimeScope?.checkDescriptions[checkId] ||
                                scope.availableDescriptions[checkId] ||
                                ''
                            ).trim()
                            const hasRuntimeResult = Boolean(scope.runtimeScope)
                            return (
                              <div key={`${scope.scopeKey}-check-${checkId}`} className="gates-check-row">
                                <div className="gates-check-copy">
                                  <code>{checkId}</code>
                                  {description ? <span className="meta">{description}</span> : null}
                                </div>
                                {hasRuntimeResult ? (
                                  <span className={`badge ${failed ? 'status-blocked' : 'status-done'}`}>
                                    {failed ? 'FAIL' : 'PASS'}
                                  </span>
                                ) : (
                                  <span className="badge">N/A</span>
                                )}
                              </div>
                            )
                          })}
                        </div>
                        {scope.diagnosticChecks.length > 0 ? (
                          <details style={{ marginTop: 8 }}>
                            <summary>Show diagnostic checks ({scope.diagnosticChecks.length})</summary>
                            <div className="gates-check-list" style={{ marginTop: 8 }}>
                              {scope.diagnosticChecks.map((checkId) => {
                                if (!checkId) return null
                                const description = String(
                                  scope.runtimeScope?.checkDescriptions[checkId] || scope.availableDescriptions[checkId] || ''
                                ).trim()
                                const runtimeValue = scope.runtimeScope?.checks?.[checkId]
                                const hasRuntimeResult = typeof runtimeValue === 'boolean'
                                const failed = hasRuntimeResult && !Boolean(runtimeValue)
                                return (
                                  <div key={`${scope.scopeKey}-diagnostic-${checkId}`} className="gates-check-row">
                                    <div className="gates-check-copy">
                                      <code>{checkId}</code>
                                      {description ? <span className="meta">{description}</span> : null}
                                    </div>
                                    {hasRuntimeResult ? (
                                      <span className={`badge ${failed ? 'status-blocked' : 'status-done'}`}>
                                        {failed ? 'FAIL' : 'PASS'}
                                      </span>
                                    ) : (
                                      <span className="badge">N/A</span>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          </details>
                        ) : null}
                      </section>
                    ))}
                  </div>
                  <div className="gates-policy-row">
                    <span className="badge">Plugin policy source</span>
                    <code>{gatePolicySource}</code>
                  </div>
                </>
              ) : (
                <div className="notice">No verification payload.</div>
              )}
              <div className="meta" style={{ marginTop: 4 }}>
                These are project-level verification checks derived from enabled plugins (`team_mode`, `git_delivery`, `docker_compose`). Hard runner execution gates are shown per-task in the Automation tab.
              </div>
            </div>
          </Tabs.Content>
        )}
        <Tabs.Content value="team-mode" className="project-editor-tab-content">
          <div className="field-control" style={{ marginTop: 10 }}>
            <div className="row wrap" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>Team Mode Configuration</h3>
              <label className="project-plugin-enabled-row" htmlFor="team-mode-enabled-checkbox">
                <input
                  id="team-mode-enabled-checkbox"
                  type="checkbox"
                  className="project-plugin-enabled-native-checkbox"
                  checked={Boolean(teamModePluginQuery.data?.enabled)}
                  disabled={setPluginEnabledMutation.isPending}
                  onChange={(e) => void runSetPluginEnabled('team_mode', Boolean(e.target.checked))}
                />
                <span className="project-plugin-enabled-label">Enabled</span>
              </label>
            </div>
            <div className="meta" style={{ marginTop: 6 }}>
              Structured source of truth for team agents, role governance, and allowed task status transitions.
            </div>
            <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Execution gates overview</div>
              {teamModeVerificationScope?.requiredChecks?.length ? (
                <div className="gates-check-list">
                  {teamModeVerificationScope.requiredChecks.map((checkId) => {
                    const runtimeFailed = teamModeVerificationScope.runtimeScope?.failedChecks ?? []
                    const failed = runtimeFailed.includes(checkId)
                    const description = String(
                      teamModeVerificationScope.runtimeScope?.checkDescriptions?.[checkId] ||
                        teamModeVerificationScope.availableDescriptions?.[checkId] ||
                        ''
                    ).trim()
                    const hasRuntimeResult = Boolean(teamModeVerificationScope.runtimeScope)
                    return (
                      <div key={`tm-overview-check-${checkId}`} className="gates-check-row">
                        <div className="gates-check-copy">
                          <code>{checkId}</code>
                          {description ? <span className="meta">{description}</span> : null}
                        </div>
                        {hasRuntimeResult ? (
                          <span className={`badge ${failed ? 'status-blocked' : 'status-done'}`}>{failed ? 'FAIL' : 'PASS'}</span>
                        ) : (
                          <span className="badge">N/A</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="meta">No Team Mode execution checks are currently active.</div>
              )}
              <div className="meta" style={{ marginTop: 6 }}>
                Task-level deterministic execution gates are visible in each task Automation tab.
              </div>
              <div className="meta" style={{ marginTop: 6 }}>{deliveryKickoffSummaryLine}</div>
              {deliveryRuntimeDeployHealth ? (
                <div className="row wrap" style={{ marginTop: 6, gap: 8 }}>
                  <span className="badge">Stack: {deliveryRuntimeDeployHealth.stack}</span>
                  <span className="badge">
                    Port: {deliveryRuntimeDeployHealth.port == null ? 'not configured' : deliveryRuntimeDeployHealth.port}
                  </span>
                  <span className="badge">Path: {deliveryRuntimeDeployHealth.healthPath}</span>
                  <span className={`badge ${deliveryRuntimeDeployHealth.ok ? 'status-done' : 'status-blocked'}`}>
                    Runtime health: {deliveryRuntimeDeployHealth.ok ? 'PASS' : 'FAIL'}
                  </span>
                  {deliveryRuntimeDeployHealth.endpoint ? <code>{deliveryRuntimeDeployHealth.endpoint}</code> : null}
                </div>
              ) : null}
              {workflowCommunicationSnapshot ? (
                <details style={{ marginTop: 8 }}>
                  <summary>
                    Workflow communication ({workflowCommunicationSnapshot.events_total})
                  </summary>
                  <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                    {Object.entries(workflowCommunicationSnapshot.totals).map(([source, count]) => (
                      <span key={`tm-workflow-source-${source}`} className="badge">
                        {source}: {count}
                      </span>
                    ))}
                  </div>
                  {workflowCommunicationSnapshot.events.length > 0 ? (
                    <div className="gates-check-list" style={{ marginTop: 8 }}>
                      {workflowCommunicationSnapshot.events.slice(0, 6).map((event) => (
                        <div key={`tm-workflow-event-${event.task_id}-${event.requested_at || event.source}`} className="gates-check-row">
                          <div className="gates-check-copy">
                            <a className="status-chip" href={`?tab=tasks&project=${selectedProject.id}&task=${event.task_id}`}>
                              {event.title}
                            </a>
                            <span className="meta">
                              Delivery: <code>{event.delivery || 'requested'}</code> | Source: <code>{event.source}</code> | Status: <code>{event.status || 'n/a'}</code>
                              {event.reason ? <> | Reason: {event.reason}</> : null}
                              {event.source_task_id ? <> | From task: <code>{event.source_task_id}</code></> : null}
                              {event.dispatch_decision?.priority ? <> | Priority: <code>{String(event.dispatch_decision.priority)}</code></> : null}
                              {event.dispatch_decision?.slot ? <> | Slot: <code>{String(event.dispatch_decision.slot)}</code></> : null}
                              {event.correlation_id ? <> | Correlation: <code>{event.correlation_id}</code></> : null}
                            </span>
                          </div>
                          {event.requested_at ? (
                            <span className="badge">
                              {new Date(event.requested_at).toLocaleString()}
                            </span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="meta" style={{ marginTop: 8 }}>
                      No workflow communication events recorded yet.
                    </div>
                  )}
                </details>
              ) : null}
              <div className="row wrap" style={{ marginTop: 6, gap: 8 }}>
                <a className="status-chip" href={`?tab=tasks&project=${selectedProject.id}`}>Open project tasks</a>
                <a
                  className="status-chip"
                  href={`?tab=projects&project=${selectedProject.id}&project_editor_tab=checks`}
                  onClick={(event) => {
                    event.preventDefault()
                    setProjectEditorTab('checks')
                  }}
                >
                  Open Delivery Verification
                </a>
              </div>
            </div>
            <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Quick configuration</div>
              <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span className="meta">Team agents</span>
                <InfoTip text="Virtual agent slots. Multiple agents can use the same executor user (for example one codex-bot user)." />
              </div>
              <div className="plugin-config-grid">
                {teamModeQuick.agents.map((agent, idx) => {
                  const agentId = String(agent.id || '').trim()
                  const agentName = String(agent.name || '').trim()
                  const selectedRole = TEAM_MODE_ROLES.includes(String(agent.authority_role || '').trim() as TeamModeRole)
                    ? (String(agent.authority_role || '').trim() as TeamModeRole)
                    : 'Developer'
                  const selectedExecutor = String(agent.executor_user_id || '').trim() || '__auto__'
                  return (
                    <div key={`team-agent-${agentId || idx}`} className="row wrap plugin-config-row plugin-member-row">
                      <input
                        className="plugin-compact-select"
                        value={agentName}
                        onChange={(e) => upsertTeamAgent(idx, { name: e.target.value })}
                        placeholder="Agent name"
                        style={{ minWidth: 180 }}
                      />
                      <input
                        className="plugin-compact-select"
                        value={agentId}
                        onChange={(e) => upsertTeamAgent(idx, { id: e.target.value })}
                        placeholder="Agent id"
                        style={{ minWidth: 150 }}
                      />
                      <Select.Root
                        value={selectedRole}
                        onValueChange={(value) =>
                          upsertTeamAgent(idx, { authority_role: String(value || '').trim() })
                        }
                      >
                        <Select.Trigger
                          className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger plugin-compact-select"
                          aria-label={`Authority role for ${agentName || `agent ${idx + 1}`}`}
                        >
                          <Select.Value />
                          <Select.Icon asChild>
                            <Icon path="M6 9l6 6 6-6" />
                          </Select.Icon>
                        </Select.Trigger>
                        <Select.Portal>
                          <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                            <Select.Viewport className="quickadd-project-viewport">
                              {TEAM_MODE_ROLES.map((role) => (
                                <Select.Item key={`team-agent-role-${idx}-${role}`} value={role} className="quickadd-project-item">
                                  <Select.ItemText>{roleLabel(role)}</Select.ItemText>
                                </Select.Item>
                              ))}
                            </Select.Viewport>
                          </Select.Content>
                        </Select.Portal>
                      </Select.Root>
                      <Select.Root
                        value={selectedExecutor}
                        onValueChange={(value) =>
                          upsertTeamAgent(idx, {
                            executor_user_id: value === '__auto__' ? '' : String(value || '').trim(),
                          })
                        }
                      >
                        <Select.Trigger
                          className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger plugin-compact-select"
                          aria-label={`Executor user for ${agentName || `agent ${idx + 1}`}`}
                        >
                          <Select.Value placeholder="Executor user" />
                          <Select.Icon asChild>
                            <Icon path="M6 9l6 6 6-6" />
                          </Select.Icon>
                        </Select.Trigger>
                        <Select.Portal>
                          <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                            <Select.Viewport className="quickadd-project-viewport">
                              <Select.Item value="__auto__" className="quickadd-project-item">
                                <Select.ItemText>Auto (task assignee)</Select.ItemText>
                              </Select.Item>
                              {(projectMembersQuery.data?.items || []).map((member) => {
                                const memberUserId = String(member.user_id || '').trim()
                                if (!memberUserId) return null
                                const label = String(member.user?.full_name || '').trim() || memberUserId
                                return (
                                  <Select.Item key={`team-agent-executor-${idx}-${memberUserId}`} value={memberUserId} className="quickadd-project-item">
                                    <Select.ItemText>{label}</Select.ItemText>
                                  </Select.Item>
                                )
                              })}
                            </Select.Viewport>
                          </Select.Content>
                        </Select.Portal>
                      </Select.Root>
                      <button className="status-chip" type="button" onClick={() => removeTeamAgent(idx)}>
                        Remove
                      </button>
                    </div>
                  )
                })}
                <div>
                  <button className="status-chip" type="button" onClick={() => addTeamAgent()}>
                    Add agent
                  </button>
                </div>
                {teamModeQuick.agents.length === 0 ? (
                  <div className="meta">
                    No team agents configured. Recommended default: 2 Developers, 1 QA, 1 Lead.
                  </div>
                ) : null}
              </div>
              <div className="meta" style={{ marginTop: 6 }}>
                Project members define access. Team agents define workflow identities.
              </div>
              <div className="row wrap plugin-compact-inline">
                <label className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <span className="meta">Lead recurring (minutes)</span>
                  <InfoTip text="Maximum interval for recurring lead oversight checks." />
                  <input
                    type="number"
                    min={1}
                    max={120}
                    value={String(teamModeQuick.leadRecurring)}
                    onChange={(e) => {
                      const next = Math.max(1, Number(e.target.value || 1))
                      patchTeamModeDraft((draft) => ({
                        ...draft,
                        automation: {
                          ...((draft.automation as Record<string, unknown> | undefined) || {}),
                          lead_recurring_max_minutes: next,
                        },
                      }))
                    }}
                    style={{ width: 100 }}
                  />
                </label>
              </div>
              <div className="plugin-config-subsection">
                <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span className="meta">Required checks</span>
                  <InfoTip text="Choose Team Mode checks that must pass before delivery is considered valid." />
                  <Select.Root
                    key={`tm-check-picker-${teamModeRequiredChecksSelected.join('|')}`}
                    onValueChange={(value) => {
                      const next = String(value || '').trim()
                      if (!next || next === '__none__') return
                      setTeamModeRequiredChecks(Array.from(new Set([...teamModeRequiredChecksSelected, next])))
                    }}
                  >
                    <Select.Trigger
                      className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger plugin-compact-select"
                      aria-label="Add Team Mode required check"
                    >
                      <Select.Value placeholder="Add check" />
                      <Select.Icon asChild>
                        <Icon path="M6 9l6 6 6-6" />
                      </Select.Icon>
                    </Select.Trigger>
                    <Select.Portal>
                      <Select.Content className="quickadd-project-content plugin-check-select-content" position="popper" sideOffset={6}>
                        <Select.Viewport className="quickadd-project-viewport">
                          {teamModePolicySummary.teamModeAvailable.filter((option) => !teamModeRequiredCheckSet.has(option.id)).length === 0 ? (
                            <div className="codex-chat-session-empty">All checks are already selected</div>
                          ) : (
                            teamModePolicySummary.teamModeAvailable
                              .filter((option) => !teamModeRequiredCheckSet.has(option.id))
                              .map((option) => (
                                <Select.Item key={`tm-required-check-${option.id}`} value={option.id} className="codex-chat-session-item plugin-check-select-item">
                                  <Select.ItemText>
                                    <span className="codex-chat-session-item-title">{option.id}</span>
                                  </Select.ItemText>
                                  <span className="codex-chat-session-item-meta">{option.description || 'No description'}</span>
                                  <Select.ItemIndicator className="codex-chat-session-item-indicator">
                                    <Icon path="M5 13l4 4L19 7" />
                                  </Select.ItemIndicator>
                                </Select.Item>
                              ))
                          )}
                        </Select.Viewport>
                      </Select.Content>
                    </Select.Portal>
                  </Select.Root>
                </div>
                <div className="row wrap plugin-required-checks-row">
                  {teamModeRequiredChecksSelected.map((checkId) => (
                    <Tooltip.Provider key={`tm-required-chip-${checkId}`} delayDuration={120}>
                      <Tooltip.Root>
                        <Tooltip.Trigger asChild>
                          <button
                            type="button"
                            className="status-chip active"
                            onClick={() => setTeamModeRequiredChecks(teamModeRequiredChecksSelected.filter((item) => item !== checkId))}
                          >
                            <code>{checkId}</code>
                            <Icon path="M6 6l12 12M18 6 6 18" />
                          </button>
                        </Tooltip.Trigger>
                        <Tooltip.Portal>
                          <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
                            {teamModeCheckDescriptionById[checkId] || checkId}
                            <Tooltip.Arrow className="header-tooltip-arrow" />
                          </Tooltip.Content>
                        </Tooltip.Portal>
                      </Tooltip.Root>
                    </Tooltip.Provider>
                  ))}
                </div>
              </div>
              <label className="plugin-wide-field">
                <span className="meta">Workflow statuses (comma-separated)</span>
                <InfoTip text="Statuses available to transitions in Team Mode orchestration." />
                <input
                  className="plugin-wide-input"
                  value={teamModeQuick.statusesCsv}
                  onChange={(e) => {
                    const next = e.target.value
                    setEditProjectCustomStatusesText(next)
                    patchTeamModeDraft((draft) => ({
                      ...draft,
                      workflow: {
                        ...((draft.workflow as Record<string, unknown> | undefined) || {}),
                        statuses: csvToList(next),
                      },
                    }))
                  }}
                  placeholder="To do, Dev, QA, Lead, Done, Blocked"
                />
              </label>
              <div className="plugin-config-subsection">
                <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span className="meta">Allowed transitions</span>
                  <InfoTip text="Define allowed status flows and which roles can execute each transition." />
                </div>
                <div className="plugin-config-grid">
                  {teamModeQuick.transitions.map((transition, idx) => {
                    const transitionFrom = String(transition.from || '').trim()
                    const transitionTo = String(transition.to || '').trim()
                    const transitionStatusOptions = Array.from(
                      new Set(
                        [
                          ...csvToList(teamModeQuick.statusesCsv),
                          transitionFrom,
                          transitionTo,
                        ].filter(Boolean)
                      )
                    )
                    const allowedRoles = Array.isArray(transition.allowed_roles)
                      ? transition.allowed_roles.map((item) => String(item || '').trim()).filter(Boolean)
                      : []
                    return (
                      <div key={`team-transition-${idx}`} className="row wrap plugin-config-row plugin-transition-row">
                        <Select.Root value={transitionFrom || '__none__'} onValueChange={(value) => upsertTransition(idx, { from: value === '__none__' ? '' : value })}>
                          <Select.Trigger
                            className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger plugin-compact-select"
                            aria-label={`Transition ${idx + 1} from`}
                          >
                            <Select.Value placeholder="From" />
                            <Select.Icon asChild>
                              <Icon path="M6 9l6 6 6-6" />
                            </Select.Icon>
                          </Select.Trigger>
                          <Select.Portal>
                            <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                              <Select.Viewport className="quickadd-project-viewport">
                                <Select.Item value="__none__" className="quickadd-project-item">
                                  <Select.ItemText>No status</Select.ItemText>
                                </Select.Item>
                                {transitionStatusOptions.map((status) => (
                                  <Select.Item key={`transition-from-${idx}-${status}`} value={status} className="quickadd-project-item">
                                    <Select.ItemText>{status}</Select.ItemText>
                                  </Select.Item>
                                ))}
                              </Select.Viewport>
                            </Select.Content>
                          </Select.Portal>
                        </Select.Root>
                        <span className="meta">to</span>
                        <Select.Root value={transitionTo || '__none__'} onValueChange={(value) => upsertTransition(idx, { to: value === '__none__' ? '' : value })}>
                          <Select.Trigger
                            className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger plugin-compact-select"
                            aria-label={`Transition ${idx + 1} to`}
                          >
                            <Select.Value placeholder="To" />
                            <Select.Icon asChild>
                              <Icon path="M6 9l6 6 6-6" />
                            </Select.Icon>
                          </Select.Trigger>
                          <Select.Portal>
                            <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                              <Select.Viewport className="quickadd-project-viewport">
                                <Select.Item value="__none__" className="quickadd-project-item">
                                  <Select.ItemText>No status</Select.ItemText>
                                </Select.Item>
                                {transitionStatusOptions.map((status) => (
                                  <Select.Item key={`transition-to-${idx}-${status}`} value={status} className="quickadd-project-item">
                                    <Select.ItemText>{status}</Select.ItemText>
                                  </Select.Item>
                                ))}
                              </Select.Viewport>
                            </Select.Content>
                          </Select.Portal>
                        </Select.Root>
                        <input
                          className="plugin-transition-roles-input"
                          value={allowedRoles.join(', ')}
                          onChange={(e) =>
                            upsertTransition(idx, {
                              allowed_roles: csvToList(e.target.value),
                            })
                          }
                          placeholder="Allowed roles (comma-separated)"
                        />
                        <button className="status-chip" type="button" onClick={() => removeTransition(idx)}>
                          Remove
                        </button>
                      </div>
                    )
                  })}
                  <div>
                    <button className="status-chip" type="button" onClick={() => addTransition()}>
                      Add transition
                    </button>
                  </div>
                </div>
              </div>
              <div className="plugin-config-subsection">
                <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span className="meta">Merge authority roles</span>
                  <InfoTip text="Roles allowed to finalize merge/close operations for Team Mode." />
                </div>
                <div className="row wrap" style={{ gap: 10 }}>
                  {teamModeQuick.teamRoles.map((role) => {
                    const checked = teamModeQuick.mergeRoles.includes(role)
                    return (
                      <label key={`merge-role-${role}`} className="row" style={{ gap: 6, alignItems: 'center' }}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) =>
                            patchTeamModeDraft((draft) => {
                              const governance = ((draft.governance as Record<string, unknown> | undefined) || {}) as Record<string, unknown>
                              const mergeRoles = Array.isArray(governance.merge_authority_roles)
                                ? governance.merge_authority_roles.map((item) => String(item || '').trim()).filter(Boolean)
                                : []
                              const next = e.target.checked
                                ? Array.from(new Set([...mergeRoles, role]))
                                : mergeRoles.filter((candidate) => candidate !== role)
                              return {
                                ...draft,
                                governance: {
                                  ...governance,
                                  merge_authority_roles: next,
                                },
                              }
                            })
                          }
                        />
                        <span className="meta">{roleLabel(role)}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
            </div>
            <details style={{ marginTop: 8 }} className="plugin-policy-details">
              <summary>Advanced JSON config</summary>
              <textarea
                className="md-textarea plugin-json-textarea"
                value={teamModeConfigText}
                onChange={(e) => {
                  setTeamModeLocalEditLock(true)
                  setTeamModeConfigText(e.target.value)
                }}
                placeholder="{}"
                style={{ width: '100%', minHeight: 260, marginTop: 8 }}
              />
            </details>
              <div className="plugin-actions-row">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button className="status-chip" type="button">
                    Config actions
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="task-group-menu-content" sideOffset={6} align="start">
                    <DropdownMenu.Item
                      className="task-group-menu-item"
                      onSelect={() => {
                        setTeamModeLocalEditLock(true)
                        setTeamModeConfigText(prettyJson(teamModeStarterConfig))
                      }}
                    >
                      Use starter config
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runValidatePluginConfig('team_mode', teamModeConfigText)}>
                      Validate
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runDiffPluginConfig('team_mode', teamModeConfigText)}>
                      Preview diff
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              <div className="plugin-actions-meta">
                <span className="badge">v{teamModePluginQuery.data?.version ?? 0}</span>
                <span className="badge">
                  Capability: {projectCapabilitiesQuery.data?.capabilities?.team_mode ? 'enabled' : 'disabled'}
                </span>
              </div>
            </div>
            {pluginUiStatus.team_mode ? (
              <div className="meta" style={{ marginTop: 8 }}>
                [{pluginUiStatus.team_mode.tone.toUpperCase()}] {pluginUiStatus.team_mode.text}
              </div>
            ) : null}
            {pluginValidationByKey.team_mode?.errors?.length ? (
              <div className="notice" style={{ marginTop: 8 }}>
                {pluginValidationByKey.team_mode.errors.map((err, idx) => (
                  <div key={`team-mode-validation-error-${idx}`}>{JSON.stringify(err)}</div>
                ))}
              </div>
            ) : null}
            {pluginDiffByKey.team_mode ? <div className="notice" style={{ marginTop: 8 }}>{renderPluginDiffDetails(pluginDiffByKey.team_mode)}</div> : null}
            <details style={{ marginTop: 8 }}>
              <summary>Effective policy overview</summary>
              <div className="plugin-policy-summary">
                <div className="row wrap plugin-policy-badges">
                  <span className="badge">Required checks: {teamModePolicySummary.teamModeRequired.length}</span>
                  <span className="badge">Available checks: {teamModePolicySummary.teamModeAvailable.length}</span>
                  <span className="badge">
                    Lead recurring: {teamModePolicySummary.recurring == null ? 'default' : `${teamModePolicySummary.recurring} min`}
                  </span>
                </div>
                <div className="meta">
                  Required: {teamModePolicySummary.teamModeRequired.join(', ') || '(none)'}
                </div>
                <details className="plugin-policy-raw">
                  <summary>Show raw compiled policy JSON</summary>
                  <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{prettyJson(teamModePolicySummary.raw)}</pre>
                </details>
              </div>
            </details>
          </div>
        </Tabs.Content>
        <Tabs.Content value="git-delivery" className="project-editor-tab-content">
          <div className="field-control" style={{ marginTop: 10 }}>
            <div className="row wrap" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>Git Delivery Configuration</h3>
              <label className="project-plugin-enabled-row" htmlFor="git-delivery-enabled-checkbox">
                <input
                  id="git-delivery-enabled-checkbox"
                  type="checkbox"
                  className="project-plugin-enabled-native-checkbox"
                  checked={Boolean(gitDeliveryPluginQuery.data?.enabled)}
                  disabled={setPluginEnabledMutation.isPending}
                  onChange={(e) => void runSetPluginEnabled('git_delivery', Boolean(e.target.checked))}
                />
                <span className="project-plugin-enabled-label">Enabled</span>
              </label>
            </div>
            <div className="meta" style={{ marginTop: 6 }}>
              Required delivery checks for a strict core delivery contract.
            </div>
            {gitDeliveryPluginQuery.data?.enabled ? (
              <div className="project-docker-runtime-bar" style={{ marginTop: 10 }}>
                <div className="project-docker-runtime-copy">
                  <div className="meta">Project repository</div>
                  <div className="project-docker-runtime-summary">
                    {gitRepositorySummaryQuery.isLoading
                      ? 'Checking repository state...'
                      : gitRepositorySummaryQuery.data?.available
                        ? `Current branch ${String(gitRepositorySummaryQuery.data.current_branch || gitRepositorySummaryQuery.data.default_branch || 'HEAD')} across ${Number(gitRepositorySummaryQuery.data.branch_count || 0)} branch${Number(gitRepositorySummaryQuery.data.branch_count || 0) === 1 ? '' : 'es'}`
                        : 'Project repository is not available yet'}
                  </div>
                </div>
                <div className="project-docker-runtime-actions">
                  {gitRepositorySummaryQuery.data?.default_branch ? (
                    <span className="badge">Default: {gitRepositorySummaryQuery.data.default_branch}</span>
                  ) : null}
                  {gitRepositorySummaryQuery.data?.available ? (
                    <button
                      type="button"
                      className="status-chip"
                      onClick={() => {
                        setGitRepositoryDialogTarget(null)
                        setGitRepositoryDialogOpen(true)
                      }}
                    >
                      View repository
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
            <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Execution gates overview</div>
              {deliveryVerificationScope?.requiredChecks?.length ? (
                <div className="gates-check-list">
                  {deliveryVerificationScope.requiredChecks.map((checkId) => {
                    const runtimeFailed = deliveryVerificationScope.runtimeScope?.failedChecks ?? []
                    const failed = runtimeFailed.includes(checkId)
                    const description = String(
                      deliveryVerificationScope.runtimeScope?.checkDescriptions?.[checkId] ||
                        deliveryVerificationScope.availableDescriptions?.[checkId] ||
                        ''
                    ).trim()
                    const hasRuntimeResult = Boolean(deliveryVerificationScope.runtimeScope)
                    return (
                      <div key={`gd-overview-check-${checkId}`} className="gates-check-row">
                        <div className="gates-check-copy">
                          <code>{checkId}</code>
                          {description ? <span className="meta">{description}</span> : null}
                        </div>
                        {hasRuntimeResult ? (
                          <span className={`badge ${failed ? 'status-blocked' : 'status-done'}`}>{failed ? 'FAIL' : 'PASS'}</span>
                        ) : (
                          <span className="badge">N/A</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="meta">No Git Delivery execution checks are currently active.</div>
              )}
              <div className="meta" style={{ marginTop: 6 }}>
                Detailed task-level deterministic gates are shown in each task Automation tab.
              </div>
              <div className="meta" style={{ marginTop: 6 }}>{deliveryKickoffSummaryLine}</div>
              {deliveryRuntimeDeployHealth ? (
                <div className="row wrap" style={{ marginTop: 6, gap: 8 }}>
                  <span className="badge">Stack: {deliveryRuntimeDeployHealth.stack}</span>
                  <span className="badge">
                    Port: {deliveryRuntimeDeployHealth.port == null ? 'not configured' : deliveryRuntimeDeployHealth.port}
                  </span>
                  <span className="badge">Path: {deliveryRuntimeDeployHealth.healthPath}</span>
                  <span className={`badge ${deliveryRuntimeDeployHealth.ok ? 'status-done' : 'status-blocked'}`}>
                    Runtime health: {deliveryRuntimeDeployHealth.ok ? 'PASS' : 'FAIL'}
                  </span>
                  {deliveryRuntimeDeployHealth.endpoint ? <code>{deliveryRuntimeDeployHealth.endpoint}</code> : null}
                </div>
              ) : null}
              {workflowCommunicationSnapshot ? (
                <details style={{ marginTop: 8 }}>
                  <summary>
                    Workflow communication ({workflowCommunicationSnapshot.events_total})
                  </summary>
                  <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                    {Object.entries(workflowCommunicationSnapshot.totals).map(([source, count]) => (
                      <span key={`gd-workflow-source-${source}`} className="badge">
                        {source}: {count}
                      </span>
                    ))}
                  </div>
                  {workflowCommunicationSnapshot.events.length > 0 ? (
                    <div className="gates-check-list" style={{ marginTop: 8 }}>
                      {workflowCommunicationSnapshot.events.slice(0, 6).map((event) => (
                        <div key={`gd-workflow-event-${event.task_id}-${event.requested_at || event.source}`} className="gates-check-row">
                          <div className="gates-check-copy">
                            <a className="status-chip" href={`?tab=tasks&project=${selectedProject.id}&task=${event.task_id}`}>
                              {event.title}
                            </a>
                            <span className="meta">
                              Delivery: <code>{event.delivery || 'requested'}</code> | Source: <code>{event.source}</code> | Status: <code>{event.status || 'n/a'}</code>
                              {event.reason ? <> | Reason: {event.reason}</> : null}
                              {event.source_task_id ? <> | From task: <code>{event.source_task_id}</code></> : null}
                              {event.dispatch_decision?.priority ? <> | Priority: <code>{String(event.dispatch_decision.priority)}</code></> : null}
                              {event.dispatch_decision?.slot ? <> | Slot: <code>{String(event.dispatch_decision.slot)}</code></> : null}
                              {event.correlation_id ? <> | Correlation: <code>{event.correlation_id}</code></> : null}
                            </span>
                          </div>
                          {event.requested_at ? (
                            <span className="badge">
                              {new Date(event.requested_at).toLocaleString()}
                            </span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="meta" style={{ marginTop: 8 }}>
                      No workflow communication events recorded yet.
                    </div>
                  )}
                </details>
              ) : null}
              <div className="row wrap" style={{ marginTop: 6, gap: 8 }}>
                <a className="status-chip" href={`?tab=tasks&project=${selectedProject.id}`}>Open project tasks</a>
                <a
                  className="status-chip"
                  href={`?tab=projects&project=${selectedProject.id}&project_editor_tab=checks`}
                  onClick={(event) => {
                    event.preventDefault()
                    setProjectEditorTab('checks')
                  }}
                >
                  Open Delivery Verification
                </a>
              </div>
            </div>
            <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Quick configuration</div>
              <div className="meta">
                Core defaults: {gitDeliveryRequiredChecksSelected.join(', ') || '(none)'}
              </div>
              <div className="meta" style={{ marginTop: 6 }}>
                Additional delivery checks are applied automatically by runtime verification when Team Mode, deploy evidence, or runtime health requirements are in play.
              </div>
              <div className="row wrap" style={{ marginTop: 8, alignItems: 'center', gap: 8 }}>
                <label className="project-plugin-enabled-row" htmlFor="git-delivery-require-dev-tests-checkbox">
                  <input
                    id="git-delivery-require-dev-tests-checkbox"
                    type="checkbox"
                    className="project-plugin-enabled-native-checkbox"
                    checked={Boolean(gitDeliveryQuick.requireDevTests)}
                    onChange={(e) => setGitDeliveryRequireDevTests(Boolean(e.target.checked))}
                  />
                  <span className="project-plugin-enabled-label">Require developer tests</span>
                </label>
                <InfoTip text="When enabled, Developer automation must report tests_run=true and tests_passed=true." />
              </div>
            </div>
            <details style={{ marginTop: 8 }} className="plugin-policy-details">
              <summary>Advanced JSON config</summary>
              <textarea
                className="md-textarea plugin-json-textarea"
                value={gitDeliveryConfigText}
                onChange={(e) => {
                  setGitDeliveryLocalEditLock(true)
                  setGlobalSaveStatus(null)
                  setGitDeliveryConfigText(e.target.value)
                }}
                placeholder="{}"
                style={{ width: '100%', minHeight: 260, marginTop: 8 }}
              />
            </details>
            <div className="plugin-actions-row">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button className="status-chip" type="button">
                    Config actions
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="task-group-menu-content" sideOffset={6} align="start">
                    <DropdownMenu.Item
                      className="task-group-menu-item"
                      onSelect={() => {
                        setGitDeliveryLocalEditLock(true)
                        setGlobalSaveStatus(null)
                        setGitDeliveryConfigText(prettyJson(GIT_DELIVERY_STARTER_CONFIG))
                      }}
                    >
                      Use starter config
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runValidatePluginConfig('git_delivery', gitDeliveryConfigText)}>
                      Validate
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runDiffPluginConfig('git_delivery', gitDeliveryConfigText)}>
                      Preview diff
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              <div className="plugin-actions-meta">
                <span className="badge">v{gitDeliveryPluginQuery.data?.version ?? 0}</span>
                <span className="badge">
                  Capability: {projectCapabilitiesQuery.data?.capabilities?.git_delivery ? 'enabled' : 'disabled'}
                </span>
              </div>
            </div>
            {pluginUiStatus.git_delivery ? (
              <div className="meta" style={{ marginTop: 8 }}>
                [{pluginUiStatus.git_delivery.tone.toUpperCase()}] {pluginUiStatus.git_delivery.text}
              </div>
            ) : null}
            {pluginValidationByKey.git_delivery?.errors?.length ? (
              <div className="notice" style={{ marginTop: 8 }}>
                {pluginValidationByKey.git_delivery.errors.map((err, idx) => (
                  <div key={`git-delivery-validation-error-${idx}`}>{JSON.stringify(err)}</div>
                ))}
              </div>
            ) : null}
            {pluginDiffByKey.git_delivery ? <div className="notice" style={{ marginTop: 8 }}>{renderPluginDiffDetails(pluginDiffByKey.git_delivery)}</div> : null}
            <details style={{ marginTop: 8 }}>
              <summary>Effective policy overview</summary>
              <div className="plugin-policy-summary">
                <div className="row wrap plugin-policy-badges">
                  <span className="badge">Required checks: {gitDeliveryPolicySummary.deliveryRequired.length}</span>
                  <span className="badge">Available checks: {gitDeliveryPolicySummary.deliveryAvailable.length}</span>
                </div>
                <div className="meta">
                  Required: {gitDeliveryPolicySummary.deliveryRequired.join(', ') || '(none)'}
                </div>
                <details className="plugin-policy-raw">
                  <summary>Show raw compiled policy JSON</summary>
                  <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{prettyJson(gitDeliveryPolicySummary.raw)}</pre>
                </details>
              </div>
            </details>
          </div>
        </Tabs.Content>
        <Tabs.Content value="docker-compose" className="project-editor-tab-content">
          <div className="field-control" style={{ marginTop: 10 }}>
            <div className="row wrap" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>Docker Compose Configuration</h3>
              <label className="project-plugin-enabled-row" htmlFor="docker-compose-enabled-checkbox">
                <input
                  id="docker-compose-enabled-checkbox"
                  type="checkbox"
                  className="project-plugin-enabled-native-checkbox"
                  checked={Boolean(dockerComposePluginQuery.data?.enabled)}
                  disabled={setPluginEnabledMutation.isPending}
                  onChange={(e) => void runSetPluginEnabled('docker_compose', Boolean(e.target.checked))}
                />
                <span className="project-plugin-enabled-label">Enabled</span>
              </label>
            </div>
            <div className="meta" style={{ marginTop: 6 }}>
              Compose execution defaults plus runtime deploy-health target used by delivery verification.
            </div>
            {dockerComposePluginQuery.data?.enabled ? (
              <div className="project-docker-runtime-bar" style={{ marginTop: 10 }}>
                <div className="project-docker-runtime-copy">
                  <div className="meta">Managed runtime</div>
                  <div className="project-docker-runtime-summary">
                    {dockerComposeRuntimeQuery.isLoading
                      ? 'Checking runtime state...'
                      : dockerComposeRuntimeQuery.data?.has_runtime
                        ? `Stack ${String(dockerComposeRuntimeQuery.data?.stack || 'unknown')} is deployed`
                        : 'No managed runtime is currently deployed'}
                  </div>
                </div>
                <div className="project-docker-runtime-actions">
                  {dockerComposeRuntimeQuery.data?.health ? (
                    <span className="badge">
                      {Boolean((dockerComposeRuntimeQuery.data.health as Record<string, unknown>).ok) ? 'Healthy' : 'Not healthy'}
                    </span>
                  ) : null}
                  {dockerComposeRuntimeQuery.data?.has_runtime ? (
                    <button
                      type="button"
                      className="status-chip"
                      onClick={() => setDockerRuntimeDialogOpen(true)}
                    >
                      View runtime
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
            <div className="notice plugin-config-shell" style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Quick configuration</div>
              <div className="plugin-config-subsection">
                <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span className="meta">Runtime health policy</span>
                  <InfoTip text="Controls whether runtime health becomes a required delivery proof and how strict the probe should be." />
                </div>
                <div className="plugin-docker-toggle-grid">
                  <label className="plugin-docker-toggle-item" htmlFor="docker-runtime-required">
                    <input
                      id="docker-runtime-required"
                      type="checkbox"
                      className="project-plugin-enabled-native-checkbox"
                      checked={dockerComposeQuick.runtimeRequired}
                      onChange={(e) =>
                        patchDockerComposeDraft((draft) => ({
                          ...draft,
                          runtime_deploy_health: {
                            ...((draft.runtime_deploy_health as Record<string, unknown> | undefined) || {}),
                            required: Boolean(e.target.checked),
                          },
                        }))
                      }
                    />
                    <span className="meta">Runtime deploy health required</span>
                  </label>
                  <label className="plugin-docker-toggle-item" htmlFor="docker-runtime-http200">
                    <input
                      id="docker-runtime-http200"
                      type="checkbox"
                      className="project-plugin-enabled-native-checkbox"
                      checked={dockerComposeQuick.runtimeRequireHttp200}
                      onChange={(e) =>
                        patchDockerComposeDraft((draft) => ({
                          ...draft,
                          runtime_deploy_health: {
                            ...((draft.runtime_deploy_health as Record<string, unknown> | undefined) || {}),
                            require_http_200: Boolean(e.target.checked),
                          },
                        }))
                      }
                    />
                    <span className="meta">Require HTTP 200 response</span>
                  </label>
                </div>
              </div>
              <div className="plugin-config-subsection">
                <div className="row wrap" style={{ alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span className="meta">Runtime target</span>
                  <InfoTip text="Set stack and endpoint that delivery verification probes when runtime health is enabled." />
                </div>
                <div className="plugin-docker-input-grid">
                  <label className="plugin-docker-field plugin-docker-field-stack">
                    <span className="meta">Runtime stack</span>
                    <input
                      value={dockerComposeQuick.runtimeStack}
                      onChange={(e) =>
                        patchDockerComposeDraft((draft) => ({
                          ...draft,
                          runtime_deploy_health: {
                            ...((draft.runtime_deploy_health as Record<string, unknown> | undefined) || {}),
                            stack: e.target.value,
                          },
                        }))
                      }
                    />
                  </label>
                  <label className="plugin-docker-field plugin-docker-field-port">
                    <span className="meta">Port</span>
                    <input
                      value={dockerComposeQuick.runtimePort}
                      onChange={(e) =>
                        patchDockerComposeDraft((draft) => ({
                          ...draft,
                          runtime_deploy_health: {
                            ...((draft.runtime_deploy_health as Record<string, unknown> | undefined) || {}),
                            port: String(e.target.value || '').trim() === '' ? null : Number(e.target.value),
                          },
                        }))
                      }
                      placeholder="6768"
                    />
                  </label>
                  <label className="plugin-docker-field">
                    <span className="meta">Health path</span>
                    <input
                      value={dockerComposeQuick.runtimeHealthPath}
                      onChange={(e) =>
                        patchDockerComposeDraft((draft) => ({
                          ...draft,
                          runtime_deploy_health: {
                            ...((draft.runtime_deploy_health as Record<string, unknown> | undefined) || {}),
                            health_path: e.target.value,
                          },
                        }))
                      }
                      placeholder="/health"
                    />
                  </label>
                </div>
              </div>
            </div>
            <details style={{ marginTop: 8 }} className="plugin-policy-details">
              <summary>Advanced JSON config</summary>
              <textarea
                className="md-textarea plugin-json-textarea"
                value={dockerComposeConfigText}
                onChange={(e) => {
                  setDockerComposeLocalEditLock(true)
                  setGlobalSaveStatus(null)
                  setDockerComposeConfigText(e.target.value)
                }}
                placeholder="{}"
                style={{ width: '100%', minHeight: 260, marginTop: 8 }}
              />
            </details>
            <div className="plugin-actions-row">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button className="status-chip" type="button">
                    Config actions
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="task-group-menu-content" sideOffset={6} align="start">
                    <DropdownMenu.Item
                      className="task-group-menu-item"
                      onSelect={() => {
                        setDockerComposeLocalEditLock(true)
                        setGlobalSaveStatus(null)
                        setDockerComposeConfigText(prettyJson(DOCKER_COMPOSE_STARTER_CONFIG))
                      }}
                    >
                      Use starter config
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runValidatePluginConfig('docker_compose', dockerComposeConfigText)}>
                      Validate
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="task-group-menu-item" onSelect={() => void runDiffPluginConfig('docker_compose', dockerComposeConfigText)}>
                      Preview diff
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              <div className="plugin-actions-meta">
                <span className="badge">v{dockerComposePluginQuery.data?.version ?? 0}</span>
                <span className="badge">
                  Capability: {projectCapabilitiesQuery.data?.capabilities?.docker_compose ? 'enabled' : 'disabled'}
                </span>
              </div>
            </div>
            {pluginUiStatus.docker_compose ? (
              <div className="meta" style={{ marginTop: 8 }}>
                [{pluginUiStatus.docker_compose.tone.toUpperCase()}] {pluginUiStatus.docker_compose.text}
              </div>
            ) : null}
            {pluginValidationByKey.docker_compose?.errors?.length ? (
              <div className="notice" style={{ marginTop: 8 }}>
                {pluginValidationByKey.docker_compose.errors.map((err, idx) => (
                  <div key={`docker-compose-validation-error-${idx}`}>{JSON.stringify(err)}</div>
                ))}
              </div>
            ) : null}
            {pluginDiffByKey.docker_compose ? <div className="notice" style={{ marginTop: 8 }}>{renderPluginDiffDetails(pluginDiffByKey.docker_compose)}</div> : null}
            <details style={{ marginTop: 8 }}>
              <summary>Effective policy overview</summary>
              <div className="plugin-policy-summary">
                <div className="row wrap plugin-policy-badges">
                  <span className="badge">{dockerPolicySummary.runtimeRequired ? 'Runtime check required' : 'Runtime check optional'}</span>
                  <span className="badge">Stack: {dockerPolicySummary.runtimeStack}</span>
                  <span className="badge">Endpoint: gateway:{dockerPolicySummary.runtimePort}{dockerPolicySummary.runtimeHealthPath}</span>
                </div>
                <details className="plugin-policy-raw">
                  <summary>Show raw compiled policy JSON</summary>
                  <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{prettyJson(dockerPolicySummary.raw)}</pre>
                </details>
              </div>
            </details>
          </div>
        </Tabs.Content>
        <Tabs.Content value="rules" className="project-editor-tab-content">
      <div
        className="rules-studio"
        style={{ marginTop: 10, marginBottom: 14 }}
      >
        <div className="row wrap rules-head-row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Project Rules ({rulesListItems.length})</h3>
        </div>
        <div className="rules-layout">
          <div className="rules-list">
            {rulesListItems.length === 0 ? (
              <div className="notice">No rules yet for this project.</div>
            ) : (
              rulesListItems.map((rule) => {
                const isSelected = selectedProjectRuleId === rule.id
                const linkedSkill = skillByGeneratedRuleId.get(rule.id)
                return (
                  <div
                    key={rule.id}
                    className={[
                      'task-item',
                      'rule-item',
                      isSelected ? 'selected' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => selectRuleInEditor(rule.id, rule.title, rule.body)}
                    role="button"
                  >
                    <div className="task-main">
                      <div className="task-title rule-item-head">
                        <div className="row rule-item-head-main">
                          {linkedSkill && <span className="rule-kind-chip">[SKILL]</span>}
                          <strong>{rule.title || 'Untitled rule'}</strong>
                        </div>
                        {isSelected && <span className="badge">Editing</span>}
                      </div>
                      <div className="meta">{(rule.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                      {rule.isNew ? <div className="meta">Staged: new rule</div> : null}
                      {rule.isPatched && !rule.isNew ? <div className="meta">Staged: edited</div> : null}
                      {linkedSkill ? (
                        <div className="meta">
                          Linked skill: {linkedSkill.skillName || linkedSkill.skillKey || linkedSkill.skillId}
                        </div>
                      ) : null}
                      {!rule.isNew ? <div className="meta">Updated: {toUserDateTime(rule.updatedAt, userTimezone)}</div> : null}
                    </div>
                    <div className="task-item-actions">
                      <DropdownMenu.Root>
                        <DropdownMenu.Trigger asChild>
                          <button
                            className="action-icon task-item-actions-trigger"
                            type="button"
                            onClick={(e) => e.stopPropagation()}
                            title="Rule actions"
                            aria-label="Rule actions"
                          >
                            <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                          </button>
                        </DropdownMenu.Trigger>
                        <DropdownMenu.Portal>
                          <DropdownMenu.Content
                            className="task-group-menu-content note-row-menu-content"
                            sideOffset={8}
                            align="end"
                          >
                            <DropdownMenu.Item
                              className="task-group-menu-item task-group-menu-item-danger"
                              disabled={saveAllPending}
                              onSelect={() => {
                                setDeleteRulePrompt({
                                  id: rule.id,
                                  title: rule.title || 'Untitled rule',
                                })
                              }}
                            >
                              <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                              <span>Delete rule</span>
                            </DropdownMenu.Item>
                          </DropdownMenu.Content>
                        </DropdownMenu.Portal>
                      </DropdownMenu.Root>
                    </div>
                  </div>
                )
              })
            )}
            <div
              className="task-item rule-item add-new-rule-item"
              role="button"
              onClick={() => {
                addNewRuleDraft()
              }}
            >
              <div className="task-main">
                <div className="task-title">
                  <strong>Add new rule</strong>
                </div>
              </div>
            </div>
          </div>
          <div className="rules-editor">
            {selectedRuleLinkedSkill ? (
              <div className="row wrap" style={{ marginBottom: 8, gap: 8, alignItems: 'center' }}>
                <span className="rule-kind-chip">[SKILL]</span>
                <span className="meta">
                  Source skill: {selectedRuleLinkedSkill.skillName || selectedRuleLinkedSkill.skillKey || selectedRuleLinkedSkill.skillId}
                </span>
                {selectedRuleLinkedSkill.skillId ? (
                  <button
                    className="status-chip"
                    type="button"
                    onClick={() => openLinkedSkill(selectedRuleLinkedSkill.skillId)}
                  >
                    Open linked skill
                  </button>
                ) : null}
              </div>
            ) : null}
            <div className="row rule-title-row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
              <input
                className="rule-title-input"
                value={projectRuleTitle}
                onChange={(e) => setProjectRuleTitle(e.target.value)}
                placeholder="Rule title"
              />
            </div>
            <div className="md-editor-surface">
              <MarkdownModeToggle
                view={projectRuleView}
                onChange={setProjectRuleView}
                ariaLabel="Project rule editor view"
              />
              <div className="md-editor-content">
                {projectRuleView === 'write' ? (
                  <textarea
                    className="md-textarea"
                    value={projectRuleBody}
                    onChange={(e) => setProjectRuleBody(e.target.value)}
                    placeholder="Rule details (Markdown)"
                    style={{ width: '100%' }}
                  />
                ) : projectRuleView === 'split' ? (
                  <MarkdownSplitPane
                    left={(
                      <textarea
                        className="md-textarea"
                        value={projectRuleBody}
                        onChange={(e) => setProjectRuleBody(e.target.value)}
                        placeholder="Rule details (Markdown)"
                        style={{ width: '100%' }}
                      />
                    )}
                    right={<MarkdownView value={projectRuleBody} onPrettifyJson={setProjectRuleBody} />}
                    ariaLabel="Resize project rule editor and preview panels"
                  />
                ) : (
                  <MarkdownView value={projectRuleBody} onPrettifyJson={setProjectRuleBody} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
        </Tabs.Content>
        <Tabs.Content value="skills" className="project-editor-tab-content">
      <div
        className="rules-studio"
        style={{ marginTop: 10, marginBottom: 14 }}
      >
        <div className="row wrap rules-head-row" style={{ justifyContent: 'space-between', marginBottom: 8, gap: 8 }}>
          <h3 style={{ margin: 0 }}>Project Skills ({projectSkills.data?.total ?? 0})</h3>
          <div className="meta">
            Project-local skills. Changes are staged locally and saved only via Save all changes.
            {(stagedSkillImportUrls.length + stagedSkillImportFiles.length + stagedSkillAttachIds.length + stagedSkillApplyIds.length + stagedSkillDeleteIds.length) > 0
              ? ` Staged ops: ${stagedSkillImportUrls.length + stagedSkillImportFiles.length + stagedSkillAttachIds.length + stagedSkillApplyIds.length + stagedSkillDeleteIds.length}.`
              : ''}
          </div>
        </div>
        <div className="row wrap" style={{ gap: 8, marginBottom: 10, alignItems: 'center' }}>
          <input
            value={skillImportSourceUrl}
            onChange={(e) => setSkillImportSourceUrl(e.target.value)}
            placeholder="Skill source URL (https://...)"
            style={{ flex: 2, minWidth: 260 }}
          />
          <input
            value={skillImportKey}
            onChange={(e) => setSkillImportKey(e.target.value)}
            placeholder="Key (e.g. testing_skill)"
            style={{ width: 170, minWidth: 140 }}
          />
          <Select.Root
            value={skillImportMode}
            onValueChange={(value) => setSkillImportMode(value === 'enforced' ? 'enforced' : 'advisory')}
          >
            <Select.Trigger
              className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
              aria-label="Import mode"
              style={{ width: 140, minWidth: 120 }}
            >
              <Select.Value />
              <Select.Icon asChild>
                <Icon path="M6 9l6 6 6-6" />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                <Select.Viewport className="quickadd-project-viewport">
                  <Select.Item value="advisory" className="quickadd-project-item">
                    <Select.ItemText>advisory</Select.ItemText>
                    <Select.ItemIndicator className="quickadd-project-item-indicator">
                      <Icon path="M5 12l4 4L19 7" />
                    </Select.ItemIndicator>
                  </Select.Item>
                  <Select.Item value="enforced" className="quickadd-project-item">
                    <Select.ItemText>enforced</Select.ItemText>
                    <Select.ItemIndicator className="quickadd-project-item-indicator">
                      <Icon path="M5 12l4 4L19 7" />
                    </Select.ItemIndicator>
                  </Select.Item>
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <Select.Root
            value={skillImportTrustLevel}
            onValueChange={(value) => {
              if (value === 'verified' || value === 'untrusted') {
                setSkillImportTrustLevel(value)
                return
              }
              setSkillImportTrustLevel('reviewed')
            }}
          >
            <Select.Trigger
              className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
              aria-label="Trust level"
              style={{ width: 150, minWidth: 120 }}
            >
              <Select.Value />
              <Select.Icon asChild>
                <Icon path="M6 9l6 6 6-6" />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                <Select.Viewport className="quickadd-project-viewport">
                  <Select.Item value="reviewed" className="quickadd-project-item">
                    <Select.ItemText>reviewed</Select.ItemText>
                    <Select.ItemIndicator className="quickadd-project-item-indicator">
                      <Icon path="M5 12l4 4L19 7" />
                    </Select.ItemIndicator>
                  </Select.Item>
                  <Select.Item value="verified" className="quickadd-project-item">
                    <Select.ItemText>verified</Select.ItemText>
                    <Select.ItemIndicator className="quickadd-project-item-indicator">
                      <Icon path="M5 12l4 4L19 7" />
                    </Select.ItemIndicator>
                  </Select.Item>
                  <Select.Item value="untrusted" className="quickadd-project-item">
                    <Select.ItemText>untrusted</Select.ItemText>
                    <Select.ItemIndicator className="quickadd-project-item-indicator">
                      <Icon path="M5 12l4 4L19 7" />
                    </Select.ItemIndicator>
                  </Select.Item>
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <div className="row" style={{ gap: 6, marginLeft: 'auto', flexShrink: 0 }}>
            <button
              className="action-icon primary"
              type="button"
              disabled={importProjectSkillMutation.isPending || importProjectSkillFileMutation.isPending}
              title="Stage project skill import from URL"
              aria-label="Stage project skill import from URL"
              onClick={() => {
                const sourceUrl = String(skillImportSourceUrl || '').trim()
                if (!sourceUrl) {
                  setUiError('Skill source URL is required')
                  return
                }
                setStagedSkillImportUrls((prev) => [
                  ...prev,
                  {
                    clientId: `staged-skill-url-${stagedSkillSeqRef.current++}`,
                    source_url: sourceUrl,
                    skill_key: String(skillImportKey || '').trim() || undefined,
                    mode: skillImportMode,
                    trust_level: skillImportTrustLevel,
                  },
                ])
                setGlobalSaveStatus(null)
                setUiError(null)
                setSkillImportSourceUrl('')
                setSkillImportKey('')
                setSkillImportMode('advisory')
                setSkillImportTrustLevel('reviewed')
              }}
            >
              {importProjectSkillMutation.isPending ? <Icon path="M12 5v14M5 12h14" /> : <Icon path="M12 5v10m0 0l4-4m-4 4l-4-4M4 21h16" />}
            </button>
            <button
              className="action-icon"
              type="button"
              disabled={importProjectSkillMutation.isPending || importProjectSkillFileMutation.isPending}
              title="Import project skill from file"
              aria-label="Import project skill from file"
              onClick={() => skillImportFileInputRef.current?.click()}
            >
              <Icon
                path={
                  importProjectSkillFileMutation.isPending
                    ? 'M12 5v14M5 12h14'
                    : 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6'
                }
              />
            </button>
            <button
              className="action-icon"
              type="button"
              disabled={attachWorkspaceSkillToProjectMutation.isPending}
              title="Browse workspace catalog"
              aria-label="Browse workspace catalog"
              onClick={() => {
                setCatalogSearchQ('')
                setShowCatalogPicker(true)
              }}
            >
              <Icon path="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2H3V6zm0 4h20v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8zm7 3h7m-7 3h5" />
            </button>
          </div>
          <input
            ref={skillImportFileInputRef}
            type="file"
            accept=".md,.markdown,.txt,.json,text/plain,text/markdown,application/json"
            style={{ display: 'none' }}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.currentTarget.value = ''
              if (!file) return
              setStagedSkillImportFiles((prev) => [
                ...prev,
                {
                  clientId: `staged-skill-file-${stagedSkillSeqRef.current++}`,
                  file,
                  skill_key: String(skillImportKey || '').trim() || undefined,
                  mode: skillImportMode,
                  trust_level: skillImportTrustLevel,
                },
              ])
              setGlobalSaveStatus(null)
              setUiError(null)
              setSkillImportSourceUrl('')
              setSkillImportKey('')
              setSkillImportMode('advisory')
              setSkillImportTrustLevel('reviewed')
            }}
          />
        </div>
        <div className="rules-list">
          {projectSkills.isLoading ? (
            <div className="notice">Loading project skills...</div>
          ) : !hasSkillRows ? (
            <div className="notice">No skills imported yet for this project.</div>
          ) : (
            <>
              {stagedSkillPreviewItems.map((staged) => (
                <div key={staged.id} className="task-item rule-item">
                  <div className="task-main">
                    <div className="task-title rule-item-head">
                      <strong>{staged.name}</strong>
                      <div className="row rule-item-head-actions">
                        <span className="rule-kind-chip">STAGED</span>
                      </div>
                    </div>
                    <div className="meta">
                      kind: {staged.kind === 'attach' ? 'attach workspace skill' : staged.kind === 'import_file' ? 'import from file' : 'import from URL'}
                      {' | '}mode: {staged.mode} | trust: {staged.trust}
                    </div>
                    <div className="meta">source: {staged.source || '(none)'}</div>
                  </div>
                </div>
              ))}
            {skillItems.map((skill: ProjectSkill) => {
              const skillId = String(skill.id || '').trim()
              const isStagedDelete = stagedSkillDeleteSet.has(skillId)
              const isExpanded = selectedProjectSkillId === skill.id
              const selectedThisSkill = isExpanded && selectedProjectSkill?.id === skill.id
              const linkedRuleId = String(skill.generated_rule_id || '').trim()
              const hasLinkedRule = Boolean(linkedRuleId) && activeProjectRuleIds.has(linkedRuleId)
              return (
                <div
                  key={skill.id}
                  className={`task-item rule-item ${isExpanded ? 'selected' : ''}`}
                  onClick={() => setSelectedProjectSkillId((current) => (current === skill.id ? null : skill.id))}
                  role="button"
                  aria-expanded={isExpanded}
                >
                  <div className="task-main">
                    <div className="task-title rule-item-head">
                        <strong>{skill.name || skill.skill_key || 'Untitled skill'}</strong>
                        <div className="row rule-item-head-actions">
                          {isStagedDelete ? <span className="rule-kind-chip">STAGED DELETE</span> : null}
                          <DropdownMenu.Root>
                            <DropdownMenu.Trigger asChild>
                              <button
                                className="action-icon task-item-actions-trigger"
                                type="button"
                                onClick={(e) => e.stopPropagation()}
                                title="Skill actions"
                                aria-label="Skill actions"
                              >
                                <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                              </button>
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Portal>
                              <DropdownMenu.Content
                                className="task-group-menu-content note-row-menu-content"
                                sideOffset={8}
                                align="end"
                              >
                                <DropdownMenu.Item
                                  className="task-group-menu-item"
                                  disabled={applyProjectSkillMutation.isPending}
                                  onSelect={() => {
                                    const normalizedSkillId = String(skill.id || '').trim()
                                    if (!normalizedSkillId) return
                                    setStagedSkillApplyIds((prev) =>
                                      prev.includes(normalizedSkillId) ? prev : [...prev, normalizedSkillId]
                                    )
                                    setGlobalSaveStatus(null)
                                  }}
                                >
                                  <Icon path="M5 13l4 4L19 7M5 7h8" />
                                  <span>{hasLinkedRule ? 'Reapply to context' : 'Apply to context'}</span>
                                </DropdownMenu.Item>
                                <DropdownMenu.Separator className="task-group-menu-separator" />
                                {isStagedDelete ? (
                                  <DropdownMenu.Item
                                    className="task-group-menu-item"
                                    onSelect={() => {
                                      setStagedSkillDeleteIds((prev) => prev.filter((id) => id !== skillId))
                                      setGlobalSaveStatus(null)
                                    }}
                                  >
                                    <Icon path="M5 12l4 4L19 7" />
                                    <span>Undo staged delete</span>
                                  </DropdownMenu.Item>
                                ) : (
                                  <DropdownMenu.Item
                                    className="task-group-menu-item task-group-menu-item-danger"
                                    disabled={saveAllPending}
                                    onSelect={() => {
                                      setDeleteSkillPrompt({
                                        id: skill.id,
                                        name: skill.name || skill.skill_key || 'Untitled skill',
                                      })
                                    }}
                                  >
                                    <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                                    <span>Delete skill</span>
                                  </DropdownMenu.Item>
                                )}
                              </DropdownMenu.Content>
                            </DropdownMenu.Portal>
                          </DropdownMenu.Root>
                        </div>
                      </div>
                    <div className="meta">
                      key: {skill.skill_key || '-'} | mode: {skill.mode || '-'} | trust: {skill.trust_level || '-'}
                    </div>
                    <div className="meta">
                      {(skill.summary || '').replace(/\s+/g, ' ').slice(0, 140) || '(no summary)'}
                    </div>
                    <div className="meta">source: {skill.source_locator || '(none)'}</div>
                    {selectedThisSkill ? (
                      <div className="note-accordion" onClick={(e) => e.stopPropagation()} role="region" aria-label="Skill editor">
                        <div className="row rule-title-row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                          <input
                            className="rule-title-input"
                            value={skillEditorName}
                            onChange={(e) => setSkillEditorName(e.target.value)}
                            placeholder="Skill name"
                          />
                          <button
                            className="action-icon primary"
                            type="button"
                            disabled={!skillEditorName.trim() || !skillEditorDirty || patchProjectSkillMutation.isPending}
                            onClick={() => {
                              patchProjectSkillMutation.mutate({
                                skillId: skill.id,
                                patch: {
                                  name: skillEditorName.trim(),
                                  summary: skillEditorSummary,
                                  content: skillEditorContent,
                                  mode: skillEditorMode,
                                  trust_level: skillEditorTrustLevel,
                                  sync_project_rule: true,
                                },
                              })
                            }}
                            title="Save skill changes"
                            aria-label="Save skill changes"
                          >
                            <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                          </button>
                        </div>
                        <div className="row wrap" style={{ gap: 8, marginBottom: 8 }}>
                          <label className="field-control" style={{ minWidth: 150, marginBottom: 0 }}>
                            <span className="field-label">Mode</span>
                            <Select.Root
                              value={skillEditorMode}
                              onValueChange={(value) => setSkillEditorMode(value === 'enforced' ? 'enforced' : 'advisory')}
                            >
                              <Select.Trigger
                                className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
                                aria-label="Skill mode"
                              >
                                <Select.Value />
                                <Select.Icon asChild>
                                  <Icon path="M6 9l6 6 6-6" />
                                </Select.Icon>
                              </Select.Trigger>
                              <Select.Portal>
                                <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                                  <Select.Viewport className="quickadd-project-viewport">
                                    <Select.Item value="advisory" className="quickadd-project-item">
                                      <Select.ItemText>advisory</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 12l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                    <Select.Item value="enforced" className="quickadd-project-item">
                                      <Select.ItemText>enforced</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 12l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                  </Select.Viewport>
                                </Select.Content>
                              </Select.Portal>
                            </Select.Root>
                          </label>
                          <label className="field-control" style={{ minWidth: 170, marginBottom: 0 }}>
                            <span className="field-label">Trust level</span>
                            <Select.Root
                              value={skillEditorTrustLevel}
                              onValueChange={(next) => {
                                if (next === 'verified' || next === 'untrusted') {
                                  setSkillEditorTrustLevel(next)
                                } else {
                                  setSkillEditorTrustLevel('reviewed')
                                }
                              }}
                            >
                              <Select.Trigger
                                className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
                                aria-label="Skill trust level"
                              >
                                <Select.Value />
                                <Select.Icon asChild>
                                  <Icon path="M6 9l6 6 6-6" />
                                </Select.Icon>
                              </Select.Trigger>
                              <Select.Portal>
                                <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                                  <Select.Viewport className="quickadd-project-viewport">
                                    <Select.Item value="reviewed" className="quickadd-project-item">
                                      <Select.ItemText>reviewed</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 12l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                    <Select.Item value="verified" className="quickadd-project-item">
                                      <Select.ItemText>verified</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 12l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                    <Select.Item value="untrusted" className="quickadd-project-item">
                                      <Select.ItemText>untrusted</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 12l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                  </Select.Viewport>
                                </Select.Content>
                              </Select.Portal>
                            </Select.Root>
                          </label>
                        </div>
                        <div className="md-editor-surface">
                          <div className="md-editor-content">
                            <textarea
                              className="md-textarea"
                              value={skillEditorSummary}
                              onChange={(e) => setSkillEditorSummary(e.target.value)}
                              placeholder="Skill summary"
                              style={{ width: '100%', minHeight: 96 }}
                            />
                          </div>
                        </div>
                        <div className="row wrap" style={{ marginTop: 8, gap: 6 }}>
                          <button
                            className="status-chip"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation()
                              const normalizedSkillId = String(skill.id || '').trim()
                              if (!normalizedSkillId) return
                              setStagedSkillApplyIds((prev) =>
                                prev.includes(normalizedSkillId) ? prev : [...prev, normalizedSkillId]
                              )
                              setGlobalSaveStatus(null)
                            }}
                          >
                            {hasLinkedRule ? 'Reapply to context' : 'Apply to context'}
                          </button>
                          {hasLinkedRule ? (
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => openLinkedRule(linkedRuleId)}
                            >
                              Open linked rule
                            </button>
                          ) : null}
                        </div>
                        <div className="meta" style={{ marginTop: 8 }}>
                          Source: {skill.source_locator || '(none)'}
                        </div>
                        <div className="meta">
                          Linked rule: {hasLinkedRule ? linkedRuleId : '(none)'}
                        </div>
                        <div className="meta" style={{ marginTop: 8 }}>Skill content</div>
                        <div className="md-editor-surface">
                          <MarkdownModeToggle
                            view={skillContentView}
                            onChange={setSkillContentView}
                            ariaLabel="Skill content editor view"
                          />
                          <div className="md-editor-content">
                            {skillContentView === 'write' ? (
                              <textarea
                                className="md-textarea"
                                value={skillEditorContent}
                                onChange={(e) => setSkillEditorContent(e.target.value)}
                                placeholder="Write skill content in Markdown..."
                                style={{ width: '100%', minHeight: 180 }}
                              />
                            ) : skillContentView === 'split' ? (
                              <MarkdownSplitPane
                                left={(
                                  <textarea
                                    className="md-textarea"
                                    value={skillEditorContent}
                                    onChange={(e) => setSkillEditorContent(e.target.value)}
                                    placeholder="Write skill content in Markdown..."
                                    style={{ width: '100%', minHeight: 180 }}
                                  />
                                )}
                                right={<MarkdownView value={skillEditorContent} />}
                                ariaLabel="Resize skill editor and preview panels"
                              />
                            ) : (
                              <MarkdownView value={skillEditorContent} />
                            )}
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              )
            })}
            </>
          )}
        </div>
      </div>
        </Tabs.Content>
      {showCatalogPicker && typeof document !== 'undefined'
        ? createPortal(
          <div className="drawer open" onClick={() => setShowCatalogPicker(false)}>
            <div className="drawer-body project-skill-catalog-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <div>
                <h3 className="drawer-title" style={{ marginBottom: 4 }}>Workspace Skill Catalog</h3>
                <div className="meta">Select a workspace skill and attach it to this project.</div>
              </div>
              <button
                className="action-icon"
                type="button"
                onClick={() => setShowCatalogPicker(false)}
                title="Close catalog"
                aria-label="Close catalog"
              >
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <div className="row wrap" style={{ marginTop: 10, marginBottom: 10 }}>
              <input
                value={catalogSearchQ}
                onChange={(e) => setCatalogSearchQ(e.target.value)}
                placeholder="Filter by name, key, or summary"
                style={{ flex: 1, minWidth: 240 }}
              />
            </div>
            <div className="task-list">
              {workspaceSkills.isLoading ? (
                <div className="notice">Loading workspace catalog...</div>
              ) : filteredWorkspaceSkillItems.length === 0 ? (
                <div className="notice">No matching workspace skills.</div>
              ) : (
                filteredWorkspaceSkillItems.map((skill: WorkspaceSkill) => {
                  const alreadyAttached = projectSkillKeys.has(String(skill.skill_key || '').trim())
                  const alreadyStagedAttach = stagedSkillAttachSet.has(String(skill.id || '').trim())
                  const skillLabel = skill.name || skill.skill_key || 'Untitled catalog skill'
                  return (
                    <div key={skill.id} className="task-item rule-item project-create-skill-item catalog-skill-item">
                      <div className="task-main">
                        <div className="task-title catalog-skill-item-header">
                          <div className="row catalog-skill-item-title-wrap" style={{ gap: 6, minWidth: 0 }}>
                            {skill.is_seeded ? <span className="rule-kind-chip">[SEEDED]</span> : null}
                            <strong>{skillLabel}</strong>
                          </div>
                        </div>
                        <div className="row wrap catalog-skill-item-meta" style={{ gap: 6 }}>
                          <span className="status-chip">key: {skill.skill_key || '-'}</span>
                          <span className="status-chip">mode: {skill.mode || '-'}</span>
                          <span className="status-chip">trust: {skill.trust_level || '-'}</span>
                        </div>
                        <div className="meta catalog-skill-item-summary">
                          {(skill.summary || '').replace(/\s+/g, ' ').slice(0, 200) || '(no summary)'}
                        </div>
                        <div className="row wrap catalog-skill-item-footer" style={{ justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                          <div className="meta">source: {skill.source_locator || '(none)'}</div>
                          <button
                            className={`status-chip ${alreadyAttached ? 'on' : ''}`.trim()}
                            type="button"
                            disabled={alreadyAttached || alreadyStagedAttach || attachWorkspaceSkillToProjectMutation.isPending}
                            onClick={() => {
                              const workspaceSkillId = String(skill.id || '').trim()
                              if (!workspaceSkillId || alreadyAttached) return
                              setStagedSkillAttachIds((prev) =>
                                prev.includes(workspaceSkillId) ? prev : [...prev, workspaceSkillId]
                              )
                              setGlobalSaveStatus(null)
                              setShowCatalogPicker(false)
                            }}
                          >
                            {alreadyAttached ? 'Attached' : alreadyStagedAttach ? 'Staged' : 'Stage attach'}
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
            </div>
          </div>,
          document.body
        )
        : null}
        <Tabs.Content value="resources" className="project-editor-tab-content">
      <Accordion.Root
        className="taskdrawer-sections note-resource-stack"
        type="multiple"
        defaultValue={['project-editor-external-links', 'project-editor-file-attachments']}
      >
        <Accordion.Item value="project-editor-external-links" className="taskdrawer-section-item taskdrawer-section-links">
          <div className="taskdrawer-section-headrow">
            <Accordion.Header className="taskdrawer-section-header">
              <Accordion.Trigger className="taskdrawer-section-trigger">
                <span className="taskdrawer-section-icon" aria-hidden="true">
                  <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                </span>
                <span className="taskdrawer-section-head">
                  <span className="taskdrawer-section-title">External links</span>
                  <span className="taskdrawer-section-meta">{`${projectExternalRefs.length} linked`}</span>
                </span>
                <span className="taskdrawer-section-badge">{projectExternalRefs.length}</span>
                <span className="taskdrawer-section-chevron" aria-hidden="true">
                  <Icon path="M6 9l6 6 6-6" />
                </span>
              </Accordion.Trigger>
            </Accordion.Header>
          </div>
          <Accordion.Content className="taskdrawer-section-content">
            <ExternalRefEditor
              refs={projectExternalRefs}
              onRemoveIndex={(idx) => setEditProjectExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
              onOpenRef={openGitRepositoryFromRef}
              onAdd={(ref) =>
                setEditProjectExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
              }
            />
          </Accordion.Content>
        </Accordion.Item>
        <Accordion.Item value="project-editor-file-attachments" className="taskdrawer-section-item taskdrawer-section-attachments">
          <div className="taskdrawer-section-headrow">
            <Accordion.Header className="taskdrawer-section-header">
              <Accordion.Trigger className="taskdrawer-section-trigger">
                <span className="taskdrawer-section-icon" aria-hidden="true">
                  <Icon path="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.2a2 2 0 0 1-2.82-2.83l8.49-8.48" />
                </span>
                <span className="taskdrawer-section-head">
                  <span className="taskdrawer-section-title">File attachments</span>
                  <span className="taskdrawer-section-meta">{`${projectAttachmentRefs.length} files attached`}</span>
                </span>
                <span className="taskdrawer-section-badge">{projectAttachmentRefs.length}</span>
                <span className="taskdrawer-section-chevron" aria-hidden="true">
                  <Icon path="M6 9l6 6 6-6" />
                </span>
              </Accordion.Trigger>
            </Accordion.Header>
            <button
              className="taskdrawer-section-quick-action"
              type="button"
              title="Upload file"
              aria-label="Upload file"
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                editProjectFileInputRef.current?.click()
              }}
            >
              <Icon path="M12 5v10m0 0l4-4m-4 4l-4-4M4 21h16" />
            </button>
          </div>
          <Accordion.Content className="taskdrawer-section-content">
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
            <AttachmentRefList
              refs={projectAttachmentRefs}
              workspaceId={workspaceId}
              userId={userId}
              onRemovePath={(path) => {
                setEditProjectAttachmentRefsText((prev) => removeAttachmentByPath(prev, path))
              }}
            />
          </Accordion.Content>
        </Accordion.Item>
      </Accordion.Root>
      <div style={{ marginTop: 10 }}>
        <div className="meta" style={{ marginBottom: 6 }}>Assigned users</div>
        <div className="row wrap" style={{ gap: 6 }}>
          {workspaceUsers.map((u) => {
            const selected = editProjectMemberIds.includes(u.id)
            return (
              <button
                key={`edit-member-${u.id}`}
                type="button"
                className={`status-chip project-member-chip ${selected ? 'active' : ''}`}
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
      <div className="row wrap resource-meta-row" style={{ marginTop: 10 }}>
        <div className="meta">Created by: {selectedProjectCreator}</div>
        {selectedProjectTimeMeta && <div className="meta">{selectedProjectTimeMeta.label}: {toUserDateTime(selectedProjectTimeMeta.value, userTimezone)}</div>}
        {templateBinding ? (
          <div className="meta">
            Template: {templateBinding.template_key} v{templateBinding.template_version}
            {' | '}
            Applied: {toUserDateTime(templateBinding.applied_at, userTimezone) || 'Unknown'}
          </div>
        ) : (
          <div className="meta">Template: Manual project (no template binding)</div>
        )}
      </div>
        </Tabs.Content>
        <Tabs.Content value="context" className="project-editor-tab-content">
          <ProjectContextSnapshotPanel
            projectId={selectedProject.id || project.id}
            projectName={selectedProject.name || project.name}
            projectDescription={String(selectedProject.description || '')}
            projectRules={projectRules.data?.items ?? []}
            projectSkills={skillItems}
            overview={projectGraphOverview?.data}
            contextPack={projectGraphContextPack?.data}
            contextLimitTokens={contextLimitTokensDefault > 0 ? contextLimitTokensDefault : undefined}
            activeChatProjectId={codexChatProjectId}
            activeChatTurns={codexChatTurns}
            codexChatUsage={codexChatUsage ?? null}
            codexChatResumeState={codexChatResumeState ?? null}
            projectChatIndexMode={selectedProject.chat_index_mode}
            projectChatAttachmentIngestionMode={selectedProject.chat_attachment_ingestion_mode}
          />
        </Tabs.Content>
      </Tabs.Root>
      {showProjectSaveBar ? (
        <div className="project-editor-savebar">
          <div className="project-editor-savebar-meta">
            {hasAnyUnsavedChanges ? (
              <span className="badge unsaved-badge">
                {unsavedSections.length} unsaved section{unsavedSections.length === 1 ? '' : 's'}
              </span>
            ) : (
              <span className="badge">All changes saved</span>
            )}
            {hasAnyUnsavedChanges ? (
              <span className="meta">Changed: {unsavedSections.join(', ')}</span>
            ) : null}
            {globalSaveStatus ? (
              <span className="meta">
                [{globalSaveStatus.tone.toUpperCase()}] {globalSaveStatus.text}
              </span>
            ) : null}
          </div>
          <button
            className="status-chip on project-editor-savebar-btn"
            type="button"
            onClick={() => void runSaveAllChanges()}
            disabled={!hasAnyUnsavedChanges || saveAllPending || !editProjectName.trim()}
          >
            <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
            <span className="project-editor-savebar-btn-label">
              {saveAllPending ? 'Saving...' : 'Save all changes'}
            </span>
          </button>
        </div>
      ) : null}
      <ProjectDockerComposeRuntimeDialog
        open={dockerRuntimeDialogOpen}
        onOpenChange={setDockerRuntimeDialogOpen}
        userId={userId}
        projectId={project.id}
      />
      <ProjectGitRepositoryDialog
        open={gitRepositoryDialogOpen}
        onOpenChange={(open) => {
          setGitRepositoryDialogOpen(open)
          if (!open) setGitRepositoryDialogTarget(null)
        }}
        userId={userId}
        projectId={project.id}
        target={gitRepositoryDialogTarget}
      />
      <AlertDialog.Root open={removeProjectPromptOpen} onOpenChange={setRemoveProjectPromptOpen}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Remove project</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {`Delete "${project.name}"? This permanently deletes project resources.`}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  disabled={deleteProjectMutation.isPending}
                  onClick={() => {
                    deleteProjectMutation.mutate(project.id)
                    setRemoveProjectPromptOpen(false)
                  }}
                >
                  Remove project
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
      <AlertDialog.Root
        open={Boolean(deleteRulePrompt)}
        onOpenChange={(open) => {
          if (!open) setDeleteRulePrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Delete rule</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {deleteRulePrompt
                ? `Delete "${deleteRulePrompt.title}"?`
                : 'This action cannot be undone.'}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  disabled={saveAllPending}
                  onClick={() => {
                    if (!deleteRulePrompt) return
                    stageDeleteRule(deleteRulePrompt.id)
                    setDeleteRulePrompt(null)
                  }}
                >
                  Delete rule
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
      <AlertDialog.Root
        open={Boolean(deleteSkillPrompt)}
        onOpenChange={(open) => {
          if (!open) setDeleteSkillPrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Delete skill</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {deleteSkillPrompt
                ? `Delete "${deleteSkillPrompt.name}" and its linked rule?`
                : 'This action cannot be undone.'}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  disabled={saveAllPending}
                  onClick={() => {
                    if (!deleteSkillPrompt) return
                    const deletingSkillId = String(deleteSkillPrompt.id || '').trim()
                    if (!deletingSkillId) return
                    setStagedSkillDeleteIds((prev) => (prev.includes(deletingSkillId) ? prev : [...prev, deletingSkillId]))
                    setStagedSkillApplyIds((prev) => prev.filter((id) => id !== deletingSkillId))
                    if (selectedProjectSkillId === deletingSkillId) setSelectedProjectSkillId(null)
                    setGlobalSaveStatus(null)
                    setDeleteSkillPrompt(null)
                  }}
                >
                  Stage delete
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </div>
  )
}
