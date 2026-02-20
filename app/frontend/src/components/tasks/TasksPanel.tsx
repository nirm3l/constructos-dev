import React from 'react'
import type { ProjectBoard, Task, TaskGroup } from '../../types'
import { priorityTone, tagHue } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import { taskDescriptionPreview, TaskListItem } from './taskViews'

type TaskSection = {
  key: string
  groupId: string | null
  name: string
  color: string | null
  tasks: Task[]
  managed: boolean
}

type BoardGroupSection = {
  key: string
  groupId: string | null
  name: string
  color: string | null
  managed: boolean
}

const ALL_TASKS_KEY = '__all_tasks__'

function formatBoardScheduleTrigger(iso: string | null | undefined): string {
  if (!iso) return 'At: not set'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return `At: ${String(iso)}`
  try {
    return `At: ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)}`
  } catch {
    return `At: ${date.toLocaleString()}`
  }
}

function formatBoardRecurring(recurringRule: string | null | undefined): string {
  const raw = String(recurringRule ?? '').trim()
  if (!raw) return 'Repeat: once'
  const parsed = raw.match(/^every:(\d+)([mhd])$/i)
  if (!parsed) return `Repeat: ${raw}`
  const amount = Number(parsed[1] ?? '0')
  const unit = String(parsed[2] ?? '').toLowerCase()
  if (unit === 'm') return `Repeat: every ${amount}m`
  if (unit === 'h') return `Repeat: every ${amount}h`
  return `Repeat: every ${amount}d`
}

type BoardTaskCardProps = {
  task: Task
  status: string
  statuses: string[]
  targetGroupId: string | null
  onOpenTaskEditor: (taskId: string) => void
  onMoveTaskStatus: (taskId: string, nextStatus: string, nextTaskGroupId?: string | null) => void
  onDragStart: (e: React.DragEvent<HTMLDivElement>, taskId: string) => void
  onDragEnd: () => void
}

