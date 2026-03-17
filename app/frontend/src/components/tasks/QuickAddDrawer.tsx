import React from 'react'
import { useQuery } from '@tanstack/react-query'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import * as Tooltip from '@radix-ui/react-tooltip'
import { getTaskGroups } from '../../api'
import { Icon } from '../shared/uiHelpers'

type DuePreset = 'in_one_hour' | 'today_end' | 'tomorrow_morning' | 'next_business_morning' | 'clear'
type QuickTaskType = 'manual' | 'scheduled_instruction'
type QuickPriority = 'Low' | 'Med' | 'High'

type QuickSelectOption = {
  value: string
  label: string
}

const QUICK_PRIORITY_OPTIONS: QuickSelectOption[] = [
  { value: 'Low', label: 'Low' },
  { value: 'Med', label: 'Med' },
  { value: 'High', label: 'High' },
]

const QUICK_TASK_TYPE_OPTIONS: QuickSelectOption[] = [
  { value: 'manual', label: 'Manual' },
  { value: 'scheduled_instruction', label: 'Scheduled' },
]

const QUICK_TIMEZONE_OPTIONS_BASE: QuickSelectOption[] = [
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

function buildTimezoneOptions(currentTimezone: string): QuickSelectOption[] {
  const normalized = String(currentTimezone || '').trim() || 'UTC'
  if (QUICK_TIMEZONE_OPTIONS_BASE.some((option) => option.value === normalized)) {
    return QUICK_TIMEZONE_OPTIONS_BASE
  }
  return [{ value: normalized, label: normalized }, ...QUICK_TIMEZONE_OPTIONS_BASE]
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

function QuickAddSelect({
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
  options: QuickSelectOption[]
  triggerClassName?: string
}) {
  return (
    <Select.Root value={value} onValueChange={onValueChange}>
      <Select.Trigger className={triggerClassName || 'quickadd-project-trigger'} aria-label={ariaLabel}>
        <Select.Value placeholder={placeholder} />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
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

function QuickAddTooltip({
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

export function QuickAddDrawer({ state }: { state: any }) {
  const [showValidation, setShowValidation] = React.useState(false)
  const [confirmDiscardOpen, setConfirmDiscardOpen] = React.useState(false)
  const localTimezone = React.useMemo(() => detectLocalTimezone(), [])

  const quickProjectId = String(state.quickProjectId || '').trim()

  const quickTaskGroupsQuery = useQuery({
    queryKey: ['quickadd-task-groups', state.userId, state.workspaceId, quickProjectId],
    queryFn: () =>
      getTaskGroups(state.userId, state.workspaceId, {
        project_id: quickProjectId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(state.userId && state.workspaceId && quickProjectId),
    staleTime: 30_000,
  })

  React.useEffect(() => {
    if (!state.showQuickAdd) {
      setShowValidation(false)
      setConfirmDiscardOpen(false)
    }
  }, [state.showQuickAdd])

  const projects = Array.isArray(state.bootstrap.data?.projects)
    ? state.bootstrap.data.projects.map((project: any) => ({
      id: String(project?.id || ''),
      name: String(project?.name || '').trim() || 'Untitled project',
    }))
    : []

  const projectSelectValue = (() => {
    if (!quickProjectId) return '__none__'
    return projects.some((project: { id: string; name: string }) => project.id === quickProjectId) ? quickProjectId : '__none__'
  })()

  const quickTaskGroups = Array.isArray(quickTaskGroupsQuery.data?.items)
    ? quickTaskGroupsQuery.data.items.map((group: any) => ({
      id: String(group?.id || ''),
      name: String(group?.name || '').trim() || 'Untitled group',
    }))
    : []

  const quickTaskGroupSelectValue = (() => {
    const current = String(state.quickTaskGroupId || '').trim()
    if (!current) return '__none__'
    return quickTaskGroups.some((group) => group.id === current) ? current : '__none__'
  })()

  const userById = new Map(
    (Array.isArray(state.bootstrap.data?.users) ? state.bootstrap.data.users : []).map((user: any) => [String(user?.id || ''), user])
  )
  const projectMemberIds = Array.from(
    new Set(
      (Array.isArray(state.bootstrap.data?.project_members) ? state.bootstrap.data.project_members : [])
        .filter((member: any) => String(member?.project_id || '') === quickProjectId)
        .map((member: any) => String(member?.user_id || '').trim())
        .filter(Boolean)
    )
  )
  const assigneeOptions = (projectMemberIds.length > 0
    ? projectMemberIds
      .map((id) => userById.get(id))
      .filter(Boolean)
    : Array.isArray(state.bootstrap.data?.users)
      ? state.bootstrap.data.users
      : []
  )
    .map((user: any) => {
      const fullName = String(user?.full_name || '').trim() || 'Unnamed user'
      const username = String(user?.username || '').trim()
      return {
        id: String(user?.id || ''),
        label: username && username !== fullName ? `${fullName} (${username})` : fullName,
      }
    })
    .sort((a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label))

  const assigneeSelectValue = (() => {
    const current = String(state.quickTaskAssigneeId || '').trim()
    if (!current) return '__none__'
    return assigneeOptions.some((option: { id: string; label: string }) => option.id === current) ? current : '__none__'
  })()

  const timezoneOptions = React.useMemo(
    () => buildTimezoneOptions(String(state.quickTaskScheduleTimezone || '').trim() || localTimezone),
    [localTimezone, state.quickTaskScheduleTimezone]
  )
  const timezoneSelectValue = String(state.quickTaskScheduleTimezone || '').trim() || localTimezone

  React.useEffect(() => {
    if (quickTaskGroupsQuery.isLoading) return
    if (quickTaskGroupSelectValue === '__none__' && String(state.quickTaskGroupId || '').trim()) {
      state.setQuickTaskGroupId('')
    }
  }, [quickTaskGroupSelectValue, quickTaskGroupsQuery.isLoading, state])

  React.useEffect(() => {
    if (assigneeSelectValue === '__none__' && String(state.quickTaskAssigneeId || '').trim()) {
      state.setQuickTaskAssigneeId('')
    }
  }, [assigneeSelectValue, state])

  const quickTaskType: QuickTaskType =
    String(state.quickTaskType || '').trim() === 'scheduled_instruction' ? 'scheduled_instruction' : 'manual'
  const quickTaskPriority: QuickPriority =
    String(state.quickTaskPriority || '').trim() === 'High'
      ? 'High'
      : String(state.quickTaskPriority || '').trim() === 'Low'
        ? 'Low'
        : 'Med'

  const hasUnsavedChanges =
    String(state.taskTitle || '').trim().length > 0 ||
    String(state.quickDueDate || '').trim().length > 0 ||
    String(state.quickTaskGroupId || '').trim().length > 0 ||
    String(state.quickTaskAssigneeId || '').trim().length > 0 ||
    (Array.isArray(state.quickTaskTags) && state.quickTaskTags.length > 0) ||
    quickTaskPriority !== 'Med' ||
    quickTaskType !== 'manual' ||
    String(state.quickTaskScheduledInstruction || '').trim().length > 0

  const closeQuickAddImmediately = React.useCallback(() => {
    state.setTaskTitle('')
    state.setQuickDueDate('')
    state.setQuickDueDateFocused(false)
    state.setQuickTaskGroupId('')
    state.setQuickTaskAssigneeId('')
    state.setQuickTaskPriority('Med')
    state.setQuickTaskType('manual')
    state.setQuickTaskScheduledInstruction('')
    state.setQuickTaskScheduleTimezone(detectLocalTimezone())
    state.setQuickTaskCreateAnother(false)
    state.setQuickTaskTags([])
    state.setShowQuickTaskTagPicker(false)
    state.setQuickTaskTagQuery('')
    state.setShowQuickAdd(false)
    setShowValidation(false)
    setConfirmDiscardOpen(false)
  }, [state])

  const requestCloseQuickAdd = React.useCallback(() => {
    if (hasUnsavedChanges) {
      setConfirmDiscardOpen(true)
      return
    }
    closeQuickAddImmediately()
  }, [closeQuickAddImmediately, hasUnsavedChanges])

  const fieldErrors = React.useMemo(() => {
    return {
      title: !String(state.taskTitle || '').trim() ? 'Task title is required' : '',
      project: !quickProjectId ? 'Project is required' : '',
      runAt:
        quickTaskType === 'scheduled_instruction' && !String(state.quickDueDate || '').trim()
          ? 'Run at date/time is required'
          : '',
      instruction:
        quickTaskType === 'scheduled_instruction' && !String(state.quickTaskScheduledInstruction || '').trim()
          ? 'Instruction is required for scheduled tasks'
          : '',
      timezone:
        quickTaskType === 'scheduled_instruction' && !String(state.quickTaskScheduleTimezone || '').trim()
          ? 'Timezone is required for scheduled tasks'
          : '',
    }
  }, [
    quickProjectId,
    quickTaskType,
    state.quickDueDate,
    state.quickTaskScheduleTimezone,
    state.quickTaskScheduledInstruction,
    state.taskTitle,
  ])

  const firstValidationError = React.useMemo(
    () => fieldErrors.title || fieldErrors.project || fieldErrors.runAt || fieldErrors.instruction || fieldErrors.timezone || '',
    [fieldErrors]
  )

  const createDisabledReason = state.createTaskMutation.isPending
    ? 'Task is being created'
    : firstValidationError

  const canCreateTask = createDisabledReason.length === 0

  React.useEffect(() => {
    if (showValidation && !firstValidationError) {
      setShowValidation(false)
    }
  }, [firstValidationError, showValidation])

  const createTask = React.useCallback(() => {
    if (state.createTaskMutation.isPending) return
    if (firstValidationError) {
      setShowValidation(true)
      return
    }
    setShowValidation(false)
    state.createTaskMutation.mutate({
      priority: quickTaskPriority,
      task_type: quickTaskType,
      task_group_id: String(state.quickTaskGroupId || '').trim() || null,
      assignee_id: String(state.quickTaskAssigneeId || '').trim() || null,
      scheduled_instruction: quickTaskType === 'scheduled_instruction' ? String(state.quickTaskScheduledInstruction || '').trim() : null,
      schedule_timezone: quickTaskType === 'scheduled_instruction' ? String(state.quickTaskScheduleTimezone || '').trim() : null,
      keep_open: Boolean(state.quickTaskCreateAnother),
    })
  }, [
    firstValidationError,
    quickTaskPriority,
    quickTaskType,
    state,
  ])

  const handleComposerKeyDown = React.useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      requestCloseQuickAdd()
      return
    }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      createTask()
    }
  }, [createTask, requestCloseQuickAdd])

  const addQuickTaskTagFromQuery = React.useCallback(() => {
    const raw = String(state.quickTaskTagQuery || '').trim()
    if (!raw) return
    const suggested = (Array.isArray(state.filteredQuickTaskTags) ? state.filteredQuickTaskTags : []).find(
      (tag: string) => String(tag || '').toLowerCase() === raw.toLowerCase()
    )
    const candidate = String(suggested || raw).trim()
    if (!candidate) return
    if (state.quickTaskTagsLower.has(candidate.toLowerCase())) {
      state.setQuickTaskTagQuery('')
      return
    }
    state.setQuickTaskTags([...(Array.isArray(state.quickTaskTags) ? state.quickTaskTags : []), candidate])
    state.setQuickTaskTagQuery('')
  }, [state])

  const applyDuePreset = (preset: DuePreset) => {
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
    state.setQuickDueDate(next)
    state.setQuickDueDateFocused(false)
  }

  const renderDueControl = (mode: 'manual' | 'scheduled') => (
    <div className={`quickadd-due ${state.quickDueDate ? 'has-value' : ''} ${state.quickDueDateFocused ? 'focused' : ''}`}>
      <span className="quickadd-due-placeholder">
        {mode === 'scheduled' ? 'Run At' : 'Due Date'}
      </span>
      <input
        id="quick-task-due-date"
        className={`due-input ${!state.quickDueDate && !state.quickDueDateFocused ? 'due-input-empty' : ''}`}
        type="datetime-local"
        value={state.quickDueDate}
        onChange={(e) => state.setQuickDueDate(e.target.value)}
        onFocus={() => state.setQuickDueDateFocused(true)}
        onBlur={() => state.setQuickDueDateFocused(false)}
        aria-label={mode === 'scheduled' ? 'Run at' : 'Due date'}
      />
      <Popover.Root>
        <Popover.Trigger asChild>
          <button
            type="button"
            className="action-icon quickadd-due-actions-trigger"
            aria-label="Due date shortcuts"
            title="Due date shortcuts"
          >
            <Icon path="M3 12h18M3 6h18M3 18h18" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className="quickadd-due-popover" side="top" align="end" sideOffset={8}>
            <div className="quickadd-due-popover-title">
              {mode === 'scheduled' ? 'Quick schedule' : 'Quick due date'}
            </div>
            <div className="quickadd-due-popover-actions">
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('in_one_hour')}>
                In 1 hour
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('today_end')}>
                Today 17:00
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('tomorrow_morning')}>
                Tomorrow 09:00
              </button>
              <button type="button" className="quickadd-due-preset" onClick={() => applyDuePreset('next_business_morning')}>
                Next business day 09:00
              </button>
              <button type="button" className="quickadd-due-preset quickadd-due-preset-clear" onClick={() => applyDuePreset('clear')}>
                Clear
              </button>
            </div>
            <Popover.Arrow className="quickadd-due-popover-arrow" />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {mode === 'scheduled' && showValidation && fieldErrors.runAt && <div className="quickadd-field-error">{fieldErrors.runAt}</div>}
    </div>
  )

  return (
    <>
      {state.showQuickAdd && (
        <Tooltip.Provider delayDuration={180}>
          <div className="drawer open" onClick={requestCloseQuickAdd}>
            <div className="drawer-body" onClick={(e) => e.stopPropagation()} onKeyDown={handleComposerKeyDown}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                <div className="row wrap" style={{ gap: 8 }}>
                  <h3 style={{ margin: 0 }}>New Task</h3>
                  {hasUnsavedChanges && <span className="badge unsaved-badge">Unsaved</span>}
                </div>
                <button className="action-icon" onClick={requestCloseQuickAdd} title="Close" aria-label="Close">
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              </div>
              <div className="quickadd-form">
                <div>
                  <input
                    className="quickadd-title"
                    value={state.taskTitle}
                    onChange={(e) => state.setTaskTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        createTask()
                      }
                    }}
                    placeholder="Task title"
                    autoFocus
                  />
                  {showValidation && fieldErrors.title && <div className="quickadd-field-error">{fieldErrors.title}</div>}
                </div>

                <div className="quickadd-meta-row">
                  <div className="quickadd-project-field">
                    <span className="meta quickadd-project-label">Project</span>
                    <QuickAddSelect
                      value={projectSelectValue}
                      onValueChange={(value) => {
                        state.setQuickProjectId(value === '__none__' ? '' : value)
                        state.setQuickTaskGroupId('')
                        state.setQuickTaskAssigneeId('')
                      }}
                      placeholder="Select project"
                      ariaLabel="Project"
                      options={[
                        { value: '__none__', label: 'Select project' },
                        ...projects.map((project: { id: string; name: string }) => ({
                          value: project.id,
                          label: project.name,
                        })),
                      ]}
                    />
                    {showValidation && fieldErrors.project && <div className="quickadd-field-error">{fieldErrors.project}</div>}
                  </div>

                  <div className="quickadd-inline-field">
                    <span className="meta quickadd-project-label">Priority</span>
                    <QuickAddSelect
                      value={quickTaskPriority}
                      onValueChange={(value) => state.setQuickTaskPriority(value)}
                      placeholder="Priority"
                      ariaLabel="Priority"
                      options={QUICK_PRIORITY_OPTIONS}
                      triggerClassName="quickadd-project-trigger quickadd-inline-trigger"
                    />
                  </div>

                  <div className="quickadd-inline-field">
                    <span className="meta quickadd-project-label">Task Type</span>
                    <QuickAddSelect
                      value={quickTaskType}
                      onValueChange={(value) => state.setQuickTaskType(value as QuickTaskType)}
                      placeholder="Task type"
                      ariaLabel="Task type"
                      options={QUICK_TASK_TYPE_OPTIONS}
                      triggerClassName="quickadd-project-trigger quickadd-inline-trigger"
                    />
                  </div>
                </div>

                {quickTaskType === 'scheduled_instruction' && (
                  <div className="quickadd-scheduled-block">
                    <div className="meta quickadd-scheduled-block-title">Scheduled setup</div>
                    <div className="quickadd-scheduled-fields">
                      {renderDueControl('scheduled')}
                      <label className="quickadd-scheduled-field quickadd-scheduled-field-timezone">
                        <span className="meta">Timezone</span>
                        <QuickAddSelect
                          value={timezoneSelectValue}
                          onValueChange={(value) => state.setQuickTaskScheduleTimezone(value)}
                          placeholder="Timezone"
                          ariaLabel="Timezone"
                          options={timezoneOptions}
                          triggerClassName="quickadd-project-trigger quickadd-inline-trigger quickadd-timezone-trigger"
                        />
                        {showValidation && fieldErrors.timezone && <div className="quickadd-field-error">{fieldErrors.timezone}</div>}
                      </label>
                    </div>
                    <label className="quickadd-scheduled-field quickadd-scheduled-field-wide">
                      <span className="meta">Instruction</span>
                      <input
                        value={state.quickTaskScheduledInstruction}
                        onChange={(e) => state.setQuickTaskScheduledInstruction(e.target.value)}
                        placeholder='Example: "Summarize inbox and create follow-up tasks"'
                      />
                      {showValidation && fieldErrors.instruction && <div className="quickadd-field-error">{fieldErrors.instruction}</div>}
                    </label>
                  </div>
                )}

                <div className="quickadd-secondary-row">
                  <div className="quickadd-inline-field">
                    <span className="meta quickadd-project-label">Task Group</span>
                    <QuickAddSelect
                      value={quickTaskGroupSelectValue}
                      onValueChange={(value) => state.setQuickTaskGroupId(value === '__none__' ? '' : value)}
                      placeholder="No task group"
                      ariaLabel="Task group"
                      options={[
                        { value: '__none__', label: quickTaskGroupsQuery.isLoading ? 'No task group (loading...)' : 'No task group' },
                        ...quickTaskGroups.map((group: { id: string; name: string }) => ({
                          value: group.id,
                          label: group.name,
                        })),
                      ]}
                      triggerClassName="quickadd-project-trigger quickadd-inline-trigger"
                    />
                  </div>
                  <div className="quickadd-inline-field">
                    <span className="meta quickadd-project-label">Assignee</span>
                    <QuickAddSelect
                      value={assigneeSelectValue}
                      onValueChange={(value) => state.setQuickTaskAssigneeId(value === '__none__' ? '' : value)}
                      placeholder="Unassigned"
                      ariaLabel="Assignee"
                      options={[
                        { value: '__none__', label: 'Unassigned' },
                        ...assigneeOptions.map((option: { id: string; label: string }) => ({
                          value: option.id,
                          label: option.label,
                        })),
                      ]}
                      triggerClassName="quickadd-project-trigger quickadd-inline-trigger"
                    />
                  </div>
                </div>

                <div className={`quickadd-actions-row ${quickTaskType === 'scheduled_instruction' ? 'quickadd-actions-row-no-due' : ''}`}>
                  {quickTaskType !== 'scheduled_instruction' && renderDueControl('manual')}

                  <div className="quickadd-actions-right">
                    <label className="quickadd-create-another-toggle">
                      <input
                        type="checkbox"
                        checked={Boolean(state.quickTaskCreateAnother)}
                        onChange={(e) => state.setQuickTaskCreateAnother(e.target.checked)}
                      />
                      <span>Create another</span>
                    </label>

                    <QuickAddTooltip content={createDisabledReason || 'Create task'}>
                      <span className="quickadd-tooltip-trigger-inline">
                        <button
                          className="action-icon primary quickadd-create"
                          disabled={!canCreateTask}
                          onClick={createTask}
                          aria-label="Create task"
                          data-tour-id="quickadd-create-task"
                        >
                          <Icon path="M12 5v14M5 12h14" />
                        </button>
                      </span>
                    </QuickAddTooltip>
                  </div>
                </div>
              </div>

              <div className="tag-bar" aria-label="Task tags" style={{ marginTop: 10 }}>
                <div className="tag-chiplist">
                  {state.quickTaskTags.length === 0 ? (
                    <span className="meta">No tags</span>
                  ) : (
                    state.quickTaskTags.map((t: string) => (
                      <span
                        key={t}
                        className="tag-chip"
                        style={{
                          background: `linear-gradient(135deg, hsl(${state.tagHue(t)}, 70%, 92%), hsl(${state.tagHue(t)}, 70%, 86%))`,
                          borderColor: `hsl(${state.tagHue(t)}, 70%, 74%)`,
                          color: `hsl(${state.tagHue(t)}, 55%, 22%)`,
                        }}
                      >
                        <span className="tag-text">{t}</span>
                      </span>
                    ))
                  )}
                </div>
                <Popover.Root open={state.showQuickTaskTagPicker} onOpenChange={(open) => state.setShowQuickTaskTagPicker(open)}>
                  <Popover.Trigger asChild>
                    <button
                      className="action-icon"
                      onClick={() => state.setShowQuickTaskTagPicker(true)}
                      title="Edit tags"
                      aria-label="Edit tags"
                    >
                      <Icon path="M3 12h8m-8 6h12m-12-12h18" />
                    </button>
                  </Popover.Trigger>
                  <Popover.Portal>
                    <Popover.Content className="quickadd-tag-popover" side="top" align="end" sideOffset={8}>
                      <div className="quickadd-tag-popover-header">
                        <h4 className="quickadd-tag-popover-title">Task Tags</h4>
                        <button
                          className="status-chip"
                          type="button"
                          onClick={() => state.setShowQuickTaskTagPicker(false)}
                          title="Close"
                          aria-label="Close"
                        >
                          Close
                        </button>
                      </div>
                      <div className="tag-picker-input-row">
                        <input
                          value={state.quickTaskTagQuery}
                          onChange={(e) => state.setQuickTaskTagQuery(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              e.stopPropagation()
                              addQuickTaskTagFromQuery()
                            }
                          }}
                          placeholder="Search or create tag"
                          autoFocus
                        />
                      </div>
                      <div className="tag-picker-list" role="listbox" aria-label="Tag list">
                        {state.filteredQuickTaskTags.map((t: string) => {
                          const selected = state.quickTaskTagsLower.has(t.toLowerCase())
                          return (
                            <button
                              key={t}
                              className={`tag-picker-item ${selected ? 'selected' : ''}`}
                              onClick={() => state.toggleQuickTaskTag(t)}
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
                        {state.filteredQuickTaskTags.length === 0 && <div className="meta">No tags found.</div>}
                      </div>
                      {state.canCreateQuickTaskTag && (
                        <button
                          className="primary tag-picker-create"
                          onClick={addQuickTaskTagFromQuery}
                          title="Create tag"
                          aria-label="Create tag"
                        >
                          Add "{state.quickTaskTagQuery.trim()}"
                        </button>
                      )}
                      <Popover.Arrow className="quickadd-tag-popover-arrow" />
                    </Popover.Content>
                  </Popover.Portal>
                </Popover.Root>
              </div>
              <div className="meta" style={{ marginTop: 10 }}>
                Tip: use Ctrl/Cmd+Enter to create fast.
              </div>
            </div>
          </div>
          <AlertDialog.Root open={confirmDiscardOpen} onOpenChange={setConfirmDiscardOpen}>
            <AlertDialog.Portal>
              <AlertDialog.Overlay className="codex-chat-alert-overlay" />
              <AlertDialog.Content className="codex-chat-alert-content">
                <AlertDialog.Title className="codex-chat-alert-title">
                  Discard quick task changes?
                </AlertDialog.Title>
                <AlertDialog.Description className="codex-chat-alert-description">
                  You have unsaved quick task input. This action cannot be undone.
                </AlertDialog.Description>
                <div className="codex-chat-alert-actions">
                  <AlertDialog.Cancel asChild>
                    <button className="status-chip" type="button">Cancel</button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button className="status-chip" type="button" onClick={closeQuickAddImmediately}>
                      Discard
                    </button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Portal>
          </AlertDialog.Root>
        </Tooltip.Provider>
      )}
    </>
  )
}
