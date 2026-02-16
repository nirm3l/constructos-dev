import React from 'react'
import type { Task } from '../../types'
import type { Tab } from '../../utils/ui'
import { priorityTone, tagHue } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'

export function TaskListItem({
  task,
  onOpen,
  onRestore,
  onReopen,
  onComplete,
  showProject = false,
  projectName,
}: {
  task: Task
  onOpen: (taskId: string) => void
  onRestore: (taskId: string) => void
  onReopen: (taskId: string) => void
  onComplete: (taskId: string) => void
  showProject?: boolean
  projectName?: string
}) {
  return (
    <div key={task.id} className={`task-item ${task.task_type === 'scheduled_instruction' ? 'scheduled' : ''}`}>
      <div className="task-main" role="button" onClick={() => onOpen(task.id)}>
        <div className="task-title">
          <strong>{task.title}</strong>
        </div>
        <span className="meta">
          {task.status} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'}
          {showProject && <> | Project: {projectName || task.project_id}</>}
        </span>
        {(task.labels ?? []).length > 0 && (
          <div className="task-tags">
            {(task.labels ?? []).map((t) => (
              <span
                key={t}
                className="tag-mini"
                style={{
                  backgroundColor: `hsl(${tagHue(t)}, 70%, 92%)`,
                  borderColor: `hsl(${tagHue(t)}, 70%, 78%)`,
                  color: `hsl(${tagHue(t)}, 55%, 28%)`
                }}
              >
                {t}
              </span>
            ))}
          </div>
        )}
        {task.task_type === 'scheduled_instruction' && (
          <span className="meta">
            Scheduled {task.scheduled_at_utc ? `for ${new Date(task.scheduled_at_utc).toLocaleString()}` : 'time not set'} (
            {task.schedule_state})
          </span>
        )}
        <div className="task-badges">
          <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
            {task.priority}
          </span>
          {task.task_type === 'scheduled_instruction' && (
            <span className={`badge ${task.schedule_state === 'done' ? 'done' : ''}`} title="Scheduled task">
              Scheduled
            </span>
          )}
        </div>
      </div>
      {task.archived ? (
        <button className="action-icon" onClick={() => onRestore(task.id)} title="Restore" aria-label="Restore">
          <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
        </button>
      ) : task.status === 'Done' ? (
        <button className="action-icon" onClick={() => onReopen(task.id)} title="Reopen" aria-label="Reopen">
          <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
        </button>
      ) : (
        <button className="action-icon" onClick={() => onComplete(task.id)} title="Complete" aria-label="Complete">
          <Icon path="m5 13 4 4L19 7" />
        </button>
      )}
    </div>
  )
}

export function BottomTabs({
  tab,
  onSelectTab,
}: {
  tab: Tab
  onSelectTab: (tab: Tab) => void
}) {
  return (
    <nav className="bottom-tabs">
      <button className={tab === 'today' ? 'primary' : ''} onClick={() => onSelectTab('today')} title="Today" aria-label="Today">
        <Icon path="M8 3v4M16 3v4M4 10h16M4 5h16v15H4z" />
        <span className="tab-label">Today</span>
      </button>
      <button className={tab === 'tasks' ? 'primary' : ''} onClick={() => onSelectTab('tasks')} title="Tasks" aria-label="Tasks">
        <Icon path="M4 6h16M4 12h10M4 18h13" />
        <span className="tab-label">Tasks</span>
      </button>
      <button className={tab === 'notes' ? 'primary' : ''} onClick={() => onSelectTab('notes')} title="Notes" aria-label="Notes">
        <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
        <span className="tab-label">Notes</span>
      </button>
    </nav>
  )
}
