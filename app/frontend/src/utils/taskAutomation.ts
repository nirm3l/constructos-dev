import type {
  Task,
  TaskExecutionTrigger,
  TaskExecutionTriggerSchedule,
  TaskExecutionTriggerStatusChange,
} from '../types'

const DEFAULT_SCHEDULE_RUN_ON_STATUSES = ['In Progress']

function normalizeString(value: unknown): string {
  return String(value ?? '').trim()
}

function uniqueCaseInsensitive(values: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of values) {
    const value = normalizeString(raw)
    if (!value) continue
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(value)
  }
  return out
}

function normalizeListOrCsv(value: unknown): string[] {
  if (Array.isArray(value)) {
    return uniqueCaseInsensitive(value.map((item) => normalizeString(item)))
  }
  const raw = normalizeString(value)
  if (!raw) return []
  return uniqueCaseInsensitive(
    raw
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  )
}

export function normalizeScheduleRunOnStatuses(values: unknown): string[] {
  if (!Array.isArray(values)) return [...DEFAULT_SCHEDULE_RUN_ON_STATUSES]
  const normalized = uniqueCaseInsensitive(values.map((value) => normalizeString(value)))
  return normalized.length > 0 ? normalized : [...DEFAULT_SCHEDULE_RUN_ON_STATUSES]
}

export function csvToUniqueList(raw: string): string[] {
  return uniqueCaseInsensitive(
    String(raw || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
  )
}

export function listToCsv(values: string[] | null | undefined): string {
  if (!Array.isArray(values) || values.length === 0) return ''
  return uniqueCaseInsensitive(values).join(', ')
}

export function parseRecurringRule(raw: string | null | undefined): { every: string; unit: 'm' | 'h' | 'd' } {
  const value = normalizeString(raw)
  const match = value.match(/^(?:every:)?\s*(\d+)\s*([mhd])\s*$/i)
  if (!match) {
    return { every: '', unit: 'h' }
  }
  const unit = String(match[2] || 'h').toLowerCase()
  return {
    every: String(match[1] || ''),
    unit: unit === 'm' || unit === 'h' || unit === 'd' ? unit : 'h',
  }
}

export function buildRecurringRule(everyRaw: string, unitRaw: string): string | null {
  const every = Math.max(1, Number(String(everyRaw || '').trim()) || 0)
  const unit = String(unitRaw || '').trim().toLowerCase()
  if (!Number.isFinite(every) || every <= 0) return null
  if (unit !== 'm' && unit !== 'h' && unit !== 'd') return null
  return `every:${every}${unit}`
}

export function normalizeExecutionTriggers(input: unknown): TaskExecutionTrigger[] {
  if (!Array.isArray(input)) return []
  const out: TaskExecutionTrigger[] = []
  for (const raw of input) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const kind = normalizeString(item.kind).toLowerCase()
    if (kind === 'manual') {
      out.push({ kind: 'manual', enabled: item.enabled !== false })
      continue
    }
    if (kind === 'schedule') {
      const scheduledAtUtc = normalizeString(item.scheduled_at_utc)
      if (!scheduledAtUtc) continue
      const runOnStatuses = normalizeScheduleRunOnStatuses(item.run_on_statuses)
      const trigger = {
        kind: 'schedule' as const,
        enabled: item.enabled !== false,
        scheduled_at_utc: scheduledAtUtc,
        run_on_statuses: runOnStatuses,
      }
      const timezone = normalizeString(item.schedule_timezone)
      const recurringRule = normalizeString(item.recurring_rule)
      out.push({
        ...trigger,
        ...(timezone ? { schedule_timezone: timezone } : {}),
        ...(recurringRule ? { recurring_rule: recurringRule } : {}),
      })
      continue
    }
    if (kind !== 'status_change') continue
    const scopeRaw = normalizeString(item.scope).toLowerCase()
    const scope = ['external', 'other', 'other_task', 'other_tasks'].includes(scopeRaw) ? 'external' : 'self'
    const modeRaw = normalizeString(item.match_mode).toLowerCase()
    const matchMode = modeRaw === 'all' ? 'all' : 'any'
    const fromStatuses = Array.isArray(item.from_statuses)
      ? uniqueCaseInsensitive((item.from_statuses as unknown[]).map((value) => normalizeString(value)))
      : []
    const toStatuses = Array.isArray(item.to_statuses)
      ? uniqueCaseInsensitive((item.to_statuses as unknown[]).map((value) => normalizeString(value)))
      : []
    const selectorRaw = item.selector
    const selectorTaskIds =
      selectorRaw && typeof selectorRaw === 'object' && Array.isArray((selectorRaw as Record<string, unknown>).task_ids)
        ? uniqueCaseInsensitive((((selectorRaw as Record<string, unknown>).task_ids as unknown[]) || []).map((value) => normalizeString(value)))
        : []
    const selectorSourceTaskIds =
      selectorRaw && typeof selectorRaw === 'object'
        ? normalizeListOrCsv((selectorRaw as Record<string, unknown>).source_task_ids)
        : []
    const topLevelSourceTaskIds = normalizeListOrCsv(item.source_task_ids)
    const topLevelSourceTaskId = normalizeString(item.source_task_id)
    const allSelectorTaskIds = uniqueCaseInsensitive([
      ...selectorTaskIds,
      ...selectorSourceTaskIds,
      ...topLevelSourceTaskIds,
      ...(topLevelSourceTaskId ? [topLevelSourceTaskId] : []),
    ])
    const trigger: TaskExecutionTriggerStatusChange = {
      kind: 'status_change',
      enabled: item.enabled !== false,
      scope,
      match_mode: matchMode,
      from_statuses: fromStatuses,
      to_statuses: toStatuses,
    }
    if (allSelectorTaskIds.length > 0) {
      trigger.selector = { task_ids: allSelectorTaskIds }
    }
    out.push(trigger)
  }
  return out
}

