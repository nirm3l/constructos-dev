import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import { ExternalRefEditor, Icon, MarkdownModeToggle } from '../shared/uiHelpers'
import { externalRefsToText, parseExternalRefsText, removeExternalRefByIndex } from '../../utils/ui'
import type { ProjectFromTemplatePreviewResponse, ProjectTemplate } from '../../types'

export type DraftProjectRule = { id: string; title: string; body: string }

type WorkspaceUser = {
  id: string
  full_name: string
  user_type: string
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
  projectTemplateParametersText: string
  setProjectTemplateParametersText: React.Dispatch<React.SetStateAction<string>>
  embeddingAllowedModels: string[]
  embeddingDefaultModel: string
  vectorStoreEnabled: boolean
  contextPackEvidenceTopKDefault: number
  projectDescriptionView: 'write' | 'preview'
  setProjectDescriptionView: React.Dispatch<React.SetStateAction<'write' | 'preview'>>
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
  draftProjectRuleView: 'write' | 'preview'
  setDraftProjectRuleView: React.Dispatch<React.SetStateAction<'write' | 'preview'>>
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
    projectTemplateParametersText,
    createProjectMemberIds,
  ])

  return (
    <div style={{ marginBottom: 10 }}>
      <h3 style={{ margin: '0 0 8px 0' }}>Create project</h3>
      <div className="row" style={{ marginBottom: 10 }}>
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
        {templateMode ? (
          <button
            type="button"
            className="status-chip"
            disabled={!canPreviewTemplatePlan}
            onClick={runTemplatePreview}
            title="Preview template creation plan"
            aria-label="Preview template creation plan"
          >
            Preview plan
          </button>
        ) : null}
        <button
          type="button"
          className="primary"
          disabled={!canCreateProject}
          onClick={runCreate}
          title={templateMode ? 'Create project from previewed template' : 'Create project'}
          aria-label={templateMode ? 'Create project from previewed template' : 'Create project'}
        >
          <Icon path="M12 5v14M5 12h14" />
        </button>
      </div>
      <label className="field-control" style={{ marginBottom: 10 }}>
        <span className="field-label">Project template</span>
        <select
          value={projectTemplateKey}
          onChange={(e) => {
            const next = e.target.value
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
            }
            setProjectContextPackEvidenceTopKText(
              template.default_context_pack_evidence_top_k == null
                ? ''
                : String(template.default_context_pack_evidence_top_k)
            )
          }}
          disabled={projectTemplatesLoading}
        >
          <option value="">Manual setup (no template)</option>
          {projectTemplates.map((template) => (
            <option key={`project-template-${template.key}`} value={template.key}>
              {template.name}
            </option>
          ))}
        </select>
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
          ) : (
            <MarkdownView value={projectDescription} />
          )}
        </div>
      </div>
      <label className="field-control" style={{ marginBottom: 10 }}>
        <span className="field-label">Board statuses (comma-separated)</span>
        <input
          value={projectCustomStatusesText}
          onChange={(e) => setProjectCustomStatusesText(e.target.value)}
          placeholder="To do, In progress, Blocked, Ready for QA, Done"
        />
      </label>
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
              }}
            />
            <span>Embedding enabled</span>
          </label>
          <select
            value={selectedModel}
            disabled={!projectEmbeddingEnabled || modelOptions.length === 0}
            onChange={(e) => setProjectEmbeddingModel(e.target.value)}
          >
            {modelOptions.map((model) => (
              <option key={`create-embedding-model-${model}`} value={model}>
                {model === defaultModel ? `${model} (default)` : model}
              </option>
            ))}
          </select>
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
      <div className="rules-studio" style={{ marginTop: 10, marginBottom: 14 }}>
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
                ) : (
                  <MarkdownView value={draftProjectRuleBody} />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="meta" style={{ marginTop: 10 }}>External links</div>
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
      <div style={{ marginTop: 10 }}>
        <div className="meta" style={{ marginBottom: 6 }}>Assign users to project</div>
        <div className="row wrap" style={{ gap: 6 }}>
          {workspaceUsers.map((u) => {
            const selected = createProjectMemberIds.includes(u.id)
            return (
              <button
                key={`create-member-${u.id}`}
                type="button"
                className={`status-chip project-member-chip ${selected ? 'active' : ''}`}
                onClick={() => toggleCreateProjectMember(u.id)}
                aria-pressed={selected}
                title={`${u.full_name} (${u.user_type})`}
              >
                {u.full_name} · {u.user_type}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
