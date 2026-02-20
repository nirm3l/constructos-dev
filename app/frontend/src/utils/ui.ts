import type { AttachmentRef, ExternalRef } from '../types'

const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000001'

export type Tab = 'today' | 'tasks' | 'notes' | 'specifications' | 'projects' | 'knowledge-graph' | 'search' | 'profile' | 'admin'

export const TAB_ORDER: Tab[] = ['today', 'tasks', 'notes', 'specifications', 'projects', 'knowledge-graph', 'search', 'profile', 'admin']

const LEGACY_TAB_REDIRECTS: Record<string, Tab> = {
  admin: 'profile',
}

export function normalizeStoredUserId(raw: string | null): string {
  if (!raw || raw === '1' || raw === '2') return DEFAULT_USER_ID
  return raw
}

export function parseStoredTab(raw: string | null): Tab {
  if (!raw) return 'tasks'
  const normalized = LEGACY_TAB_REDIRECTS[raw] ?? raw
  if (TAB_ORDER.includes(normalized as Tab)) return normalized as Tab
  return 'tasks'
}

export function parseStoredProjectId(raw: string | null): string {
  if (!raw) return ''
  return raw
}

export function parseStoredProjectsMode(raw: string | null): 'board' | 'list' {
  if (raw === 'list') return 'list'
  return 'board'
}

export function parseUrlTab(raw: string | null): Tab | null {
  if (!raw) return null
  const normalized = LEGACY_TAB_REDIRECTS[raw] ?? raw
  return TAB_ORDER.includes(normalized as Tab) ? (normalized as Tab) : null
}

