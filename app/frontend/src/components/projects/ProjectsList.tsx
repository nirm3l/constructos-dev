import React from 'react'
import type { Project } from '../../types'
import { AttachmentRefList, ExternalRefList, Icon } from '../shared/uiHelpers'

type CountQuery = { data?: { total?: number } }

export function ProjectsList({
  projects,
  selectedProjectId,
  showProjectEditForm,
  selectedProject,
  projectTaskCountQueries,
  projectNoteCountQueries,
  projectRuleCountQueries,
  projectMemberCounts,
  workspaceId,
  userId,
  toggleProjectEditor,
  onCopyShareLink,
  renderInlineEditor,
}: {
  projects: Project[]
  selectedProjectId: string
  showProjectEditForm: boolean
  selectedProject: Project | null
  projectTaskCountQueries: CountQuery[]
  projectNoteCountQueries: CountQuery[]
  projectRuleCountQueries: CountQuery[]
  projectMemberCounts: Record<string, number>
  workspaceId: string
  userId: string
  toggleProjectEditor: (projectId: string) => void
  onCopyShareLink: (projectId: string) => void
  renderInlineEditor: (project: Project) => React.ReactNode
}) {
  return (
    <div className="task-list">
      {projects.map((project, idx) => {
        const isSelected = selectedProjectId === project.id
        const isOpen = isSelected && showProjectEditForm && selectedProject?.id === project.id
        const taskCount = projectTaskCountQueries[idx]?.data?.total
        const noteCount = projectNoteCountQueries[idx]?.data?.total
        const ruleCount = projectRuleCountQueries[idx]?.data?.total
        return (
          <div key={project.id} className={`task-item project-item ${isOpen ? 'open selected' : isSelected ? 'selected' : ''}`}>
            <div className="task-main" role="button" onClick={() => toggleProjectEditor(project.id)}>
              <div className="task-title">
                <strong>{project.name}</strong>
              </div>
              <span className="meta">Status: {project.status || 'active'}</span>
              <div className="meta">{project.description || '(no description)'}</div>
              <div className="meta">
                {[
                  typeof taskCount === 'number' && taskCount > 0 ? `Tasks: ${taskCount}` : '',
                  typeof noteCount === 'number' && noteCount > 0 ? `Notes: ${noteCount}` : '',
                  typeof ruleCount === 'number' && ruleCount > 0 ? `Rules: ${ruleCount}` : '',
                  (projectMemberCounts[project.id] ?? 0) > 0 ? `Members: ${projectMemberCounts[project.id] ?? 0}` : '',
                ]
                  .filter(Boolean)
                  .join(' | ')}
              </div>
              <ExternalRefList refs={project.external_refs} />
              <AttachmentRefList refs={project.attachment_refs} workspaceId={workspaceId} userId={userId} />
              {isOpen && selectedProject && renderInlineEditor(project)}
            </div>
            <div className="project-item-actions">
              <button
                className="action-icon"
                type="button"
                onClick={() => onCopyShareLink(project.id)}
                title="Copy project link"
                aria-label="Copy project link"
              >
                <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
