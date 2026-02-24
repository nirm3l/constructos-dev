import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import type {
  AttachmentRef,
  GraphContextPack,
  GraphProjectOverview,
  Project,
  ProjectRule,
  ProjectRulesPage,
  ProjectSkill,
  ProjectSkillsPage,
  WorkspaceSkill,
  WorkspaceSkillsPage,
} from '../../types'
import { AttachmentRefList, ExternalRefEditor, Icon, MarkdownModeToggle } from '../shared/uiHelpers'
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
  embeddingAllowedModels,
  embeddingDefaultModel,
  vectorStoreEnabled,
  contextPackEvidenceTopKDefault,
  contextLimitTokensDefault,
  codexChatProjectId,
  codexChatTurns,
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
  embeddingAllowedModels: string[]
  embeddingDefaultModel: string
  vectorStoreEnabled: boolean
  contextPackEvidenceTopKDefault: number
  contextLimitTokensDefault: number
  codexChatProjectId: string
  codexChatTurns: Array<{ role?: string; content?: string }>
  saveProjectMutation: ProjectMutation
  deleteProjectMutation: ProjectMutation
  editProjectDescriptionView: 'write' | 'preview'
  setEditProjectDescriptionView: React.Dispatch<React.SetStateAction<'write' | 'preview'>>
  editProjectDescriptionRef: React.RefObject<HTMLTextAreaElement | null>
  editProjectDescription: string
  setEditProjectDescription: React.Dispatch<React.SetStateAction<string>>
  projectRules: { data?: ProjectRulesPage }
  projectSkills: { data?: ProjectSkillsPage; isLoading?: boolean; isFetching?: boolean }
  projectGraphOverview?: { data?: GraphProjectOverview }
  projectGraphContextPack?: { data?: GraphContextPack }
  workspaceSkills: { data?: WorkspaceSkillsPage; isLoading?: boolean; isFetching?: boolean }
  selectedProjectRuleId: string | null
  setSelectedProjectRuleId: React.Dispatch<React.SetStateAction<string | null>>
  projectRuleTitle: string
  setProjectRuleTitle: React.Dispatch<React.SetStateAction<string>>
  projectRuleBody: string
  setProjectRuleBody: React.Dispatch<React.SetStateAction<string>>
  projectRuleView: 'write' | 'preview'
  setProjectRuleView: React.Dispatch<React.SetStateAction<'write' | 'preview'>>
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
  const templateBinding = selectedProject.template_binding
  const [selectedProjectSkillId, setSelectedProjectSkillId] = React.useState<string | null>(null)
  const [skillImportSourceUrl, setSkillImportSourceUrl] = React.useState('')
  const skillImportFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const rulesSectionRef = React.useRef<HTMLDivElement | null>(null)
  const rulesFocusTimerRef = React.useRef<number | null>(null)
  const [rulesSectionFocused, setRulesSectionFocused] = React.useState(false)
  const skillsSectionRef = React.useRef<HTMLDivElement | null>(null)
  const skillsFocusTimerRef = React.useRef<number | null>(null)
  const [skillsSectionFocused, setSkillsSectionFocused] = React.useState(false)
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
  const [skillContentView, setSkillContentView] = React.useState<'write' | 'preview'>('write')
  const [showCatalogPicker, setShowCatalogPicker] = React.useState(false)
  const [catalogSearchQ, setCatalogSearchQ] = React.useState('')

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

  React.useEffect(
    () => () => {
      if (rulesFocusTimerRef.current !== null) {
        window.clearTimeout(rulesFocusTimerRef.current)
        rulesFocusTimerRef.current = null
      }
      if (skillsFocusTimerRef.current !== null) {
        window.clearTimeout(skillsFocusTimerRef.current)
        skillsFocusTimerRef.current = null
      }
    },
    []
  )

  const openLinkedRule = React.useCallback((ruleId: string | null | undefined) => {
    const normalizedRuleId = String(ruleId || '').trim()
    if (!normalizedRuleId) return
    setSelectedProjectRuleId(normalizedRuleId)
    setProjectRuleView('preview')
    setRulesSectionFocused(true)
    if (rulesFocusTimerRef.current !== null) {
      window.clearTimeout(rulesFocusTimerRef.current)
    }
    rulesFocusTimerRef.current = window.setTimeout(() => {
      setRulesSectionFocused(false)
      rulesFocusTimerRef.current = null
    }, 1400)
    window.requestAnimationFrame(() => {
      rulesSectionRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    })
  }, [])

  const openLinkedSkill = React.useCallback((skillId: string | null | undefined) => {
    const normalizedSkillId = String(skillId || '').trim()
    if (!normalizedSkillId) return
    setSelectedProjectSkillId(normalizedSkillId)
    setSkillsSectionFocused(true)
    if (skillsFocusTimerRef.current !== null) {
      window.clearTimeout(skillsFocusTimerRef.current)
    }
    skillsFocusTimerRef.current = window.setTimeout(() => {
      setSkillsSectionFocused(false)
      skillsFocusTimerRef.current = null
    }, 1400)
    window.requestAnimationFrame(() => {
      skillsSectionRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    })
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
        <button
          className="action-icon danger-ghost"
          onClick={() => {
            if (!window.confirm(`Delete ${project.name}? This permanently deletes project resources.`)) return
            deleteProjectMutation.mutate(project.id)
          }}
          disabled={deleteProjectMutation.isPending}
          title="Delete project"
          aria-label="Delete project"
        >
          <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
        </button>
      </div>
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
          <select
            value={selectedModel}
            disabled={!editProjectEmbeddingEnabled || modelOptions.length === 0}
            onChange={(e) => setEditProjectEmbeddingModel(e.target.value)}
          >
            {modelOptions.map((model) => (
              <option key={`embedding-model-${model}`} value={model}>
                {model === defaultModel ? `${model} (default)` : model}
              </option>
            ))}
          </select>
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
              <select
                value={effectiveChatIndexMode}
                disabled={chatPolicyDisabled}
                onChange={(e) => {
                  const next = e.target.value
                  if (next === 'VECTOR_ONLY' || next === 'KG_AND_VECTOR') {
                    setEditProjectChatIndexMode(next)
                    return
                  }
                  setEditProjectChatIndexMode('OFF')
                }}
                aria-label="Chat message indexing mode"
              >
                <option value="OFF">OFF</option>
                <option value="VECTOR_ONLY">VECTOR_ONLY</option>
                <option value="KG_AND_VECTOR">KG_AND_VECTOR</option>
              </select>
            </label>
            <label className="field-control project-chat-policy-select">
              <span className="field-label">Attachments</span>
              <select
                value={editProjectChatAttachmentIngestionMode}
                disabled={chatAttachmentDisabled}
                onChange={(e) => {
                  const next = e.target.value
                  if (next === 'OFF' || next === 'FULL_TEXT') {
                    setEditProjectChatAttachmentIngestionMode(next)
                    return
                  }
                  setEditProjectChatAttachmentIngestionMode('METADATA_ONLY')
                }}
                aria-label="Chat attachment ingestion mode"
              >
                <option value="METADATA_ONLY">METADATA_ONLY</option>
                <option value="OFF">OFF</option>
                <option value="FULL_TEXT">FULL_TEXT</option>
              </select>
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
      <div
        ref={rulesSectionRef}
        className={`rules-studio ${rulesSectionFocused ? 'rules-studio-focus' : ''}`}
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
                      <div className="task-title">
                        <div className="row" style={{ gap: 6, minWidth: 0 }}>
                          {linkedSkill && <span className="rule-kind-chip">[SKILL]</span>}
                          <strong>{rule.title || 'Untitled rule'}</strong>
                        </div>
                        <div className="row" style={{ gap: 6 }}>
                          {isSelected && <span className="badge">Editing</span>}
                          <button
                            className="action-icon danger-ghost"
                            disabled={deleteProjectRuleMutation.isPending}
                            onClick={(e) => {
                              e.stopPropagation()
                              if (!window.confirm('Delete this rule?')) return
                              deleteProjectRuleMutation.mutate(rule.id)
                            }}
                            title="Delete rule"
                            aria-label="Delete rule"
                          >
                            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                          </button>
                        </div>
                      </div>
                      <div className="meta">{(rule.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                      {linkedSkill ? (
                        <div className="meta">
                          Linked skill: {linkedSkill.skillName || linkedSkill.skillKey || linkedSkill.skillId}
                        </div>
                      ) : null}
                      <div className="meta">Updated: {toUserDateTime(rule.updated_at, userTimezone)}</div>
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
                setProjectRuleView('write')
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
                    style={{ width: '100%', minHeight: 140 }}
                  />
                ) : (
                  <MarkdownView value={projectRuleBody} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div
        ref={skillsSectionRef}
        className={`rules-studio ${skillsSectionFocused ? 'rules-studio-focus' : ''}`}
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
          <select
            value={skillImportMode}
            title="Import mode"
            aria-label="Import mode"
            onChange={(e) => setSkillImportMode(e.target.value === 'enforced' ? 'enforced' : 'advisory')}
            style={{ width: 120 }}
          >
            <option value="advisory">advisory</option>
            <option value="enforced">enforced</option>
          </select>
          <select
            value={skillImportTrustLevel}
            title="Trust level"
            aria-label="Trust level"
            onChange={(e) => {
              const next = e.target.value
              if (next === 'verified' || next === 'untrusted') {
                setSkillImportTrustLevel(next)
              } else {
                setSkillImportTrustLevel('reviewed')
              }
            }}
            style={{ width: 120 }}
          >
            <option value="reviewed">reviewed</option>
            <option value="verified">verified</option>
            <option value="untrusted">untrusted</option>
          </select>
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
                    <div className="task-title">
                      <strong>{skill.name || skill.skill_key || 'Untitled skill'}</strong>
                      <div className="row" style={{ gap: 6 }}>
                        <button
                          className="action-icon danger-ghost"
                          disabled={deleteProjectSkillMutation.isPending}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (!window.confirm('Delete this skill and linked rule?')) return
                            deleteProjectSkillMutation.mutate(
                              {
                                skillId: skill.id,
                                delete_linked_rule: true,
                              },
                              {
                                onSuccess: () => {
                                  if (selectedProjectSkillId === skill.id) setSelectedProjectSkillId(null)
                                },
                              }
                            )
                          }}
                          title="Delete skill"
                          aria-label="Delete skill"
                        >
                          <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                        </button>
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
                            <select
                              value={skillEditorMode}
                              onChange={(e) => setSkillEditorMode(e.target.value === 'enforced' ? 'enforced' : 'advisory')}
                            >
                              <option value="advisory">advisory</option>
                              <option value="enforced">enforced</option>
                            </select>
                          </label>
                          <label className="field-control" style={{ minWidth: 170, marginBottom: 0 }}>
                            <span className="field-label">Trust level</span>
                            <select
                              value={skillEditorTrustLevel}
                              onChange={(e) => {
                                const next = e.target.value
                                if (next === 'verified' || next === 'untrusted') {
                                  setSkillEditorTrustLevel(next)
                                } else {
                                  setSkillEditorTrustLevel('reviewed')
                                }
                              }}
                            >
                              <option value="reviewed">reviewed</option>
                              <option value="verified">verified</option>
                              <option value="untrusted">untrusted</option>
                            </select>
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
      {showCatalogPicker ? (
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
                  return (
                    <div key={skill.id} className="task-item rule-item">
                      <div className="task-main">
                        <div className="task-title">
                          <div className="row" style={{ gap: 6, minWidth: 0 }}>
                            {skill.is_seeded ? <span className="rule-kind-chip">[SEEDED]</span> : null}
                            <strong>{skill.name || skill.skill_key || 'Untitled catalog skill'}</strong>
                          </div>
                          <button
                            className="status-chip"
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
                        <div className="meta">
                          key: {skill.skill_key || '-'} | mode: {skill.mode || '-'} | trust: {skill.trust_level || '-'}
                        </div>
                        <div className="meta">
                          {(skill.summary || '').replace(/\s+/g, ' ').slice(0, 200) || '(no summary)'}
                        </div>
                        <div className="meta">source: {skill.source_locator || '(none)'}</div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      ) : null}
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
        projectChatIndexMode={selectedProject.chat_index_mode}
        projectChatAttachmentIngestionMode={selectedProject.chat_attachment_ingestion_mode}
      />
    </div>
  )
}
