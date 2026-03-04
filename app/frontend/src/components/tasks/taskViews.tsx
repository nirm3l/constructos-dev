import React from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import { createPortal } from 'react-dom'
import type { Task } from '../../types'
import type { Tab } from '../../utils/ui'
import { priorityTone, tagHue } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'

export function taskDescriptionPreview(description: string | null | undefined): string {
  return String(description ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function formatScheduleTrigger(iso: string | null | undefined): string {
  if (!iso) return 'At: not set'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return `At: ${String(iso)}`
  try {
    return `At: ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)}`
  } catch {
    return `At: ${date.toLocaleString()}`
  }
}

function formatRecurringRuleCompact(recurringRule: string | null | undefined): string {
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

function formatScheduleState(state: Task['schedule_state'] | null | undefined): string {
  const raw = String(state ?? '').trim()
  if (!raw) return 'Unknown'
  return `${raw.charAt(0).toUpperCase()}${raw.slice(1)}`
}

function formatAutomationState(state: string | null | undefined): string {
  const raw = String(state ?? '').trim()
  if (!raw) return 'Idle'
  if (raw === 'completed') return 'Completed'
  return `${raw.charAt(0).toUpperCase()}${raw.slice(1)}`
}

function toExecutionChipClassState(state: string | null | undefined): string {
  const raw = String(state ?? 'idle').trim().toLowerCase()
  if (!raw) return 'idle'
  if (raw === 'completed') return 'done'
  return raw
}

function resolveEffectiveExecutionState(task: Task): string {
  const automation = String(task.automation_state ?? '').trim().toLowerCase()
  if (automation && automation !== 'idle') return automation
  const schedule = String(task.schedule_state ?? '').trim().toLowerCase()
  if (task.task_type === 'scheduled_instruction' && schedule) return schedule
  return automation || 'idle'
}

const BOTTOM_TAB_ITEMS: Array<{ value: Tab; label: string; shortLabel: string; iconPath: string }> = [
  {
    value: 'inbox',
    label: 'Inbox',
    shortLabel: 'Inbox',
    iconPath: 'M8 3v4M16 3v4M4 10h16M4 5h16v15H4z',
  },
  {
    value: 'tasks',
    label: 'Tasks',
    shortLabel: 'Tasks',
    iconPath: 'M4 6h16M4 12h10M4 18h13',
  },
  {
    value: 'notes',
    label: 'Notes',
    shortLabel: 'Notes',
    iconPath: 'M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3',
  },
  {
    value: 'specifications',
    label: 'Specifications',
    shortLabel: 'Specs',
    iconPath: 'M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4',
  },
  {
    value: 'projects',
    label: 'Projects',
    shortLabel: 'Projects',
    iconPath: 'M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2',
  },
]

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

export function TaskListItem({
  task,
  onOpen,
  onOpenSpecification,
  onTagClick,
  onRestore,
  onReopen,
  onComplete,
  semanticHit = false,
  showProject = false,
  projectName,
  specificationName,
  assigneeLabel,
}: {
  task: Task
  onOpen: (taskId: string) => void
  onOpenSpecification?: (specificationId: string, projectId: string) => void
  onTagClick?: (tag: string) => void
  onRestore: (taskId: string) => void
  onReopen: (taskId: string) => void
  onComplete: (taskId: string) => void
  semanticHit?: boolean
  showProject?: boolean
  projectName?: string
  specificationName?: string
  assigneeLabel?: string
}) {
  const descriptionPreviewText = taskDescriptionPreview(task.description)
  const isScheduled = task.task_type === 'scheduled_instruction'
  const hasAutomationInstruction = Boolean(String(task.instruction || task.scheduled_instruction || '').trim())
  const externalRefCount = Array.isArray(task.external_refs) ? task.external_refs.length : 0
  const attachmentCount = Array.isArray(task.attachment_refs) ? task.attachment_refs.length : 0
  const linkedNoteCount = Number.isFinite(task.linked_note_count as number) ? Number(task.linked_note_count) : 0
  const scheduleTrigger = formatScheduleTrigger(task.scheduled_at_utc)
  const scheduleRepeat = formatRecurringRuleCompact(task.recurring_rule)
  const scheduleState = formatScheduleState(task.schedule_state)
  const effectiveExecutionState = resolveEffectiveExecutionState(task)
  const executionStateLabel = formatAutomationState(effectiveExecutionState)
  const executionStateClass = toExecutionChipClassState(effectiveExecutionState)
  const primaryAction = task.archived
    ? {
        label: 'Restore task',
        iconPath: 'M20 16v5H4v-5M12 3v12M7 8l5-5 5 5',
        onSelect: () => onRestore(task.id),
      }
    : task.status === 'Done'
      ? {
          label: 'Reopen task',
          iconPath: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5',
          onSelect: () => onReopen(task.id),
        }
      : {
          label: 'Complete task',
          iconPath: 'm5 13 4 4L19 7',
          onSelect: () => onComplete(task.id),
        }

  return (
    <Tooltip.Provider delayDuration={120}>
      <div key={task.id} className={`task-item ${isScheduled ? 'scheduled' : ''}`}>
      <div className="task-main" role="button" onClick={() => onOpen(task.id)}>
        <div className="task-title">
          <strong>{task.title}</strong>
          {semanticHit || isScheduled ? (
            <div className="task-title-badges">
              {semanticHit ? (
                <ChipTooltip label="Ranked as a semantic search hit">
                  <span className="task-kind-pill task-kind-pill-semantic">SEMANTIC</span>
                </ChipTooltip>
              ) : null}
              {isScheduled ? (
                <ChipTooltip label="Scheduled task">
                  <span className="task-kind-pill">Scheduled</span>
                </ChipTooltip>
              ) : null}
            </div>
          ) : null}
        </div>
        {descriptionPreviewText && (
          <p className="task-desc-preview" title={descriptionPreviewText}>
            {descriptionPreviewText}
          </p>
        )}
        {isScheduled && (
          <div className="task-schedule-compact">
            <ChipTooltip label={scheduleTrigger}>
              <span className="task-schedule-chip task-schedule-chip-primary">
                <Icon path="M12 8v5l3 2m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0" />
                <span>{scheduleTrigger}</span>
              </span>
            </ChipTooltip>
            <ChipTooltip label={scheduleRepeat}>
              <span className="task-schedule-chip">
                <Icon path="M21 12a9 9 0 0 1-9 9m0 0-4-4m4 4v-4m-9-5a9 9 0 0 1 9-9m0 0 4 4m-4-4v4" />
                <span>{scheduleRepeat}</span>
              </span>
            </ChipTooltip>
            <ChipTooltip label={scheduleState}>
              <span className={`task-schedule-chip task-schedule-state task-schedule-state-${executionStateClass}`}>
                {executionStateLabel}
              </span>
            </ChipTooltip>
          </div>
        )}
        {!isScheduled && hasAutomationInstruction && (
          <div className="task-schedule-compact">
            <ChipTooltip label={executionStateLabel}>
              <span className={`task-schedule-chip task-schedule-state task-schedule-state-${executionStateClass}`}>
                {executionStateLabel}
              </span>
            </ChipTooltip>
          </div>
        )}
        <span className="meta">
          {task.status} | {task.due_date ? new Date(task.due_date).toLocaleString() : 'No due date'}
          {showProject && <> | Project: {projectName || task.project_id}</>}
        </span>
        {assigneeLabel && (
          <div className="task-assignee-compact" title={`Assigned to ${assigneeLabel}`}>
            <Icon path="M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8" />
            <span>{assigneeLabel}</span>
          </div>
        )}
        {(task.labels ?? []).length > 0 && (
          <div className="task-tags">
            {(task.labels ?? []).map((t) => (
              <button
                key={t}
                type="button"
                className="tag-mini tag-clickable"
                onClick={(event) => {
                  event.stopPropagation()
                  onTagClick?.(t)
                }}
                title={`Filter by tag: ${t}`}
                style={{
                  backgroundColor: `hsl(${tagHue(t)}, 70%, 92%)`,
                  borderColor: `hsl(${tagHue(t)}, 70%, 78%)`,
                  color: `hsl(${tagHue(t)}, 55%, 28%)`
                }}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {task.specification_id && (
          <div className="row wrap" style={{ marginTop: 2 }}>
            <button
              className="pill subtle task-project-pill task-spec-pill"
              onClick={(e) => {
                e.stopPropagation()
                onOpenSpecification?.(task.specification_id as string, task.project_id)
              }}
              title="Open linked specification"
              aria-label="Open linked specification"
            >
              <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
              <span>{specificationName || `Specification ${String(task.specification_id).slice(0, 8)}`}</span>
            </button>
          </div>
        )}
        <div className="task-badges">
          {linkedNoteCount > 0 && (
            <ChipTooltip label={`${linkedNoteCount} linked note${linkedNoteCount === 1 ? '' : 's'}`}>
              <span className="task-resource-chip">
                <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
                <span>{linkedNoteCount}</span>
              </span>
            </ChipTooltip>
          )}
          {externalRefCount > 0 && (
            <ChipTooltip label={`${externalRefCount} external link${externalRefCount === 1 ? '' : 's'}`}>
              <span className="task-resource-chip">
                <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                <span>{externalRefCount}</span>
              </span>
            </ChipTooltip>
          )}
          {attachmentCount > 0 && (
            <ChipTooltip label={`${attachmentCount} attachment${attachmentCount === 1 ? '' : 's'}`}>
              <span className="task-resource-chip">
                <Icon path="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.2a2 2 0 0 1-2.82-2.83l8.49-8.48" />
                <span>{attachmentCount}</span>
              </span>
            </ChipTooltip>
          )}
          <ChipTooltip label={`Priority: ${task.priority}`}>
            <span className={`prio prio-${priorityTone(task.priority)}`}>
              {task.priority}
            </span>
          </ChipTooltip>
        </div>
      </div>
      <div className="task-item-actions">
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              className="action-icon task-item-actions-trigger"
              type="button"
              title="Task actions"
              aria-label="Task actions"
            >
              <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="task-group-menu-content task-item-actions-menu-content" sideOffset={8} align="end">
              <DropdownMenu.Item className="task-group-menu-item" onSelect={() => onOpen(task.id)}>
                <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                <span>Open task</span>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="task-group-menu-separator" />
              <DropdownMenu.Item className="task-group-menu-item" onSelect={primaryAction.onSelect}>
                <Icon path={primaryAction.iconPath} />
                <span>{primaryAction.label}</span>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      </div>
    </Tooltip.Provider>
  )
}

export function BottomTabs({
  tab,
  onSelectTab,
}: {
  tab: Tab
  onSelectTab: (tab: Tab) => void
}) {
  const [portalTarget, setPortalTarget] = React.useState<HTMLElement | null>(null)
  const tabValue = BOTTOM_TAB_ITEMS.some((item) => item.value === tab) ? tab : '__none__'

  React.useEffect(() => {
    setPortalTarget(document.body)
  }, [])

  const nav = (
    <nav className="bottom-tabs" style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 1200 }}>
      <Tabs.Root
        className="bottom-tabs-root"
        value={tabValue}
        onValueChange={(value) => {
          const next = String(value || '').trim()
          if (!next || next === '__none__') return
          onSelectTab(next as Tab)
        }}
      >
        <Tabs.List className="bottom-tabs-list" aria-label="Primary sections">
          {BOTTOM_TAB_ITEMS.map((item) => (
            <Tabs.Trigger key={item.value} value={item.value} className="bottom-tab-trigger" title={item.label} aria-label={item.label}>
              <Icon path={item.iconPath} />
              <span className="tab-label">{item.shortLabel}</span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs.Root>
    </nav>
  )

  if (!portalTarget) return nav
  return createPortal(nav, portalTarget)
}
