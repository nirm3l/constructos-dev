import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import { ExternalRefEditor, Icon, MarkdownModeToggle } from '../shared/uiHelpers'
import { externalRefsToText, parseExternalRefsText, removeExternalRefByIndex } from '../../utils/ui'

export type DraftProjectRule = { id: string; title: string; body: string }

type WorkspaceUser = {
  id: string
  full_name: string
  user_type: string
}

export function ProjectsCreateForm({
  projectName,
  setProjectName,
  createProjectMutation,
  projectCustomStatusesText,
  setProjectCustomStatusesText,
  projectEmbeddingEnabled,
  setProjectEmbeddingEnabled,
  projectEmbeddingModel,
  setProjectEmbeddingModel,
  projectContextPackEvidenceTopKText,
  setProjectContextPackEvidenceTopKText,
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
  createProjectMutation: { mutate: () => void; isPending: boolean }
  projectCustomStatusesText: string
  setProjectCustomStatusesText: React.Dispatch<React.SetStateAction<string>>
  projectEmbeddingEnabled: boolean
  setProjectEmbeddingEnabled: React.Dispatch<React.SetStateAction<boolean>>
  projectEmbeddingModel: string
  setProjectEmbeddingModel: React.Dispatch<React.SetStateAction<string>>
  projectContextPackEvidenceTopKText: string
  setProjectContextPackEvidenceTopKText: React.Dispatch<React.SetStateAction<string>>
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

  return (
    <div style={{ marginBottom: 10 }}>
      <h3 style={{ margin: '0 0 8px 0' }}>Create project</h3>
      <div className="row" style={{ marginBottom: 10 }}>
        <input
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              const name = projectName.trim()
              if (!name || createProjectMutation.isPending) return
              createProjectMutation.mutate()
            }
          }}
          placeholder="New project"
        />
        <button
          className="primary"
          disabled={!projectName.trim() || createProjectMutation.isPending}
          onClick={() => createProjectMutation.mutate()}
        >
          <Icon path="M12 5v14M5 12h14" />
        </button>
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
      <div className="md-editor-surface">
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
