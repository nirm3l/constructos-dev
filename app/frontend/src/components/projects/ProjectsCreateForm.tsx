import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Select from '@radix-ui/react-select'
import { MarkdownView } from '../../markdown/MarkdownView'
import { ExternalRefEditor, Icon, MarkdownModeToggle, MarkdownSplitPane } from '../shared/uiHelpers'
import { externalRefsToText, parseExternalRefsText, removeExternalRefByIndex } from '../../utils/ui'
import type { ProjectFromTemplatePreviewResponse, ProjectTemplate } from '../../types'

export type DraftProjectRule = { id: string; title: string; body: string }

type WorkspaceUser = {
  id: string
  full_name: string
  user_type: string
}

type ProjectCreateSelectOption = {
  value: string
  label: string
  disabled?: boolean
}

function ProjectCreateSelect({
  value,
  onValueChange,
  options,
  disabled,
  ariaLabel,
  placeholder,
}: {
  value: string
  onValueChange: (value: string) => void
  options: ProjectCreateSelectOption[]
  disabled?: boolean
  ariaLabel: string
  placeholder?: string
}) {
  return (
    <Select.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <Select.Trigger
        className="quickadd-project-trigger taskdrawer-select-trigger project-inline-select-trigger"
        aria-label={ariaLabel}
      >
        <Select.Value placeholder={placeholder} />
        <Select.Icon asChild>
          <Icon path="M6 9l6 6 6-6" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
          <Select.Viewport className="quickadd-project-viewport">
            {options.map((option) => (
              <Select.Item
                key={`project-create-select-${ariaLabel}-${option.value}`}
                value={option.value}
                className="quickadd-project-item"
                disabled={option.disabled}
              >
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="quickadd-project-item-indicator">
                  <Icon path="m5 13 4 4L19 7" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}

export function ProjectsCreateForm({
  projectName,
  setProjectName,
  projectTemplateKey,
  setProjectTemplateKey,
  projectTemplates,
  projectTemplatesLoading,
  previewProjectFromTemplateMutation,
  createProjectMutation,
  projectCustomStatusesText,
  setProjectCustomStatusesText,
  projectEmbeddingEnabled,
  setProjectEmbeddingEnabled,
  projectEmbeddingModel,
  setProjectEmbeddingModel,
  projectContextPackEvidenceTopKText,
  setProjectContextPackEvidenceTopKText,
  projectChatIndexMode,
  setProjectChatIndexMode,
  projectChatAttachmentIngestionMode,
  setProjectChatAttachmentIngestionMode,
  projectEventStormingEnabled,
  setProjectEventStormingEnabled,
  projectTemplateParametersText,
  setProjectTemplateParametersText,
  embeddingAllowedModels,
  embeddingDefaultModel,
  vectorStoreEnabled,
  contextPackEvidenceTopKDefault,
  projectDescriptionView,
  setProjectDescriptionView,
  projectDescriptionRef,
  projectDescription,
  setProjectDescription,
  draftProjectRules,
  setDraftProjectRules,
  selectedDraftProjectRuleId,
  setSelectedDraftProjectRuleId,
  draftProjectRuleTitle,
  setDraftProjectRuleTitle,
  draftProjectRuleBody,
  setDraftProjectRuleBody,
  draftProjectRuleView,
  setDraftProjectRuleView,
  projectExternalRefsText,
  setProjectExternalRefsText,
  workspaceUsers,
  createProjectMemberIds,
  toggleCreateProjectMember,
}: {
  projectName: string
  setProjectName: React.Dispatch<React.SetStateAction<string>>
  projectTemplateKey: string
  setProjectTemplateKey: React.Dispatch<React.SetStateAction<string>>
  projectTemplates: ProjectTemplate[]
  projectTemplatesLoading: boolean
  previewProjectFromTemplateMutation: {
    mutate: () => void
    data?: ProjectFromTemplatePreviewResponse
    isPending: boolean
    reset: () => void
  }
  createProjectMutation: { mutate: () => void; isPending: boolean }
  projectCustomStatusesText: string
  setProjectCustomStatusesText: React.Dispatch<React.SetStateAction<string>>
  projectEmbeddingEnabled: boolean
  setProjectEmbeddingEnabled: React.Dispatch<React.SetStateAction<boolean>>
  projectEmbeddingModel: string
  setProjectEmbeddingModel: React.Dispatch<React.SetStateAction<string>>
  projectContextPackEvidenceTopKText: string
  setProjectContextPackEvidenceTopKText: React.Dispatch<React.SetStateAction<string>>
  projectChatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'
  setProjectChatIndexMode: React.Dispatch<React.SetStateAction<'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'>>
  projectChatAttachmentIngestionMode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
  setProjectChatAttachmentIngestionMode: React.Dispatch<
    React.SetStateAction<'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'>
  >
  projectEventStormingEnabled: boolean
  setProjectEventStormingEnabled: React.Dispatch<React.SetStateAction<boolean>>
  projectTemplateParametersText: string
  setProjectTemplateParametersText: React.Dispatch<React.SetStateAction<string>>
  embeddingAllowedModels: string[]
  embeddingDefaultModel: string
  vectorStoreEnabled: boolean
  contextPackEvidenceTopKDefault: number
  projectDescriptionView: 'write' | 'preview' | 'split'
  setProjectDescriptionView: React.Dispatch<React.SetStateAction<'write' | 'preview' | 'split'>>
  projectDescriptionRef: React.RefObject<HTMLTextAreaElement | null>
  projectDescription: string
  setProjectDescription: React.Dispatch<React.SetStateAction<string>>
  draftProjectRules: DraftProjectRule[]
  setDraftProjectRules: React.Dispatch<React.SetStateAction<DraftProjectRule[]>>
  selectedDraftProjectRuleId: string | null
  setSelectedDraftProjectRuleId: React.Dispatch<React.SetStateAction<string | null>>
  draftProjectRuleTitle: string
  setDraftProjectRuleTitle: React.Dispatch<React.SetStateAction<string>>
  draftProjectRuleBody: string
  setDraftProjectRuleBody: React.Dispatch<React.SetStateAction<string>>
  draftProjectRuleView: 'write' | 'preview' | 'split'
  setDraftProjectRuleView: React.Dispatch<React.SetStateAction<'write' | 'preview' | 'split'>>
  projectExternalRefsText: string
  setProjectExternalRefsText: React.Dispatch<React.SetStateAction<string>>
  workspaceUsers: WorkspaceUser[]
  createProjectMemberIds: string[]
  toggleCreateProjectMember: (userIdToToggle: string) => void
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
    const current = String(projectEmbeddingModel || '').trim()
    if (current && modelOptions.includes(current)) return current
    return defaultModel
  }, [defaultModel, modelOptions, projectEmbeddingModel])
  const selectedTemplate = React.useMemo(
    () => projectTemplates.find((item) => item.key === projectTemplateKey) ?? null,
    [projectTemplateKey, projectTemplates]
  )
  const templateMode = Boolean(String(projectTemplateKey || '').trim())
  const templatePreview = templateMode ? (previewProjectFromTemplateMutation.data ?? null) : null
  const templatePreviewParametersJson = React.useMemo(() => {
    if (!templatePreview) return ''
    const parameters = templatePreview.binding_preview?.parameters ?? {}
    const entries = Object.entries(parameters)
    if (entries.length === 0) return ''
    return JSON.stringify(parameters, null, 2)
  }, [templatePreview])
  const templatePreviewSkillNames = React.useMemo(() => {
    const raw = templatePreview?.seed_blueprint?.skills
    if (!Array.isArray(raw) || raw.length === 0) return []
    return raw
      .map((item) => {
        if (!item || typeof item !== 'object') return ''
        const payload = item as Record<string, unknown>
        const name = String(payload.name || '').trim()
        const key = String(payload.skill_key || '').trim()
        return name || key
      })
      .filter(Boolean)
  }, [templatePreview])
  const previewCanCreate = Boolean(templatePreview?.project_conflict?.can_create)
  const previewConflictStatus = String(templatePreview?.project_conflict?.status || '').trim()
  const canPreviewTemplatePlan =
    templateMode && !previewProjectFromTemplateMutation.isPending && !createProjectMutation.isPending
  const canCreateProject =
    Boolean(projectName.trim()) &&
    !createProjectMutation.isPending &&
    (!templateMode || previewCanCreate)

  const conflictMessage = React.useMemo(() => {
    if (!templateMode || !templatePreview) return ''
    if (previewConflictStatus === 'none') return 'No project name conflict detected.'
    if (previewConflictStatus === 'active') return 'A project with this name already exists in this workspace.'
    if (previewConflictStatus === 'deleted') {
      return 'A deleted project with this name exists; choose another name.'
    }
    if (previewConflictStatus === 'name_missing') return 'Enter a project name to validate conflicts.'
    return `Project conflict status: ${previewConflictStatus}`
  }, [previewConflictStatus, templateMode, templatePreview])
  const chatPolicyDisabled = !projectEmbeddingEnabled
  const effectiveProjectChatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' = chatPolicyDisabled
    ? 'OFF'
    : projectChatIndexMode
  const chatAttachmentDisabled = chatPolicyDisabled || effectiveProjectChatIndexMode === 'OFF'
  const [createFormSections, setCreateFormSections] = React.useState<string[]>([
    'setup',
    'retrieval',
    'rules',
    'resources',
  ])
  const [createMemberSearch, setCreateMemberSearch] = React.useState('')
  const projectTemplateSelectValue = projectTemplateKey || '__manual__'
  const projectTemplateOptions = React.useMemo<ProjectCreateSelectOption[]>(
    () => [
      { value: '__manual__', label: 'Manual setup (no template)' },
      ...projectTemplates.map((template) => ({
        value: template.key,
        label: template.name,
      })),
    ],
    [projectTemplates]
  )
  const embeddingModelSelectOptions = React.useMemo<ProjectCreateSelectOption[]>(
    () =>
      modelOptions.length > 0
        ? modelOptions.map((model) => ({
            value: model,
            label: model === defaultModel ? `${model} (default)` : model,
          }))
        : [{ value: '__none__', label: 'No embedding models available', disabled: true }],
    [defaultModel, modelOptions]
  )
  const chatMessageModeOptions = React.useMemo<ProjectCreateSelectOption[]>(
    () => [
      { value: 'OFF', label: 'OFF' },
      { value: 'VECTOR_ONLY', label: 'VECTOR_ONLY' },
      { value: 'KG_AND_VECTOR', label: 'KG_AND_VECTOR' },
    ],
    []
  )
  const chatAttachmentModeOptions = React.useMemo<ProjectCreateSelectOption[]>(
    () => [
      { value: 'METADATA_ONLY', label: 'METADATA_ONLY' },
      { value: 'OFF', label: 'OFF' },
      { value: 'FULL_TEXT', label: 'FULL_TEXT' },
    ],
    []
  )
  const selectedMemberSet = React.useMemo(
    () => new Set(createProjectMemberIds.map((value) => String(value || '').trim()).filter(Boolean)),
    [createProjectMemberIds]
  )
  const filteredWorkspaceUsers = React.useMemo(() => {
    const query = String(createMemberSearch || '').trim().toLowerCase()
    if (!query) return workspaceUsers
    return workspaceUsers.filter((user) => {
      const name = String(user.full_name || '').toLowerCase()
      const userType = String(user.user_type || '').toLowerCase()
      return name.includes(query) || userType.includes(query)
    })
  }, [createMemberSearch, workspaceUsers])
  const selectedWorkspaceUsers = React.useMemo(
    () => workspaceUsers.filter((user) => selectedMemberSet.has(String(user.id || '').trim())),
    [selectedMemberSet, workspaceUsers]
  )
  const canSelectAllMembers = workspaceUsers.some((user) => !selectedMemberSet.has(String(user.id || '').trim()))
  const canClearMembers = selectedMemberSet.size > 0
  const sectionMetaSetup = templateMode
    ? `Template: ${selectedTemplate?.name || projectTemplateKey}`
    : 'Manual project setup'
  const sectionMetaRetrieval = projectEmbeddingEnabled
    ? `Embeddings on · Chat ${effectiveProjectChatIndexMode}`
    : 'Embeddings off · Chat OFF'
  const sectionMetaResources = `${selectedWorkspaceUsers.length} member${selectedWorkspaceUsers.length === 1 ? '' : 's'} selected`
  const sectionMetaRules = `${draftProjectRules.length} draft rule${draftProjectRules.length === 1 ? '' : 's'}`

  const runTemplatePreview = React.useCallback(() => {
    if (!canPreviewTemplatePlan) return
    previewProjectFromTemplateMutation.mutate()
  }, [canPreviewTemplatePlan, previewProjectFromTemplateMutation])

  const runCreate = React.useCallback(() => {
    if (!projectName.trim() || createProjectMutation.isPending) return
    if (!templateMode) {
      createProjectMutation.mutate()
      return
    }
    if (!templatePreview) {
      runTemplatePreview()
      return
    }
    if (!previewCanCreate) return
    createProjectMutation.mutate()
  }, [
    createProjectMutation,
    previewCanCreate,
    projectName,
    runTemplatePreview,
    templateMode,
    templatePreview,
  ])
  const selectAllMembers = React.useCallback(() => {
    for (const user of workspaceUsers) {
      const userId = String(user.id || '').trim()
      if (!userId || selectedMemberSet.has(userId)) continue
      toggleCreateProjectMember(userId)
    }
  }, [selectedMemberSet, toggleCreateProjectMember, workspaceUsers])
  const clearAllMembers = React.useCallback(() => {
    for (const user of workspaceUsers) {
      const userId = String(user.id || '').trim()
      if (!userId || !selectedMemberSet.has(userId)) continue
      toggleCreateProjectMember(userId)
    }
  }, [selectedMemberSet, toggleCreateProjectMember, workspaceUsers])

  const resetTemplatePreview = previewProjectFromTemplateMutation.reset
  React.useEffect(() => {
    resetTemplatePreview()
  }, [
    resetTemplatePreview,
    projectTemplateKey,
    projectName,
    projectDescription,
    projectCustomStatusesText,
    projectEmbeddingEnabled,
    projectEmbeddingModel,
    projectContextPackEvidenceTopKText,
    projectChatIndexMode,
    projectChatAttachmentIngestionMode,
    projectTemplateParametersText,
    createProjectMemberIds,
  ])

  return (
    <div className="project-create-form">
      <div className="project-create-headrow">
        <h3 style={{ margin: 0 }}>Create project</h3>
        <span className="meta">{templateMode ? 'Template flow' : 'Manual flow'}</span>
      </div>

      <label className="field-control project-create-name-field">
        <span className="field-label">Project name</span>
        <input
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              runCreate()
            }
          }}
          placeholder="New project"
        />
      </label>

      <div className="project-create-actions-bar project-create-actions-bar-top">
        {templateMode ? (
          <button
            type="button"
            className="status-chip"
            disabled={!canPreviewTemplatePlan}
            onClick={runTemplatePreview}
            title="Preview template creation plan"
            aria-label="Preview template creation plan"
          >
            {previewProjectFromTemplateMutation.isPending ? 'Previewing...' : 'Preview plan'}
          </button>
        ) : null}
        <button
          type="button"
          className="primary project-create-submit-btn"
          disabled={!canCreateProject}
          onClick={runCreate}
          title={templateMode ? 'Create project from previewed template' : 'Create project'}
          aria-label={templateMode ? 'Create project from previewed template' : 'Create project'}
        >
          <Icon path="M12 5v14M5 12h14" />
          <span>{createProjectMutation.isPending ? 'Creating...' : 'Create project'}</span>
        </button>
      </div>

      <Accordion.Root
        className="project-create-sections"
        type="multiple"
        value={createFormSections}
        onValueChange={setCreateFormSections}
      >
        <Accordion.Item className="project-create-section-item" value="setup">
          <Accordion.Header>
            <Accordion.Trigger className="project-create-section-trigger">
              <span className="project-create-section-head">
                <span className="project-create-section-title">Setup</span>
                <span className="meta">{sectionMetaSetup}</span>
              </span>
              <span className="project-create-section-chevron" aria-hidden="true">
                <Icon path="M6 9l6 6 6-6" />
              </span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content className="project-create-section-content">
            <label className="field-control" style={{ marginBottom: 10 }}>
              <span className="field-label">Project template</span>
              <ProjectCreateSelect
                value={projectTemplateSelectValue}
                onValueChange={(value) => {
                  const next = value === '__manual__' ? '' : value
                  setProjectTemplateKey(next)
                  if (!next) return
                  const template = projectTemplates.find((item) => item.key === next)
                  if (!template) return
                  setProjectCustomStatusesText((template.default_custom_statuses ?? []).join(', '))
                  setProjectEmbeddingEnabled(Boolean(template.default_embedding_enabled))
                  if (template.default_embedding_enabled && !String(projectEmbeddingModel || '').trim() && defaultModel) {
                    setProjectEmbeddingModel(defaultModel)
                  }
                  if (!template.default_embedding_enabled) {
                    setProjectEmbeddingModel('')
                    setProjectChatIndexMode('OFF')
                    setProjectChatAttachmentIngestionMode('METADATA_ONLY')
                  }
                  setProjectContextPackEvidenceTopKText(
                    template.default_context_pack_evidence_top_k == null
                      ? ''
                      : String(template.default_context_pack_evidence_top_k)
                  )
                }}
                options={projectTemplateOptions}
                disabled={projectTemplatesLoading}
                ariaLabel="Project template"
                placeholder="Select template"
              />
              {selectedTemplate ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  {selectedTemplate.description}
                  {' · '}
                  Seed specs: {selectedTemplate.seed_counts.specifications}, tasks: {selectedTemplate.seed_counts.tasks}, rules:{' '}
                  {selectedTemplate.seed_counts.rules}, skills: {selectedTemplate.seed_counts.skills ?? 0}
                </div>
              ) : (
                <div className="meta" style={{ marginTop: 6 }}>
                  Use manual mode for a blank project, or pick a template to seed initial specs, tasks, rules, and skills.
                </div>
              )}
            </label>
            {templateMode ? (
              <div className="field-control" style={{ marginBottom: 10 }}>
                <span className="field-label">Template plan preview</span>
                {previewProjectFromTemplateMutation.isPending ? (
                  <div className="meta">Building preview...</div>
                ) : !templatePreview ? (
                  <div className="meta">
                    Run preview to validate creation and inspect what will be seeded before creating the project.
                  </div>
                ) : (
                  <div className="meta">
                    Seed specs: {templatePreview.seed_summary.specification_count}, tasks: {templatePreview.seed_summary.task_count},
                    rules: {templatePreview.seed_summary.rule_count}, skills: {templatePreview.seed_summary.skill_count ?? 0},
                    graph nodes: {templatePreview.seed_summary.graph_node_count}, graph edges: {templatePreview.seed_summary.graph_edge_count}.
                    {' '}
                    {conflictMessage}
                  </div>
                )}
                {templatePreview ? (
                  <div className="meta" style={{ marginTop: 6 }}>
                    Resolved statuses: {templatePreview.project_blueprint.custom_statuses.join(', ') || '(none)'}.
                    {' '}
                    Embeddings: {templatePreview.project_blueprint.embedding_enabled ? 'enabled' : 'disabled'}
                    {templatePreview.project_blueprint.embedding_model
                      ? ` (${templatePreview.project_blueprint.embedding_model})`
                      : ''}.
                    {' '}
                    Context top K:{' '}
                    {templatePreview.project_blueprint.context_pack_evidence_top_k == null
                      ? 'default'
                      : templatePreview.project_blueprint.context_pack_evidence_top_k}
                    .
                    {' '}
                    Chat indexing: {templatePreview.project_blueprint.chat_index_mode}.
                    {' '}
                    Chat attachment ingestion: {templatePreview.project_blueprint.chat_attachment_ingestion_mode}.
                  </div>
                ) : null}
                {templatePreviewParametersJson ? (
                  <div className="meta" style={{ marginTop: 6 }}>
                    Applied parameters:
                    <pre style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap' }}>{templatePreviewParametersJson}</pre>
                  </div>
                ) : null}
                {templatePreviewSkillNames.length > 0 ? (
                  <div className="meta" style={{ marginTop: 6 }}>
                    Seeded skills: {templatePreviewSkillNames.join(', ')}
                  </div>
                ) : null}
              </div>
            ) : null}
            {templateMode ? (
              <label className="field-control" style={{ marginBottom: 10 }}>
                <span className="field-label">Template parameters (JSON, optional)</span>
                <textarea
                  value={projectTemplateParametersText}
                  onChange={(e) => setProjectTemplateParametersText(e.target.value)}
                  placeholder='{"domain_name":"Order","bounded_context_name":"Sales Context"}'
                  rows={4}
                  style={{ width: '100%', minHeight: 84 }}
                />
                <div className="meta" style={{ marginTop: 6 }}>
                  Parameters are applied in template preview and template create.
                </div>
              </label>
            ) : null}
            <div className="md-editor-surface" style={{ marginBottom: 10 }}>
              <MarkdownModeToggle
                view={projectDescriptionView}
                onChange={setProjectDescriptionView}
                ariaLabel="Project description editor view"
              />
              <div className="md-editor-content">
                {projectDescriptionView === 'write' ? (
                  <textarea
                    className="md-textarea"
                    ref={projectDescriptionRef}
                    value={projectDescription}
                    onChange={(e) => setProjectDescription(e.target.value)}
                    placeholder="Project description (Markdown)"
                    style={{ width: '100%', minHeight: 96, maxHeight: 280, resize: 'none', overflowY: 'hidden' }}
                  />
                ) : projectDescriptionView === 'split' ? (
                  <MarkdownSplitPane
                    left={(
                      <textarea
                        className="md-textarea"
                        ref={projectDescriptionRef}
                        value={projectDescription}
                        onChange={(e) => setProjectDescription(e.target.value)}
                        placeholder="Project description (Markdown)"
                        style={{ width: '100%' }}
                      />
                    )}
                    right={<MarkdownView value={projectDescription} />}
                    ariaLabel="Resize project description editor and preview panels"
                  />
                ) : (
                  <MarkdownView value={projectDescription} />
                )}
              </div>
            </div>
            <label className="field-control">
              <span className="field-label">Board statuses (comma-separated)</span>
              <input
                value={projectCustomStatusesText}
                onChange={(e) => setProjectCustomStatusesText(e.target.value)}
                placeholder="To do, In progress, Blocked, Ready for QA, Done"
              />
            </label>
          </Accordion.Content>
        </Accordion.Item>

        <Accordion.Item className="project-create-section-item" value="retrieval">
          <Accordion.Header>
            <Accordion.Trigger className="project-create-section-trigger">
              <span className="project-create-section-head">
                <span className="project-create-section-title">Retrieval and Chat</span>
                <span className="meta">{sectionMetaRetrieval}</span>
              </span>
              <span className="project-create-section-chevron" aria-hidden="true">
                <Icon path="M6 9l6 6 6-6" />
              </span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content className="project-create-section-content">
            <div className="field-control" style={{ marginBottom: 10 }}>
              <span className="field-label">Embeddings</span>
              <div className="row wrap" style={{ gap: 10, alignItems: 'center' }}>
                <label className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <input
                    type="checkbox"
                    checked={projectEmbeddingEnabled}
                    onChange={(e) => {
                      const next = e.target.checked
                      setProjectEmbeddingEnabled(next)
                      if (next && !String(projectEmbeddingModel || '').trim() && defaultModel) {
                        setProjectEmbeddingModel(defaultModel)
                      }
                      if (!next) {
                        setProjectChatIndexMode('OFF')
                        setProjectChatAttachmentIngestionMode('METADATA_ONLY')
                      }
                    }}
                  />
                  <span>Embedding enabled</span>
                </label>
                <ProjectCreateSelect
                  value={modelOptions.length > 0 ? selectedModel : '__none__'}
                  disabled={!projectEmbeddingEnabled || modelOptions.length === 0}
                  onValueChange={(value) => {
                    if (value === '__none__') return
                    setProjectEmbeddingModel(value)
                  }}
                  options={embeddingModelSelectOptions}
                  ariaLabel="Embedding model"
                  placeholder="Select embedding model"
                />
                <span className="badge">Index: Not indexed</span>
              </div>
              <label className="field-control" style={{ marginTop: 8 }}>
                <span className="field-label">Context pack evidence top K (optional override)</span>
                <input
                  type="number"
                  min={1}
                  max={40}
                  step={1}
                  value={projectContextPackEvidenceTopKText}
                  onChange={(e) => setProjectContextPackEvidenceTopKText(e.target.value)}
                  placeholder={String(contextPackEvidenceTopKDefault || 10)}
                  inputMode="numeric"
                />
              </label>
              <div className="meta" style={{ marginTop: 6 }}>
                Leave empty to use global default ({contextPackEvidenceTopKDefault || 10}).
              </div>
              {!vectorStoreEnabled ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Vector store is currently unavailable. Project retrieval runs in graph-only mode.
                </div>
              ) : !projectEmbeddingEnabled ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Vector store is enabled globally. Enable embeddings for this project to use graph+vector retrieval.
                </div>
              ) : (
                <div className="meta" style={{ marginTop: 6 }}>
                  Indexing starts after project creation.
                </div>
              )}
            </div>
            <div className="field-control">
              <div
                className="row wrap"
                style={{ gap: 10, alignItems: 'center', marginBottom: 8, padding: '8px 10px', border: '1px solid var(--line)', borderRadius: 8 }}
              >
                <span className="field-label" style={{ marginBottom: 0 }}>Event Storming</span>
                <label className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <input
                    type="checkbox"
                    checked={projectEventStormingEnabled ?? true}
                    onChange={(e) => setProjectEventStormingEnabled(Boolean(e.target.checked))}
                  />
                  <span>Enable processing</span>
                </label>
              </div>
              <div className="project-chat-policy-inline">
                <span className="field-label">Chat indexing policy</span>
                <div className="project-chat-policy-controls">
                  <label className="field-control project-chat-policy-select">
                    <span className="field-label">Messages</span>
                    <ProjectCreateSelect
                      value={effectiveProjectChatIndexMode}
                      disabled={chatPolicyDisabled}
                      onValueChange={(next) => {
                        if (next === 'VECTOR_ONLY' || next === 'KG_AND_VECTOR') {
                          setProjectChatIndexMode(next)
                          return
                        }
                        setProjectChatIndexMode('OFF')
                      }}
                      options={chatMessageModeOptions}
                      ariaLabel="Chat message indexing mode"
                      placeholder="Select message indexing mode"
                    />
                  </label>
                  <label className="field-control project-chat-policy-select">
                    <span className="field-label">Attachments</span>
                    <ProjectCreateSelect
                      value={projectChatAttachmentIngestionMode}
                      disabled={chatAttachmentDisabled}
                      onValueChange={(next) => {
                        if (next === 'OFF' || next === 'FULL_TEXT') {
                          setProjectChatAttachmentIngestionMode(next)
                          return
                        }
                        setProjectChatAttachmentIngestionMode('METADATA_ONLY')
                      }}
                      options={chatAttachmentModeOptions}
                      ariaLabel="Chat attachment ingestion mode"
                      placeholder="Select attachment ingestion mode"
                    />
                  </label>
                </div>
              </div>
              {chatPolicyDisabled ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Enable embeddings to configure chat indexing. While embeddings are disabled, chat indexing mode is forced to OFF.
                </div>
              ) : effectiveProjectChatIndexMode === 'OFF' ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Chat history stays operational-only and is excluded from Knowledge Graph and vector search.
                </div>
              ) : effectiveProjectChatIndexMode === 'VECTOR_ONLY' ? (
                <div className="meta" style={{ marginTop: 6 }}>
                  Chat history is indexed for semantic vector search; graph relations are not created from chat events.
                </div>
              ) : (
                <div className="meta" style={{ marginTop: 6 }}>
                  Chat history can contribute graph relations and semantic retrieval context for this project.
                </div>
              )}
            </div>
          </Accordion.Content>
        </Accordion.Item>

        <Accordion.Item className="project-create-section-item" value="rules">
          <Accordion.Header>
            <Accordion.Trigger className="project-create-section-trigger">
              <span className="project-create-section-head">
                <span className="project-create-section-title">Rules</span>
                <span className="meta">{sectionMetaRules}</span>
              </span>
              <span className="project-create-section-chevron" aria-hidden="true">
                <Icon path="M6 9l6 6 6-6" />
              </span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content className="project-create-section-content">
            <div className="rules-studio">
              <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                <h3 style={{ margin: 0 }}>Project Rules (Draft: {draftProjectRules.length})</h3>
                <div className="meta">These rules are created with the new project.</div>
              </div>
              <div className="rules-layout">
                <div className="rules-list">
                  {draftProjectRules.length === 0 ? (
                    <div className="notice">No draft rules yet.</div>
                  ) : (
                    draftProjectRules.map((rule) => {
                      const isSelected = selectedDraftProjectRuleId === rule.id
                      return (
                        <div
                          key={rule.id}
                          className={`task-item rule-item ${isSelected ? 'selected' : ''}`}
                          onClick={() => setSelectedDraftProjectRuleId(rule.id)}
                          role="button"
                        >
                          <div className="task-main">
                            <div className="task-title">
                              <strong>{rule.title || 'Untitled rule'}</strong>
                              <div className="row" style={{ gap: 6 }}>
                                {isSelected && <span className="badge">Editing</span>}
                                <button
                                  className="action-icon danger-ghost"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    setDraftProjectRules((prev) => prev.filter((item) => item.id !== rule.id))
                                    if (selectedDraftProjectRuleId === rule.id) {
                                      setSelectedDraftProjectRuleId(null)
                                      setDraftProjectRuleTitle('')
                                      setDraftProjectRuleBody('')
                                    }
                                  }}
                                  title="Delete draft rule"
                                  aria-label="Delete draft rule"
                                >
                                  <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                                </button>
                              </div>
                            </div>
                            <div className="meta">{(rule.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                          </div>
                        </div>
                      )
                    })
                  )}
                  <div
                    className="task-item rule-item add-new-rule-item"
                    role="button"
                    onClick={() => {
                      setSelectedDraftProjectRuleId(null)
                      setDraftProjectRuleTitle('')
                      setDraftProjectRuleBody('')
                      setDraftProjectRuleView('write')
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
                  <div className="row rule-title-row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                    <input
                      className="rule-title-input"
                      value={draftProjectRuleTitle}
                      onChange={(e) => setDraftProjectRuleTitle(e.target.value)}
                      placeholder="Rule title"
                    />
                    <button
                      className="action-icon primary"
                      disabled={!draftProjectRuleTitle.trim()}
                      onClick={() => {
                        const title = draftProjectRuleTitle.trim()
                        if (!title) return
                        if (selectedDraftProjectRuleId) {
                          setDraftProjectRules((prev) =>
                            prev.map((item) =>
                              item.id === selectedDraftProjectRuleId
                                ? { ...item, title, body: draftProjectRuleBody }
                                : item
                            )
                          )
                        } else {
                          const newId = globalThis.crypto?.randomUUID?.() ?? `draft-rule-${Date.now()}`
                          setDraftProjectRules((prev) => [...prev, { id: newId, title, body: draftProjectRuleBody }])
                          setSelectedDraftProjectRuleId(newId)
                        }
                      }}
                      title={selectedDraftProjectRuleId ? 'Update draft rule' : 'Add draft rule'}
                      aria-label={selectedDraftProjectRuleId ? 'Update draft rule' : 'Add draft rule'}
                    >
                      <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                    </button>
                  </div>
                  <div className="md-editor-surface">
                    <MarkdownModeToggle
                      view={draftProjectRuleView}
                      onChange={setDraftProjectRuleView}
                      ariaLabel="Draft project rule editor view"
                    />
                    <div className="md-editor-content">
                      {draftProjectRuleView === 'write' ? (
                        <textarea
                          className="md-textarea"
                          value={draftProjectRuleBody}
                          onChange={(e) => setDraftProjectRuleBody(e.target.value)}
                          placeholder="Rule details (Markdown)"
                          style={{ width: '100%', minHeight: 140 }}
                        />
                      ) : draftProjectRuleView === 'split' ? (
                        <MarkdownSplitPane
                          left={(
                            <textarea
                              className="md-textarea"
                              value={draftProjectRuleBody}
                              onChange={(e) => setDraftProjectRuleBody(e.target.value)}
                              placeholder="Rule details (Markdown)"
                              style={{ width: '100%', minHeight: 140 }}
                            />
                          )}
                          right={<MarkdownView value={draftProjectRuleBody} />}
                          ariaLabel="Resize project rule editor and preview panels"
                        />
                      ) : (
                        <MarkdownView value={draftProjectRuleBody} />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </Accordion.Content>
        </Accordion.Item>

        <Accordion.Item className="project-create-section-item" value="resources">
          <Accordion.Header>
            <Accordion.Trigger className="project-create-section-trigger">
              <span className="project-create-section-head">
                <span className="project-create-section-title">Resources and Members</span>
                <span className="meta">{sectionMetaResources}</span>
              </span>
              <span className="project-create-section-chevron" aria-hidden="true">
                <Icon path="M6 9l6 6 6-6" />
              </span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Content className="project-create-section-content">
            <div className="meta" style={{ marginBottom: 8 }}>External links</div>
            <ExternalRefEditor
              refs={parseExternalRefsText(projectExternalRefsText)}
              onRemoveIndex={(idx) => setProjectExternalRefsText((prev) => removeExternalRefByIndex(prev, idx))}
              onAdd={(ref) =>
                setProjectExternalRefsText((prev) => externalRefsToText([...parseExternalRefsText(prev), ref]))
              }
            />
            <div className="meta" style={{ marginTop: 8 }}>
              File attachments are available after project is created.
            </div>

            <div className="project-create-members-block">
              <div className="project-create-members-head">
                <span className="field-label">Assign users to project</span>
                <DropdownMenu.Root
                  onOpenChange={(open) => {
                    if (!open) setCreateMemberSearch('')
                  }}
                >
                  <DropdownMenu.Trigger asChild>
                    <button
                      type="button"
                      className="status-chip project-create-members-trigger"
                      title="Manage project members"
                      aria-label="Manage project members"
                    >
                      <Icon path="M16 11a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm-8 1a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm8 2c-3.3 0-6 1.34-6 3v1h12v-1c0-1.66-2.7-3-6-3ZM8 14c-.58 0-1.13.05-1.66.13C4.35 14.42 3 15.18 3 16v1h6v-1c0-.77.32-1.45.87-2-.58-.02-1.2-.03-1.87-.03Z" />
                      <span>Members</span>
                      <span className="badge">{selectedWorkspaceUsers.length}</span>
                    </button>
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content className="task-group-menu-content project-create-members-menu-content" sideOffset={8} align="end">
                      <div className="project-create-members-menu-head">
                        <input
                          value={createMemberSearch}
                          onChange={(e) => setCreateMemberSearch(e.target.value)}
                          placeholder="Filter users"
                          aria-label="Filter workspace users"
                        />
                        <div className="row wrap project-create-members-menu-actions">
                          <button
                            type="button"
                            className="status-chip"
                            onClick={selectAllMembers}
                            disabled={!canSelectAllMembers}
                          >
                            Select all
                          </button>
                          <button
                            type="button"
                            className="status-chip"
                            onClick={clearAllMembers}
                            disabled={!canClearMembers}
                          >
                            Clear
                          </button>
                        </div>
                      </div>
                      <div className="project-create-members-menu-list">
                        {filteredWorkspaceUsers.length === 0 ? (
                          <div className="meta">No users match your filter.</div>
                        ) : (
                          filteredWorkspaceUsers.map((user) => {
                            const selected = selectedMemberSet.has(String(user.id || '').trim())
                            return (
                              <DropdownMenu.CheckboxItem
                                key={`create-member-menu-${user.id}`}
                                className="task-group-menu-item project-create-members-menu-item"
                                checked={selected}
                                onCheckedChange={() => toggleCreateProjectMember(user.id)}
                              >
                                <span className="project-create-members-menu-item-main">
                                  <span>{user.full_name}</span>
                                  <span className="meta">{user.user_type}</span>
                                </span>
                                <DropdownMenu.ItemIndicator className="quickadd-project-item-indicator">
                                  <Icon path="m5 13 4 4L19 7" />
                                </DropdownMenu.ItemIndicator>
                              </DropdownMenu.CheckboxItem>
                            )
                          })
                        )}
                      </div>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </div>
              {selectedWorkspaceUsers.length === 0 ? (
                <div className="meta">No members selected.</div>
              ) : (
                <div className="row wrap project-create-members-selected">
                  {selectedWorkspaceUsers.map((user) => (
                    <button
                      key={`selected-create-member-${user.id}`}
                      type="button"
                      className="status-chip project-member-chip active"
                      onClick={() => toggleCreateProjectMember(user.id)}
                      title={`Remove ${user.full_name}`}
                      aria-label={`Remove ${user.full_name}`}
                    >
                      <span>{user.full_name}</span>
                      <Icon path="M6 6l12 12M18 6 6 18" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </Accordion.Content>
        </Accordion.Item>
      </Accordion.Root>
    </div>
  )
}
