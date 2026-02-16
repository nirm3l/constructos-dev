import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { AttachmentRef, Project, ProjectRule, ProjectRulesPage } from '../../types'
import { AttachmentRefList, ExternalRefEditor, Icon, MarkdownModeToggle } from '../shared/uiHelpers'
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
  saveProjectMutation,
  deleteProjectMutation,
  editProjectDescriptionView,
  setEditProjectDescriptionView,
  editProjectDescriptionRef,
  editProjectDescription,
  setEditProjectDescription,
  projectRules,
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
  saveProjectMutation: ProjectMutation
  deleteProjectMutation: ProjectMutation
  editProjectDescriptionView: 'write' | 'preview'
  setEditProjectDescriptionView: React.Dispatch<React.SetStateAction<'write' | 'preview'>>
  editProjectDescriptionRef: React.RefObject<HTMLTextAreaElement | null>
  editProjectDescription: string
  setEditProjectDescription: React.Dispatch<React.SetStateAction<string>>
  projectRules: { data?: ProjectRulesPage }
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
          disabled={saveProjectMutation.isPending || !editProjectName.trim() || !projectIsDirty}
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
      <div className="rules-studio" style={{ marginTop: 10, marginBottom: 14 }}>
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
                return (
                  <div
                    key={rule.id}
                    className={`task-item rule-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedProjectRuleId(rule.id)}
                    role="button"
                  >
                    <div className="task-main">
                      <div className="task-title">
                        <strong>{rule.title || 'Untitled rule'}</strong>
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
                className={`status-chip ${selected ? 'active' : ''}`}
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
      </div>
    </div>
  )
}
