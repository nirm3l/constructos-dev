import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { Note } from '../../types'
import { AttachmentRefList, ExternalRefEditor, Icon } from '../shared/uiHelpers'
import { TaskDrawerInsights } from './TaskDrawerInsights'

type TaskSelectOption = {
  value: string
  label: string
}

type DuePreset = 'in_one_hour' | 'today_end' | 'tomorrow_morning' | 'next_business_morning' | 'clear'

const TASK_PRIORITY_OPTIONS: TaskSelectOption[] = [
  { value: 'Low', label: 'Low' },
  { value: 'Med', label: 'Med' },
  { value: 'High', label: 'High' },
]

const TASK_TYPE_OPTIONS: TaskSelectOption[] = [
  { value: 'manual', label: 'Manual' },
  { value: 'scheduled_instruction', label: 'Scheduled' },
]

const RECURRING_UNIT_OPTIONS: TaskSelectOption[] = [
  { value: 'm', label: 'minutes' },
  { value: 'h', label: 'hours' },
  { value: 'd', label: 'days' },
]

const STATUS_MATCH_MODE_OPTIONS: TaskSelectOption[] = [
  { value: 'any', label: 'Any selected task' },
  { value: 'all', label: 'All selected tasks' },
]

const TASK_TIMEZONE_OPTIONS_BASE: TaskSelectOption[] = [
  { value: 'UTC', label: 'UTC' },
  { value: 'Europe/Sarajevo', label: 'Europe/Sarajevo' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin' },
  { value: 'Europe/London', label: 'Europe/London' },
  { value: 'Europe/Paris', label: 'Europe/Paris' },
  { value: 'Europe/Rome', label: 'Europe/Rome' },
  { value: 'Europe/Madrid', label: 'Europe/Madrid' },
  { value: 'Europe/Amsterdam', label: 'Europe/Amsterdam' },
  { value: 'Europe/Zurich', label: 'Europe/Zurich' },
  { value: 'Europe/Istanbul', label: 'Europe/Istanbul' },
  { value: 'America/New_York', label: 'America/New_York' },
  { value: 'America/Chicago', label: 'America/Chicago' },
  { value: 'America/Denver', label: 'America/Denver' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles' },
  { value: 'America/Toronto', label: 'America/Toronto' },
  { value: 'America/Sao_Paulo', label: 'America/Sao_Paulo' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo' },
  { value: 'Asia/Seoul', label: 'Asia/Seoul' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney' },
]

function parseCsvIds(raw: string): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const part of String(raw || '').split(',')) {
    const value = String(part || '').trim()
    if (!value) continue
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(value)
  }
  return out
}

function toCsvIds(values: string[]): string {
  return parseCsvIds(values.join(',')).join(', ')
}

function normalizeStatusList(values: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of values) {
    const value = String(raw || '').trim()
    if (!value) continue
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(value)
  }
  return out
}

function shortTaskId(value: string): string {
  const normalized = String(value || '').trim()
  if (!normalized) return ''
  return normalized.length <= 8 ? normalized : normalized.slice(0, 8)
}

function padTwo(value: number): string {
  return String(value).padStart(2, '0')
}

function toLocalDateTimeValue(date: Date): string {
  return [
    `${date.getFullYear()}-${padTwo(date.getMonth() + 1)}-${padTwo(date.getDate())}`,
    `${padTwo(date.getHours())}:${padTwo(date.getMinutes())}`,
  ].join('T')
}

function withTime(date: Date, hour: number, minute: number): Date {
  const next = new Date(date)
  next.setHours(hour, minute, 0, 0)
  return next
}

function nextBusinessDayMorning(base: Date): Date {
  const next = new Date(base)
  next.setDate(next.getDate() + 1)
  while (next.getDay() === 0 || next.getDay() === 6) {
    next.setDate(next.getDate() + 1)
  }
  return withTime(next, 9, 0)
}

function detectLocalTimezone(): string {
  if (typeof Intl === 'undefined' || typeof Intl.DateTimeFormat !== 'function') return 'UTC'
  try {
    const value = String(Intl.DateTimeFormat().resolvedOptions().timeZone || '').trim()
    return value || 'UTC'
  } catch {
    return 'UTC'
  }
}

function buildTimezoneOptions(currentTimezone: string): TaskSelectOption[] {
  const normalized = String(currentTimezone || '').trim() || 'UTC'
  if (TASK_TIMEZONE_OPTIONS_BASE.some((option) => option.value === normalized)) {
    return TASK_TIMEZONE_OPTIONS_BASE
  }
  return [{ value: normalized, label: normalized }, ...TASK_TIMEZONE_OPTIONS_BASE]
}

function TaskDrawerSelect({
  value,
  onValueChange,
  placeholder,
  ariaLabel,
  options,
  triggerClassName,
}: {
  value: string
  onValueChange: (value: string) => void
  placeholder: string
  ariaLabel: string
  options: TaskSelectOption[]
  triggerClassName?: string
}) {
  return (
    <Select.Root value={value} onValueChange={onValueChange}>
      <Select.Trigger className={triggerClassName || 'quickadd-project-trigger taskdrawer-select-trigger'} aria-label={ariaLabel}>
        <Select.Value placeholder={placeholder} />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content taskdrawer-select-content" position="popper" sideOffset={6}>
          <Select.Viewport className="quickadd-project-viewport">
            {options.map((option) => (
              <Select.Item key={option.value} value={option.value} className="quickadd-project-item">
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="quickadd-project-item-indicator">
                  <Icon path="M5 13l4 4L19 7" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}

function TaskDrawerTooltip({
  content,
  children,
}: {
  content: string
  children: React.ReactElement
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="quickadd-tooltip-content" sideOffset={6}>
          {content}
          <Tooltip.Arrow className="quickadd-tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

function applyDuePreset(preset: DuePreset, setValue: (value: string) => void): void {
  const now = new Date()
  let next = ''
  if (preset === 'in_one_hour') {
    const inOneHour = new Date(now.getTime() + 60 * 60 * 1000)
    inOneHour.setMinutes(0, 0, 0)
    next = toLocalDateTimeValue(inOneHour)
  } else if (preset === 'today_end') {
    next = toLocalDateTimeValue(withTime(now, 17, 0))
  } else if (preset === 'tomorrow_morning') {
    const tomorrow = new Date(now)
    tomorrow.setDate(tomorrow.getDate() + 1)
    next = toLocalDateTimeValue(withTime(tomorrow, 9, 0))
  } else if (preset === 'next_business_morning') {
    next = toLocalDateTimeValue(nextBusinessDayMorning(now))
  } else {
    next = ''
  }
  setValue(next)
}

function TaskDueInputWithPresets({
  value,
  onChange,
  label,
  ariaLabel,
}: {
  value: string
  onChange: (value: string) => void
  label: string
  ariaLabel: string
}) {
  return (
    <div className={`quickadd-due ${value ? 'has-value' : ''}`}>
      <span className="quickadd-due-placeholder">{label}</span>
      <input
        className={`due-input ${!value ? 'due-input-empty' : ''}`}
        type="datetime-local"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
      />
      <Popover.Root>
        <Popover.Trigger asChild>
          <button
            type="button"
            className="action-icon quickadd-due-actions-trigger"
            aria-label={`${label} shortcuts`}
            title={`${label} shortcuts`}
          >
            <Icon path="M3 12h18M3 6h18M3 18h18" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className="quickadd-due-popover taskdrawer-due-popover" side="top" align="end" sideOffset={8}>
            <div className="quickadd-due-popover-title">Quick {label.toLowerCase()}</div>
            <div className="quickadd-due-popover-actions">
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('in_one_hour', onChange)}>
                In 1 hour
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('today_end', onChange)}>
                Today 17:00
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('tomorrow_morning', onChange)}>
                Tomorrow 09:00
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('next_business_morning', onChange)}>
                Next business day 09:00
              </button>
              <button type="button" className="quickadd-due-preset quickadd-due-preset-clear" onClick={() => applyDuePreset('clear', onChange)}>
                Clear
              </button>
            </div>
            <Popover.Arrow className="quickadd-due-popover-arrow" />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  )
}

export function TaskDrawer({ state }: { state: any }) {
  const [openSections, setOpenSections] = React.useState<string[]>([])
  const [confirmDiscardOpen, setConfirmDiscardOpen] = React.useState(false)
  const [externalTaskPickerQuery, setExternalTaskPickerQuery] = React.useState('')
  const pendingPostDiscardActionRef = React.useRef<(() => void) | null>(null)

  const forceCloseTaskEditor = React.useCallback(() => {
    state.setSelectedTaskId(null)
    state.setTaskEditorError(null)
  }, [state])

  const requestTaskClose = React.useCallback((postDiscardAction?: () => void) => {
    if (state.taskIsDirty) {
      pendingPostDiscardActionRef.current = postDiscardAction ?? null
      setConfirmDiscardOpen(true)
      return
    }
    forceCloseTaskEditor()
    if (postDiscardAction) postDiscardAction()
  }, [forceCloseTaskEditor, state.taskIsDirty])

  const cancelDiscardTaskChanges = React.useCallback(() => {
    pendingPostDiscardActionRef.current = null
    setConfirmDiscardOpen(false)
  }, [])

  const confirmDiscardTaskChanges = React.useCallback(() => {
    const postDiscardAction = pendingPostDiscardActionRef.current
    pendingPostDiscardActionRef.current = null
    setConfirmDiscardOpen(false)
    forceCloseTaskEditor()
    if (postDiscardAction) postDiscardAction()
  }, [forceCloseTaskEditor])

  const ensureSectionOpen = React.useCallback((section: string) => {
    setOpenSections((prev) => (prev.includes(section) ? prev : [...prev, section]))
  }, [])

  React.useEffect(() => {
    setOpenSections([])
  }, [state.selectedTask?.id])

  React.useEffect(() => {
    setExternalTaskPickerQuery('')
  }, [state.selectedTask?.id])

  if (!state.selectedTask) return null
  const linkedNotes: Note[] = state.taskNotes?.data?.items ?? []
  const taskGroups: Array<{ id: string; name: string }> = state.taskGroups ?? []
  const selectedTaskGroupId = String(state.editTaskGroupId || '')
  const hasSelectedTaskGroup = selectedTaskGroupId
    ? taskGroups.some((group) => group.id === selectedTaskGroupId)
    : true
  const statusOptions: string[] = (state.taskStatusOptions ?? []).length > 0
    ? state.taskStatusOptions
    : ['To do', 'In progress', 'Done']
  const localTimezone = detectLocalTimezone()

  const statusSelectOptions = (() => {
    const ordered = [...statusOptions, String(state.editStatus || '').trim()].map((item) => String(item || '').trim())
    const out: TaskSelectOption[] = []
    const seen = new Set<string>()
    for (const status of ordered) {
      if (!status) continue
      const key = status.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ value: status, label: status })
    }
    return out
  })()

  const groupSelectOptions = (() => {
    const out: TaskSelectOption[] = [{ value: '__none__', label: 'Ungrouped' }]
    if (!hasSelectedTaskGroup && selectedTaskGroupId) {
      out.push({
        value: selectedTaskGroupId,
        label: `Missing group (${selectedTaskGroupId.slice(0, 8)})`,
      })
    }
    for (const group of taskGroups) {
      out.push({ value: group.id, label: group.name })
    }
    return out
  })()

  const groupSelectValue = selectedTaskGroupId || '__none__'
  const statusSelectValue = String(state.editStatus || '').trim() || statusSelectOptions[0]?.value || 'To do'
  const prioritySelectValue = (() => {
    const normalized = String(state.editPriority || '').trim()
    if (normalized === 'Low' || normalized === 'Med' || normalized === 'High') return normalized
    return 'Med'
  })()
  const taskTypeSelectValue = String(state.editTaskType || '').trim() === 'scheduled_instruction' ? 'scheduled_instruction' : 'manual'
  const recurringUnitSelectValue = (() => {
    const normalized = String(state.editRecurringUnit || '').trim().toLowerCase()
    if (normalized === 'm' || normalized === 'h' || normalized === 'd') return normalized
    return 'h'
  })()
  const externalMatchModeValue = String(state.editStatusTriggerExternalMatchMode || '').trim().toLowerCase() === 'all' ? 'all' : 'any'
  const timezoneSelectValue = String(state.editScheduleTimezone || '').trim() || localTimezone
  const timezoneOptions = buildTimezoneOptions(timezoneSelectValue)
  const scheduleRunOnStatusesValue = (() => {
    const current = normalizeStatusList(Array.isArray(state.editScheduleRunOnStatuses) ? state.editScheduleRunOnStatuses : [])
    if (current.length > 0) return current
    return ['In progress']
  })()
  const scheduleRunStatusOptions = (() => {
    const ordered = [...statusOptions, ...scheduleRunOnStatusesValue].map((item) => String(item || '').trim())
    const out: string[] = []
    const seen = new Set<string>()
    for (const status of ordered) {
      if (!status) continue
      const key = status.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push(status)
    }
    return out
  })()
  const selectedExternalTaskIds = parseCsvIds(state.editStatusTriggerExternalTaskIdsText)
  const externalSourceTaskOptions = (() => {
    const selectedTaskId = String(state.selectedTask?.id || '').trim()
    const selectedProjectId = String(state.selectedTask?.project_id || '').trim()
    const out: Array<{ id: string; title: string; status: string }> = []
    const seen = new Set<string>()
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        const id = String(item?.id || '').trim()
        if (!id || seen.has(id)) continue
        if (id === selectedTaskId) continue
        const projectId = String(item?.project_id || '').trim()
        if (selectedProjectId && projectId && projectId !== selectedProjectId) continue
        seen.add(id)
        out.push({
          id,
          title: String(item?.title || 'Untitled task').trim() || 'Untitled task',
          status: String(item?.status || '').trim(),
        })
      }
    }
    attach(state.taskLookupItems)
    attach(state.taskListItems)
    out.sort((a, b) => a.title.localeCompare(b.title))
    return out
  })()
  const filteredExternalSourceTaskOptions = (() => {
    const query = String(externalTaskPickerQuery || '').trim().toLowerCase()
    if (!query) return externalSourceTaskOptions
    return externalSourceTaskOptions.filter((item) => {
      return (
        item.id.toLowerCase().includes(query) ||
        item.title.toLowerCase().includes(query) ||
        item.status.toLowerCase().includes(query)
      )
    })
  })()
  const selectedExternalSourceTaskLabels = (() => {
    if (selectedExternalTaskIds.length === 0) return []
    const byId = new Map<string, { title: string; status: string }>()
    for (const item of externalSourceTaskOptions) {
      byId.set(item.id, { title: item.title, status: item.status })
    }
    return selectedExternalTaskIds.map((taskId) => {
      const fallbackTitle = String(state.taskNameMap?.[taskId] || '').trim() || `Task ${taskId.slice(0, 8)}`
      const fromOptions = byId.get(taskId)
      return {
        id: taskId,
        title: fromOptions?.title || fallbackTitle,
        status: fromOptions?.status || '',
      }
    })
  })()

  const toggleExternalSourceTask = (taskId: string) => {
    const current = parseCsvIds(state.editStatusTriggerExternalTaskIdsText)
    const taskIdKey = String(taskId || '').trim().toLowerCase()
    const next = current.filter((value) => String(value || '').trim().toLowerCase() !== taskIdKey)
    if (next.length === current.length) {
      next.push(taskId)
    }
    state.setEditStatusTriggerExternalTaskIdsText(toCsvIds(next))
  }

  const clearExternalSourceTasks = () => {
    state.setEditStatusTriggerExternalTaskIdsText('')
  }
  const externalRefs = state.parseExternalRefsText(state.editTaskExternalRefsText)
  const attachmentRefs = state.parseAttachmentRefsText(state.editTaskAttachmentRefsText)
  const externalLinksMeta = externalRefs.length === 0 ? 'No links yet' : `${externalRefs.length} linked reference${externalRefs.length === 1 ? '' : 's'}`
  const attachmentsMeta = attachmentRefs.length === 0 ? 'No files yet' : `${attachmentRefs.length} attached file${attachmentRefs.length === 1 ? '' : 's'}`
  const linkedNotesMeta = state.taskNotes?.isLoading
    ? 'Loading notes...'
    : linkedNotes.length === 0
      ? 'No notes linked'
      : `${linkedNotes.length} note${linkedNotes.length === 1 ? '' : 's'} linked`

  const addTaskTagFromQuery = () => {
    const raw = String(state.taskTagPickerQuery || '').trim()
    if (!raw) return
    const suggested = (Array.isArray(state.filteredTaskTags) ? state.filteredTaskTags : []).find(
      (tag: string) => String(tag || '').toLowerCase() === raw.toLowerCase()
    )
    const candidate = String(suggested || raw).trim()
    if (!candidate) return
    if (state.taskTagsLower.has(candidate.toLowerCase())) {
      state.setTaskTagPickerQuery('')
      return
    }
    state.toggleTaskTag(candidate)
    state.setTaskTagPickerQuery('')
  }

  const handleTaskFileInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.currentTarget.value = ''
    if (files.length === 0 || !state.selectedTask) return
    const uploadedRefs: any[] = []
    let firstErrorMessage = ''
    for (const file of files) {
      try {
        const ref = await state.uploadAttachmentRef(file, {
          project_id: state.selectedTask.project_id,
          task_id: state.selectedTask.id,
        })
        uploadedRefs.push(ref)
      } catch (err) {
        if (!firstErrorMessage) firstErrorMessage = state.toErrorMessage(err, 'Upload failed')
      }
    }
    if (uploadedRefs.length > 0) {
      state.setEditTaskAttachmentRefsText((prev: string) =>
        state.attachmentRefsToText([
          ...state.parseAttachmentRefsText(prev),
          ...uploadedRefs,
        ])
      )
    }
    if (firstErrorMessage) {
      state.setUiError(firstErrorMessage)
      state.setTaskEditorError(firstErrorMessage)
    }
  }

  return (
    <Tooltip.Provider delayDuration={180}>
      <div className="drawer open" onClick={() => requestTaskClose()}>
        <div className="drawer-body task-drawer-body" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="task-header-main">
            <h3 className="drawer-title">{state.selectedTask.title}</h3>
          </div>
          <div className="row task-header-actions">
            {state.taskIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
            <TaskDrawerTooltip content="Save task">
              <button
                className="action-icon primary"
                onClick={() => state.saveTaskMutation.mutate()}
                disabled={state.saveTaskMutation.isPending || !state.taskIsDirty}
                title="Save task"
                aria-label="Save task"
              >
                <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
              </button>
            </TaskDrawerTooltip>
            <TaskDrawerTooltip content="Copy task link">
              <button
                className="action-icon"
                onClick={() =>
                  state.copyShareLink({
                    tab: 'tasks',
                    projectId: state.selectedTask.project_id,
                    taskId: state.selectedTask.id,
                  })
                }
                title="Copy task link"
                aria-label="Copy task link"
              >
                <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
              </button>
            </TaskDrawerTooltip>
            <DropdownMenu.Root>
              <TaskDrawerTooltip content="More actions">
                <DropdownMenu.Trigger asChild>
                  <button className="action-icon" title="More actions" aria-label="More actions">
                    <Icon path="M4 12h16M4 6h16M4 18h16" />
                  </button>
                </DropdownMenu.Trigger>
              </TaskDrawerTooltip>
              <DropdownMenu.Portal>
                <DropdownMenu.Content className="taskdrawer-actions-menu-content" sideOffset={8} align="end">
                  <DropdownMenu.Item
                    className="taskdrawer-actions-menu-item"
                    onSelect={() => {
                      if (state.selectedTask.status === 'Done') state.reopenTaskMutation.mutate(state.selectedTask.id)
                      else state.completeTaskMutation.mutate(state.selectedTask.id)
                    }}
                  >
                    {state.selectedTask.status === 'Done' ? 'Reopen task' : 'Complete task'}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className="taskdrawer-actions-menu-item"
                    onSelect={() => {
                      if (state.selectedTask.archived) state.restoreTaskMutation.mutate(state.selectedTask.id)
                      else state.archiveTaskMutation.mutate(state.selectedTask.id)
                    }}
                  >
                    {state.selectedTask.archived ? 'Restore task' : 'Archive task'}
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
            <TaskDrawerTooltip content="Close task">
              <button className="action-icon" onClick={() => requestTaskClose()} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </TaskDrawerTooltip>
          </div>
        </div>
        <label className="field-control" style={{ marginTop: 8, marginBottom: 8 }}>
          <span className="field-label">Task name</span>
          <input
            value={state.editTitle}
            onChange={(e) => state.setEditTitle(e.target.value)}
            placeholder="Task title"
            style={{ width: '100%' }}
          />
        </label>
        <div className="field-control" style={{ marginBottom: 8 }}>
          <span className="field-label">Project</span>
          <button
            className="pill subtle task-project-pill"
            onClick={() => {
              requestTaskClose(() => {
                state.setSelectedProjectId(state.selectedTask.project_id)
                state.setTab('projects')
              })
            }}
            title="Open project"
            aria-label="Open project"
          >
            <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
            <span>{state.projectNames[state.selectedTask.project_id] || state.selectedTask.project_id}</span>
          </button>
        </div>
        {state.selectedTask.specification_id && (
          <div className="field-control" style={{ marginBottom: 8 }}>
            <span className="field-label">Specification</span>
            <button
              className="pill subtle task-project-pill task-spec-pill"
              onClick={() => state.openSpecification(state.selectedTask.specification_id as string, state.selectedTask.project_id)}
              title="Open linked specification"
              aria-label="Open linked specification"
            >
              <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
              <span>
                {state.specificationNameMap[state.selectedTask.specification_id] ||
                  `Specification ${String(state.selectedTask.specification_id).slice(0, 8)}`}
              </span>
            </button>
          </div>
        )}
        <div className="task-edit-grid task-main-fields" style={{ marginBottom: 8 }}>
          <label className="field-control task-field-full">
            <span className="field-label">Group</span>
            <TaskDrawerSelect
              value={groupSelectValue}
              onValueChange={(value) => state.setEditTaskGroupId(value === '__none__' ? '' : value)}
              placeholder="Ungrouped"
              ariaLabel="Task group"
              options={groupSelectOptions}
            />
          </label>
          <label className="field-control task-field-half">
            <span className="field-label">Status</span>
            <TaskDrawerSelect
              value={statusSelectValue}
              onValueChange={(value) => state.setEditStatus(value)}
              placeholder="Select status"
              ariaLabel="Task status"
              options={statusSelectOptions}
            />
          </label>
          <label className="field-control task-field-half">
            <span className="field-label">Priority</span>
            <TaskDrawerSelect
              value={prioritySelectValue}
              onValueChange={(value) => state.setEditPriority(value)}
              placeholder="Priority"
              ariaLabel="Task priority"
              options={TASK_PRIORITY_OPTIONS}
            />
          </label>
          <label className="field-control task-field-full">
            <span className="field-label">Due date</span>
            <TaskDueInputWithPresets
              value={state.editDueDate}
              onChange={(value) => state.setEditDueDate(value)}
              label="Due date"
              ariaLabel="Due date"
            />
          </label>
        </div>
        <label className="field-control" style={{ marginBottom: 10 }}>
          <span className="field-label">Description</span>
          <textarea value={state.editDescription} onChange={(e) => state.setEditDescription(e.target.value)} rows={4} style={{ width: '100%' }} />
        </label>
        <div className="tag-bar" aria-label="Task tags" style={{ marginBottom: 10 }}>
          <div className="tag-chiplist">
            {state.editTaskTags.length === 0 ? (
              <span className="meta">No tags</span>
            ) : (
              state.editTaskTags.map((t: string) => (
                <span
                  key={t}
                  className="tag-chip"
                  style={{
                    background: `linear-gradient(135deg, hsl(${state.tagHue(t)}, 70%, 92%), hsl(${state.tagHue(t)}, 70%, 86%))`,
                    borderColor: `hsl(${state.tagHue(t)}, 70%, 74%)`,
                    color: `hsl(${state.tagHue(t)}, 55%, 22%)`
                  }}
                >
                  <span className="tag-text">{t}</span>
                </span>
              ))
            )}
          </div>
          <Popover.Root open={state.showTaskTagPicker} onOpenChange={(open) => state.setShowTaskTagPicker(open)}>
            <Popover.Trigger asChild>
              <button className="action-icon" title="Edit tags" aria-label="Edit tags">
                <Icon path="M3 12h8m-8 6h12m-12-12h18" />
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content className="quickadd-tag-popover taskdrawer-tag-popover" side="top" align="end" sideOffset={8}>
                <div className="quickadd-tag-popover-header">
                  <h4 className="quickadd-tag-popover-title">Task Tags</h4>
                  <button
                    className="status-chip"
                    type="button"
                    onClick={() => state.setShowTaskTagPicker(false)}
                    title="Done"
                    aria-label="Done"
                  >
                    Done
                  </button>
                </div>
                <div className="tag-picker-input-row">
                  <input
                    value={state.taskTagPickerQuery}
                    onChange={(e) => state.setTaskTagPickerQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        e.stopPropagation()
                        addTaskTagFromQuery()
                      }
                    }}
                    placeholder="Search or create tag"
                    autoFocus
                  />
                </div>
                <div className="tag-picker-list" role="listbox" aria-label="Tag list">
                  {state.filteredTaskTags.map((t: string) => {
                    const selected = state.taskTagsLower.has(t.toLowerCase())
                    return (
                      <button
                        key={t}
                        className={`tag-picker-item ${selected ? 'selected' : ''}`}
                        onClick={() => state.toggleTaskTag(t)}
                        aria-label={selected ? `Remove tag ${t}` : `Add tag ${t}`}
                        title={selected ? 'Remove tag' : 'Add tag'}
                      >
                        <span className="tag-picker-check" aria-hidden="true">
                          <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
                        </span>
                        <span className="tag-picker-name">{t}</span>
                      </button>
                    )
                  })}
                  {state.filteredTaskTags.length === 0 && <div className="meta">No tags found.</div>}
                </div>
                {state.canCreateTaskTag && (
                  <button
                    className="primary tag-picker-create"
                    onClick={addTaskTagFromQuery}
                    title="Create tag"
                    aria-label="Create tag"
                  >
                    Add "{state.taskTagPickerQuery.trim()}"
                  </button>
                )}
                <Popover.Arrow className="quickadd-tag-popover-arrow" />
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
        <div className="task-edit-grid" style={{ marginBottom: 8 }}>
          <label className="field-control">
            <span className="field-label">Task type</span>
            <ToggleGroup.Root
              type="single"
              className="taskdrawer-type-toggle-group"
              value={taskTypeSelectValue}
              onValueChange={(value) => {
                if (!value) return
                const normalized = value === 'scheduled_instruction' ? 'scheduled_instruction' : 'manual'
                state.setEditTaskType(normalized)
              }}
              aria-label="Task type"
            >
              {TASK_TYPE_OPTIONS.map((option) => (
                <ToggleGroup.Item
                  key={option.value}
                  value={option.value}
                  className="taskdrawer-type-toggle-item"
                  aria-label={option.label}
                >
                  {option.label}
                </ToggleGroup.Item>
              ))}
            </ToggleGroup.Root>
          </label>
          <label className="field-control">
            <span className="field-label">Status triggers</span>
            <div className="row wrap">
              <label className="status-chip" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  checked={Boolean(state.editStatusTriggerSelfEnabled)}
                  onChange={(e) => state.setEditStatusTriggerSelfEnabled(Boolean(e.target.checked))}
                />
                This task changes status
              </label>
              <label className="status-chip" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  checked={Boolean(state.editStatusTriggerExternalEnabled)}
                  onChange={(e) => state.setEditStatusTriggerExternalEnabled(Boolean(e.target.checked))}
                />
                Other task changes status
              </label>
            </div>
          </label>
        </div>
        {state.taskEditorError && <div className="notice notice-error" role="alert" style={{ marginBottom: 8 }}>{state.taskEditorError}</div>}
        {(state.editTaskType === 'scheduled_instruction' ||
          state.editStatusTriggerSelfEnabled ||
          state.editStatusTriggerExternalEnabled) && (
          <label className="field-control" style={{ marginBottom: 8 }}>
            <span className="field-label">Instruction</span>
            <textarea
              value={state.editScheduledInstruction}
              onChange={(e) => state.setEditScheduledInstruction(e.target.value)}
              rows={3}
              style={{ width: '100%' }}
              placeholder="Executed when any enabled trigger fires"
            />
          </label>
        )}
        {state.editStatusTriggerSelfEnabled && (
          <div className="task-edit-grid" style={{ marginBottom: 8 }}>
            <label className="field-control">
              <span className="field-label">Self trigger from statuses (optional)</span>
              <input
                value={state.editStatusTriggerSelfFromStatusesText}
                onChange={(e) => state.setEditStatusTriggerSelfFromStatusesText(e.target.value)}
                placeholder="To do, In progress"
              />
            </label>
            <label className="field-control">
              <span className="field-label">Self trigger to statuses (required)</span>
              <input
                value={state.editStatusTriggerSelfToStatusesText}
                onChange={(e) => state.setEditStatusTriggerSelfToStatusesText(e.target.value)}
                placeholder="Done"
              />
            </label>
          </div>
        )}
        {state.editStatusTriggerExternalEnabled && (
          <>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <label className="field-control">
                <span className="field-label">External match mode</span>
                <TaskDrawerSelect
                  value={externalMatchModeValue}
                  onValueChange={(value) => state.setEditStatusTriggerExternalMatchMode(value === 'all' ? 'all' : 'any')}
                  placeholder="Match mode"
                  ariaLabel="External trigger match mode"
                  options={STATUS_MATCH_MODE_OPTIONS}
                />
              </label>
              <label className="field-control">
                <span className="field-label">Source task IDs (comma-separated)</span>
                <input
                  value={state.editStatusTriggerExternalTaskIdsText}
                  onChange={(e) => state.setEditStatusTriggerExternalTaskIdsText(e.target.value)}
                  placeholder="a1b2c3, d4e5f6"
                />
                <div className="meta" style={{ marginTop: 6 }}>
                  Paste IDs directly, or use picker below.
                </div>
                <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
                  <Popover.Root>
                    <Popover.Trigger asChild>
                      <button
                        type="button"
                        className="status-chip"
                        aria-label="Pick source tasks"
                        title="Pick source tasks"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
                      >
                        <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
                        <span>Pick source tasks</span>
                        <span className="badge">{selectedExternalTaskIds.length}</span>
                      </button>
                    </Popover.Trigger>
                    <Popover.Portal>
                      <Popover.Content className="quickadd-tag-popover taskdrawer-tag-popover" side="top" align="start" sideOffset={8}>
                        <div className="quickadd-tag-popover-header">
                          <h4 className="quickadd-tag-popover-title">Source Tasks</h4>
                          <button
                            className="status-chip"
                            type="button"
                            onClick={clearExternalSourceTasks}
                            title="Clear selection"
                            aria-label="Clear selection"
                          >
                            Clear
                          </button>
                        </div>
                        <div className="tag-picker-input-row">
                          <input
                            value={externalTaskPickerQuery}
                            onChange={(e) => setExternalTaskPickerQuery(e.target.value)}
                            placeholder="Search by title, status, or ID"
                          />
                        </div>
                        <div className="tag-picker-list" role="listbox" aria-label="Source task list">
                          {filteredExternalSourceTaskOptions.map((taskItem) => {
                            const selected = selectedExternalTaskIds.some((id) => id.toLowerCase() === taskItem.id.toLowerCase())
                            return (
                              <button
                                key={taskItem.id}
                                className={`tag-picker-item ${selected ? 'selected' : ''}`}
                                onClick={() => toggleExternalSourceTask(taskItem.id)}
                                aria-label={selected ? `Remove ${taskItem.title}` : `Add ${taskItem.title}`}
                                title={taskItem.id}
                              >
                                <span className="tag-picker-check" aria-hidden="true">
                                  <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
                                </span>
                                <span className="tag-picker-name">{taskItem.title}</span>
                                <span className="meta">#{shortTaskId(taskItem.id)}</span>
                                {taskItem.status && <span className="meta">{taskItem.status}</span>}
                              </button>
                            )
                          })}
                          {filteredExternalSourceTaskOptions.length === 0 && <div className="meta">No tasks found.</div>}
                        </div>
                        <Popover.Arrow className="quickadd-tag-popover-arrow" />
                      </Popover.Content>
                    </Popover.Portal>
                  </Popover.Root>
                </div>
                {selectedExternalSourceTaskLabels.length > 0 && (
                  <div className="row wrap" style={{ marginTop: 8 }}>
                    {selectedExternalSourceTaskLabels.map((taskItem) => (
                      <button
                        key={taskItem.id}
                        type="button"
                        className="status-chip"
                        onClick={() => toggleExternalSourceTask(taskItem.id)}
                        title={taskItem.id}
                        aria-label={`Remove ${taskItem.title}`}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                      >
                        <Icon path="M6 6l12 12M18 6 6 18" />
                        <span>{taskItem.title}</span>
                        {taskItem.status && <span className="meta">{taskItem.status}</span>}
                      </button>
                    ))}
                  </div>
                )}
              </label>
            </div>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <label className="field-control">
                <span className="field-label">External trigger from statuses (optional)</span>
                <input
                  value={state.editStatusTriggerExternalFromStatusesText}
                  onChange={(e) => state.setEditStatusTriggerExternalFromStatusesText(e.target.value)}
                  placeholder="To do, In progress"
                />
              </label>
              <label className="field-control">
                <span className="field-label">External trigger to statuses (required)</span>
                <input
                  value={state.editStatusTriggerExternalToStatusesText}
                  onChange={(e) => state.setEditStatusTriggerExternalToStatusesText(e.target.value)}
                  placeholder="Done"
                />
              </label>
            </div>
          </>
        )}
        {state.editTaskType === 'scheduled_instruction' && (
          <>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <label className="field-control">
                <span className="field-label">Scheduled for</span>
                <TaskDueInputWithPresets
                  value={state.editScheduledAtUtc}
                  onChange={(value) => state.setEditScheduledAtUtc(value)}
                  label="Run at"
                  ariaLabel="Scheduled for"
                />
              </label>
              <label className="field-control">
                <span className="field-label">Timezone</span>
                <TaskDrawerSelect
                  value={timezoneSelectValue}
                  onValueChange={(value) => state.setEditScheduleTimezone(value)}
                  placeholder="Timezone"
                  ariaLabel="Schedule timezone"
                  options={timezoneOptions}
                />
              </label>
              <label className="field-control taskdrawer-schedule-statuses-field">
                <span className="field-label">Run on statuses</span>
                <ToggleGroup.Root
                  type="multiple"
                  className="taskdrawer-status-toggle-group"
                  value={scheduleRunOnStatusesValue}
                  onValueChange={(value) => {
                    const normalized = normalizeStatusList(value)
                    if (normalized.length === 0) return
                    state.setEditScheduleRunOnStatuses(normalized)
                  }}
                  aria-label="Statuses that allow scheduled runs"
                >
                  {scheduleRunStatusOptions.map((status) => (
                    <ToggleGroup.Item
                      key={status}
                      value={status}
                      className="taskdrawer-status-toggle-item"
                      aria-label={`Schedule runs on ${status}`}
                    >
                      <span className="taskdrawer-status-toggle-check" aria-hidden="true">
                        <Icon path="M5 13l4 4L19 7" />
                      </span>
                      <span>{status}</span>
                    </ToggleGroup.Item>
                  ))}
                </ToggleGroup.Root>
                <div className="meta" style={{ marginTop: 6 }}>
                  Scheduler queues only while task status matches one of the selected values.
                </div>
              </label>
            </div>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <div className="field-control">
                <span className="field-label">Repeat (optional)</span>
                <div className="row wrap">
                  <input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={state.editRecurringEvery}
                    onChange={(e) => state.setEditRecurringEvery(e.target.value)}
                    placeholder="Every"
                    style={{ width: 120 }}
                  />
                  <TaskDrawerSelect
                    value={recurringUnitSelectValue}
                    onValueChange={(value) => state.setEditRecurringUnit(value as 'm' | 'h' | 'd')}
                    placeholder="Unit"
                    ariaLabel="Recurring unit"
                    options={RECURRING_UNIT_OPTIONS}
                    triggerClassName="quickadd-project-trigger taskdrawer-select-trigger taskdrawer-recurring-unit-trigger"
                  />
                  <button
                    className="action-icon"
                    onClick={() => {
                      state.setEditRecurringEvery('')
                      state.setEditRecurringUnit('h')
                    }}
                    title="Clear repeat"
                    aria-label="Clear repeat"
                  >
                    <Icon path="M6 6l12 12M18 6 6 18" />
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
        {state.selectedTask.schedule_state && state.editTaskType === 'scheduled_instruction' && (
          <div className="row wrap" style={{ marginBottom: 8 }}>
            <span className="badge">Schedule: {state.selectedTask.schedule_state}</span>
            <span className={`prio prio-${state.priorityTone(state.selectedTask.priority)}`} title="Priority">
              {state.selectedTask.priority}
            </span>
            {state.selectedTask.scheduled_at_utc && <span className="meta">Scheduled for: {new Date(state.selectedTask.scheduled_at_utc).toLocaleString()}</span>}
            {scheduleRunOnStatusesValue.length > 0 && <span className="meta">Runs on: {scheduleRunOnStatusesValue.join(', ')}</span>}
            {state.selectedTask.recurring_rule && <span className="meta">Repeats: {String(state.selectedTask.recurring_rule)}</span>}
            {state.selectedTask.last_schedule_error && <span className="meta">Last error: {state.selectedTask.last_schedule_error}</span>}
          </div>
        )}
        <input
          ref={state.taskFileInputRef}
          type="file"
          multiple
          style={{ display: 'none' }}
          onChange={handleTaskFileInputChange}
        />
        <Accordion.Root
          type="multiple"
          className="taskdrawer-sections"
          value={openSections}
          onValueChange={setOpenSections}
        >
          <Accordion.Item value="external-links" className="taskdrawer-section-item taskdrawer-section-links">
            <div className="taskdrawer-section-headrow">
              <Accordion.Header className="taskdrawer-section-header">
                <Accordion.Trigger className="taskdrawer-section-trigger">
                  <span className="taskdrawer-section-icon" aria-hidden="true">
                    <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                  </span>
                  <span className="taskdrawer-section-head">
                    <span className="taskdrawer-section-title">External links</span>
                    <span className="taskdrawer-section-meta">{externalLinksMeta}</span>
                  </span>
                  <span className="taskdrawer-section-badge">{externalRefs.length}</span>
                  <span className="taskdrawer-section-chevron" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <button
                className="status-chip taskdrawer-section-quick-action"
                type="button"
                onClick={() => ensureSectionOpen('external-links')}
                aria-label="Edit external links"
                title="Edit external links"
              >
                <Icon path="M12 20h9M4 16l10.5-10.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
              </button>
            </div>
            <Accordion.Content className="taskdrawer-section-content">
              <ExternalRefEditor
                refs={externalRefs}
                onRemoveIndex={(idx) => state.setEditTaskExternalRefsText((prev: string) => state.removeExternalRefByIndex(prev, idx))}
                onAdd={(ref) => state.setEditTaskExternalRefsText((prev: string) => state.externalRefsToText([...state.parseExternalRefsText(prev), ref]))}
              />
            </Accordion.Content>
          </Accordion.Item>

          <Accordion.Item value="attachments" className="taskdrawer-section-item taskdrawer-section-attachments">
            <div className="taskdrawer-section-headrow">
              <Accordion.Header className="taskdrawer-section-header">
                <Accordion.Trigger className="taskdrawer-section-trigger">
                  <span className="taskdrawer-section-icon" aria-hidden="true">
                    <Icon path="M21.44 11.05 12 20.5a5 5 0 1 1-7.07-7.07l9.9-9.9a3.5 3.5 0 1 1 4.95 4.95l-9.2 9.19a2 2 0 1 1-2.83-2.83l8.49-8.48" />
                  </span>
                  <span className="taskdrawer-section-head">
                    <span className="taskdrawer-section-title">File attachments</span>
                    <span className="taskdrawer-section-meta">{attachmentsMeta}</span>
                  </span>
                  <span className="taskdrawer-section-badge">{attachmentRefs.length}</span>
                  <span className="taskdrawer-section-chevron" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <button
                className="status-chip taskdrawer-section-quick-action"
                type="button"
                onClick={() => state.taskFileInputRef.current?.click()}
                aria-label="Upload files"
                title="Upload files"
              >
                <Icon path="M12 3v12m0-12-4 4m4-4 4 4M4 17v3h16v-3" />
              </button>
            </div>
            <Accordion.Content className="taskdrawer-section-content">
              <div className="row" style={{ marginBottom: 8 }}>
                <button className="status-chip" type="button" onClick={() => state.taskFileInputRef.current?.click()}>
                  Upload files
                </button>
              </div>
              <AttachmentRefList
                refs={attachmentRefs}
                workspaceId={state.workspaceId}
                userId={state.userId}
                onRemovePath={(path) => state.setEditTaskAttachmentRefsText((prev: string) => state.removeAttachmentByPath(prev, path))}
              />
            </Accordion.Content>
          </Accordion.Item>

          <Accordion.Item value="linked-notes" className="taskdrawer-section-item taskdrawer-section-notes">
            <div className="taskdrawer-section-headrow">
              <Accordion.Header className="taskdrawer-section-header">
                <Accordion.Trigger className="taskdrawer-section-trigger">
                  <span className="taskdrawer-section-icon" aria-hidden="true">
                    <Icon path="M7 4h10a2 2 0 0 1 2 2v14l-4-2-3 2-3-2-4 2V6a2 2 0 0 1 2-2z" />
                  </span>
                  <span className="taskdrawer-section-head">
                    <span className="taskdrawer-section-title">Linked notes</span>
                    <span className="taskdrawer-section-meta">{linkedNotesMeta}</span>
                  </span>
                  <span className="taskdrawer-section-badge">{linkedNotes.length}</span>
                  <span className="taskdrawer-section-chevron" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <button
                className="status-chip taskdrawer-section-quick-action"
                type="button"
                onClick={() => {
                  requestTaskClose(() => {
                    state.createNoteMutation.mutate({
                      title: 'Untitled note',
                      body: '',
                      project_id: state.selectedTask.project_id,
                      task_id: state.selectedTask.id,
                      force_new: true,
                    })
                  })
                }}
                disabled={state.createNoteMutation.isPending}
                aria-label="Create linked note"
                title="Create linked note"
              >
                <Icon path="M12 5v14M5 12h14" />
              </button>
            </div>
            <Accordion.Content className="taskdrawer-section-content">
              <div className="meta" style={{ marginBottom: 4 }}>Notes linked to this task</div>
              {state.taskNotes?.isLoading ? (
                <div className="meta">Loading linked notes...</div>
              ) : linkedNotes.length === 0 ? (
                <div className="meta">No linked notes yet.</div>
              ) : (
                <div className="spec-linked-list">
                  {linkedNotes.map((note) => (
                    <div key={note.id} className="spec-linked-row">
                      <div style={{ minWidth: 0 }}>
                        <strong>{note.title || 'Untitled note'}</strong>
                        <div className="meta">{(note.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                      </div>
                      <button
                        className="status-chip"
                        type="button"
                        onClick={() => {
                          requestTaskClose(() => {
                            state.openNote(note.id, note.project_id)
                          })
                        }}
                      >
                        Open
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </Accordion.Content>
          </Accordion.Item>
        </Accordion.Root>

        <div className="taskdrawer-meta-panel" role="note" aria-label="Task metadata">
          <div className="taskdrawer-meta-item">
            <span className="taskdrawer-meta-label">Task ID</span>
            <code className="taskdrawer-meta-code">{state.selectedTask.id}</code>
          </div>
          <div className="taskdrawer-meta-item">
            <span className="taskdrawer-meta-label">Timeline</span>
            <span className="taskdrawer-meta-value">
              Created by: {state.selectedTaskCreator}
              {state.selectedTaskTimeMeta ? ` | ${state.selectedTaskTimeMeta.label}: ${state.toUserDateTime(state.selectedTaskTimeMeta.value, state.userTimezone)}` : ''}
            </span>
          </div>
        </div>
        <TaskDrawerInsights state={state} />
        </div>
      </div>
      <AlertDialog.Root
        open={confirmDiscardOpen}
        onOpenChange={(open) => {
          if (!open) cancelDiscardTaskChanges()
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Discard task changes?</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              You have unsaved task changes. Discard and continue?
            </AlertDialog.Description>
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
              <AlertDialog.Cancel asChild>
                <button className="status-chip" type="button" onClick={cancelDiscardTaskChanges}>
                  Keep editing
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button className="action-icon primary" type="button" onClick={confirmDiscardTaskChanges} aria-label="Discard task changes">
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </Tooltip.Provider>
  )
}