export function extractEnabledStatusTrigger(
  triggers: TaskExecutionTrigger[],
  scope: 'self' | 'external'
): TaskExecutionTriggerStatusChange | null {
  for (const trigger of normalizeExecutionTriggers(triggers)) {
    if (trigger.kind !== 'status_change') continue
    if (trigger.enabled === false) continue
    if ((trigger.scope || 'self') !== scope) continue
    return trigger
  }
  return null
}

export function extractEnabledScheduleTrigger(
  triggers: TaskExecutionTrigger[]
): TaskExecutionTriggerSchedule | null {
  for (const trigger of normalizeExecutionTriggers(triggers)) {
    if (trigger.kind !== 'schedule') continue
    if (trigger.enabled === false) continue
    return trigger
  }
  return null
}

export function deriveInstruction(task: Task | null | undefined): string {
  return normalizeString(task?.instruction || task?.scheduled_instruction || '')
}

export type BuildTaskAutomationInput = {
  taskType: 'manual' | 'scheduled_instruction'
  scheduledAtUtc: string
  scheduleTimezone: string
  scheduleRunOnStatuses: string[]
  recurringEvery: string
  recurringUnit: 'm' | 'h' | 'd'
  selfEnabled: boolean
  selfFromStatusesText: string
  selfToStatusesText: string
  externalEnabled: boolean
  externalMatchMode: 'any' | 'all'
  externalTaskIdsText: string
  externalFromStatusesText: string
  externalToStatusesText: string
}

export function buildExecutionTriggersFromEditor(input: BuildTaskAutomationInput): TaskExecutionTrigger[] {
  const out: TaskExecutionTrigger[] = []
  if (input.taskType === 'scheduled_instruction') {
    const scheduledAtUtc = normalizeString(input.scheduledAtUtc)
    if (scheduledAtUtc) {
      const timezone = normalizeString(input.scheduleTimezone)
      const recurringRule = buildRecurringRule(input.recurringEvery, input.recurringUnit)
      const runOnStatuses = normalizeScheduleRunOnStatuses(input.scheduleRunOnStatuses)
      out.push({
        kind: 'schedule',
        enabled: true,
        scheduled_at_utc: scheduledAtUtc,
        run_on_statuses: runOnStatuses,
        ...(timezone ? { schedule_timezone: timezone } : {}),
        ...(recurringRule ? { recurring_rule: recurringRule } : {}),
      })
    }
  }

  if (input.selfEnabled) {
    out.push({
      kind: 'status_change',
      enabled: true,
      scope: 'self',
      match_mode: 'any',
      from_statuses: csvToUniqueList(input.selfFromStatusesText),
      to_statuses: csvToUniqueList(input.selfToStatusesText),
    })
  }

  if (input.externalEnabled) {
    const taskIds = csvToUniqueList(input.externalTaskIdsText)
    const trigger: TaskExecutionTriggerStatusChange = {
      kind: 'status_change',
      enabled: true,
      scope: 'external',
      match_mode: input.externalMatchMode === 'all' ? 'all' : 'any',
      from_statuses: csvToUniqueList(input.externalFromStatusesText),
      to_statuses: csvToUniqueList(input.externalToStatusesText),
    }
    if (taskIds.length > 0) {
      trigger.selector = { task_ids: taskIds }
    }
    out.push(trigger)
  }
  return out
}

export function hasConfiguredNonManualTrigger(triggers: TaskExecutionTrigger[]): boolean {
  return normalizeExecutionTriggers(triggers).some((trigger) => trigger.kind !== 'manual')
}
