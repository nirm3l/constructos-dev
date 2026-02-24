import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
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
  const ensureSectionOpen = React.useCallback((section: string) => {
    setOpenSections((prev) => (prev.includes(section) ? prev : [...prev, section]))
  }, [])

  React.useEffect(() => {
    setOpenSections([])
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
  const timezoneSelectValue = String(state.editScheduleTimezone || '').trim() || localTimezone
  const timezoneOptions = buildTimezoneOptions(timezoneSelectValue)
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
          project_id: state.editProjectId || state.selectedTask.project_id,
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
      <div className="drawer open" onClick={() => state.closeTaskEditor()}>
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
                    onSelect={() =>
                      state.copyShareLink({
                        tab: 'tasks',
                        projectId: state.selectedTask.project_id,
                        taskId: state.selectedTask.id,
                      })
                    }
                  >
                    Copy task link
                  </DropdownMenu.Item>
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
              <button className="action-icon" onClick={() => state.closeTaskEditor()} title="Close" aria-label="Close">
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
              if (!state.closeTaskEditor()) return
              state.setSelectedProjectId(state.selectedTask.project_id)
              state.setTab('projects')
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
        </div>
        {state.taskEditorError && <div className="notice notice-error" role="alert" style={{ marginBottom: 8 }}>{state.taskEditorError}</div>}
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
            <label className="field-control" style={{ marginBottom: 8 }}>
              <span className="field-label">Instruction</span>
              <textarea
                value={state.editScheduledInstruction}
                onChange={(e) => state.setEditScheduledInstruction(e.target.value)}
                rows={3}
                style={{ width: '100%' }}
                placeholder="Scheduled (executed automatically when due)"
              />
            </label>
          </>
        )}
        {state.selectedTask.schedule_state && state.editTaskType === 'scheduled_instruction' && (
          <div className="row wrap" style={{ marginBottom: 8 }}>
            <span className="badge">Schedule: {state.selectedTask.schedule_state}</span>
            <span className={`prio prio-${state.priorityTone(state.selectedTask.priority)}`} title="Priority">
              {state.selectedTask.priority}
            </span>
            {state.selectedTask.scheduled_at_utc && <span className="meta">Scheduled for: {new Date(state.selectedTask.scheduled_at_utc).toLocaleString()}</span>}
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
                  if (!state.closeTaskEditor()) return
                  state.createNoteMutation.mutate({
                    title: 'Untitled note',
                    body: '',
                    project_id: state.selectedTask.project_id,
                    task_id: state.selectedTask.id,
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
                          if (!state.closeTaskEditor()) return
                          state.openNote(note.id, note.project_id)
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
    </Tooltip.Provider>
  )
}
