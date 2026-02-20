import React from 'react'
import type { ProjectBoard, Task } from '../../types'
import { priorityTone, tagHue } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import { taskDescriptionPreview, TaskListItem } from './taskViews'

type TasksPanelProps = {
  projectsMode: 'board' | 'list'
  setProjectsMode: React.Dispatch<React.SetStateAction<'board' | 'list'>>
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
  clearSearchTags: () => void
  getTagUsage: (tag: string) => number
  boardData: ProjectBoard | undefined
  onOpenTaskEditor: (taskId: string) => void
  onOpenSpecification: (specificationId: string, projectId: string) => void
  specificationNames: Record<string, string>
  onMoveTaskStatus: (taskId: string, nextStatus: string) => void
  tasks: Task[]
  onRestoreTask: (taskId: string) => void
  onReopenTask: (taskId: string) => void
  onCompleteTask: (taskId: string) => void
}

export function TasksPanel({
  projectsMode,
  setProjectsMode,
  taskTagSuggestions,
  searchTags,
  toggleSearchTag,
  clearSearchTags,
  getTagUsage,
  boardData,
  onOpenTaskEditor,
  onOpenSpecification,
  specificationNames,
  onMoveTaskStatus,
  tasks,
  onRestoreTask,
  onReopenTask,
  onCompleteTask,
}: TasksPanelProps) {
  const visibleBoardStatuses = boardData
    ? boardData.statuses.filter((status) => (boardData.lanes[status] ?? []).length > 0)
    : []

  return (
    <section className="card">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Tasks</h2>
        <div className="seg" role="tablist" aria-label="Task view mode">
          <button
            className={`seg-btn ${projectsMode === 'board' ? 'active' : ''}`}
            onClick={() => setProjectsMode('board')}
            role="tab"
            aria-selected={projectsMode === 'board'}
          >
            <Icon path="M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z" />
            Board
          </button>
          <button
            className={`seg-btn ${projectsMode === 'list' ? 'active' : ''}`}
            onClick={() => setProjectsMode('list')}
            role="tab"
            aria-selected={projectsMode === 'list'}
          >
            <Icon path="M4 6h16M4 12h16M4 18h16" />
            List
          </button>
        </div>
      </div>
      <div className="row wrap notes-tag-filters task-tag-filters">
        <PopularTagFilters
          tags={taskTagSuggestions}
          selectedTags={searchTags}
          onToggleTag={toggleSearchTag}
          onClear={clearSearchTags}
          getTagUsage={getTagUsage}
          idPrefix="project-tag"
        />
      </div>

      {projectsMode === 'board' && boardData && (
        <>
          {visibleBoardStatuses.length > 0 ? (
            <div className="kanban">
              {visibleBoardStatuses.map((status) => (
                <div key={status} className="kanban-col">
                  <div className="kanban-head">
                    <strong>{status}</strong>
                    <span className="meta">{(boardData.lanes[status] ?? []).length}</span>
                  </div>
                  <div className="kanban-list">
                    {(boardData.lanes[status] ?? []).map((task) => {
                      const descriptionPreviewText = taskDescriptionPreview(task.description)
                      return (
                        <div key={task.id} className="kanban-card" onClick={() => onOpenTaskEditor(task.id)} role="button">
                          <div className="kanban-title">
                            <strong>{task.title}</strong>
                            <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
                              {task.priority}
                            </span>
                          </div>
                          {descriptionPreviewText && (
                            <p className="kanban-desc-preview" title={descriptionPreviewText}>
                              {descriptionPreviewText}
                            </p>
                          )}
                          {(task.labels ?? []).length > 0 && (
                            <div className="task-tags">
                              {(task.labels ?? []).map((tag) => (
                                <span
                                  key={`${task.id}-${tag}`}
                                  className="tag-mini"
                                  style={{
                                    backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                                    borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                                    color: `hsl(${tagHue(tag)}, 55%, 28%)`
                                  }}
                                >
                                  #{tag}
                                </span>
                              ))}
                            </div>
                          )}
                          <div className="kanban-actions">
                            {boardData.statuses.filter((s) => s !== status).slice(0, 3).map((nextStatus) => (
                              <button
                                key={nextStatus}
                                className="status-chip"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onMoveTaskStatus(task.id, nextStatus)
                                }}
                              >
                                {nextStatus}
                              </button>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="notice" style={{ marginTop: 12 }}>No tasks in this project.</div>
          )}
        </>
      )}

      {projectsMode === 'list' && (
        <div className="task-list" style={{ marginTop: 12 }}>
          {tasks.map((task) => (
            <TaskListItem
              key={task.id}
              task={task}
              onOpen={onOpenTaskEditor}
              onOpenSpecification={onOpenSpecification}
              onRestore={onRestoreTask}
              onReopen={onReopenTask}
              onComplete={onCompleteTask}
              specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
            />
          ))}
          {tasks.length === 0 && <div className="notice" style={{ marginTop: 10 }}>No tasks in this project.</div>}
        </div>
      )}
    </section>
  )
}
