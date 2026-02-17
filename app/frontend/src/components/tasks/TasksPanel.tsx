import React from 'react'
import type { ProjectBoard, Task } from '../../types'
import { priorityTone } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'
import { TaskListItem } from './taskViews'

type TasksPanelProps = {
  projectsMode: 'board' | 'list'
  setProjectsMode: React.Dispatch<React.SetStateAction<'board' | 'list'>>
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
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
      <div className="row wrap" style={{ marginBottom: 8 }}>
        {taskTagSuggestions.slice(0, 10).map((tag) => (
          <button
            key={`project-tag-${tag}`}
            className={`status-chip ${searchTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
            onClick={() => toggleSearchTag(tag)}
          >
            #{tag}
          </button>
        ))}
      </div>

      {projectsMode === 'board' && boardData && (
        <div className="kanban">
          {boardData.statuses.map((status) => (
            <div key={status} className="kanban-col">
              <div className="kanban-head">
                <strong>{status}</strong>
                <span className="meta">{(boardData.lanes[status] ?? []).length}</span>
              </div>
              <div className="kanban-list">
                {(boardData.lanes[status] ?? []).map((task) => (
                  <div key={task.id} className="kanban-card" onClick={() => onOpenTaskEditor(task.id)} role="button">
                    <div className="kanban-title">
                      <strong>{task.title}</strong>
                      <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
                        {task.priority}
                      </span>
                    </div>
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
                ))}
              </div>
            </div>
          ))}
        </div>
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
