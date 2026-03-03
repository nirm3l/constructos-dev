import React from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Select from '@radix-ui/react-select'
import * as Accordion from '@radix-ui/react-accordion'
import * as Tabs from '@radix-ui/react-tabs'
import { getProjectEventStormingOverview, getProjectGatesVerification } from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import type {
  AgentChatUsage,
  AttachmentRef,
  EventStormingOverview,
  GraphContextPack,
  GraphProjectOverview,
  Project,
  ProjectGatesVerifyResponse,
  ProjectRule,
  ProjectRulesPage,
  ProjectSkill,
  ProjectSkillsPage,
  WorkspaceSkill,
  WorkspaceSkillsPage,
} from '../../types'
import {
  AttachmentRefList,
  ExternalRefEditor,
  Icon,
  MarkdownModeToggle,
  MarkdownSplitPane,
} from '../shared/uiHelpers'
import { ProjectContextSnapshotPanel } from './ProjectContextSnapshotPanel'
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
  const inlineEventStormingOverviewQuery = useQuery({
    queryKey: ['project-event-storming-overview', userId, project.id],
    queryFn: () => getProjectEventStormingOverview(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id),
  })
  const eventStormingOverview = inlineEventStormingOverviewQuery.data ?? projectEventStormingOverview?.data
  const gateSkillKeys = React.useMemo(
    () =>
      new Set(
        (projectSkills.data?.items ?? [])
          .map((item) => String(item.skill_key || '').trim())
          .filter(Boolean)
      ),
    [projectSkills.data?.items]
  )
  const hasGateRelevantSkills = gateSkillKeys.has('team_mode') || gateSkillKeys.has('git_delivery') || gateSkillKeys.has('github_delivery')
  const hasGatePolicyRule = React.useMemo(
    () =>
      (projectRules.data?.items ?? []).some((rule) => {
        const title = String(rule.title || '').trim().toLowerCase()
        return title.includes('gate policy') || title.includes('delivery gates') || title.includes('workflow gates')
      }),
    [projectRules.data?.items]
  )
  const shouldShowProjectGates = hasGateRelevantSkills || hasGatePolicyRule
  const projectGatesQuery = useQuery<ProjectGatesVerifyResponse>({
    queryKey: ['project-gates-verify', userId, project.id],
    queryFn: () => getProjectGatesVerification(userId, project.id),
    enabled: Boolean(userId && project.id && selectedProject?.id === project.id && shouldShowProjectGates),
    refetchInterval: 20_000,
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
  const projectGatesSnapshot = projectGatesQuery.data
  const gateScopeEntries = React.useMemo<
    Array<{
      scopeKey: string
      scopeTitle: string
      checks: Record<string, boolean | string | number | null>
      requiredChecks: string[]
      failedChecks: string[]
      checkDescriptions: Record<string, string>
      availableChecks: Array<{ id: string; description?: string }>
      gatePolicySource: string
      gatePolicy?: Record<string, unknown>
    }>
  >(() => {
    if (!projectGatesSnapshot || typeof projectGatesSnapshot !== 'object') return []
    const payload = projectGatesSnapshot as Record<string, unknown>
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

        const policyRaw = scope.gate_policy
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
          checks,
          requiredChecks,
          failedChecks,
          checkDescriptions,
          availableChecks,
          gatePolicySource: String(scope.gate_policy_source || '').trim() || 'default',
          gatePolicy: policy,
        }
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item))
  }, [projectGatesSnapshot])
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
        availableDescriptions: scope.checkDescriptions,
        runtimeScope: scope,
      }))
    }
    return scopeKeys.map((scopeKey) => {
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
        availableDescriptions,
        runtimeScope: runtimeScopeMap.get(scopeKey),
      }
    })
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
  const gatePolicyRuleId = React.useMemo(() => {
    const match = /^project_rule:([a-f0-9-]{36})$/i.exec(gatePolicySource)
    return match?.[1] ?? null
  }, [gatePolicySource])
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
  const [projectEditorTab, setProjectEditorTab] = React.useState<
    'overview' | 'gates' | 'rules' | 'skills' | 'resources' | 'context'
  >('overview')
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

  const skillItems = projectSkills.data?.items ?? []
  const workspaceSkillItems = workspaceSkills.data?.items ?? []
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
    () => new Set(skillItems.map((item: ProjectSkill) => String(item.skill_key || '').trim()).filter(Boolean)),
    [skillItems]
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
  const projectRuleCount = projectRules.data?.total ?? projectRules.data?.items?.length ?? 0
  const projectSkillCount = projectSkills.data?.total ?? skillItems.length
  const projectResourceCount = projectExternalRefs.length + projectAttachmentRefs.length
  React.useEffect(() => {
    setProjectEditorTab('overview')
  }, [project.id])

  React.useEffect(() => {
    if (projectEditorTab === 'gates' && !shouldShowProjectGates) {
      setProjectEditorTab('overview')
    }
  }, [projectEditorTab, shouldShowProjectGates])

  return (
    <div className="project-inline-editor" style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
      <div className="row wrap" style={{ marginBottom: 10 }}>
        <input
          value={editProjectName}
          onChange={(e) => setEditProjectName(e.target.value)}
          placeholder="Project name"
          style={{ flex: 1, minWidth: 0 }}
        />
        {projectIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
        <button
          className="action-icon primary"
          onClick={() => saveProjectMutation.mutate()}
          disabled={saveProjectMutation.isPending || !editProjectName.trim()}
          title="Save project"
          aria-label="Save project"
        >
          <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
        </button>
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
            next === 'gates' ||
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
          {shouldShowProjectGates && (
            <Tabs.Trigger className="project-editor-tab-trigger" value="gates">
              <span>Gates</span>
              <span className="project-editor-tab-count">{projectGatesQuery.data?.ok ? 'OK' : '!!'}</span>
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
          onChange={(e) => setEditProjectCustomStatusesText(e.target.value)}
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
        <div className="meta" style={{ marginTop: 6 }}>
          Save project to persist this setting.
        </div>
      </div>
        </Tabs.Content>
        {shouldShowProjectGates && (
          <Tabs.Content value="gates" className="project-editor-tab-content">
            <div className="gates-panel">
              <div className="gates-panel-head">
                <div className="gates-panel-title-row">
                  <h3 style={{ margin: 0 }}>Delivery Gates</h3>
                  <span className={`badge ${projectGatesSnapshot?.ok ? 'status-done' : 'status-blocked'}`}>
                    {projectGatesSnapshot?.ok ? 'PASS' : 'FAIL'}
                  </span>
                </div>
                <div className="gates-panel-summary">
                  <span className="badge">Scopes: {gateConfigScopes.length}</span>
                  <span className="badge">Failed required: {gateSummary.failed}</span>
                  <span className="badge">Required checks: {gateSummary.required}</span>
                  {gateSummary.unknown > 0 ? <span className="badge">Unknown: {gateSummary.unknown}</span> : null}
                </div>
              </div>
              {projectGatesQuery.isLoading ? (
                <div className="meta">Loading gate verification...</div>
              ) : projectGatesQuery.isError ? (
                <div className="notice">Gate verification unavailable.</div>
              ) : projectGatesSnapshot ? (
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
                        <div className="meta">Available checks ({Object.keys(scope.availableDescriptions).length})</div>
                        <div className="gates-available-tags">
                          {Object.keys(scope.availableDescriptions).map((checkId) => {
                            if (!checkId) return null
                            const description = String(
                              scope.runtimeScope?.checkDescriptions[checkId] || scope.availableDescriptions[checkId] || ''
                            ).trim()
                            return (
                              <span key={`${scope.scopeKey}-available-${checkId}`} className="gates-available-tag" title={description || undefined}>
                                {checkId}
                              </span>
                            )
                          })}
                        </div>
                      </section>
                    ))}
                  </div>
                  <div className="gates-policy-row">
                    <span className="badge">Policy source</span>
                    <code>{gatePolicySource}</code>
                    {gatePolicyRuleId ? (
                      <button
                        className="status-chip"
                        type="button"
                        onClick={() => openLinkedRule(gatePolicyRuleId)}
                      >
                        Open gate policy
                      </button>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="notice">No gate verification payload.</div>
              )}
              <div className="meta" style={{ marginTop: 4 }}>
                Gate behavior is driven by the <strong>Gate Policy</strong> project rule JSON.
              </div>
            </div>
          </Tabs.Content>
        )}
        <Tabs.Content value="rules" className="project-editor-tab-content">
      <div
        className="rules-studio"
        style={{ marginTop: 10, marginBottom: 14 }}
      >
        <div className="row wrap rules-head-row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>Project Rules ({projectRules.data?.total ?? 0})</h3>
        </div>
        <div className="rules-layout">
          <div className="rules-list">
            {(projectRules.data?.items ?? []).length === 0 ? (
              <div className="notice">No rules yet for this project.</div>
            ) : (
              (projectRules.data?.items ?? []).map((rule: ProjectRule) => {
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
                    onClick={() => setSelectedProjectRuleId(rule.id)}
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
                      {linkedSkill ? (
                        <div className="meta">
                          Linked skill: {linkedSkill.skillName || linkedSkill.skillKey || linkedSkill.skillId}
                        </div>
                      ) : null}
                      <div className="meta">Updated: {toUserDateTime(rule.updated_at, userTimezone)}</div>
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
                              disabled={deleteProjectRuleMutation.isPending}
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
                setSelectedProjectRuleId(null)
                setProjectRuleTitle('')
                setProjectRuleBody('')
                setProjectRuleView('split')
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
              <button
                className="action-icon primary"
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
          <div className="meta">Project-local skills. Import adds skill metadata to context; use Apply to include full skill content via linked rule.</div>
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
              title="Import project skill from URL"
              aria-label="Import project skill from URL"
              onClick={() => {
                const sourceUrl = String(skillImportSourceUrl || '').trim()
                if (!sourceUrl) {
                  setUiError('Skill source URL is required')
                  return
                }
                importProjectSkillMutation.mutate(
                  {
                    source_url: sourceUrl,
                    skill_key: String(skillImportKey || '').trim() || undefined,
                    mode: skillImportMode,
                    trust_level: skillImportTrustLevel,
                  },
                  {
                    onSuccess: (created: ProjectSkill) => {
                      setUiError(null)
                      if (created?.id) setSelectedProjectSkillId(created.id)
                      setSkillImportSourceUrl('')
                      setSkillImportKey('')
                      setSkillImportMode('advisory')
                      setSkillImportTrustLevel('reviewed')
                    },
                  }
                )
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
              importProjectSkillFileMutation.mutate(
                {
                  file,
                  skill_key: String(skillImportKey || '').trim() || undefined,
                  mode: skillImportMode,
                  trust_level: skillImportTrustLevel,
                },
                {
                  onSuccess: (created: ProjectSkill) => {
                    setUiError(null)
                    if (created?.id) setSelectedProjectSkillId(created.id)
                    setSkillImportSourceUrl('')
                    setSkillImportKey('')
                    setSkillImportMode('advisory')
                    setSkillImportTrustLevel('reviewed')
                  },
                }
              )
            }}
          />
        </div>
        <div className="rules-list">
          {projectSkills.isLoading ? (
            <div className="notice">Loading project skills...</div>
          ) : skillItems.length === 0 ? (
            <div className="notice">No skills imported yet for this project.</div>
          ) : (
            skillItems.map((skill: ProjectSkill) => {
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
                                    applyProjectSkillMutation.mutate({ skillId: skill.id })
                                  }}
                                >
                                  <Icon path="M5 13l4 4L19 7M5 7h8" />
                                  <span>{hasLinkedRule ? 'Reapply to context' : 'Apply to context'}</span>
                                </DropdownMenu.Item>
                                <DropdownMenu.Separator className="task-group-menu-separator" />
                                <DropdownMenu.Item
                                  className="task-group-menu-item task-group-menu-item-danger"
                                  disabled={deleteProjectSkillMutation.isPending}
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
                            onClick={() => applyProjectSkillMutation.mutate({ skillId: skill.id })}
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
            })
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
                            disabled={alreadyAttached || attachWorkspaceSkillToProjectMutation.isPending}
                            onClick={() => {
                              attachWorkspaceSkillToProjectMutation.mutate(
                                { skillId: skill.id },
                                {
                                  onSuccess: () => {
                                    setShowCatalogPicker(false)
                                  },
                                }
                              )
                            }}
                          >
                            {alreadyAttached ? 'Attached' : 'Attach'}
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
      <AlertDialog.Root open={removeProjectPromptOpen} onOpenChange={setRemoveProjectPromptOpen}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="drawer-backdrop" />
          <AlertDialog.Content className="dialog-content">
            <AlertDialog.Title>Remove project</AlertDialog.Title>
            <AlertDialog.Description className="meta" style={{ marginTop: 6 }}>
              {`Delete "${project.name}"? This permanently deletes project resources.`}
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel asChild>
                <button className="status-chip" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip danger-ghost"
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
          <AlertDialog.Overlay className="drawer-backdrop" />
          <AlertDialog.Content className="dialog-content">
            <AlertDialog.Title>Delete rule</AlertDialog.Title>
            <AlertDialog.Description className="meta" style={{ marginTop: 6 }}>
              {deleteRulePrompt
                ? `Delete "${deleteRulePrompt.title}"?`
                : 'This action cannot be undone.'}
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel asChild>
                <button className="status-chip" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip danger-ghost"
                  type="button"
                  disabled={deleteProjectRuleMutation.isPending}
                  onClick={() => {
                    if (!deleteRulePrompt) return
                    deleteProjectRuleMutation.mutate(deleteRulePrompt.id)
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
          <AlertDialog.Overlay className="drawer-backdrop" />
          <AlertDialog.Content className="dialog-content">
            <AlertDialog.Title>Delete skill</AlertDialog.Title>
            <AlertDialog.Description className="meta" style={{ marginTop: 6 }}>
              {deleteSkillPrompt
                ? `Delete "${deleteSkillPrompt.name}" and its linked rule?`
                : 'This action cannot be undone.'}
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel asChild>
                <button className="status-chip" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip danger-ghost"
                  type="button"
                  disabled={deleteProjectSkillMutation.isPending}
                  onClick={() => {
                    if (!deleteSkillPrompt) return
                    const deletingSkillId = deleteSkillPrompt.id
                    deleteProjectSkillMutation.mutate(
                      {
                        skillId: deletingSkillId,
                        delete_linked_rule: true,
                      },
                      {
                        onSuccess: () => {
                          if (selectedProjectSkillId === deletingSkillId) setSelectedProjectSkillId(null)
                        },
                      }
                    )
                    setDeleteSkillPrompt(null)
                  }}
                >
                  Delete skill
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </div>
  )
}
