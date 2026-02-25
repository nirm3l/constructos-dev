import React from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { Project } from '../../types'
import { Icon } from '../shared/uiHelpers'

type CountQuery = { data?: { total?: number } }

function formatTemplateAppliedAt(value: string | null | undefined): string {
  if (!value) return 'Unknown'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

function formatProjectTimestamp(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function ChipTooltip({
  label,
  children,
}: {
  label: string
  children: React.ReactElement
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
          <span>{label}</span>
          <Tooltip.Arrow className="header-tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

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
  onRemoveProject,
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
  onRemoveProject: (projectId: string, projectName: string) => void
  renderInlineEditor: (project: Project) => React.ReactNode
}) {
  const [removeProjectPrompt, setRemoveProjectPrompt] = React.useState<{ id: string; name: string } | null>(null)

  return (
    <>
      <Tooltip.Provider delayDuration={120}>
        <div className="task-list">
          {projects.map((project, idx) => {
          const isSelected = selectedProjectId === project.id
          const isOpen = isSelected && showProjectEditForm && selectedProject?.id === project.id
          const noteCount = projectNoteCountQueries[idx]?.data?.total
          const ruleCount = projectRuleCountQueries[idx]?.data?.total
          const memberCount = projectMemberCounts[project.id] ?? 0
          const externalRefCount = project.external_refs?.length ?? 0
          const attachmentRefCount = project.attachment_refs?.length ?? 0
          const updatedAtLabel = formatProjectTimestamp(project.updated_at)
          return (
            <div key={project.id} className={`task-item project-item ${isOpen ? 'open selected' : isSelected ? 'selected' : ''}`}>
              <div className="task-main" role="button" onClick={() => toggleProjectEditor(project.id)}>
              <div className="task-title">
                <strong>{project.name}</strong>
              </div>
              <div className="meta">{project.description || '(no description)'}</div>
              <div className="note-meta-row project-meta-row">
                <ChipTooltip label={`Status: ${project.status || 'active'}`}>
                  <span className="status-chip project-status-chip">{project.status || 'active'}</span>
                </ChipTooltip>
                {project.template_binding ? (
                  <ChipTooltip label={`Template: ${project.template_binding.template_key} v${project.template_binding.template_version}`}>
                    <span className="note-meta-chip">
                      <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
                      <span>{`${project.template_binding.template_key} v${project.template_binding.template_version}`}</span>
                    </span>
                  </ChipTooltip>
                ) : null}
                {typeof noteCount === 'number' && noteCount > 0 && (
                  <ChipTooltip label={`${noteCount} notes`}>
                    <span className="note-meta-chip project-count-chip">
                      <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
                      <span>{noteCount}</span>
                    </span>
                  </ChipTooltip>
                )}
                {typeof ruleCount === 'number' && ruleCount > 0 && (
                  <ChipTooltip label={`${ruleCount} rules`}>
                    <span className="note-meta-chip project-count-chip">
                      <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
                      <span>{ruleCount}</span>
                    </span>
                  </ChipTooltip>
                )}
                {memberCount > 0 && (
                  <ChipTooltip label={`${memberCount} members`}>
                    <span className="note-meta-chip project-count-chip">
                      <Icon path="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2m19 0v-2a4 4 0 0 0-3-3.87m-1-9.13a4 4 0 1 1 0 8" />
                      <span>{memberCount}</span>
                    </span>
                  </ChipTooltip>
                )}
                {externalRefCount > 0 && (
                  <ChipTooltip label={`${externalRefCount} external links`}>
                    <span className="note-meta-chip project-count-chip">
                      <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                      <span>{externalRefCount}</span>
                    </span>
                  </ChipTooltip>
                )}
                {attachmentRefCount > 0 && (
                  <ChipTooltip label={`${attachmentRefCount} file attachments`}>
                    <span className="note-meta-chip project-count-chip">
                      <Icon path="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.2a2 2 0 0 1-2.82-2.83l8.49-8.48" />
                      <span>{attachmentRefCount}</span>
                    </span>
                  </ChipTooltip>
                )}
              </div>
              {project.template_binding ? (
                <div className="meta">{`Template applied: ${formatTemplateAppliedAt(project.template_binding.applied_at)}`}</div>
              ) : null}
              {updatedAtLabel && <div className="meta">{`Updated: ${updatedAtLabel}`}</div>}
              {isOpen && selectedProject && renderInlineEditor(project)}
            </div>
            {!isOpen && (
              <div className="project-item-actions" onClick={(event) => event.stopPropagation()}>
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger asChild>
                    <button
                      className="action-icon note-row-actions-trigger"
                      type="button"
                      title="Project actions"
                      aria-label="Project actions"
                    >
                      <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                    </button>
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                      <DropdownMenu.Item
                        className="task-group-menu-item"
                        onSelect={() => toggleProjectEditor(project.id)}
                      >
                        <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                        <span>{isOpen ? 'Collapse project' : 'Open project'}</span>
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        className="task-group-menu-item"
                        onSelect={() => onCopyShareLink(project.id)}
                      >
                        <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                        <span>Copy project link</span>
                      </DropdownMenu.Item>
                      <DropdownMenu.Separator className="task-group-menu-separator" />
                      <DropdownMenu.Item
                        className="task-group-menu-item task-group-menu-item-danger"
                        onSelect={() => {
                          setRemoveProjectPrompt({ id: project.id, name: project.name })
                        }}
                      >
                        <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                        <span>Remove project</span>
                      </DropdownMenu.Item>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </div>
            )}
            </div>
          )
        })}
        </div>
      </Tooltip.Provider>
      <AlertDialog.Root
        open={Boolean(removeProjectPrompt)}
        onOpenChange={(open) => {
          if (!open) setRemoveProjectPrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="drawer-backdrop" />
          <AlertDialog.Content className="dialog-content">
            <AlertDialog.Title>Remove project</AlertDialog.Title>
            <AlertDialog.Description className="meta" style={{ marginTop: 6 }}>
              {removeProjectPrompt
                ? `Delete "${removeProjectPrompt.name}"? This permanently deletes project resources.`
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
                  onClick={() => {
                    if (!removeProjectPrompt) return
                    onRemoveProject(removeProjectPrompt.id, removeProjectPrompt.name)
                    setRemoveProjectPrompt(null)
                  }}
                >
                  Remove project
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </>
  )
}