export function toLocalDateTimeInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day}T${hh}:${mm}`
}

export function toReadableDate(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

export function toUserDateTime(iso: unknown, timezone: string | undefined): string {
  if (typeof iso !== 'string' || !iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: timezone || 'UTC',
    }).format(d)
  } catch {
    return d.toLocaleString()
  }
}

export function pickSingleTimeMeta(createdAt: string | null | undefined, updatedAt: string | null | undefined): { label: 'Created' | 'Updated'; value: string } | null {
  const created = createdAt || null
  const updated = updatedAt || null
  if (updated && created && updated !== created) return { label: 'Updated', value: updated }
  if (created) return { label: 'Created', value: created }
  if (updated) return { label: 'Updated', value: updated }
  return null
}

export function formatActivitySummary(
  action: string,
  details: Record<string, unknown>,
  actorName: string
): { title: string; detail: string } {
  const keys = Object.keys(details)
  switch (action) {
    case 'TaskCreated':
      return {
        title: `${actorName} created the task`,
        detail: `Title: ${String(details.title ?? '') || '(none)'}`,
      }
    case 'TaskUpdated':
      return {
        title: `${actorName} updated the task`,
        detail: `Changed: ${keys.join(', ') || 'fields'}`,
      }
    case 'TaskCompleted':
      return {
        title: `${actorName} completed the task`,
        detail: `Completed at: ${toReadableDate(details.completed_at) || 'n/a'}`,
      }
    case 'TaskReopened':
      return {
        title: `${actorName} reopened the task`,
        detail: `Status: ${String(details.status ?? 'To do')}`,
      }
    case 'TaskArchived':
      return { title: `${actorName} archived the task`, detail: 'Task moved to archive' }
    case 'TaskRestored':
      return { title: `${actorName} restored the task`, detail: 'Task restored from archive' }
    case 'TaskCommentAdded':
      return {
        title: `${actorName} added a comment`,
        detail: String(details.body ?? '').slice(0, 180) || '(empty comment)',
      }
    case 'TaskAutomationRequested':
      return {
        title: `${actorName} requested Codex run`,
        detail: String(details.instruction ?? '(no instruction)'),
      }
    case 'TaskAutomationStarted':
      return {
        title: 'Codex run started',
        detail: `Started at: ${toReadableDate(details.started_at) || 'n/a'}`,
      }
    case 'TaskAutomationCompleted':
      return {
        title: 'Codex run completed',
        detail: String(details.summary ?? 'Completed'),
      }
    case 'TaskAutomationFailed':
      return {
        title: 'Codex run failed',
        detail: String(details.error ?? details.summary ?? 'Unknown error'),
      }
    case 'TaskScheduleConfigured':
      return {
        title: `${actorName} configured schedule`,
        detail: `At: ${toReadableDate(details.scheduled_at_utc)} | TZ: ${String(details.schedule_timezone ?? 'UTC')}`,
      }
    case 'TaskScheduleQueued':
      return {
        title: 'Scheduled run queued',
        detail: `Queued at: ${toReadableDate(details.queued_at) || 'n/a'}`,
      }
    case 'TaskScheduleStarted':
      return {
        title: 'Scheduled run started',
        detail: `Started at: ${toReadableDate(details.started_at) || 'n/a'}`,
      }
    case 'TaskScheduleCompleted':
      return {
        title: 'Scheduled run completed',
        detail: String(details.summary ?? `Completed at ${toReadableDate(details.completed_at)}`),
      }
    case 'TaskScheduleFailed':
      return {
        title: 'Scheduled run failed',
        detail: String(details.error ?? 'Unknown error'),
      }
    default:
      return {
        title: `${actorName} triggered ${action}`,
        detail: keys.length ? `Details: ${keys.join(', ')}` : 'No details',
      }
  }
}

export function activityTone(action: string): 'ok' | 'warn' | 'error' | 'neutral' {
  if (action.includes('Failed')) return 'error'
  if (action.includes('Completed')) return 'ok'
  if (action.includes('Queued') || action.includes('Started') || action.includes('Requested')) return 'warn'
  return 'neutral'
}

export function priorityTone(priority: string): 'low' | 'med' | 'high' {
  const p = String(priority || '').trim().toLowerCase()
  if (p === 'high') return 'high'
  if (p === 'low') return 'low'
  return 'med'
}

export function parseCommaTags(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const t of String(raw || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)) {
    const key = t.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(t)
  }
  return out
}

export const DEFAULT_PROJECT_STATUSES: string[] = ['To do', 'In progress', 'Done']
export const PROJECT_EVIDENCE_TOP_K_MIN = 1
export const PROJECT_EVIDENCE_TOP_K_MAX = 40

export function parseProjectStatusesText(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of String(raw || '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)) {
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(value)
  }
  return out.length > 0 ? out : [...DEFAULT_PROJECT_STATUSES]
}

export function projectStatusesToText(statuses: string[] | undefined | null): string {
  const items = Array.isArray(statuses) && statuses.length > 0 ? statuses : DEFAULT_PROJECT_STATUSES
  return items.join(', ')
}

export function parseProjectEvidenceTopKInput(raw: string): number | null {
  const text = String(raw || '').trim()
  if (!text) return null
  if (!/^\d+$/.test(text)) {
    throw new Error('Evidence top K must be a whole number.')
  }
  const value = Number(text)
  if (!Number.isInteger(value) || value < PROJECT_EVIDENCE_TOP_K_MIN || value > PROJECT_EVIDENCE_TOP_K_MAX) {
    throw new Error(`Evidence top K must be between ${PROJECT_EVIDENCE_TOP_K_MIN} and ${PROJECT_EVIDENCE_TOP_K_MAX}.`)
  }
  return value
}

export function parseTemplateParametersInput(raw: string): Record<string, unknown> {
  const text = String(raw || '').trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('Template parameters must be a valid JSON object.')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Template parameters must be a JSON object.')
  }
  return parsed as Record<string, unknown>
}

export function parseExternalRefsText(raw: string): ExternalRef[] {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [urlPart, titlePart, sourcePart] = line.split('|').map((x) => x.trim())
      const item: ExternalRef = { url: urlPart || '' }
      if (titlePart) item.title = titlePart
      if (sourcePart) item.source = sourcePart
      return item
    })
    .filter((item) => item.url)
}

export function externalRefsToText(items: ExternalRef[] | undefined | null): string {
  return (items ?? [])
    .map((item) => [item.url, item.title, item.source].filter(Boolean).join(' | '))
    .join('\n')
}

export function removeExternalRefByIndex(raw: string, index: number): string {
  const parsed = parseExternalRefsText(raw)
  if (index < 0 || index >= parsed.length) return raw
  parsed.splice(index, 1)
  return externalRefsToText(parsed)
}

export function parseAttachmentRefsText(raw: string): AttachmentRef[] {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [pathPart, namePart, mimePart, sizePart] = line.split('|').map((x) => x.trim())
      const item: AttachmentRef = { path: pathPart || '' }
      if (namePart) item.name = namePart
      if (mimePart) item.mime_type = mimePart
      if (sizePart) {
        const n = Number(sizePart)
        if (Number.isFinite(n) && n >= 0) item.size_bytes = Math.floor(n)
      }
      return item
    })
    .filter((item) => item.path)
}

export function attachmentRefsToText(items: AttachmentRef[] | undefined | null): string {
  return (items ?? [])
    .map((item) => [item.path, item.name, item.mime_type, item.size_bytes != null ? String(item.size_bytes) : ''].filter(Boolean).join(' | '))
    .join('\n')
}

export function removeAttachmentByPath(raw: string, path: string): string {
  const filtered = parseAttachmentRefsText(raw).filter((item) => item.path !== path)
  return attachmentRefsToText(filtered)
}

export function toErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  if (typeof err === 'string' && err.trim()) return err.trim()
  return fallback
}

export function stableJson(value: unknown): string {
  return JSON.stringify(value ?? null)
}

export function tagHue(tag: string): number {
  // Deterministic hash -> hue for consistent chip coloring.
  let h = 0
  const s = String(tag || '')
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  // Avoid harsh reds by snapping into a cool palette.
  const palette = [150, 170, 190, 205, 220, 235, 250, 265]
  return palette[h % palette.length] ?? 205
}