function BoardTaskCard({
  task,
  status,
  statuses,
  targetGroupId,
  onOpenTaskEditor,
  onMoveTaskStatus,
  onDragStart,
  onDragEnd,
}: BoardTaskCardProps) {
  const descriptionPreviewText = taskDescriptionPreview(task.description)

  return (
    <div
      key={task.id}
      className="kanban-card"
      onClick={() => onOpenTaskEditor(task.id)}
      role="button"
      draggable
      onDragStart={(e) => onDragStart(e, task.id)}
      onDragEnd={onDragEnd}
    >
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
      {task.task_type === 'scheduled_instruction' && (
        <div className="kanban-schedule-compact">
          <span className="kanban-schedule-chip kanban-schedule-chip-kind">Scheduled</span>
          <span className="kanban-schedule-chip">{formatBoardScheduleTrigger(task.scheduled_at_utc)}</span>
          <span className="kanban-schedule-chip">{formatBoardRecurring(task.recurring_rule)}</span>
        </div>
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
        {statuses.filter((s) => s !== status).slice(0, 3).map((nextStatus) => (
          <button
            key={nextStatus}
            className="status-chip"
            onClick={(e) => {
              e.stopPropagation()
              onMoveTaskStatus(task.id, nextStatus, targetGroupId)
            }}
          >
            {nextStatus}
          </button>
        ))}
      </div>
    </div>
  )
}

type TasksPanelProps = {
  projectsMode: 'board' | 'list'
  setProjectsMode: React.Dispatch<React.SetStateAction<'board' | 'list'>>
  taskGroups: TaskGroup[]
  taskGroupFilterId: string
  setTaskGroupFilterId: React.Dispatch<React.SetStateAction<string>>
  createTaskGroupMutation: any
  patchTaskGroupMutation: any
  deleteTaskGroupMutation: any
  reorderTaskGroupsMutation: any
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
  clearSearchTags: () => void
  getTagUsage: (tag: string) => number
  boardData: ProjectBoard | undefined
  onOpenTaskEditor: (taskId: string) => void
  onOpenSpecification: (specificationId: string, projectId: string) => void
  specificationNames: Record<string, string>
  onMoveTaskStatus: (taskId: string, nextStatus: string, nextTaskGroupId?: string | null) => void
  tasks: Task[]
  onRestoreTask: (taskId: string) => void
  onReopenTask: (taskId: string) => void
  onCompleteTask: (taskId: string) => void
}

export function TasksPanel({
  projectsMode,
  setProjectsMode,
  taskGroups,
  taskGroupFilterId,
  setTaskGroupFilterId,
  createTaskGroupMutation,
  patchTaskGroupMutation,
  deleteTaskGroupMutation,
  reorderTaskGroupsMutation,
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
  const selectedGroupFilter = String(taskGroupFilterId || '')

  const filteredTasks = React.useMemo(() => {
    if (!selectedGroupFilter) return tasks
    return tasks.filter((task) => task.task_group_id === selectedGroupFilter || !task.task_group_id)
  }, [tasks, selectedGroupFilter])

  const ungroupedTasks = React.useMemo(
    () => tasks.filter((task) => !task.task_group_id),
    [tasks]
  )

  const boardLanes = React.useMemo(() => {
    if (!boardData) return null
    if (!selectedGroupFilter) return boardData.lanes
    const lanes: Record<string, Task[]> = {}
    for (const status of boardData.statuses) {
      lanes[status] = (boardData.lanes[status] ?? []).filter((task) => task.task_group_id === selectedGroupFilter || !task.task_group_id)
    }
    return lanes
  }, [boardData, selectedGroupFilter])

  const [draggingTaskId, setDraggingTaskId] = React.useState<string | null>(null)
  const [dropTargetKey, setDropTargetKey] = React.useState<string | null>(null)

  const taskById = React.useMemo(() => {
    const out = new Map<string, Task>()
    for (const task of tasks) out.set(task.id, task)
    return out
  }, [tasks])

  const moveDraggedTask = React.useCallback((taskId: string, nextStatus: string, nextGroupId: string | null) => {
    const task = taskById.get(taskId)
    if (!task) return
    const currentGroupId = task.task_group_id ?? null
    if (task.status === nextStatus && currentGroupId === nextGroupId) return
    onMoveTaskStatus(taskId, nextStatus, nextGroupId)
  }, [onMoveTaskStatus, taskById])

  const onBoardCardDragStart = React.useCallback((event: React.DragEvent<HTMLDivElement>, taskId: string) => {
    setDraggingTaskId(taskId)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', taskId)
  }, [])

  const onBoardCardDragEnd = React.useCallback(() => {
    setDraggingTaskId(null)
    setDropTargetKey(null)
  }, [])

  const onBoardLaneDrop = React.useCallback((event: React.DragEvent<HTMLDivElement>, nextStatus: string, nextGroupId: string | null) => {
    event.preventDefault()
    const draggedId = event.dataTransfer.getData('text/plain') || draggingTaskId || ''
    setDropTargetKey(null)
    setDraggingTaskId(null)
    if (!draggedId) return
    moveDraggedTask(draggedId, nextStatus, nextGroupId)
  }, [draggingTaskId, moveDraggedTask])

  const onListSectionDrop = React.useCallback((event: React.DragEvent<HTMLDivElement>, nextGroupId: string | null) => {
    event.preventDefault()
    const draggedId = event.dataTransfer.getData('text/plain') || draggingTaskId || ''
    setDropTargetKey(null)
    setDraggingTaskId(null)
    if (!draggedId) return
    const task = taskById.get(draggedId)
    if (!task) return
    moveDraggedTask(draggedId, task.status, nextGroupId)
  }, [draggingTaskId, moveDraggedTask, taskById])

  const maybeAutoScrollWhileDragging = React.useCallback((event: React.DragEvent) => {
    if (typeof window === 'undefined') return
    const edgeThreshold = 96
    const scrollStep = 20
    const y = event.clientY
    const viewportHeight = window.innerHeight
    if (y > viewportHeight - edgeThreshold) {
      window.scrollBy(0, scrollStep)
      return
    }
    if (y < edgeThreshold) {
      window.scrollBy(0, -scrollStep)
    }
  }, [])

  const taskSections = React.useMemo<TaskSection[]>(() => {
    if (taskGroups.length === 0) {
      return [{
        key: ALL_TASKS_KEY,
        groupId: null,
        name: 'All tasks',
        color: null,
        tasks: filteredTasks,
        managed: false,
      }]
    }

    const sourceGroups = selectedGroupFilter
      ? taskGroups.filter((group) => group.id === selectedGroupFilter)
      : taskGroups

    return sourceGroups.map((group) => ({
      key: group.id,
      groupId: group.id,
      name: group.name,
      color: group.color,
      tasks: filteredTasks.filter((task) => task.task_group_id === group.id),
      managed: true,
    }))
  }, [filteredTasks, selectedGroupFilter, taskGroups])

  const [collapsedSectionMap, setCollapsedSectionMap] = React.useState<Record<string, boolean>>({})

  React.useEffect(() => {
    setCollapsedSectionMap((prev) => {
      const allowed = new Set(taskSections.map((section) => section.key))
      let changed = false
      const next: Record<string, boolean> = {}
      for (const [key, value] of Object.entries(prev)) {
        if (!allowed.has(key)) {
          changed = true
          continue
        }
        next[key] = value
      }
      return changed ? next : prev
    })
  }, [taskSections])

  const toggleSection = React.useCallback((sectionKey: string) => {
    setCollapsedSectionMap((prev) => ({ ...prev, [sectionKey]: !prev[sectionKey] }))
  }, [])

  const createGroupBusy = Boolean(createTaskGroupMutation?.isPending)
  const updateGroupBusy = Boolean(patchTaskGroupMutation?.isPending)
  const deleteGroupBusy = Boolean(deleteTaskGroupMutation?.isPending)
  const reorderGroupBusy = Boolean(reorderTaskGroupsMutation?.isPending)
  const groupActionBusy = createGroupBusy || updateGroupBusy || deleteGroupBusy || reorderGroupBusy

  const createTaskGroup = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const rawName = window.prompt('New task group name')
    if (rawName == null) return
    const name = rawName.trim()
    if (!name) return
    createTaskGroupMutation.mutate({ name })
  }, [createTaskGroupMutation])

  const renameTaskGroup = React.useCallback((groupId: string, currentName: string) => {
    if (typeof window === 'undefined') return
    const rawName = window.prompt('Rename task group', currentName)
    if (rawName == null) return
    const name = rawName.trim()
    if (!name || name === currentName) return
    patchTaskGroupMutation.mutate({ taskGroupId: groupId, name })
  }, [patchTaskGroupMutation])

  const deleteTaskGroupById = React.useCallback((groupId: string, groupName: string) => {
    if (typeof window === 'undefined') return
    const ok = window.confirm(`Delete task group "${groupName}"? Linked tasks will become ungrouped.`)
    if (!ok) return
    deleteTaskGroupMutation.mutate(groupId)
  }, [deleteTaskGroupMutation])

  const moveTaskGroup = React.useCallback((groupId: string, direction: -1 | 1) => {
    const orderedIds = taskGroups.map((group) => group.id)
    const index = orderedIds.indexOf(groupId)
    if (index < 0) return
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= orderedIds.length) return
    const nextOrdered = [...orderedIds]
    const [moved] = nextOrdered.splice(index, 1)
    if (!moved) return
    nextOrdered.splice(nextIndex, 0, moved)
    reorderTaskGroupsMutation.mutate(nextOrdered)
  }, [reorderTaskGroupsMutation, taskGroups])

  const boardGroupSections = React.useMemo<BoardGroupSection[]>(() => {
    if (taskGroups.length === 0) return []
    const sourceGroups = selectedGroupFilter
      ? taskGroups.filter((group) => group.id === selectedGroupFilter)
      : taskGroups

    return sourceGroups.map((group) => ({
      key: group.id,
      groupId: group.id,
      name: group.name,
      color: group.color,
      managed: true,
    }))
  }, [selectedGroupFilter, taskGroups])

  const hasGroups = taskGroups.length > 0

  const visibleBoardStatuses = React.useMemo(() => {
    if (!boardData || !boardLanes) return []
    if (hasGroups) return boardData.statuses
    return boardData.statuses.filter((status) => (boardLanes[status] ?? []).length > 0)
  }, [boardData, boardLanes, hasGroups])

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

      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8, gap: 8 }}>
        <label className="row wrap" style={{ gap: 6, alignItems: 'center' }}>
          <span className="meta">Group filter</span>
          <select
            value={taskGroupFilterId}
            onChange={(e) => setTaskGroupFilterId(e.target.value)}
            disabled={taskGroups.length === 0}
          >
            <option value="">All groups</option>
            {taskGroups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="status-chip"
          type="button"
          onClick={createTaskGroup}
          disabled={groupActionBusy}
          title="Create task group"
          aria-label="Create task group"
        >
          + Group
        </button>
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

      {projectsMode === 'board' && boardData && boardLanes && (
        <>
          {hasGroups ? (
            <div style={{ marginTop: 12 }}>
              {ungroupedTasks.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <div className="kanban">
                    {visibleBoardStatuses.map((status) => {
                      const laneTasks = (boardLanes[status] ?? []).filter((task) => !task.task_group_id)
                      const dropKey = `plain:${status}`
                      const isDropTarget = dropTargetKey === dropKey
                      return (
                        <div key={`plain:${status}`} className="kanban-col">
                          <div className="kanban-head">
                            <strong>{status}</strong>
                            <span className="meta">{laneTasks.length}</span>
                          </div>
                          <div
                            className="kanban-list"
                            style={isDropTarget ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10 } : undefined}
                            onDragOver={(event) => {
                              event.preventDefault()
                              setDropTargetKey(dropKey)
                            }}
                            onDragLeave={() => {
                              setDropTargetKey((prev) => (prev === dropKey ? null : prev))
                            }}
                            onDrop={(event) => onBoardLaneDrop(event, status, null)}
                          >
                            {laneTasks.map((task) => (
                              <BoardTaskCard
                                key={task.id}
                                task={task}
                                status={status}
                                statuses={boardData.statuses}
                                targetGroupId={null}
                                onOpenTaskEditor={onOpenTaskEditor}
                                onMoveTaskStatus={onMoveTaskStatus}
                                onDragStart={onBoardCardDragStart}
                                onDragEnd={onBoardCardDragEnd}
                              />
                            ))}
                            {laneTasks.length === 0 && <div className="meta">Drop task here</div>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              {boardGroupSections.map((group) => {
                const groupIndex = group.groupId ? taskGroups.findIndex((item) => item.id === group.groupId) : -1
                const canMoveUp = Boolean(group.managed && groupIndex > 0)
                const canMoveDown = Boolean(group.managed && groupIndex >= 0 && groupIndex < taskGroups.length - 1)
                const groupHasTasks = boardData.statuses.some((status) =>
                  (boardLanes[status] ?? []).some((task) => task.task_group_id === group.groupId)
                )
                return (
                  <div
                    key={`board-group-${group.key}`}
                    style={{
                      borderLeft: group.color ? `3px solid ${group.color}` : '3px solid transparent',
                      paddingLeft: 8,
                      marginBottom: 14,
                    }}
                  >
                    <div className="row wrap group-section-head">
                      <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                        <strong className="group-title-text">{group.name}</strong>
                      </div>
                      <div className="group-actions">
                        <button
                          className="action-icon group-action-icon"
                          type="button"
                          onClick={() => group.groupId && moveTaskGroup(group.groupId, -1)}
                          disabled={!canMoveUp || groupActionBusy}
                          title="Move group up"
                          aria-label="Move group up"
                        >
                          <Icon path="M12 19V5M5 12l7-7 7 7" />
                        </button>
                        <button
                          className="action-icon group-action-icon"
                          type="button"
                          onClick={() => group.groupId && moveTaskGroup(group.groupId, 1)}
                          disabled={!canMoveDown || groupActionBusy}
                          title="Move group down"
                          aria-label="Move group down"
                        >
                          <Icon path="M12 5v14M5 12l7 7 7-7" />
                        </button>
                        <button
                          className="action-icon group-action-icon"
                          type="button"
                          onClick={() => group.groupId && renameTaskGroup(group.groupId, group.name)}
                          disabled={!group.managed || groupActionBusy}
                          title="Rename group"
                          aria-label="Rename group"
                        >
                          <Icon path="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                        </button>
                        <button
                          className="action-icon group-action-icon"
                          type="button"
                          onClick={() => group.groupId && deleteTaskGroupById(group.groupId, group.name)}
                          disabled={!group.managed || groupActionBusy}
                          title="Delete group"
                          aria-label="Delete group"
                        >
                          <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                        </button>
                      </div>
                    </div>
                    <div className="kanban">
                      {visibleBoardStatuses.map((status) => {
                        const laneTasks = (boardLanes[status] ?? []).filter((task) => task.task_group_id === group.groupId)
                        const dropKey = `${group.key}:${status}`
                        const isDropTarget = dropTargetKey === dropKey
                        return (
                          <div key={`${group.key}:${status}`} className="kanban-col">
                            <div className="kanban-head">
                              <strong>{status}</strong>
                              <span className="meta">{laneTasks.length}</span>
                            </div>
                            <div
                              className="kanban-list"
                              style={isDropTarget ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10 } : undefined}
                              onDragOver={(event) => {
                                event.preventDefault()
                                setDropTargetKey(dropKey)
                              }}
                              onDragLeave={() => {
                                setDropTargetKey((prev) => (prev === dropKey ? null : prev))
                              }}
                              onDrop={(event) => onBoardLaneDrop(event, status, group.groupId)}
                            >
                              {laneTasks.map((task) => (
                                <BoardTaskCard
                                  key={task.id}
                                  task={task}
                                  status={status}
                                  statuses={boardData.statuses}
                                  targetGroupId={group.groupId}
                                  onOpenTaskEditor={onOpenTaskEditor}
                                  onMoveTaskStatus={onMoveTaskStatus}
                                  onDragStart={onBoardCardDragStart}
                                  onDragEnd={onBoardCardDragEnd}
                                />
                              ))}
                              {laneTasks.length === 0 && <div className="meta">Drop task here</div>}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {!groupHasTasks && <div className="meta" style={{ marginTop: 6 }}>No tasks in this group.</div>}
                  </div>
                )
              })}
              {boardGroupSections.length === 0 && <div className="notice">No groups available.</div>}
            </div>
          ) : (
            <>
              {visibleBoardStatuses.length > 0 ? (
                <div className="kanban" style={{ marginTop: 12 }}>
                  {visibleBoardStatuses.map((status) => {
                    const laneTasks = boardLanes[status] ?? []
                    const dropKey = `ungrouped:${status}`
                    const isDropTarget = dropTargetKey === dropKey
                    return (
                      <div key={status} className="kanban-col">
                        <div className="kanban-head">
                          <strong>{status}</strong>
                          <span className="meta">{laneTasks.length}</span>
                        </div>
                        <div
                          className="kanban-list"
                          style={isDropTarget ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10 } : undefined}
                          onDragOver={(event) => {
                            event.preventDefault()
                            setDropTargetKey(dropKey)
                          }}
                          onDragLeave={() => {
                            setDropTargetKey((prev) => (prev === dropKey ? null : prev))
                          }}
                          onDrop={(event) => onBoardLaneDrop(event, status, null)}
                        >
                          {laneTasks.map((task) => (
                            <BoardTaskCard
                              key={task.id}
                              task={task}
                              status={status}
                              statuses={boardData.statuses}
                              targetGroupId={null}
                              onOpenTaskEditor={onOpenTaskEditor}
                              onMoveTaskStatus={onMoveTaskStatus}
                              onDragStart={onBoardCardDragStart}
                              onDragEnd={onBoardCardDragEnd}
                            />
                          ))}
                          {laneTasks.length === 0 && <div className="meta">Drop task here</div>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="notice" style={{ marginTop: 12 }}>No tasks in this view.</div>
              )}
            </>
          )}
        </>
      )}

      {projectsMode === 'list' && (
        <div className="task-list tasks-list" style={{ marginTop: 12 }}>
          {hasGroups && ungroupedTasks.length > 0 && (
            <div
              className="task-list-dropzone"
              style={dropTargetKey === 'list:plain' ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10, padding: 6, marginBottom: 10 } : { marginBottom: 10 }}
              onDragOver={(event) => {
                event.preventDefault()
                maybeAutoScrollWhileDragging(event)
                setDropTargetKey('list:plain')
              }}
              onDragLeave={() => {
                setDropTargetKey((prev) => (prev === 'list:plain' ? null : prev))
              }}
              onDrop={(event) => onListSectionDrop(event, null)}
            >
              {ungroupedTasks.map((task) => (
                <div
                  key={task.id}
                  draggable
                  onDragStart={(event) => onBoardCardDragStart(event, task.id)}
                  onDragEnd={onBoardCardDragEnd}
                >
                  <TaskListItem
                    task={task}
                    onOpen={onOpenTaskEditor}
                    onOpenSpecification={onOpenSpecification}
                    onRestore={onRestoreTask}
                    onReopen={onReopenTask}
                    onComplete={onCompleteTask}
                    specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
                  />
                </div>
              ))}
              {ungroupedTasks.length === 0 && <div className="meta">Drop task here</div>}
            </div>
          )}
          {taskSections.map((section) => {
            const collapsed = Boolean(collapsedSectionMap[section.key])
            const sectionGroup = section.groupId
              ? taskGroups.find((group) => group.id === section.groupId) ?? null
              : null
            const listDropKey = `list:${section.key}`
            const isListDropTarget = dropTargetKey === listDropKey
            const sectionIndex = sectionGroup ? taskGroups.findIndex((group) => group.id === sectionGroup.id) : -1
            const canMoveUp = sectionGroup ? sectionIndex > 0 : false
            const canMoveDown = sectionGroup ? sectionIndex >= 0 && sectionIndex < taskGroups.length - 1 : false

            return (
              <div
                key={section.key}
                style={{
                  borderLeft: section.color ? `3px solid ${section.color}` : '3px solid transparent',
                  paddingLeft: 8,
                  marginBottom: 10,
                }}
              >
                <div className="row wrap group-section-head">
                  <button
                    className="pill subtle group-toggle-pill"
                    type="button"
                    onClick={() => toggleSection(section.key)}
                    aria-expanded={!collapsed}
                    aria-label={collapsed ? `Expand ${section.name}` : `Collapse ${section.name}`}
                  >
                    <span>{collapsed ? '▸' : '▾'}</span>
                    <span>{section.name}</span>
                    <span className="meta">({section.tasks.length})</span>
                  </button>

                  {sectionGroup && section.managed && (
                    <div className="group-actions">
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => moveTaskGroup(sectionGroup.id, -1)}
                        disabled={!canMoveUp || groupActionBusy}
                        title="Move group up"
                        aria-label="Move group up"
                      >
                        <Icon path="M12 19V5M5 12l7-7 7 7" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => moveTaskGroup(sectionGroup.id, 1)}
                        disabled={!canMoveDown || groupActionBusy}
                        title="Move group down"
                        aria-label="Move group down"
                      >
                        <Icon path="M12 5v14M5 12l7 7 7-7" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => renameTaskGroup(sectionGroup.id, sectionGroup.name)}
                        disabled={groupActionBusy}
                        title="Rename group"
                        aria-label="Rename group"
                      >
                        <Icon path="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => deleteTaskGroupById(sectionGroup.id, sectionGroup.name)}
                        disabled={groupActionBusy}
                        title="Delete group"
                        aria-label="Delete group"
                      >
                        <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                      </button>
                    </div>
                  )}
                </div>

                {!collapsed && (
                  <div
                    className="task-list-dropzone"
                    style={isListDropTarget ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10, padding: 6 } : undefined}
                    onDragOver={(event) => {
                      event.preventDefault()
                      maybeAutoScrollWhileDragging(event)
                      setDropTargetKey(listDropKey)
                    }}
                    onDragLeave={() => {
                      setDropTargetKey((prev) => (prev === listDropKey ? null : prev))
                    }}
                    onDrop={(event) => onListSectionDrop(event, section.groupId)}
                  >
                    {section.tasks.map((task) => (
                      <div
                        key={task.id}
                        draggable
                        onDragStart={(event) => onBoardCardDragStart(event, task.id)}
                        onDragEnd={onBoardCardDragEnd}
                      >
                        <TaskListItem
                          task={task}
                          onOpen={onOpenTaskEditor}
                          onOpenSpecification={onOpenSpecification}
                          onRestore={onRestoreTask}
                          onReopen={onReopenTask}
                          onComplete={onCompleteTask}
                          specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
                        />
                      </div>
                    ))}
                    {section.tasks.length === 0 && (
                      <div className="meta" style={{ minHeight: 64, display: 'grid', alignItems: 'center' }}>
                        Drop task here to move it to this section.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {taskSections.length === 0 && (!hasGroups || ungroupedTasks.length === 0) && (
            <div className="notice" style={{ marginTop: 10 }}>No tasks in this project.</div>
          )}
        </div>
      )}
    </section>
  )
}
