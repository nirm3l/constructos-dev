import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Accordion from '@radix-ui/react-accordion'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import type { ProjectBoard, Task, TaskGroup } from '../../types'
import { priorityTone, tagHue } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import { ChipTooltip, taskDescriptionPreview, TaskListItem } from './taskViews'

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

type TaskGroupDialogTarget = {
  id: string
  name: string
}

type TaskGroupActionsMenuProps = {
  groupName: string
  busy: boolean
  onRename: () => void
  onDelete: () => void
}

function TaskGroupActionsMenu({
  groupName,
  busy,
  onRename,
  onDelete,
}: TaskGroupActionsMenuProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="action-icon group-action-icon group-action-menu-trigger"
          type="button"
          title={`Manage group ${groupName}`}
          aria-label={`Manage group ${groupName}`}
          disabled={busy}
        >
          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="task-group-menu-content" sideOffset={8} align="end">
          <DropdownMenu.Item
            className="task-group-menu-item"
            onSelect={onRename}
            disabled={busy}
          >
            <Icon path="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
            <span>Rename group</span>
          </DropdownMenu.Item>
          <DropdownMenu.Item
            className="task-group-menu-item task-group-menu-item-danger"
            onSelect={onDelete}
            disabled={busy}
          >
            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
            <span>Delete group</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

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

function formatBoardScheduleState(state: Task['schedule_state'] | null | undefined): string {
  const raw = String(state ?? '').trim()
  if (!raw) return 'Unknown'
  return `${raw.charAt(0).toUpperCase()}${raw.slice(1)}`
}

function formatBoardAutomationState(state: string | null | undefined): string {
  const raw = String(state ?? '').trim()
  if (!raw || raw.toLowerCase() === 'idle') return 'Idle'
  if (raw === 'completed') return 'Execution Completed'
  return `Execution ${raw.charAt(0).toUpperCase()}${raw.slice(1)}`
}

function toBoardExecutionChipClassState(state: string | null | undefined): string {
  const raw = String(state ?? 'idle').trim().toLowerCase()
  if (!raw) return 'idle'
  if (raw === 'completed') return 'done'
  return raw
}

function resolveBoardEffectiveExecutionState(task: Task): string {
  const automation = String(task.automation_state ?? '').trim().toLowerCase()
  if (automation && automation !== 'idle') return automation
  const schedule = String(task.schedule_state ?? '').trim().toLowerCase()
  if (task.task_type === 'scheduled_instruction' && schedule) return schedule
  return automation || 'idle'
}

type BoardTaskCardProps = {
  task: Task
  status: string
  statuses: string[]
  targetGroupId: string | null
  assigneeLabel?: string
  onTagClick: (tag: string) => void
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
  assigneeLabel,
  onTagClick,
  onOpenTaskEditor,
  onMoveTaskStatus,
  onDragStart,
  onDragEnd,
}: BoardTaskCardProps) {
  const descriptionPreviewText = taskDescriptionPreview(task.description)
  const isScheduled = task.task_type === 'scheduled_instruction'
  const externalRefCount = Array.isArray(task.external_refs) ? task.external_refs.length : 0
  const effectiveExecutionState = resolveBoardEffectiveExecutionState(task)
  const hasVisibleAutomationState = effectiveExecutionState !== 'idle'
  const executionStateLabel = formatBoardAutomationState(effectiveExecutionState)
  const executionStateClass = toBoardExecutionChipClassState(effectiveExecutionState)
  const availableStatuses = statuses.filter((candidateStatus) => candidateStatus !== status)
  const currentStatusIndex = statuses.indexOf(status)
  const nextStatus = currentStatusIndex >= 0 && currentStatusIndex < statuses.length - 1
    ? statuses[currentStatusIndex + 1]
    : null

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
        <div
          className="kanban-title-controls"
          onClick={(event) => event.stopPropagation()}
        >
          <span className={`prio prio-${priorityTone(task.priority)}`} title={`Priority: ${task.priority}`}>
            {task.priority}
          </span>
          {availableStatuses.length > 0 ? (
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button
                  className="status-chip kanban-move-trigger"
                  type="button"
                  onClick={(event) => event.stopPropagation()}
                  aria-label="Move task to another status"
                  title="Move task to another status"
                >
                  <span>Move</span>
                  <Icon path="M6 9l6 6 6-6" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content className="task-group-menu-content kanban-move-menu-content" sideOffset={6} align="end">
                  {nextStatus && (
                    <>
                      <DropdownMenu.Item
                        className="task-group-menu-item"
                        onSelect={() => onMoveTaskStatus(task.id, nextStatus, targetGroupId)}
                      >
                        <Icon path="M13 5l7 7-7 7M5 12h14" />
                        <span>{`Move to next (${nextStatus})`}</span>
                      </DropdownMenu.Item>
                      <DropdownMenu.Separator className="task-group-menu-separator" />
                    </>
                  )}
                  <DropdownMenu.RadioGroup
                    value={status}
                    onValueChange={(value) => {
                      if (value !== status) onMoveTaskStatus(task.id, value, targetGroupId)
                    }}
                  >
                    {statuses.map((candidateStatus) => (
                      <DropdownMenu.RadioItem
                        key={candidateStatus}
                        value={candidateStatus}
                        className="task-group-menu-item kanban-move-menu-item"
                        disabled={candidateStatus === status}
                      >
                        <span className="kanban-move-menu-label">{candidateStatus}</span>
                        {candidateStatus === status && <span className="meta kanban-move-menu-meta">Current</span>}
                        <DropdownMenu.ItemIndicator className="kanban-move-menu-indicator">
                          <Icon path="M5 13l4 4L19 7" />
                        </DropdownMenu.ItemIndicator>
                      </DropdownMenu.RadioItem>
                    ))}
                  </DropdownMenu.RadioGroup>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          ) : (
            <button
              className="status-chip kanban-move-trigger"
              type="button"
              disabled
              aria-label="No available status transitions"
              title="No available status transitions"
            >
              <span>Move</span>
              <Icon path="M6 9l6 6 6-6" />
            </button>
          )}
        </div>
      </div>
      {descriptionPreviewText && (
        <p className="kanban-desc-preview" title={descriptionPreviewText}>
          {descriptionPreviewText}
        </p>
      )}
      {isScheduled && (
        <div className="kanban-schedule-compact">
          <span className="kanban-schedule-chip kanban-schedule-chip-kind">Scheduled</span>
          <span className="kanban-schedule-chip">{formatBoardScheduleTrigger(task.scheduled_at_utc)}</span>
          <span className="kanban-schedule-chip">{formatBoardRecurring(task.recurring_rule)}</span>
          <span className={`task-schedule-chip task-schedule-state task-schedule-state-${executionStateClass}`}>
            {executionStateLabel}
          </span>
        </div>
      )}
      {(assigneeLabel || externalRefCount > 0) && (
        <div className="kanban-meta-compact">
          <div className="kanban-meta-left">
            {assigneeLabel && (
              <div className="task-assignee-compact" title={`Assigned to ${assigneeLabel}`}>
                <Icon path="M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8" />
                <span>{assigneeLabel}</span>
              </div>
            )}
          </div>
          <div className="kanban-meta-right">
            {!isScheduled && hasVisibleAutomationState && (
              <span className={`task-schedule-chip task-schedule-state task-schedule-state-${executionStateClass}`}>
                {executionStateLabel}
              </span>
            )}
            {externalRefCount > 0 && (
              <ChipTooltip label={`${externalRefCount} external link${externalRefCount === 1 ? '' : 's'}`}>
                <span className="task-resource-chip">
                  <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                  <span>{externalRefCount}</span>
                </span>
              </ChipTooltip>
            )}
          </div>
        </div>
      )}
      {(task.labels ?? []).length > 0 && (
        <div className="task-tags">
          {(task.labels ?? []).map((tag) => (
            <button
              key={`${task.id}-${tag}`}
              type="button"
              className="tag-mini tag-clickable"
              onClick={(event) => {
                event.stopPropagation()
                onTagClick(tag)
              }}
              title={`Filter by tag: ${tag}`}
              style={{
                backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                color: `hsl(${tagHue(tag)}, 55%, 28%)`
              }}
            >
              #{tag}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

type TasksPanelProps = {
  panelTitle?: string
  allowBoardView?: boolean
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
  boardData: ProjectBoard | undefined
  actorNames: Record<string, string>
  taskTeamAgentLabelsByProjectId: Record<string, Record<string, string>>
  onOpenTaskEditor: (taskId: string) => void
  onOpenSpecification: (specificationId: string, projectId: string) => void
  specificationNames: Record<string, string>
  onMoveTaskStatus: (taskId: string, nextStatus: string, nextTaskGroupId?: string | null) => void
  tasks: Task[]
  canLoadMoreTasks: boolean
  onLoadMoreTasks: () => void
  onRestoreTask: (taskId: string) => void
  onReopenTask: (taskId: string) => void
  onCompleteTask: (taskId: string) => void
  onNewTask: (taskType?: 'manual' | 'scheduled_instruction') => void
}

export function TasksPanel({
  panelTitle = 'Tasks',
  allowBoardView = true,
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
  boardData,
  actorNames,
  taskTeamAgentLabelsByProjectId,
  onOpenTaskEditor,
  onOpenSpecification,
  specificationNames,
  onMoveTaskStatus,
  tasks,
  canLoadMoreTasks,
  onLoadMoreTasks,
  onRestoreTask,
  onReopenTask,
  onCompleteTask,
  onNewTask,
}: TasksPanelProps) {
  const getTeamAgentLabel = React.useCallback((task: Task): string => {
    const projectId = String(task.project_id || '').trim()
    const slot = String(task.assigned_agent_code || '').trim()
    if (!projectId || !slot) return ''
    return String(taskTeamAgentLabelsByProjectId?.[projectId]?.[slot] || '').trim()
  }, [taskTeamAgentLabelsByProjectId])
  const getAssigneeLabel = React.useCallback((task: Task): string => {
    const agent = getTeamAgentLabel(task)
    if (agent) return agent
    if (String(task.assigned_agent_code || '').trim()) return ''
    const assigneeId = String(task.assignee_id || '').trim()
    return assigneeId ? String(actorNames?.[assigneeId] || assigneeId).trim() : ''
  }, [actorNames, getTeamAgentLabel])

  const selectedGroupFilter = ''

  React.useEffect(() => {
    if (String(taskGroupFilterId || '').trim().length > 0) {
      setTaskGroupFilterId('')
    }
  }, [setTaskGroupFilterId, taskGroupFilterId])

  const filteredTasks = React.useMemo(() => {
    if (!selectedGroupFilter) return tasks
    return tasks.filter((task) => task.task_group_id === selectedGroupFilter || !task.task_group_id)
  }, [tasks, selectedGroupFilter])

  const ungroupedTasks = React.useMemo(
    () => filteredTasks.filter((task) => !task.task_group_id),
    [filteredTasks]
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
    if (taskGroups.length === 0) return []

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
  const [openSectionKeys, setOpenSectionKeys] = React.useState<string[]>([])

  React.useEffect(() => {
    const allKeys = taskSections.map((section) => section.key)
    setOpenSectionKeys((previousOpenKeys) => {
      const allowed = new Set(allKeys)
      const filteredOpenKeys = previousOpenKeys.filter((key) => allowed.has(key))
      const existing = new Set(filteredOpenKeys)
      const missing = allKeys.filter((key) => !existing.has(key))
      return [...filteredOpenKeys, ...missing]
    })
  }, [taskSections])

  const createGroupBusy = Boolean(createTaskGroupMutation?.isPending)
  const updateGroupBusy = Boolean(patchTaskGroupMutation?.isPending)
  const deleteGroupBusy = Boolean(deleteTaskGroupMutation?.isPending)
  const reorderGroupBusy = Boolean(reorderTaskGroupsMutation?.isPending)
  const groupActionBusy = createGroupBusy || updateGroupBusy || deleteGroupBusy || reorderGroupBusy
  const [taskGroupDialogMode, setTaskGroupDialogMode] = React.useState<'create' | 'rename' | null>(null)
  const [taskGroupDialogName, setTaskGroupDialogName] = React.useState('')
  const [taskGroupDialogTarget, setTaskGroupDialogTarget] = React.useState<TaskGroupDialogTarget | null>(null)
  const [deleteTaskGroupPrompt, setDeleteTaskGroupPrompt] = React.useState<TaskGroupDialogTarget | null>(null)

  const closeTaskGroupDialog = React.useCallback(() => {
    setTaskGroupDialogMode(null)
    setTaskGroupDialogName('')
    setTaskGroupDialogTarget(null)
  }, [])

  const openCreateTaskGroupDialog = React.useCallback(() => {
    setTaskGroupDialogMode('create')
    setTaskGroupDialogName('')
    setTaskGroupDialogTarget(null)
  }, [])

  const openRenameTaskGroupDialog = React.useCallback((groupId: string, currentName: string) => {
    setTaskGroupDialogMode('rename')
    setTaskGroupDialogName(currentName)
    setTaskGroupDialogTarget({ id: groupId, name: currentName })
  }, [])

  const submitTaskGroupDialog = React.useCallback(() => {
    const name = taskGroupDialogName.trim()
    if (!name) return

    if (taskGroupDialogMode === 'create') {
      createTaskGroupMutation.mutate(
        { name },
        { onSuccess: () => closeTaskGroupDialog() }
      )
      return
    }

    if (taskGroupDialogMode === 'rename' && taskGroupDialogTarget) {
      if (name === taskGroupDialogTarget.name) {
        closeTaskGroupDialog()
        return
      }
      patchTaskGroupMutation.mutate(
        { taskGroupId: taskGroupDialogTarget.id, name },
        { onSuccess: () => closeTaskGroupDialog() }
      )
    }
  }, [
    closeTaskGroupDialog,
    createTaskGroupMutation,
    patchTaskGroupMutation,
    taskGroupDialogMode,
    taskGroupDialogName,
    taskGroupDialogTarget,
  ])

  const requestDeleteTaskGroup = React.useCallback((groupId: string, groupName: string) => {
    setDeleteTaskGroupPrompt({ id: groupId, name: groupName })
  }, [])

  const confirmDeleteTaskGroup = React.useCallback(() => {
    if (!deleteTaskGroupPrompt) return
    deleteTaskGroupMutation.mutate(
      deleteTaskGroupPrompt.id,
      { onSuccess: () => setDeleteTaskGroupPrompt(null) }
    )
  }, [deleteTaskGroupMutation, deleteTaskGroupPrompt])

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
    const statuses: string[] = []
    const seen = new Set<string>()

    const pushStatus = (raw: string) => {
      const status = String(raw || '').trim()
      if (!status) return
      const key = status.toLowerCase()
      if (seen.has(key)) return
      seen.add(key)
      statuses.push(status)
    }

    for (const status of boardData.statuses) pushStatus(status)
    for (const status of Object.keys(boardLanes)) pushStatus(status)

    if (hasGroups) return statuses
    return statuses.filter((status) => (boardLanes[status] ?? []).length > 0)
  }, [boardData, boardLanes, hasGroups])

  const onProjectsModeChange = React.useCallback((value: string) => {
    if (!allowBoardView) return
    if (value === 'board' || value === 'list') setProjectsMode(value)
  }, [allowBoardView, setProjectsMode])

  const taskGroupDialogOpen = taskGroupDialogMode !== null
  const taskGroupDialogSubmitDisabled =
    groupActionBusy ||
    !taskGroupDialogName.trim() ||
    (taskGroupDialogMode === 'rename' &&
      taskGroupDialogTarget !== null &&
      taskGroupDialogName.trim() === taskGroupDialogTarget.name)
  const taskGroupDialogTitle = taskGroupDialogMode === 'rename' ? 'Rename task group' : 'Create task group'
  const taskGroupDialogDescription = taskGroupDialogMode === 'rename'
    ? 'Set a new name for this task group.'
    : 'Create a new group to organize tasks in list and board views.'
  const taskGroupDialogSubmitLabel = taskGroupDialogMode === 'rename' ? 'Save' : 'Create'

  return (
    <section className="card" data-tour-id="tasks-panel">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>{panelTitle}</h2>
        {allowBoardView && (
          <ToggleGroup.Root
            className="seg"
            type="single"
            value={projectsMode}
            onValueChange={onProjectsModeChange}
            aria-label="Task view mode"
          >
            <ToggleGroup.Item className="seg-btn" value="board" aria-label="Board view">
              <Icon path="M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z" />
              Board
            </ToggleGroup.Item>
            <ToggleGroup.Item className="seg-btn" value="list" aria-label="List view">
              <Icon path="M4 6h16M4 12h16M4 18h16" />
              List
            </ToggleGroup.Item>
          </ToggleGroup.Root>
        )}
      </div>

      <div className="row wrap tasks-create-actions" style={{ justifyContent: 'flex-end', marginBottom: 8, gap: 8 }}>
        <button
          className="status-chip"
          type="button"
          onClick={openCreateTaskGroupDialog}
          disabled={groupActionBusy}
          title="Create task group"
          aria-label="Create task group"
        >
          + Group
        </button>
        <div className="row" style={{ gap: 6 }}>
          <button
            className="status-chip task-new-task-btn"
            type="button"
            onClick={() => onNewTask('manual')}
            title="Create task"
            aria-label="Create task"
            data-tour-id="tasks-new-task"
          >
            <Icon path="M12 5v14M5 12h14" />
            <span>Task</span>
          </button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                className="action-icon"
                type="button"
                title="More task create options"
                aria-label="More task create options"
              >
                <Icon path="M6 9l6 6 6-6" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="task-group-menu-content" sideOffset={8} align="end">
                <DropdownMenu.Item className="task-group-menu-item" onSelect={() => onNewTask('manual')}>
                  <Icon path="M12 5v14M5 12h14" />
                  <span>Manual task</span>
                </DropdownMenu.Item>
                <DropdownMenu.Item className="task-group-menu-item" onSelect={() => onNewTask('scheduled_instruction')}>
                  <Icon path="M12 8v5l3 2m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0" />
                  <span>Scheduled task</span>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </div>

      {taskTagSuggestions.length > 0 && (
        <div className="row wrap notes-tag-filters task-tag-filters">
          <PopularTagFilters
            tags={taskTagSuggestions}
            selectedTags={searchTags}
            onToggleTag={toggleSearchTag}
            onClear={clearSearchTags}
            idPrefix="project-tag"
          />
        </div>
      )}

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
                            {laneTasks.length > 0 && laneTasks.map((task) => (
                              <BoardTaskCard
                                key={task.id}
                                task={task}
                                status={status}
                                statuses={boardData.statuses}
                                targetGroupId={null}
                                assigneeLabel={getAssigneeLabel(task)}
                                onTagClick={toggleSearchTag}
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
              {boardGroupSections.length > 0 && (
                boardGroupSections.map((group) => {
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
                            {group.groupId && group.managed && (
                              <TaskGroupActionsMenu
                                groupName={group.name}
                                busy={groupActionBusy}
                                onRename={() => openRenameTaskGroupDialog(group.groupId as string, group.name)}
                                onDelete={() => requestDeleteTaskGroup(group.groupId as string, group.name)}
                              />
                            )}
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
                                  {laneTasks.length > 0 && laneTasks.map((task) => (
                                    <BoardTaskCard
                                      key={task.id}
                                      task={task}
                                      status={status}
                                      statuses={boardData.statuses}
                                      targetGroupId={group.groupId}
                                      assigneeLabel={getAssigneeLabel(task)}
                                      onTagClick={toggleSearchTag}
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
                  })
              )}
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
                          {laneTasks.length > 0 && laneTasks.map((task) => (
                            <BoardTaskCard
                              key={task.id}
                              task={task}
                              status={status}
                              statuses={boardData.statuses}
                              targetGroupId={null}
                              assigneeLabel={getAssigneeLabel(task)}
                              onTagClick={toggleSearchTag}
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
          {ungroupedTasks.length > 0 && (
            hasGroups ? (
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
                {ungroupedTasks.length > 0 && ungroupedTasks.map((task) => (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={(event) => onBoardCardDragStart(event, task.id)}
                    onDragEnd={onBoardCardDragEnd}
                  >
                    <TaskListItem
                      task={task}
                      assigneeLabel={getAssigneeLabel(task)}
                      onOpen={onOpenTaskEditor}
                      onTagClick={toggleSearchTag}
                      onRestore={onRestoreTask}
                      onReopen={onReopenTask}
                      onComplete={onCompleteTask}
                    />
                  </div>
                ))}
                {ungroupedTasks.length === 0 && <div className="meta">Drop task here</div>}
              </div>
            ) : (
              <div style={{ marginBottom: 10 }}>
                {ungroupedTasks.map((task) => (
                  <TaskListItem
                    key={task.id}
                    task={task}
                    assigneeLabel={getAssigneeLabel(task)}
                    onOpen={onOpenTaskEditor}
                    onTagClick={toggleSearchTag}
                    onRestore={onRestoreTask}
                    onReopen={onReopenTask}
                    onComplete={onCompleteTask}
                  />
                ))}
              </div>
            )
          )}
          <Accordion.Root
            type="multiple"
            value={openSectionKeys}
            onValueChange={setOpenSectionKeys}
            className="tasks-sections-accordion"
          >
            {taskSections.length > 0 && (
              taskSections.map((section) => {
                  const sectionGroup = section.groupId
                    ? taskGroups.find((group) => group.id === section.groupId) ?? null
                    : null
                  const listDropKey = `list:${section.key}`
                  const isListDropTarget = dropTargetKey === listDropKey
                  const sectionIndex = sectionGroup ? taskGroups.findIndex((group) => group.id === sectionGroup.id) : -1
                  const canMoveUp = sectionGroup ? sectionIndex > 0 : false
                  const canMoveDown = sectionGroup ? sectionIndex >= 0 && sectionIndex < taskGroups.length - 1 : false

                  return (
                    <Accordion.Item
                      key={section.key}
                      value={section.key}
                      className="tasks-section-accordion-item"
                      style={{
                        borderLeft: section.color ? `3px solid ${section.color}` : '3px solid transparent',
                        paddingLeft: 8,
                        marginBottom: 10,
                      }}
                    >
                      <div className="row wrap group-section-head">
                        <Accordion.Header className="group-section-accordion-header">
                          <Accordion.Trigger className="pill subtle group-toggle-pill group-toggle-pill-trigger">
                            <span className="group-toggle-pill-chevron">
                              <Icon path="M6 9l6 6 6-6" />
                            </span>
                            <span className="group-toggle-pill-label">{section.name}</span>
                            <span className="meta group-toggle-pill-count">({section.tasks.length})</span>
                          </Accordion.Trigger>
                        </Accordion.Header>

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
                            <TaskGroupActionsMenu
                              groupName={sectionGroup.name}
                              busy={groupActionBusy}
                              onRename={() => openRenameTaskGroupDialog(sectionGroup.id, sectionGroup.name)}
                              onDelete={() => requestDeleteTaskGroup(sectionGroup.id, sectionGroup.name)}
                            />
                          </div>
                        )}
                      </div>

                      <Accordion.Content className="tasks-section-accordion-content">
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
                                assigneeLabel={getAssigneeLabel(task)}
                                onOpen={onOpenTaskEditor}
                                onTagClick={toggleSearchTag}
                                onRestore={onRestoreTask}
                                onReopen={onReopenTask}
                                onComplete={onCompleteTask}
                              />
                            </div>
                          ))}
                          {section.tasks.length === 0 && (
                            <div className="meta" style={{ minHeight: 64, display: 'grid', alignItems: 'center' }}>
                              Drop task here to move it to this section.
                            </div>
                          )}
                        </div>
                      </Accordion.Content>
                    </Accordion.Item>
                  )
                })
            )}
          </Accordion.Root>

          {filteredTasks.length === 0 && (
            <div className="notice" style={{ marginTop: 10 }}>No tasks in this project.</div>
          )}
        </div>
      )}

      {canLoadMoreTasks && (
        <div className="row" style={{ justifyContent: 'center', marginTop: 12 }}>
          <button
            className="pill subtle"
            type="button"
            onClick={onLoadMoreTasks}
            title="Load more tasks"
            aria-label="Load more tasks"
          >
            Load more tasks
          </button>
        </div>
      )}

      <AlertDialog.Root
        open={taskGroupDialogOpen}
        onOpenChange={(open) => {
          if (!open) closeTaskGroupDialog()
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">{taskGroupDialogTitle}</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">{taskGroupDialogDescription}</AlertDialog.Description>
            <div className="field-control">
              <span className="field-label">Group name</span>
              <input
                type="text"
                value={taskGroupDialogName}
                onChange={(event) => setTaskGroupDialogName(event.target.value)}
                placeholder="Enter group name"
                autoFocus
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    if (!taskGroupDialogSubmitDisabled) submitTaskGroupDialog()
                  }
                }}
              />
            </div>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <button
                className="primary"
                type="button"
                onClick={submitTaskGroupDialog}
                disabled={taskGroupDialogSubmitDisabled}
              >
                {taskGroupDialogSubmitLabel}
              </button>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={deleteTaskGroupPrompt !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTaskGroupPrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Delete task group?</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {deleteTaskGroupPrompt
                ? `Delete "${deleteTaskGroupPrompt.name}"? Linked tasks will become ungrouped.`
                : 'Delete selected task group?'}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="danger"
                  type="button"
                  onClick={confirmDeleteTaskGroup}
                  disabled={groupActionBusy}
                >
                  Delete
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </section>
  )
}
