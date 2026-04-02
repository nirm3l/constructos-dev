import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import * as Dialog from '@radix-ui/react-dialog'
import * as Checkbox from '@radix-ui/react-checkbox'
import * as Collapsible from '@radix-ui/react-collapsible'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Select from '@radix-ui/react-select'
import * as Switch from '@radix-ui/react-switch'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import type {
  AdminWorkspaceUser,
  AgentAuthStatus,
  AgentAuthProvider,
  ChatReasoningEffort,
  ClaudeAuthLoginMethod,
  CodexAuthLoginMethod,
  LicenseStatus,
  Note,
  Specification,
  Task,
  WorkspaceDoctorStatus,
  ArchitectureInventorySummary,
  WorkspaceSkill,
  WorkspaceSkillsPage,
} from '../types'
import { tagHue } from '../utils/ui'
import {
  authSourceLabel,
  formatAgentExecutionModelLabel,
  getAgentExecutionProviderLabel,
  normalizeAgentExecutionModel,
  parseAgentExecutionModel,
  resolveActiveAgentExecutionProvider,
} from '../utils/agentExecution'
import { MarkdownView } from '../markdown/MarkdownView'
import { PopularTagFilters } from './shared/PopularTagFilters'
import { Icon, MarkdownModeToggle, MarkdownSplitPane } from './shared/uiHelpers'
import { TaskListItem } from './tasks/taskViews'

const VOICE_LANG_OPTIONS = [
  { value: 'bs-BA', label: 'Bosnian (bs-BA)' },
  { value: 'en-US', label: 'English (en-US)' },
]

const CODEX_CHAT_REASONING_OPTIONS: Array<{ value: ChatReasoningEffort; label: string }> = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'xhigh', label: 'Very high' },
]
const CLAUDE_CHAT_REASONING_OPTIONS: Array<{ value: ChatReasoningEffort; label: string }> = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'xhigh', label: 'Max' },
]
const CHAT_MODEL_DEFAULT_VALUE = '__default__'
const BACKGROUND_RUNTIME_MODEL_DEFAULT_VALUE = '__background_runtime_default__'

function normalizeChatReasoningEffort(value: unknown): ChatReasoningEffort {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'max' || normalized === 'maximum') return 'xhigh'
  if (normalized === 'low' || normalized === 'high' || normalized === 'xhigh') return normalized
  return 'medium'
}

function getChatReasoningOptions(provider: AgentAuthProvider): Array<{ value: ChatReasoningEffort; label: string }> {
  return provider === 'claude' ? CLAUDE_CHAT_REASONING_OPTIONS : CODEX_CHAT_REASONING_OPTIONS
}

function getChatReasoningLabel(value: unknown, provider: AgentAuthProvider): string {
  const normalized = normalizeChatReasoningEffort(value)
  return getChatReasoningOptions(provider).find((item) => item.value === normalized)?.label || 'Medium'
}

function normalizeCodexAuthLoginMethod(value: unknown): CodexAuthLoginMethod {
  return String(value || '').trim().toLowerCase() === 'browser' ? 'browser' : 'device_code'
}

function formatCodexAuthLoginMethodLabel(value: unknown): string {
  return normalizeCodexAuthLoginMethod(value) === 'browser' ? 'Browser sign-in' : 'Device code'
}

function normalizeClaudeAuthLoginMethod(value: unknown): ClaudeAuthLoginMethod {
  return String(value || '').trim().toLowerCase() === 'console' ? 'console' : 'claudeai'
}

function formatClaudeAuthLoginMethodLabel(value: unknown): string {
  return normalizeClaudeAuthLoginMethod(value) === 'console' ? 'Anthropic Console' : 'Claude subscription'
}

function isFinalClaudeAuthStatus(payload: AgentAuthStatus | null | undefined): boolean {
  if (!payload || typeof payload !== 'object') return false
  if (payload.configured) return true
  if (String(payload.effective_source || '').trim().toLowerCase() === 'system_override') return true
  const loginSession = payload.login_session
  const status = String(loginSession?.status || '').trim().toLowerCase()
  return status === 'succeeded'
}

const PROFILE_FEEDBACK_TYPE_OPTIONS: Array<{
  value: 'general' | 'feature_request' | 'question' | 'other'
  label: string
}> = [
  { value: 'general', label: 'General' },
  { value: 'feature_request', label: 'Feature request' },
  { value: 'question', label: 'Question' },
  { value: 'other', label: 'Other' },
]

const GITHUB_ISSUES_URL = 'https://github.com/nirm3l/constructos/issues'
const SEARCH_ANY_VALUE = '__any__'

const SEARCH_TASK_STATUS_OPTIONS = [
  { value: 'To Do', label: 'To Do' },
  { value: 'In Progress', label: 'In Progress' },
  { value: 'In Review', label: 'In Review' },
  { value: 'Awaiting Decision', label: 'Awaiting Decision' },
  { value: 'Blocked', label: 'Blocked' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Done', label: 'Done' },
]

const SEARCH_SPEC_STATUS_OPTIONS = [
  { value: 'Draft', label: 'Draft' },
  { value: 'Ready', label: 'Ready' },
  { value: 'In Progress', label: 'In Progress' },
  { value: 'Implemented', label: 'Implemented' },
  { value: 'Archived', label: 'Archived' },
]

const SEARCH_PRIORITY_OPTIONS = [
  { value: 'Low', label: 'Low' },
  { value: 'Med', label: 'Med' },
  { value: 'High', label: 'High' },
]

const ADMIN_ROLE_OPTIONS = [
  { value: 'Owner', label: 'Owner' },
  { value: 'Admin', label: 'Admin' },
  { value: 'Member', label: 'Member' },
  { value: 'Guest', label: 'Guest' },
]

const NON_OWNER_ROLE_OPTIONS = ADMIN_ROLE_OPTIONS.filter((option) => (
  option.value === 'Member' || option.value === 'Guest'
))

const SKILL_MODE_OPTIONS = [
  { value: 'advisory', label: 'advisory' },
  { value: 'enforced', label: 'enforced' },
]

const SKILL_TRUST_OPTIONS = [
  { value: 'reviewed', label: 'reviewed' },
  { value: 'verified', label: 'verified' },
  { value: 'untrusted', label: 'untrusted' },
]

function normalizeOptionValue(
  value: string,
  options: Array<{ value: string; label: string }>,
  fallback: string
): string {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) return fallback
  const match = options.find((option) => option.value.toLowerCase() === normalized)
  return match?.value || fallback
}

function isAdminTierRole(value: unknown): boolean {
  const normalized = String(value || '').trim()
  return normalized === 'Owner' || normalized === 'Admin'
}

function resolveWorkspaceBotProvider(item: AdminWorkspaceUser): AgentAuthProvider | null {
  const configuredProvider = String(item.background_agent_provider || '').trim().toLowerCase()
  if (configuredProvider === 'claude') return 'claude'
  if (configuredProvider === 'opencode') return 'opencode'
  if (configuredProvider === 'codex') return 'codex'
  const username = String(item.username || '').trim().toLowerCase()
  if (username === 'claude-bot') return 'claude'
  if (username === 'opencode-bot') return 'opencode'
  if (username === 'codex-bot') return 'codex'
  const parsed = parseAgentExecutionModel(item.background_agent_model)
  return parsed?.provider || null
}

function getWorkspaceUserMonogram(item: AdminWorkspaceUser): string {
  const username = String(item.username || '').trim().toLowerCase()
  if (username === 'codex-bot') return 'CX'
  if (username === 'claude-bot') return 'CL'
  if (username === 'opencode-bot') return 'OC'
  const source = String(item.full_name || item.username || '').trim()
  if (!source) return '??'
  const tokens = source.split(/\s+/).filter(Boolean)
  if (tokens.length >= 2) {
    return `${tokens[0]?.charAt(0) || ''}${tokens[1]?.charAt(0) || ''}`.toUpperCase()
  }
  return source.slice(0, 2).toUpperCase()
}

function buildProviderModelOptions(
  models: string[],
  provider: AgentAuthProvider
): Array<{ value: string; label: string }> {
  const seen = new Set<string>()
  const options: Array<{ value: string; label: string }> = []
  for (const raw of Array.isArray(models) ? models : []) {
    const normalized = normalizeAgentExecutionModel(raw)
    const parsed = parseAgentExecutionModel(normalized)
    if (!parsed || parsed.provider !== provider) continue
    if (seen.has(normalized.toLowerCase())) continue
    seen.add(normalized.toLowerCase())
    options.push({
      value: normalized,
      label: parsed.model,
    })
  }
  return options
}

type WorkspaceAuthSummaryPill = {
  label: string
  value: string
}

type WorkspaceAuthFact = {
  label: string
  value: string
}

function WorkspaceAuthCard({
  id,
  containerRef,
  title,
  providerLabel,
  actorUsername,
  loading,
  loadingText,
  description,
  statusLabel,
  statusTone = 'default',
  sessionStatusLabel,
  summaryPills,
  facts,
  actionSlot,
  feedback,
  canManage,
  manageHint,
  forceDetailsOpen = false,
}: {
  id: string
  containerRef?: React.RefObject<HTMLDivElement | null>
  title: string
  providerLabel: string
  actorUsername: string
  loading: boolean
  loadingText: string
  description: string
  statusLabel: string
  statusTone?: 'default' | 'error'
  sessionStatusLabel?: string | null
  summaryPills: WorkspaceAuthSummaryPill[]
  facts: WorkspaceAuthFact[]
  actionSlot?: React.ReactNode
  feedback?: { tone: 'success' | 'error'; message: string } | null
  canManage: boolean
  manageHint: string
  forceDetailsOpen?: boolean
}) {
  const [detailsOpen, setDetailsOpen] = React.useState(forceDetailsOpen)

  React.useEffect(() => {
    if (forceDetailsOpen) {
      setDetailsOpen(true)
    }
  }, [forceDetailsOpen])

  return (
    <section className="profile-pane-card workspace-auth-card" aria-label={title} id={id} ref={containerRef}>
      <div className="workspace-auth-card-head">
        <div className="workspace-auth-card-title-group">
          <div className="profile-pane-head">
            <h3>
              <span className="profile-pane-head-icon" aria-hidden="true">
                <Icon path="M12 3l7 4v6c0 5-3.5 9-7 10-3.5-1-7-5-7-10V7l7-4zM8 12h8M8 16h5" />
              </span>
              <span>{title}</span>
            </h3>
            <span className="status-chip">{providerLabel}</span>
          </div>
          <p className="meta workspace-auth-card-title-meta">Shared workspace connection for @{actorUsername}</p>
        </div>
        <div className="workspace-auth-card-badges">
          <span className={`status-chip ${statusTone === 'error' ? 'is-error' : ''}`.trim()}>
            {statusLabel}
          </span>
          {sessionStatusLabel ? <span className="status-chip">{sessionStatusLabel}</span> : null}
        </div>
      </div>

      {loading ? (
        <p className="meta">{loadingText}</p>
      ) : (
        <>
          <p className="meta workspace-auth-card-description">{description}</p>
          {summaryPills.length > 0 ? (
            <div className="workspace-auth-pill-row">
              {summaryPills.map((item) => (
                <div key={`${item.label}:${item.value}`} className="workspace-auth-pill">
                  <span className="workspace-auth-pill-label">{item.label}</span>
                  <span className="workspace-auth-pill-value">{item.value}</span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="workspace-auth-card-actions">
            <div className="workspace-auth-card-actions-main">
              {actionSlot}
            </div>
            <Collapsible.Root open={detailsOpen} onOpenChange={setDetailsOpen}>
              <Collapsible.Trigger asChild>
                <button className="button-secondary profile-action-button workspace-auth-details-trigger" type="button">
                  <span>{detailsOpen ? 'Hide details' : 'Show details'}</span>
                  <span className={`workspace-auth-details-chevron ${detailsOpen ? 'is-open' : ''}`.trim()} aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </button>
              </Collapsible.Trigger>
              <Collapsible.Content className="workspace-auth-details">
                <dl className="workspace-auth-facts">
                  {facts.map((item) => (
                    <div key={`${item.label}:${item.value}`} className="workspace-auth-fact">
                      <dt>{item.label}</dt>
                      <dd>{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </Collapsible.Content>
            </Collapsible.Root>
          </div>
          {!canManage ? (
            <p className="meta">{manageHint}</p>
          ) : null}
          {feedback ? (
            <div className={`notice ${feedback.tone === 'error' ? 'notice-error' : ''}`.trim()}>
              {feedback.message}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}

function WorkspaceDoctorCard({
  doctorStatus,
  architectureInventorySummary,
  doctorLoading,
  doctorError,
  canManage,
  onSeedDoctor,
  seedDoctorPending,
  onRunDoctor,
  runDoctorPending,
  onResetDoctor,
  resetDoctorPending,
}: {
  doctorStatus: WorkspaceDoctorStatus | null
  architectureInventorySummary: ArchitectureInventorySummary | null
  doctorLoading: boolean
  doctorError: string | null
  canManage: boolean
  onSeedDoctor: () => Promise<unknown>
  seedDoctorPending: boolean
  onRunDoctor: () => Promise<unknown>
  runDoctorPending: boolean
  onResetDoctor: () => Promise<unknown>
  resetDoctorPending: boolean
}) {
  const formatDateTime = (value: string | null): string => {
    if (!value) return 'n/a'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  }
  const [selectedRunId, setSelectedRunId] = React.useState('')
  const recentRuns = Array.isArray(doctorStatus?.recent_runs) ? doctorStatus.recent_runs : []
  const selectedRun = React.useMemo(() => {
    if (!recentRuns.length) return doctorStatus?.last_run ?? null
    if (!selectedRunId) return doctorStatus?.last_run ?? recentRuns[0] ?? null
    return recentRuns.find((item) => item.id === selectedRunId) ?? doctorStatus?.last_run ?? recentRuns[0] ?? null
  }, [doctorStatus?.last_run, recentRuns, selectedRunId])
  React.useEffect(() => {
    if (!recentRuns.length) {
      setSelectedRunId('')
      return
    }
    if (selectedRunId && recentRuns.some((item) => item.id === selectedRunId)) return
    setSelectedRunId(String((doctorStatus?.last_run ?? recentRuns[0])?.id || ''))
  }, [doctorStatus?.last_run, recentRuns, selectedRunId])
  const checks = Array.isArray(selectedRun?.summary?.checks) ? selectedRun.summary.checks : []
  const architectureAudit = architectureInventorySummary?.audit ?? null
  const architectureCounts = architectureInventorySummary?.counts ?? null
  const architectureGeneratedAt = architectureInventorySummary?.generated_at ?? null
  const architectureCacheStatus = architectureInventorySummary?.cache_status ?? null
  const architectureAuditLabel = architectureAudit?.ok ? 'Healthy' : 'Issues detected'
  return (
    <section className="profile-pane-card" aria-label="ConstructOS Doctor" data-tour-id="workspace-doctor-card">
      <div className="profile-pane-head">
        <h3>
          <span className="profile-pane-head-icon" aria-hidden="true">
            <Icon path="M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4zM9.5 12.5l1.5 1.5 3.5-4" />
          </span>
          <span>ConstructOS Doctor</span>
        </h3>
        <span className="status-chip">
          {doctorStatus?.supported ? (doctorStatus?.seeded ? 'Seeded' : 'Ready') : 'Unsupported'}
        </span>
      </div>
      {doctorLoading ? <div className="notice">Loading Doctor status...</div> : null}
      {doctorError ? <div className="notice notice-error">{doctorError}</div> : null}
      {doctorStatus && !doctorStatus.supported ? (
        <div className="notice notice-error">
          Doctor is not enabled in <code>AGENT_ENABLED_PLUGINS</code>.
        </div>
      ) : null}
      <dl className="profile-facts">
        <div className="profile-fact">
          <dt>Fixture version</dt>
          <dd>{doctorStatus?.fixture_version || 'n/a'}</dd>
        </div>
        <div className="profile-fact">
          <dt>Doctor project</dt>
          <dd>{doctorStatus?.project?.name || 'Not seeded'}</dd>
        </div>
        <div className="profile-fact">
          <dt>Seeded team tasks</dt>
          <dd>{doctorStatus?.checks?.seeded_team_task_count ?? 0}</dd>
        </div>
        <div className="profile-fact">
          <dt>Last run</dt>
          <dd>{doctorStatus?.last_run_status || 'Never run'}</dd>
        </div>
      </dl>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
        <button
          className="status-chip"
          onClick={() => { void onSeedDoctor() }}
          disabled={!canManage || seedDoctorPending || !doctorStatus?.supported}
        >
          {seedDoctorPending ? 'Seeding...' : (doctorStatus?.seeded ? 'Reseed Doctor Project' : 'Seed Doctor Project')}
        </button>
        <button
          className="status-chip"
          onClick={() => { void onRunDoctor() }}
          disabled={!canManage || runDoctorPending || !doctorStatus?.supported}
        >
          {runDoctorPending ? 'Running...' : 'Run Doctor'}
        </button>
        <button
          className="status-chip"
          onClick={() => { void onResetDoctor() }}
          disabled={!canManage || resetDoctorPending || !doctorStatus?.seeded}
        >
          {resetDoctorPending ? 'Resetting...' : 'Reset Doctor Project'}
        </button>
        {doctorStatus?.project?.link ? (
          <a className="status-chip" href={doctorStatus.project.link}>Open Doctor Project</a>
        ) : null}
      </div>
      <p className="meta" style={{ marginTop: 12 }}>
        Doctor seeds a dedicated workspace validation project, verifies Team Mode wiring, and queues a lead automation cycle.
      </p>
      <dl className="profile-facts" style={{ marginTop: 12 }}>
        <div className="profile-fact">
          <dt>Runner</dt>
          <dd>{doctorStatus?.runner_enabled ? 'Enabled' : 'Disabled'}</dd>
        </div>
        <div className="profile-fact">
          <dt>Last seeded</dt>
          <dd>{formatDateTime(doctorStatus?.last_seeded_at || null)}</dd>
        </div>
        <div className="profile-fact">
          <dt>Last run at</dt>
          <dd>{formatDateTime(doctorStatus?.last_run_at || null)}</dd>
        </div>
        <div className="profile-fact">
          <dt>Project plugins</dt>
          <dd>
            Team Mode {doctorStatus?.checks?.team_mode_enabled ? 'on' : 'off'} / Git Delivery {doctorStatus?.checks?.git_delivery_enabled ? 'on' : 'off'}
          </dd>
        </div>
      </dl>
      {architectureInventorySummary ? (
        <>
          <p className="meta" style={{ marginTop: 12 }}>
            Runtime contract summary from `/api/bootstrap`.
          </p>
          <dl className="profile-facts" style={{ marginTop: 8 }}>
            <div className="profile-fact">
              <dt>Architecture audit</dt>
              <dd>{architectureAuditLabel}</dd>
            </div>
            <div className="profile-fact">
              <dt>Audit errors / warnings</dt>
              <dd>
                {architectureAudit?.error_count ?? 0} / {architectureAudit?.warning_count ?? 0}
              </dd>
            </div>
            <div className="profile-fact">
              <dt>Execution providers / plugins</dt>
              <dd>
                {Number(architectureCounts?.execution_providers ?? 0)} / {Number(architectureCounts?.workflow_plugins ?? 0)}
              </dd>
            </div>
            <div className="profile-fact">
              <dt>MCP tools / prompt templates</dt>
              <dd>
                {Number(architectureCounts?.constructos_mcp_tools ?? 0)} / {Number(architectureCounts?.prompt_templates ?? 0)}
              </dd>
            </div>
            <div className="profile-fact">
              <dt>Summary generated</dt>
              <dd>{formatDateTime(architectureGeneratedAt)}</dd>
            </div>
            <div className="profile-fact">
              <dt>Summary cache</dt>
              <dd>
                hits {Number(architectureCacheStatus?.hit_count ?? 0)} / misses {Number(architectureCacheStatus?.miss_count ?? 0)}
              </dd>
            </div>
          </dl>
        </>
      ) : null}
      {recentRuns.length > 0 ? (
        <div style={{ marginTop: 14 }}>
          <strong>Recent runs</strong>
          <div className="profile-facts" style={{ marginTop: 10 }}>
            {recentRuns.slice(0, 6).map((item) => (
              <div className="profile-fact" key={item.id}>
                <dt>
                  <button
                    className="status-chip"
                    onClick={() => setSelectedRunId(item.id)}
                    style={{ width: '100%', textAlign: 'left' }}
                  >
                    {formatDateTime(item.started_at)}
                  </button>
                </dt>
                <dd>{item.status}</dd>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {selectedRun ? (
        <div style={{ marginTop: 14 }}>
          <strong>Run details</strong>
          <dl className="profile-facts" style={{ marginTop: 10 }}>
            <div className="profile-fact">
              <dt>Started</dt>
              <dd>{formatDateTime(selectedRun.started_at)}</dd>
            </div>
            <div className="profile-fact">
              <dt>Finished</dt>
              <dd>{formatDateTime(selectedRun.finished_at)}</dd>
            </div>
            <div className="profile-fact">
              <dt>Status</dt>
              <dd>{selectedRun.status}</dd>
            </div>
            <div className="profile-fact">
              <dt>Fixture version</dt>
              <dd>{selectedRun.fixture_version}</dd>
            </div>
          </dl>
          {checks.length > 0 ? (
            <div style={{ marginTop: 12 }}>
              <strong>Checks</strong>
              <div className="profile-facts" style={{ marginTop: 10 }}>
                {checks.map((item) => (
                  <div className="profile-fact" key={item.id}>
                    <dt>{item.label}</dt>
                    <dd>{String(item.status || 'unknown')}</dd>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div style={{ marginTop: 12 }}>
            <strong>Summary</strong>
            <pre style={{ marginTop: 10, overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(selectedRun.summary || {}, null, 2)}
            </pre>
          </div>
        </div>
      ) : null}
    </section>
  )
}

function SearchFilterSelect({
  value,
  onValueChange,
  anyLabel,
  options,
  ariaLabel,
}: {
  value: string
  onValueChange: (value: string) => void
  anyLabel: string
  options: Array<{ value: string; label: string }>
  ariaLabel: string
}) {
  const normalizedValue = String(value || '').trim() || SEARCH_ANY_VALUE
  return (
    <Select.Root
      value={normalizedValue}
      onValueChange={(nextValue) => onValueChange(nextValue === SEARCH_ANY_VALUE ? '' : nextValue)}
    >
      <Select.Trigger className="quickadd-project-trigger search-panel-select-trigger" aria-label={ariaLabel}>
        <Select.Value />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content search-panel-select-content" position="popper" sideOffset={6}>
          <Select.Viewport className="quickadd-project-viewport">
            <Select.Item value={SEARCH_ANY_VALUE} className="quickadd-project-item">
              <Select.ItemText>{anyLabel}</Select.ItemText>
              <Select.ItemIndicator className="quickadd-project-item-indicator">
                <Icon path="M5 13l4 4L19 7" />
              </Select.ItemIndicator>
            </Select.Item>
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

function AdminSelect({
  value,
  onValueChange,
  options,
  ariaLabel,
  disabled = false,
}: {
  value: string
  onValueChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  ariaLabel: string
  disabled?: boolean
}) {
  return (
    <Select.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <Select.Trigger
        className="quickadd-project-trigger taskdrawer-select-trigger admin-select-trigger"
        aria-label={ariaLabel}
        disabled={disabled}
      >
        <Select.Value />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content admin-select-content" position="popper" sideOffset={6}>
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

export function SearchPanel({
  searchQ,
  setSearchQ,
  searchStatus,
  setSearchStatus,
  searchSpecificationStatus,
  setSearchSpecificationStatus,
  searchPriority,
  setSearchPriority,
  searchArchived,
  setSearchArchived,
  taskTagSuggestions,
  searchTags,
  toggleSearchTag,
  clearSearchTags,
  onClose,
}: {
  searchQ: string
  setSearchQ: React.Dispatch<React.SetStateAction<string>>
  searchStatus: string
  setSearchStatus: React.Dispatch<React.SetStateAction<string>>
  searchSpecificationStatus: string
  setSearchSpecificationStatus: React.Dispatch<React.SetStateAction<string>>
  searchPriority: string
  setSearchPriority: React.Dispatch<React.SetStateAction<string>>
  searchArchived: boolean
  setSearchArchived: React.Dispatch<React.SetStateAction<boolean>>
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
  clearSearchTags: () => void
  onClose: () => void
}) {
  const activeAdvancedFilterCount = React.useMemo(() => {
    let count = 0
    if (String(searchStatus || '').trim()) count += 1
    if (String(searchSpecificationStatus || '').trim()) count += 1
    if (String(searchPriority || '').trim()) count += 1
    if (searchArchived) count += 1
    return count
  }, [searchArchived, searchPriority, searchSpecificationStatus, searchStatus])
  const [advancedOpen, setAdvancedOpen] = React.useState<boolean>(activeAdvancedFilterCount > 0)

  React.useEffect(() => {
    if (activeAdvancedFilterCount > 0) setAdvancedOpen(true)
  }, [activeAdvancedFilterCount])

  const resetAllFilters = React.useCallback(() => {
    setSearchQ('')
    setSearchStatus('')
    setSearchSpecificationStatus('')
    setSearchPriority('')
    setSearchArchived(false)
    clearSearchTags()
    setAdvancedOpen(false)
  }, [
    clearSearchTags,
    setSearchArchived,
    setSearchPriority,
    setSearchQ,
    setSearchSpecificationStatus,
    setSearchStatus,
  ])

  return (
    <section className="card search-panel-card" data-tour-id="search-panel">
      <div className="row search-panel-header">
        <h2 style={{ margin: 0 }}>Search</h2>
        <div className="search-panel-header-actions">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="action-icon" type="button" title="Search actions" aria-label="Search actions">
                <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="task-group-menu-content search-panel-menu-content" sideOffset={8} align="end">
                <DropdownMenu.Item className="task-group-menu-item" onSelect={resetAllFilters}>
                  <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
                  <span>Reset all filters</span>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
          <button className="action-icon" onClick={onClose} title="Close search" aria-label="Close search">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      </div>

      <Collapsible.Root open={advancedOpen} onOpenChange={setAdvancedOpen} className="search-panel-collapsible">
        <div className="search-panel-primary-row">
          <input
            className="search-panel-input"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="Search tasks, notes, and specifications"
            aria-label="Search query"
          />
          <Collapsible.Trigger asChild>
            <button
              className={`status-chip search-panel-advanced-trigger ${advancedOpen ? 'active' : ''}`}
              type="button"
              aria-expanded={advancedOpen}
            >
              <Icon path={advancedOpen ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} />
              <span>Advanced</span>
              {activeAdvancedFilterCount > 0 ? (
                <span className="search-panel-filter-count">{activeAdvancedFilterCount}</span>
              ) : null}
            </button>
          </Collapsible.Trigger>
        </div>
        <Collapsible.Content className="search-panel-advanced-grid">
          <SearchFilterSelect
            value={searchStatus}
            onValueChange={setSearchStatus}
            anyLabel="Any task status"
            options={SEARCH_TASK_STATUS_OPTIONS}
            ariaLabel="Filter by task status"
          />
          <SearchFilterSelect
            value={searchSpecificationStatus}
            onValueChange={setSearchSpecificationStatus}
            anyLabel="Any specification status"
            options={SEARCH_SPEC_STATUS_OPTIONS}
            ariaLabel="Filter by specification status"
          />
          <SearchFilterSelect
            value={searchPriority}
            onValueChange={setSearchPriority}
            anyLabel="Any priority"
            options={SEARCH_PRIORITY_OPTIONS}
            ariaLabel="Filter by task priority"
          />
          <label className="search-panel-checkbox-row" htmlFor="search-archived-only">
            <Checkbox.Root
              className="search-panel-checkbox-root"
              id="search-archived-only"
              checked={searchArchived}
              onCheckedChange={(checked: boolean | 'indeterminate') => setSearchArchived(checked === true)}
            >
              <Checkbox.Indicator className="search-panel-checkbox-indicator">
                <Icon path="M5 13l4 4L19 7" />
              </Checkbox.Indicator>
            </Checkbox.Root>
            <span>Archived only</span>
          </label>
        </Collapsible.Content>
      </Collapsible.Root>

      <div className="search-panel-tags-row">
        <div className="search-panel-tags-title-row">
          <span className="meta">Tag filters</span>
          {searchTags.length > 0 ? <span className="badge">{searchTags.length} selected</span> : null}
        </div>
        <div className="search-panel-tags-scroll">
          <div className="row wrap search-panel-tags-wrap">
            <PopularTagFilters
              tags={taskTagSuggestions}
              selectedTags={searchTags}
              onToggleTag={toggleSearchTag}
              onClear={clearSearchTags}
              idPrefix="search-tag"
            />
          </div>
        </div>
      </div>
    </section>
  )
}

export function ProfilePanel({
  userUsername,
  theme,
  speechLang,
  agentChatModel,
  agentChatReasoningEffort,
  agentChatDefaultModel,
  agentChatDefaultReasoningEffort,
  agentChatAvailableModels,
  frontendVersion,
  backendVersion,
  backendBuild,
  deployedAtUtc,
  codexAuthStatus,
  codexAuthLoading,
  canManageCodexAuth,
  claudeAuthStatus,
  claudeAuthLoading,
  canManageClaudeAuth,
  license,
  licenseLoading,
  licenseError,
  onLogout,
  onToggleTheme,
  onChangeSpeechLang,
  onSaveChatExecutionPreferences,
  saveChatExecutionPreferencesPending,
  changePassword,
  passwordChangePending,
  onStartCodexDeviceAuth,
  startCodexDeviceAuthPending,
  onCancelCodexDeviceAuth,
  cancelCodexDeviceAuthPending,
  onSubmitCodexBrowserCallback,
  submitCodexBrowserCallbackPending,
  onDeleteCodexAuthOverride,
  deleteCodexAuthOverridePending,
  onStartClaudeDeviceAuth,
  startClaudeDeviceAuthPending,
  onCancelClaudeDeviceAuth,
  cancelClaudeDeviceAuthPending,
  onSubmitClaudeDeviceAuthCode,
  submitClaudeDeviceAuthCodePending,
  onDeleteClaudeAuthOverride,
  deleteClaudeAuthOverridePending,
  submitFeedback,
  feedbackSubmitting,
}: {
  userUsername: string
  theme: 'light' | 'dark'
  speechLang: string
  agentChatModel: string
  agentChatReasoningEffort: ChatReasoningEffort | string
  agentChatDefaultModel: string
  agentChatDefaultReasoningEffort: ChatReasoningEffort | string
  agentChatAvailableModels: string[]
  frontendVersion: string
  backendVersion: string
  backendBuild: string | null
  deployedAtUtc: string | null
  codexAuthStatus: AgentAuthStatus | null
  codexAuthLoading: boolean
  canManageCodexAuth: boolean
  claudeAuthStatus: AgentAuthStatus | null
  claudeAuthLoading: boolean
  canManageClaudeAuth: boolean
  license: LicenseStatus | null | undefined
  licenseLoading: boolean
  licenseError: string | null
  onLogout: () => void
  onToggleTheme: () => void
  onChangeSpeechLang: (value: string) => void
  onSaveChatExecutionPreferences: (payload: {
    agent_chat_model: string | null
    agent_chat_reasoning_effort: ChatReasoningEffort
  }) => Promise<unknown>
  saveChatExecutionPreferencesPending: boolean
  changePassword: (payload: { current_password: string; new_password: string }) => Promise<unknown>
  passwordChangePending: boolean
  onStartCodexDeviceAuth: (loginMethod: CodexAuthLoginMethod) => Promise<unknown>
  startCodexDeviceAuthPending: boolean
  onCancelCodexDeviceAuth: () => Promise<unknown>
  cancelCodexDeviceAuthPending: boolean
  onSubmitCodexBrowserCallback: (payload: { sessionId: string; callbackUrl: string }) => Promise<unknown>
  submitCodexBrowserCallbackPending: boolean
  onDeleteCodexAuthOverride: () => Promise<unknown>
  deleteCodexAuthOverridePending: boolean
  onStartClaudeDeviceAuth: (loginMethod: ClaudeAuthLoginMethod) => Promise<unknown>
  startClaudeDeviceAuthPending: boolean
  onCancelClaudeDeviceAuth: () => Promise<unknown>
  cancelClaudeDeviceAuthPending: boolean
  onSubmitClaudeDeviceAuthCode: (code: string) => Promise<AgentAuthStatus>
  submitClaudeDeviceAuthCodePending: boolean
  onDeleteClaudeAuthOverride: () => Promise<unknown>
  deleteClaudeAuthOverridePending: boolean
  submitFeedback: (payload: {
    title: string
    description: string
    feedback_type: 'general' | 'feature_request' | 'question' | 'other'
    context?: Record<string, unknown>
    metadata?: Record<string, unknown>
  }) => Promise<unknown>
  feedbackSubmitting: boolean
}) {
  const nextTheme = theme === 'light' ? 'dark' : 'light'
  const licenseStatus = String(license?.status || '').trim().toLowerCase() || 'unknown'
  const licenseStatusLabel = licenseStatus.charAt(0).toUpperCase() + licenseStatus.slice(1)
  const formatDateTime = (value: string | null): string => {
    if (!value) return 'n/a'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  }
  const formatLabel = (value: string): string => {
    const normalized = String(value || '').trim().replace(/_/g, ' ')
    if (!normalized) return 'n/a'
    return normalized
      .split(/\s+/)
      .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
      .join(' ')
  }
  const licenseMetadata = (license?.metadata && typeof license.metadata === 'object'
    ? (license.metadata as Record<string, unknown>)
    : {}) as Record<string, unknown>
  const subscriptionStatus = String(licenseMetadata.subscription_status ?? '').trim().toLowerCase()
  const subscriptionValidUntil = String(licenseMetadata.subscription_valid_until ?? '').trim() || null
  const publicBetaEnabled = licenseMetadata.public_beta === true
  const publicBetaFreeUntil = String(licenseMetadata.public_beta_free_until ?? '').trim() || null
  const entitlementSource = publicBetaEnabled
    ? `Public beta until ${formatDateTime(publicBetaFreeUntil)}`
    : subscriptionStatus
      ? `Subscription (${formatLabel(subscriptionStatus)})`
      : 'Trial fallback'
  const showTrialWindow = licenseStatus === 'trial' || licenseStatus === 'grace'
  const [profileTab, setProfileTab] = React.useState<'preferences' | 'security' | 'feedback'>('preferences')
  const [currentPasswordInput, setCurrentPasswordInput] = React.useState('')
  const [newPasswordInput, setNewPasswordInput] = React.useState('')
  const [confirmPasswordInput, setConfirmPasswordInput] = React.useState('')
  const [passwordFeedback, setPasswordFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [feedbackTitleInput, setFeedbackTitleInput] = React.useState('')
  const [feedbackDescriptionInput, setFeedbackDescriptionInput] = React.useState('')
  const [feedbackTypeInput, setFeedbackTypeInput] = React.useState<'general' | 'feature_request' | 'question' | 'other'>('general')
  const [feedbackResult, setFeedbackResult] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [installationCopyState, setInstallationCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const [runtimeCopyState, setRuntimeCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const voiceFactRef = React.useRef<HTMLDivElement | null>(null)
  const voiceSelectTriggerRef = React.useRef<HTMLButtonElement | null>(null)
  const chatExecutionFactRef = React.useRef<HTMLDivElement | null>(null)
  const chatExecutionModelTriggerRef = React.useRef<HTMLButtonElement | null>(null)
  const codexAuthFactRef = React.useRef<HTMLDivElement | null>(null)
  const codexAuthPrimaryButtonRef = React.useRef<HTMLButtonElement | null>(null)
  const claudeAuthFactRef = React.useRef<HTMLDivElement | null>(null)
  const claudeAuthPrimaryButtonRef = React.useRef<HTMLButtonElement | null>(null)
  const [codexAuthDialogOpen, setCodexAuthDialogOpen] = React.useState(false)
  const [codexAuthFeedback, setCodexAuthFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [codexAuthManualCallbackInput, setCodexAuthManualCallbackInput] = React.useState('')
  const [claudeAuthDialogOpen, setClaudeAuthDialogOpen] = React.useState(false)
  const [claudeAuthFeedback, setClaudeAuthFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [claudeAuthManualCodeInput, setClaudeAuthManualCodeInput] = React.useState('')
  const [chatModelInput, setChatModelInput] = React.useState(() => normalizeAgentExecutionModel(agentChatModel))
  const [chatReasoningInput, setChatReasoningInput] = React.useState<ChatReasoningEffort>(() =>
    normalizeChatReasoningEffort(agentChatReasoningEffort)
  )
  const [chatExecutionFeedback, setChatExecutionFeedback] = React.useState<{ tone: 'error'; message: string } | null>(null)
  const chatExecutionLastAttemptKeyRef = React.useRef('')
  const chatExecutionLastFailedKeyRef = React.useRef('')
  const chatExecutionDirtyRef = React.useRef(false)
  const browserTimeZone = React.useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'n/a'
    } catch {
      return 'n/a'
    }
  }, [])
  const selectedVoiceLabel = React.useMemo(() => {
    return VOICE_LANG_OPTIONS.find((item) => item.value === speechLang)?.label || speechLang
  }, [speechLang])
  const chatModelOptions = React.useMemo(() => {
    const out: string[] = []
    const seen = new Set<string>()
    const push = (value: string) => {
      const model = normalizeAgentExecutionModel(value)
      if (!model) return
      const key = model.toLowerCase()
      if (seen.has(key)) return
      seen.add(key)
      out.push(model)
    }
    for (const model of Array.isArray(agentChatAvailableModels) ? agentChatAvailableModels : []) {
      push(model)
    }
    push(agentChatDefaultModel)
    push(agentChatModel)
    push(chatModelInput)
    return out
  }, [agentChatAvailableModels, agentChatDefaultModel, agentChatModel, chatModelInput])
  const normalizedChatModelInput = normalizeAgentExecutionModel(chatModelInput)
  const normalizedChatReasoningInput = normalizeChatReasoningEffort(chatReasoningInput)
  const normalizedPersistedChatModel = normalizeAgentExecutionModel(agentChatModel)
  const normalizedPersistedChatReasoning = normalizeChatReasoningEffort(agentChatReasoningEffort)
  const activeExecutionProvider = resolveActiveAgentExecutionProvider(
    normalizedChatModelInput || normalizedPersistedChatModel,
    agentChatDefaultModel
  )
  const chatReasoningOptions = React.useMemo(
    () => getChatReasoningOptions(activeExecutionProvider),
    [activeExecutionProvider]
  )
  const selectedChatReasoningLabel = React.useMemo(
    () => getChatReasoningLabel(chatReasoningInput, activeExecutionProvider),
    [activeExecutionProvider, chatReasoningInput]
  )
  const chatExecutionHasPendingChanges = (
    normalizedChatModelInput !== normalizedPersistedChatModel
    || normalizedChatReasoningInput !== normalizedPersistedChatReasoning
  )
  const chatExecutionStatusLabel: string | null = chatExecutionFeedback
    ? 'Save failed'
    : (saveChatExecutionPreferencesPending || chatExecutionHasPendingChanges)
      ? 'Saving automatically...'
      : null
  const selectedFeedbackTypeLabel = React.useMemo(() => {
    return PROFILE_FEEDBACK_TYPE_OPTIONS.find((item) => item.value === feedbackTypeInput)?.label || 'General'
  }, [feedbackTypeInput])
  const activeExecutionProviderLabel = getAgentExecutionProviderLabel(activeExecutionProvider)
  const activeExecutionModelLabel = formatAgentExecutionModelLabel(
    normalizedPersistedChatModel || agentChatDefaultModel
  )
  const codexAuthSource = String(codexAuthStatus?.effective_source || '').trim().toLowerCase()
  const codexAuthLoginSession = codexAuthStatus?.login_session ?? null
  const codexAuthStatusLabel = authSourceLabel(
    'codex',
    codexAuthStatus?.effective_source,
    codexAuthStatus?.target_actor_username
  )
  const codexAuthSessionStatusLabel = (() => {
    if (codexAuthSource === 'system_override') return 'Connected'
    const status = String(codexAuthLoginSession?.status || '').trim().toLowerCase()
    if (status === 'pending') return 'Awaiting browser confirmation'
    if (status === 'succeeded') return 'Connected'
    if (status === 'failed') return 'Sign-in failed'
    if (status === 'cancelled') return 'Sign-in cancelled'
    return null
  })()
  const codexAuthLoginMethod = normalizeCodexAuthLoginMethod(
    codexAuthLoginSession?.login_method ?? codexAuthStatus?.selected_login_method
  )
  const codexAuthLoginMethodLabel = formatCodexAuthLoginMethodLabel(codexAuthLoginMethod)
  const codexAuthHasSystemOverride = codexAuthSource === 'system_override'
  const codexAuthHasPendingSignIn = String(codexAuthLoginSession?.status || '').trim().toLowerCase() === 'pending'
  const codexAuthCanConnect = canManageCodexAuth && !startCodexDeviceAuthPending && !cancelCodexDeviceAuthPending
  const codexAuthCanSubmitBrowserCallback = canManageCodexAuth
    && codexAuthHasPendingSignIn
    && codexAuthLoginMethod === 'browser'
    && !submitCodexBrowserCallbackPending
    && codexAuthManualCallbackInput.trim().length > 0
  const codexAuthCanRemoveOverride = canManageCodexAuth
    && Boolean(codexAuthStatus?.override_available)
    && !deleteCodexAuthOverridePending
  const claudeAuthSource = String(claudeAuthStatus?.effective_source || '').trim().toLowerCase()
  const claudeAuthLoginSession = claudeAuthStatus?.login_session ?? null
  const claudeAuthStatusLabel = authSourceLabel(
    'claude',
    claudeAuthStatus?.effective_source,
    claudeAuthStatus?.target_actor_username
  )
  const claudeAuthSessionStatusLabel = (() => {
    if (claudeAuthSource === 'system_override') return 'Connected'
    const status = String(claudeAuthLoginSession?.status || '').trim().toLowerCase()
    if (status === 'pending') return 'Awaiting browser confirmation'
    if (status === 'succeeded') return 'Connected'
    if (status === 'failed') return 'Sign-in failed'
    if (status === 'cancelled') return 'Sign-in cancelled'
    return null
  })()
  const claudeAuthLoginMethod = normalizeClaudeAuthLoginMethod(
    claudeAuthLoginSession?.login_method ?? claudeAuthStatus?.selected_login_method
  )
  const claudeAuthLoginMethodLabel = formatClaudeAuthLoginMethodLabel(claudeAuthLoginMethod)
  const claudeAuthHasSystemOverride = claudeAuthSource === 'system_override'
  const claudeAuthHasPendingSignIn = (
    String(claudeAuthLoginSession?.status || '').trim().toLowerCase() === 'pending'
    && !claudeAuthHasSystemOverride
  )
  const claudeAuthCanConnect = canManageClaudeAuth && !startClaudeDeviceAuthPending && !cancelClaudeDeviceAuthPending
  const claudeAuthCanSubmitCode = canManageClaudeAuth
    && claudeAuthHasPendingSignIn
    && !submitClaudeDeviceAuthCodePending
    && claudeAuthManualCodeInput.trim().length > 0
  const claudeAuthCanRemoveOverride = canManageClaudeAuth
    && Boolean(claudeAuthStatus?.override_available)
    && !deleteClaudeAuthOverridePending
  const runtimeSnapshotText = React.useMemo(() => {
    return [
      `Frontend version: ${frontendVersion || 'n/a'}`,
      `Backend version: ${backendVersion || 'n/a'}`,
      `Backend build: ${backendBuild || 'n/a'}`,
      `Deployed UTC: ${deployedAtUtc || 'unknown'}`,
      `Theme: ${theme}`,
      `Voice language: ${selectedVoiceLabel}`,
      `Chat execution provider: ${activeExecutionProviderLabel}`,
      `Chat execution model: ${activeExecutionModelLabel}`,
      `Chat execution reasoning: ${normalizeChatReasoningEffort(agentChatReasoningEffort)}`,
      `Browser timezone: ${browserTimeZone}`,
    ].join('\n')
  }, [
    activeExecutionModelLabel,
    activeExecutionProviderLabel,
    agentChatDefaultModel,
    agentChatReasoningEffort,
    backendBuild,
    backendVersion,
    browserTimeZone,
    deployedAtUtc,
    frontendVersion,
    selectedVoiceLabel,
    theme,
  ])

  const scrollVoiceLanguageIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return

    const scrollNearestContainer = () => {
      const target = voiceFactRef.current
      if (!target) return

      const findScrollableParent = (node: HTMLElement | null): HTMLElement | null => {
        let current = node?.parentElement ?? null
        while (current) {
          const styles = window.getComputedStyle(current)
          const overflowY = styles.overflowY
          const isScrollable =
            (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
            current.scrollHeight > current.clientHeight + 1
          if (isScrollable) return current
          current = current.parentElement
        }
        return null
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })

      const parent = findScrollableParent(target)
      if (parent) {
        const targetRect = target.getBoundingClientRect()
        const parentRect = parent.getBoundingClientRect()
        const nextTop = parent.scrollTop + (targetRect.top - parentRect.top) - parent.clientHeight * 0.35
        parent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
      }
    }

    const focusVoiceSelect = () => {
      try {
        voiceSelectTriggerRef.current?.focus({ preventScroll: true })
      } catch {
        voiceSelectTriggerRef.current?.focus()
      }
    }

    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(scrollNearestContainer, 300)
    window.setTimeout(focusVoiceSelect, 340)
  }, [])

  const scrollChatExecutionIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return

    const scrollNearestContainer = () => {
      const target = chatExecutionFactRef.current
      if (!target) return

      const findScrollableParent = (node: HTMLElement | null): HTMLElement | null => {
        let current = node?.parentElement ?? null
        while (current) {
          const styles = window.getComputedStyle(current)
          const overflowY = styles.overflowY
          const isScrollable =
            (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
            current.scrollHeight > current.clientHeight + 1
          if (isScrollable) return current
          current = current.parentElement
        }
        return null
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })

      const parent = findScrollableParent(target)
      if (parent) {
        const targetRect = target.getBoundingClientRect()
        const parentRect = parent.getBoundingClientRect()
        const nextTop = parent.scrollTop + (targetRect.top - parentRect.top) - parent.clientHeight * 0.35
        parent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
      }
    }

    const focusModelInput = () => {
      try {
        chatExecutionModelTriggerRef.current?.focus({ preventScroll: true })
      } catch {
        chatExecutionModelTriggerRef.current?.focus()
      }
    }

    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(scrollNearestContainer, 300)
    window.setTimeout(focusModelInput, 340)
  }, [])

  const scrollCodexAuthIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return

    const scrollNearestContainer = () => {
      const target = codexAuthFactRef.current
      if (!target) return

      const findScrollableParent = (node: HTMLElement | null): HTMLElement | null => {
        let current = node?.parentElement ?? null
        while (current) {
          const styles = window.getComputedStyle(current)
          const overflowY = styles.overflowY
          const isScrollable =
            (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
            current.scrollHeight > current.clientHeight + 1
          if (isScrollable) return current
          current = current.parentElement
        }
        return null
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })

      const parent = findScrollableParent(target)
      if (parent) {
        const targetRect = target.getBoundingClientRect()
        const parentRect = parent.getBoundingClientRect()
        const nextTop = parent.scrollTop + (targetRect.top - parentRect.top) - parent.clientHeight * 0.35
        parent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
      }
    }

    const focusPrimaryAction = () => {
      try {
        codexAuthPrimaryButtonRef.current?.focus({ preventScroll: true })
      } catch {
        codexAuthPrimaryButtonRef.current?.focus()
      }
    }

    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(scrollNearestContainer, 300)
    window.setTimeout(focusPrimaryAction, 340)
  }, [])

  const scrollClaudeAuthIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return

    const scrollNearestContainer = () => {
      const target = claudeAuthFactRef.current
      if (!target) return

      const findScrollableParent = (node: HTMLElement | null): HTMLElement | null => {
        let current = node?.parentElement ?? null
        while (current) {
          const styles = window.getComputedStyle(current)
          const overflowY = styles.overflowY
          const isScrollable =
            (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
            current.scrollHeight > current.clientHeight + 1
          if (isScrollable) return current
          current = current.parentElement
        }
        return null
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })

      const parent = findScrollableParent(target)
      if (parent) {
        const targetRect = target.getBoundingClientRect()
        const parentRect = parent.getBoundingClientRect()
        const nextTop = parent.scrollTop + (targetRect.top - parentRect.top) - parent.clientHeight * 0.35
        parent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
      }
    }

    const focusPrimaryAction = () => {
      try {
        claudeAuthPrimaryButtonRef.current?.focus({ preventScroll: true })
      } catch {
        claudeAuthPrimaryButtonRef.current?.focus()
      }
    }

    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(scrollNearestContainer, 300)
    window.setTimeout(focusPrimaryAction, 340)
  }, [])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleVoiceFocus = () => {
      setProfileTab('preferences')
      window.setTimeout(() => {
        scrollVoiceLanguageIntoView()
      }, 80)
    }

    window.addEventListener('ui:focus-voice-language', handleVoiceFocus)

    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'voice_language'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (!shouldScroll) {
      return () => {
        window.removeEventListener('ui:focus-voice-language', handleVoiceFocus)
      }
    }

    const frameId = window.requestAnimationFrame(() => {
      handleVoiceFocus()
    })
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('ui:focus-voice-language', handleVoiceFocus)
    }
  }, [scrollVoiceLanguageIntoView])

  React.useEffect(() => {
    setChatModelInput(normalizeAgentExecutionModel(agentChatModel))
    setChatReasoningInput(normalizeChatReasoningEffort(agentChatReasoningEffort))
  }, [agentChatModel, agentChatReasoningEffort])

  React.useEffect(() => {
    const currentKey = `${normalizedChatModelInput}::${normalizedChatReasoningInput}`
    const persistedKey = `${normalizedPersistedChatModel}::${normalizedPersistedChatReasoning}`

    if (chatExecutionLastFailedKeyRef.current && chatExecutionLastFailedKeyRef.current !== currentKey) {
      chatExecutionLastFailedKeyRef.current = ''
    }

    if (currentKey === persistedKey) {
      chatExecutionLastAttemptKeyRef.current = ''
      chatExecutionDirtyRef.current = false
      if (chatExecutionFeedback) setChatExecutionFeedback(null)
      return
    }
    if (!chatExecutionDirtyRef.current) return
    if (saveChatExecutionPreferencesPending) return
    if (chatExecutionLastFailedKeyRef.current === currentKey) return
    if (chatExecutionLastAttemptKeyRef.current === currentKey) return

    chatExecutionLastAttemptKeyRef.current = currentKey
    void onSaveChatExecutionPreferences({
      agent_chat_model: normalizedChatModelInput || null,
      agent_chat_reasoning_effort: normalizedChatReasoningInput,
    })
      .then(() => {
        chatExecutionLastAttemptKeyRef.current = ''
        chatExecutionLastFailedKeyRef.current = ''
        setChatExecutionFeedback(null)
      })
      .catch((error) => {
        chatExecutionLastAttemptKeyRef.current = ''
        chatExecutionLastFailedKeyRef.current = currentKey
        const message = error instanceof Error ? error.message : 'Failed to save chat execution settings.'
        setChatExecutionFeedback({ tone: 'error', message })
      })
  }, [
    normalizedChatModelInput,
    normalizedChatReasoningInput,
    normalizedPersistedChatModel,
    normalizedPersistedChatReasoning,
    chatExecutionFeedback,
    onSaveChatExecutionPreferences,
    saveChatExecutionPreferencesPending,
  ])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleChatExecutionFocus = () => {
      setProfileTab('preferences')
      window.setTimeout(() => {
        scrollChatExecutionIntoView()
      }, 80)
    }

    window.addEventListener('ui:focus-chat-execution', handleChatExecutionFocus)

    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'chat_execution'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (!shouldScroll) {
      return () => {
        window.removeEventListener('ui:focus-chat-execution', handleChatExecutionFocus)
      }
    }

    const frameId = window.requestAnimationFrame(() => {
      handleChatExecutionFocus()
    })
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('ui:focus-chat-execution', handleChatExecutionFocus)
    }
  }, [scrollChatExecutionIntoView])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleCodexAuthFocus = () => {
      setProfileTab('security')
      window.setTimeout(() => {
        scrollCodexAuthIntoView()
      }, 80)
    }

    window.addEventListener('ui:focus-codex-auth', handleCodexAuthFocus)

    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'codex_auth'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (!shouldScroll) {
      return () => {
        window.removeEventListener('ui:focus-codex-auth', handleCodexAuthFocus)
      }
    }

    const frameId = window.requestAnimationFrame(() => {
      handleCodexAuthFocus()
    })
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('ui:focus-codex-auth', handleCodexAuthFocus)
    }
  }, [scrollCodexAuthIntoView])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleClaudeAuthFocus = () => {
      setProfileTab('security')
      window.setTimeout(() => {
        scrollClaudeAuthIntoView()
      }, 80)
    }

    window.addEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)

    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'claude_auth'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (!shouldScroll) {
      return () => {
        window.removeEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)
      }
    }

    const frameId = window.requestAnimationFrame(() => {
      handleClaudeAuthFocus()
    })
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)
    }
  }, [scrollClaudeAuthIntoView])

  const resetPasswordForm = React.useCallback(() => {
    setCurrentPasswordInput('')
    setNewPasswordInput('')
    setConfirmPasswordInput('')
  }, [])

  const resetFeedbackForm = React.useCallback(() => {
    setFeedbackTitleInput('')
    setFeedbackDescriptionInput('')
    setFeedbackTypeInput('general')
  }, [])

  const handleSubmitPasswordChange = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const currentPassword = String(currentPasswordInput || '').trim()
      const nextPassword = String(newPasswordInput || '').trim()
      const confirmedPassword = String(confirmPasswordInput || '').trim()
      if (!currentPassword) {
        setPasswordFeedback({ tone: 'error', message: 'Current password is required.' })
        return
      }
      if (nextPassword.length < 8) {
        setPasswordFeedback({ tone: 'error', message: 'New password must be at least 8 characters.' })
        return
      }
      if (nextPassword !== confirmedPassword) {
        setPasswordFeedback({ tone: 'error', message: 'Password confirmation does not match.' })
        return
      }
      if (currentPassword === nextPassword) {
        setPasswordFeedback({ tone: 'error', message: 'New password must be different from current password.' })
        return
      }
      try {
        await changePassword({
          current_password: currentPassword,
          new_password: nextPassword,
        })
        resetPasswordForm()
        setPasswordFeedback({ tone: 'success', message: 'Password changed successfully.' })
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to change password.'
        setPasswordFeedback({ tone: 'error', message })
      }
    },
    [changePassword, confirmPasswordInput, currentPasswordInput, newPasswordInput, resetPasswordForm]
  )

  const handleSubmitFeedback = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const title = String(feedbackTitleInput || '').trim()
      const description = String(feedbackDescriptionInput || '').trim()
      if (title.length < 3) {
        setFeedbackResult({ tone: 'error', message: 'Feedback title must be at least 3 characters.' })
        return
      }
      if (description.length < 5) {
        setFeedbackResult({ tone: 'error', message: 'Feedback description must be at least 5 characters.' })
        return
      }
      try {
        await submitFeedback({
          title,
          description,
          feedback_type: feedbackTypeInput,
          context: {
            tab: 'profile',
          },
        })
        resetFeedbackForm()
        setFeedbackResult({ tone: 'success', message: 'Feedback sent successfully.' })
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to send feedback.'
        setFeedbackResult({ tone: 'error', message })
      }
    },
    [feedbackDescriptionInput, feedbackTitleInput, feedbackTypeInput, resetFeedbackForm, submitFeedback]
  )

  const handleThemeCheckedChange = React.useCallback(
    (checked: boolean) => {
      const nextTheme = checked ? 'dark' : 'light'
      if (nextTheme !== theme) onToggleTheme()
    },
    [onToggleTheme, theme]
  )

  const copyInstallationId = React.useCallback(async () => {
    const value = String(license?.installation_id || '').trim()
    if (!value) return
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setInstallationCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(value)
      setInstallationCopyState('copied')
      window.setTimeout(() => setInstallationCopyState('idle'), 1400)
    } catch {
      setInstallationCopyState('error')
      window.setTimeout(() => setInstallationCopyState('idle'), 1800)
    }
  }, [license?.installation_id])

  const copyRuntimeSnapshot = React.useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setRuntimeCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(runtimeSnapshotText)
      setRuntimeCopyState('copied')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1400)
    } catch {
      setRuntimeCopyState('error')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1800)
    }
  }, [runtimeSnapshotText])

  const handleStartCodexDeviceAuth = React.useCallback(async (loginMethod: CodexAuthLoginMethod) => {
    try {
      await onStartCodexDeviceAuth(loginMethod)
      setCodexAuthFeedback(null)
      setCodexAuthDialogOpen(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start Codex sign-in.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onStartCodexDeviceAuth])

  const handleCancelCodexDeviceAuth = React.useCallback(async () => {
    try {
      await onCancelCodexDeviceAuth()
      setCodexAuthFeedback({ tone: 'success', message: 'Codex sign-in was cancelled.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel Codex sign-in.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onCancelCodexDeviceAuth])

  const handleSubmitCodexBrowserCallback = React.useCallback(async () => {
    const callbackUrl = codexAuthManualCallbackInput.trim()
    if (!callbackUrl) {
      setCodexAuthFeedback({ tone: 'error', message: 'Callback URL is required.' })
      return
    }
    const sessionId = String(codexAuthLoginSession?.id || '').trim()
    if (!sessionId) {
      setCodexAuthFeedback({ tone: 'error', message: 'Codex sign-in session is missing.' })
      return
    }
    try {
      await onSubmitCodexBrowserCallback({ sessionId, callbackUrl })
      setCodexAuthManualCallbackInput('')
      setCodexAuthFeedback({ tone: 'success', message: 'Callback URL submitted. Waiting for Codex to finish sign-in.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to submit Codex callback URL.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [codexAuthLoginSession?.id, codexAuthManualCallbackInput, onSubmitCodexBrowserCallback])

  const handleDeleteCodexAuthOverride = React.useCallback(async () => {
    try {
      await onDeleteCodexAuthOverride()
      setCodexAuthFeedback({ tone: 'success', message: 'Shared Codex authentication was removed.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove shared Codex authentication.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onDeleteCodexAuthOverride])

  const handleStartClaudeDeviceAuth = React.useCallback(async (loginMethod: ClaudeAuthLoginMethod) => {
    try {
      await onStartClaudeDeviceAuth(loginMethod)
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start Claude sign-in.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onStartClaudeDeviceAuth])

  const handleCancelClaudeDeviceAuth = React.useCallback(async () => {
    try {
      await onCancelClaudeDeviceAuth()
      setClaudeAuthFeedback({ tone: 'success', message: 'Claude sign-in was cancelled.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel Claude sign-in.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onCancelClaudeDeviceAuth])

  const handleSubmitClaudeDeviceAuthCode = React.useCallback(async () => {
    const code = claudeAuthManualCodeInput.trim()
    if (!code) {
      setClaudeAuthFeedback({ tone: 'error', message: 'Authentication code is required.' })
      return
    }
    try {
      const payload = await onSubmitClaudeDeviceAuthCode(code)
      setClaudeAuthManualCodeInput('')
      if (isFinalClaudeAuthStatus(payload)) {
        setClaudeAuthFeedback(null)
        setClaudeAuthDialogOpen(false)
        return
      }
      setClaudeAuthFeedback({ tone: 'success', message: 'Authentication code submitted. Waiting for Claude to finish sign-in.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to submit Claude authentication code.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [claudeAuthManualCodeInput, onSubmitClaudeDeviceAuthCode])

  const handleDeleteClaudeAuthOverride = React.useCallback(async () => {
    try {
      await onDeleteClaudeAuthOverride()
      setClaudeAuthFeedback({ tone: 'success', message: 'Shared Claude authentication was removed.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove shared Claude authentication.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onDeleteClaudeAuthOverride])

  React.useEffect(() => {
    if (
      canManageCodexAuth
      && !codexAuthHasSystemOverride
      && codexAuthLoginSession?.status === 'pending'
      && (codexAuthLoginSession.user_code || codexAuthLoginSession.verification_uri)
    ) {
      setCodexAuthDialogOpen(true)
      return
    }
    if (codexAuthLoginSession?.status === 'succeeded') {
      setCodexAuthDialogOpen(false)
    }
    if (codexAuthHasSystemOverride) {
      setCodexAuthFeedback(null)
      setCodexAuthDialogOpen(false)
    }
  }, [
    canManageCodexAuth,
    codexAuthHasSystemOverride,
    codexAuthLoginSession?.status,
    codexAuthLoginSession?.user_code,
    codexAuthLoginSession?.verification_uri,
  ])

  React.useEffect(() => {
    if (
      canManageClaudeAuth
      && !claudeAuthHasSystemOverride
      && claudeAuthLoginSession?.status === 'pending'
      && (claudeAuthLoginSession.user_code || claudeAuthLoginSession.verification_uri)
    ) {
      setClaudeAuthDialogOpen(true)
      return
    }
    if (claudeAuthLoginSession?.status === 'succeeded') {
      setClaudeAuthManualCodeInput('')
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(false)
    }
    if (claudeAuthHasSystemOverride) {
      setClaudeAuthManualCodeInput('')
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(false)
    }
  }, [
    canManageClaudeAuth,
    claudeAuthHasSystemOverride,
    claudeAuthLoginSession?.status,
    claudeAuthLoginSession?.user_code,
    claudeAuthLoginSession?.verification_uri,
  ])

  return (
    <Tooltip.Provider delayDuration={180}>
      <section className="card profile-panel">
        <div className="profile-panel-head">
          <div className="profile-panel-identity">
            <div className="profile-avatar" aria-hidden="true">
              <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
            </div>
            <div className="profile-head-copy">
              <h2>Profile</h2>
              <p className="meta">Personal preferences, account security, and feedback</p>
            </div>
          </div>
          <div className="profile-head-chips">
            <span className="status-chip profile-signin-chip">Signed in as @{userUsername}</span>
            <button
              className="button-secondary profile-action-button profile-head-logout"
              type="button"
              onClick={onLogout}
              title="Logout"
            >
              <Icon path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
              <span>Logout</span>
            </button>
          </div>
        </div>

        <Tabs.Root
          className="profile-tabs"
          value={profileTab}
          onValueChange={(nextValue) => {
            if (
              nextValue === 'preferences' ||
              nextValue === 'security' ||
              nextValue === 'feedback'
            ) {
              setProfileTab(nextValue)
            }
          }}
        >
          <Tabs.List className="profile-tabs-list" aria-label="Profile sections">
            <Tabs.Trigger className="profile-tab-trigger" value="preferences">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M3 6h18M3 12h18M3 18h18" />
              </span>
              <span>Preferences</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="security">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M12 2l7 4v6c0 5-3.5 9-7 10-3.5-1-7-5-7-10V6l7-4zM9 12h6M12 9v6" />
              </span>
              <span>Security</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="feedback">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M21 15a2 2 0 0 1-2 2H8l-5 5V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </span>
              <span>Feedback</span>
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content className="profile-tab-content" value="preferences">
            <div className="profile-pane-grid">
              <section className="profile-pane-card" aria-label="Appearance">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M12 3l8 4v5c0 6-5 9-8 9s-8-3-8-9V7l8-4zM8 12h8M12 8v8" />
                    </span>
                    <span>Appearance</span>
                  </h3>
                  <span className="status-chip">Theme</span>
                </div>
                <div className="profile-theme-row">
                  <label className="profile-switch-label" htmlFor="profile-theme-switch">Dark mode</label>
                  <div className="profile-theme-controls">
                    <Tooltip.Root>
                      <Tooltip.Trigger asChild>
                        <Switch.Root
                          id="profile-theme-switch"
                          className="profile-theme-switch"
                          checked={theme === 'dark'}
                          onCheckedChange={handleThemeCheckedChange}
                          aria-label={`Switch to ${nextTheme} mode`}
                        >
                          <Switch.Thumb className="profile-theme-switch-thumb" />
                        </Switch.Root>
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                          Toggle between light and dark themes
                          <Tooltip.Arrow className="header-tooltip-arrow" />
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
                    <button className="button-secondary profile-action-button" type="button" onClick={onToggleTheme}>
                      <Icon path="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79" />
                      <span>{`Switch to ${nextTheme}`}</span>
                    </button>
                  </div>
                </div>
                <p className="meta">Current mode: {theme}.</p>
              </section>

              <section className="profile-pane-card" aria-label="Voice language" id="profile-voice-language" ref={voiceFactRef}>
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3M6 11a6 6 0 0 0 12 0M12 17v4M8 21h8" />
                    </span>
                    <span>Voice language</span>
                  </h3>
                  <span className="status-chip">Speech</span>
                </div>
                <Select.Root value={speechLang} onValueChange={onChangeSpeechLang}>
                  <Select.Trigger
                    ref={voiceSelectTriggerRef}
                    className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger"
                    aria-label="Voice recognition language"
                  >
                    <Select.Value />
                    <Select.Icon asChild>
                      <span className="quickadd-project-trigger-icon" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Select.Icon>
                  </Select.Trigger>
                  <Select.Portal>
                    <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                      <Select.Viewport className="quickadd-project-viewport">
                        {VOICE_LANG_OPTIONS.map((option) => (
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
                <p className="meta">Selected: {selectedVoiceLabel}</p>
              </section>

              <section className="profile-pane-card" aria-label="Chat execution" id="profile-chat-execution" ref={chatExecutionFactRef}>
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M4 5h16v10H4zM7 19h10M12 15v4M8 9h8M8 12h5" />
                    </span>
                    <span>Chat execution</span>
                  </h3>
                  <span className="status-chip">{activeExecutionProviderLabel}</span>
                </div>
                <div className="profile-chat-execution-grid">
                <label className="field-control profile-chat-execution-field profile-chat-execution-field-model">
                  <span className="field-label">Model</span>
                  <Select.Root
                    value={chatModelInput || CHAT_MODEL_DEFAULT_VALUE}
                    onValueChange={(value) => {
                      chatExecutionDirtyRef.current = true
                      setChatModelInput(value === CHAT_MODEL_DEFAULT_VALUE ? '' : value)
                      setChatExecutionFeedback(null)
                    }}
                  >
                    <Select.Trigger
                      ref={chatExecutionModelTriggerRef}
                      className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger profile-chat-model-trigger"
                      aria-label="Chat execution model"
                    >
                      <Select.Value />
                      <Select.Icon asChild>
                        <span className="quickadd-project-trigger-icon" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Select.Icon>
                    </Select.Trigger>
                    <Select.Portal>
                      <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                        <Select.Viewport className="quickadd-project-viewport">
                          <Select.Item value={CHAT_MODEL_DEFAULT_VALUE} className="quickadd-project-item">
                            <Select.ItemText>
                              {agentChatDefaultModel
                                ? `System default (${formatAgentExecutionModelLabel(agentChatDefaultModel)})`
                                : 'System default'}
                            </Select.ItemText>
                            <Select.ItemIndicator className="quickadd-project-item-indicator">
                              <Icon path="M5 13l4 4L19 7" />
                            </Select.ItemIndicator>
                          </Select.Item>
                          {chatModelOptions.map((model) => (
                            <Select.Item key={model} value={model} className="quickadd-project-item">
                              <Select.ItemText>{formatAgentExecutionModelLabel(model)}</Select.ItemText>
                              <Select.ItemIndicator className="quickadd-project-item-indicator">
                                <Icon path="M5 13l4 4L19 7" />
                              </Select.ItemIndicator>
                            </Select.Item>
                          ))}
                        </Select.Viewport>
                      </Select.Content>
                    </Select.Portal>
                  </Select.Root>
                </label>
                <label className="field-control profile-chat-execution-field profile-chat-execution-field-reasoning">
                  <span className="field-label">Reasoning</span>
                  <Select.Root
                    value={normalizeChatReasoningEffort(chatReasoningInput)}
                    onValueChange={(value) => {
                      chatExecutionDirtyRef.current = true
                      setChatReasoningInput(normalizeChatReasoningEffort(value))
                      setChatExecutionFeedback(null)
                    }}
                  >
                    <Select.Trigger
                      className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger profile-chat-reasoning-trigger"
                      aria-label="Chat execution reasoning level"
                    >
                      <Select.Value />
                      <Select.Icon asChild>
                        <span className="quickadd-project-trigger-icon" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Select.Icon>
                    </Select.Trigger>
                    <Select.Portal>
                      <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                        <Select.Viewport className="quickadd-project-viewport">
                          {chatReasoningOptions.map((option) => (
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
                </label>
                </div>
                <div className="profile-chat-execution-status">
                  {chatExecutionStatusLabel ? (
                    <span className={`status-chip ${chatExecutionFeedback ? 'is-error' : ''}`.trim()}>{chatExecutionStatusLabel}</span>
                  ) : null}
                  <p className="meta">
                    Active provider: {activeExecutionProviderLabel} · Active model: {activeExecutionModelLabel} · Reasoning: {selectedChatReasoningLabel}
                  </p>
                  <p className="meta">This preference controls the provider and model used for interactive agent chat in this workspace session.</p>
                </div>
                {chatExecutionFeedback ? (
                  <div className="notice notice-error">
                    {chatExecutionFeedback.message}
                  </div>
                ) : null}
              </section>

            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="security">
            <div className="profile-pane-grid">
              <section className="profile-pane-card profile-password" aria-label="Password settings">
                <Accordion.Root className="profile-accordion" type="single" collapsible defaultValue="change-password">
                  <Accordion.Item className="profile-accordion-item" value="change-password">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Change password</span>
                          <span className="profile-accordion-meta">Current password required · minimum 8 chars</span>
                        </span>
                        <span className="status-chip">Security</span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <form className="profile-bug-form" onSubmit={handleSubmitPasswordChange}>
                        <label className="field-control">
                          <span className="field-label">Current password</span>
                          <input
                            type="password"
                            value={currentPasswordInput}
                            onChange={(event) => setCurrentPasswordInput(event.target.value)}
                            autoComplete="current-password"
                            placeholder="Current password"
                          />
                        </label>
                        <label className="field-control">
                          <span className="field-label">New password</span>
                          <input
                            type="password"
                            value={newPasswordInput}
                            onChange={(event) => setNewPasswordInput(event.target.value)}
                            autoComplete="new-password"
                            placeholder="New password"
                          />
                        </label>
                        <label className="field-control">
                          <span className="field-label">Confirm new password</span>
                          <input
                            type="password"
                            value={confirmPasswordInput}
                            onChange={(event) => setConfirmPasswordInput(event.target.value)}
                            autoComplete="new-password"
                            placeholder="Confirm new password"
                          />
                        </label>
                        <div className="row wrap profile-actions">
                          <button
                            className="primary"
                            type="submit"
                            disabled={
                              passwordChangePending ||
                              !currentPasswordInput.trim() ||
                              !newPasswordInput.trim() ||
                              !confirmPasswordInput.trim()
                            }
                          >
                            {passwordChangePending ? 'Saving...' : 'Save new password'}
                          </button>
                          <button
                            className="button-secondary"
                            type="button"
                            onClick={resetPasswordForm}
                            disabled={passwordChangePending}
                          >
                            Reset
                          </button>
                        </div>
                      </form>
                      {passwordFeedback ? (
                        <div className={`notice ${passwordFeedback.tone === 'error' ? 'notice-error' : ''}`.trim()}>
                          {passwordFeedback.message}
                        </div>
                      ) : null}
                    </Accordion.Content>
                  </Accordion.Item>
                </Accordion.Root>
              </section>
            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="feedback">
            <div className="profile-pane-grid">
              <section className="profile-pane-card profile-bug-report" aria-label="Feedback">
                <Accordion.Root className="profile-accordion" type="single" collapsible defaultValue="submit-feedback">
                  <Accordion.Item className="profile-accordion-item" value="submit-feedback">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Leave feedback</span>
                          <span className="profile-accordion-meta">Product feedback routed to support pipeline</span>
                        </span>
                        <span className="status-chip">Support</span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <form className="profile-bug-form" onSubmit={handleSubmitFeedback}>
                        <label className="field-control">
                          <span className="field-label">Topic</span>
                          <input
                            value={feedbackTitleInput}
                            onChange={(event) => setFeedbackTitleInput(event.target.value)}
                            placeholder="Short feedback title"
                          />
                        </label>
                        <label className="field-control">
                          <span className="field-label">Type</span>
                          <Select.Root
                            value={feedbackTypeInput}
                            onValueChange={(value: 'general' | 'feature_request' | 'question' | 'other') => setFeedbackTypeInput(value)}
                          >
                            <Select.Trigger
                              className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger"
                              aria-label="Feedback type"
                            >
                              <Select.Value />
                              <Select.Icon asChild>
                                <span className="quickadd-project-trigger-icon" aria-hidden="true">
                                  <Icon path="M6 9l6 6 6-6" />
                                </span>
                              </Select.Icon>
                            </Select.Trigger>
                            <Select.Portal>
                              <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                                <Select.Viewport className="quickadd-project-viewport">
                                  {PROFILE_FEEDBACK_TYPE_OPTIONS.map((option) => (
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
                          <span className="meta">{selectedFeedbackTypeLabel}</span>
                        </label>
                        <label className="field-control">
                          <span className="field-label">Details</span>
                          <textarea
                            rows={5}
                            value={feedbackDescriptionInput}
                            onChange={(event) => setFeedbackDescriptionInput(event.target.value)}
                            placeholder="Describe your feedback"
                          />
                        </label>
                        <div className="row wrap profile-actions">
                          <button
                            className="primary"
                            type="submit"
                            disabled={feedbackSubmitting || !feedbackTitleInput.trim() || !feedbackDescriptionInput.trim()}
                          >
                            {feedbackSubmitting ? 'Sending...' : 'Send feedback'}
                          </button>
                          <button
                            className="button-secondary"
                            type="button"
                            onClick={resetFeedbackForm}
                            disabled={feedbackSubmitting}
                          >
                            Reset
                          </button>
                        </div>
                      </form>
                      {feedbackResult ? (
                        <div className={`notice ${feedbackResult.tone === 'error' ? 'notice-error' : ''}`.trim()}>
                          {feedbackResult.message}
                        </div>
                      ) : null}
                    </Accordion.Content>
                  </Accordion.Item>
                </Accordion.Root>
              </section>

              <section className="profile-pane-card" aria-label="GitHub issues">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M9 3h6l1 2h3v4h-2l-1 8H8L7 9H5V5h3zM10 11h4M10 14h4" />
                    </span>
                    <span>Bug reports</span>
                  </h3>
                  <span className="status-chip">GitHub</span>
                </div>
                <p className="meta">For reproducible defects and stack traces, open an issue in the project repository.</p>
                <div className="row wrap profile-actions" style={{ marginTop: 4 }}>
                  <a
                    className="primary"
                    href={GITHUB_ISSUES_URL}
                    target="_blank"
                    rel="noreferrer"
                    style={{ textDecoration: 'none' }}
                  >
                    Open GitHub Issues
                  </a>
                </div>
              </section>
            </div>
          </Tabs.Content>

        </Tabs.Root>
      </section>
    </Tooltip.Provider>
  )
}

export function WorkspacePanel({
  workspaceName,
  workspaceRole,
  canManageUsers,
  doctorStatus,
  architectureInventorySummary,
  doctorLoading,
  doctorError,
  onSeedDoctor,
  seedDoctorPending,
  onRunDoctor,
  runDoctorPending,
  onResetDoctor,
  resetDoctorPending,
  workspaceUsersCount,
  workspaceSkillsCount,
  workspaceUsersContent,
  workspaceSkillsContent,
  frontendVersion,
  backendVersion,
  backendBuild,
  deployedAtUtc,
  codexAuthStatus,
  codexAuthLoading,
  canManageCodexAuth,
  opencodeAuthStatus,
  opencodeAuthLoading,
  claudeAuthStatus,
  claudeAuthLoading,
  canManageClaudeAuth,
  license,
  licenseLoading,
  licenseError,
  onStartCodexDeviceAuth,
  startCodexDeviceAuthPending,
  onCancelCodexDeviceAuth,
  cancelCodexDeviceAuthPending,
  onSubmitCodexBrowserCallback,
  submitCodexBrowserCallbackPending,
  onDeleteCodexAuthOverride,
  deleteCodexAuthOverridePending,
  onStartClaudeDeviceAuth,
  startClaudeDeviceAuthPending,
  onCancelClaudeDeviceAuth,
  cancelClaudeDeviceAuthPending,
  onSubmitClaudeDeviceAuthCode,
  submitClaudeDeviceAuthCodePending,
  onDeleteClaudeAuthOverride,
  deleteClaudeAuthOverridePending,
}: {
  workspaceName: string
  workspaceRole: string
  canManageUsers: boolean
  doctorStatus: WorkspaceDoctorStatus | null
  architectureInventorySummary: ArchitectureInventorySummary | null
  doctorLoading: boolean
  doctorError: string | null
  onSeedDoctor: () => Promise<unknown>
  seedDoctorPending: boolean
  onRunDoctor: () => Promise<unknown>
  runDoctorPending: boolean
  onResetDoctor: () => Promise<unknown>
  resetDoctorPending: boolean
  workspaceUsersCount: number
  workspaceSkillsCount: number
  workspaceUsersContent?: React.ReactNode
  workspaceSkillsContent?: React.ReactNode
  frontendVersion: string
  backendVersion: string
  backendBuild: string | null
  deployedAtUtc: string | null
  codexAuthStatus: AgentAuthStatus | null
  codexAuthLoading: boolean
  canManageCodexAuth: boolean
  opencodeAuthStatus: AgentAuthStatus | null
  opencodeAuthLoading: boolean
  claudeAuthStatus: AgentAuthStatus | null
  claudeAuthLoading: boolean
  canManageClaudeAuth: boolean
  license: LicenseStatus | null | undefined
  licenseLoading: boolean
  licenseError: string | null
  onStartCodexDeviceAuth: (loginMethod: CodexAuthLoginMethod) => Promise<unknown>
  startCodexDeviceAuthPending: boolean
  onCancelCodexDeviceAuth: () => Promise<unknown>
  cancelCodexDeviceAuthPending: boolean
  onSubmitCodexBrowserCallback: (payload: { sessionId: string; callbackUrl: string }) => Promise<unknown>
  submitCodexBrowserCallbackPending: boolean
  onDeleteCodexAuthOverride: () => Promise<unknown>
  deleteCodexAuthOverridePending: boolean
  onStartClaudeDeviceAuth: (loginMethod: ClaudeAuthLoginMethod) => Promise<unknown>
  startClaudeDeviceAuthPending: boolean
  onCancelClaudeDeviceAuth: () => Promise<unknown>
  cancelClaudeDeviceAuthPending: boolean
  onSubmitClaudeDeviceAuthCode: (code: string) => Promise<AgentAuthStatus>
  submitClaudeDeviceAuthCodePending: boolean
  onDeleteClaudeAuthOverride: () => Promise<unknown>
  deleteClaudeAuthOverridePending: boolean
}) {
  const formatDateTime = (value: string | null): string => {
    if (!value) return 'n/a'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  }
  const formatLabel = (value: string): string => {
    const normalized = String(value || '').trim().replace(/_/g, ' ')
    if (!normalized) return 'n/a'
    return normalized
      .split(/\s+/)
      .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
      .join(' ')
  }
  const licenseStatus = String(license?.status || '').trim().toLowerCase() || 'unknown'
  const licenseStatusLabel = licenseStatus.charAt(0).toUpperCase() + licenseStatus.slice(1)
  const licenseMetadata = (license?.metadata && typeof license.metadata === 'object'
    ? (license.metadata as Record<string, unknown>)
    : {}) as Record<string, unknown>
  const subscriptionStatus = String(licenseMetadata.subscription_status ?? '').trim().toLowerCase()
  const subscriptionValidUntil = String(licenseMetadata.subscription_valid_until ?? '').trim() || null
  const publicBetaEnabled = licenseMetadata.public_beta === true
  const publicBetaFreeUntil = String(licenseMetadata.public_beta_free_until ?? '').trim() || null
  const entitlementSource = publicBetaEnabled
    ? `Public beta until ${formatDateTime(publicBetaFreeUntil)}`
    : subscriptionStatus
      ? `Subscription (${formatLabel(subscriptionStatus)})`
      : 'Trial fallback'
  const showTrialWindow = licenseStatus === 'trial' || licenseStatus === 'grace'
  const [workspaceTab, setWorkspaceTab] = React.useState<'connections' | 'runtime' | 'doctor' | 'users' | 'skills' | 'license'>('connections')
  const [installationCopyState, setInstallationCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const [runtimeCopyState, setRuntimeCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const codexAuthFactRef = React.useRef<HTMLDivElement | null>(null)
  const codexAuthPrimaryButtonRef = React.useRef<HTMLButtonElement | null>(null)
  const claudeAuthFactRef = React.useRef<HTMLDivElement | null>(null)
  const claudeAuthPrimaryButtonRef = React.useRef<HTMLButtonElement | null>(null)
  const [codexAuthDialogOpen, setCodexAuthDialogOpen] = React.useState(false)
  const [codexAuthFeedback, setCodexAuthFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [codexAuthManualCallbackInput, setCodexAuthManualCallbackInput] = React.useState('')
  const [claudeAuthDialogOpen, setClaudeAuthDialogOpen] = React.useState(false)
  const [claudeAuthFeedback, setClaudeAuthFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [claudeAuthManualCodeInput, setClaudeAuthManualCodeInput] = React.useState('')
  const codexAuthSource = String(codexAuthStatus?.effective_source || '').trim().toLowerCase()
  const codexAuthLoginSession = codexAuthStatus?.login_session ?? null
  const codexAuthStatusLabel = authSourceLabel(
    'codex',
    codexAuthStatus?.effective_source,
    codexAuthStatus?.target_actor_username
  )
  const codexAuthSessionStatusLabel = (() => {
    if (codexAuthSource === 'system_override') return 'Connected'
    const status = String(codexAuthLoginSession?.status || '').trim().toLowerCase()
    if (status === 'pending') return 'Awaiting browser confirmation'
    if (status === 'succeeded') return 'Connected'
    if (status === 'failed') return 'Sign-in failed'
    if (status === 'cancelled') return 'Sign-in cancelled'
    return null
  })()
  const codexAuthLoginMethod = normalizeCodexAuthLoginMethod(
    codexAuthLoginSession?.login_method ?? codexAuthStatus?.selected_login_method
  )
  const codexAuthLoginMethodLabel = formatCodexAuthLoginMethodLabel(codexAuthLoginMethod)
  const codexAuthHasSystemOverride = codexAuthSource === 'system_override'
  const codexAuthHasPendingSignIn = String(codexAuthLoginSession?.status || '').trim().toLowerCase() === 'pending'
  const codexAuthCanConnect = canManageCodexAuth && !startCodexDeviceAuthPending && !cancelCodexDeviceAuthPending
  const codexAuthCanSubmitBrowserCallback = canManageCodexAuth
    && codexAuthHasPendingSignIn
    && codexAuthLoginMethod === 'browser'
    && !submitCodexBrowserCallbackPending
    && codexAuthManualCallbackInput.trim().length > 0
  const codexAuthCanRemoveOverride = canManageCodexAuth
    && Boolean(codexAuthStatus?.override_available)
    && !deleteCodexAuthOverridePending
  const opencodeAuthSource = String(opencodeAuthStatus?.effective_source || '').trim().toLowerCase()
  const opencodeAuthStatusLabel = authSourceLabel(
    'opencode',
    opencodeAuthStatus?.effective_source,
    opencodeAuthStatus?.target_actor_username
  )
  const claudeAuthSource = String(claudeAuthStatus?.effective_source || '').trim().toLowerCase()
  const claudeAuthLoginSession = claudeAuthStatus?.login_session ?? null
  const claudeAuthStatusLabel = authSourceLabel(
    'claude',
    claudeAuthStatus?.effective_source,
    claudeAuthStatus?.target_actor_username
  )
  const claudeAuthSessionStatusLabel = (() => {
    if (claudeAuthSource === 'system_override') return 'Connected'
    const status = String(claudeAuthLoginSession?.status || '').trim().toLowerCase()
    if (status === 'pending') return 'Awaiting browser confirmation'
    if (status === 'succeeded') return 'Connected'
    if (status === 'failed') return 'Sign-in failed'
    if (status === 'cancelled') return 'Sign-in cancelled'
    return null
  })()
  const claudeAuthLoginMethod = normalizeClaudeAuthLoginMethod(
    claudeAuthLoginSession?.login_method ?? claudeAuthStatus?.selected_login_method
  )
  const claudeAuthLoginMethodLabel = formatClaudeAuthLoginMethodLabel(claudeAuthLoginMethod)
  const claudeAuthHasSystemOverride = claudeAuthSource === 'system_override'
  const claudeAuthHasPendingSignIn = (
    String(claudeAuthLoginSession?.status || '').trim().toLowerCase() === 'pending'
    && !claudeAuthHasSystemOverride
  )
  const claudeAuthCanConnect = canManageClaudeAuth && !startClaudeDeviceAuthPending && !cancelClaudeDeviceAuthPending
  const claudeAuthCanSubmitCode = canManageClaudeAuth
    && claudeAuthHasPendingSignIn
    && !submitClaudeDeviceAuthCodePending
    && claudeAuthManualCodeInput.trim().length > 0
  const claudeAuthCanRemoveOverride = canManageClaudeAuth
    && Boolean(claudeAuthStatus?.override_available)
    && !deleteClaudeAuthOverridePending
  const runtimeSnapshotText = React.useMemo(() => {
    return [
      `Workspace: ${workspaceName || 'n/a'}`,
      `Workspace role: ${workspaceRole || 'n/a'}`,
      `Frontend version: ${frontendVersion || 'n/a'}`,
      `Backend version: ${backendVersion || 'n/a'}`,
      `Backend build: ${backendBuild || 'n/a'}`,
      `Deployed UTC: ${deployedAtUtc || 'unknown'}`,
    ].join('\n')
  }, [backendBuild, backendVersion, deployedAtUtc, frontendVersion, workspaceName, workspaceRole])
  const codexAuthSummaryPills: WorkspaceAuthSummaryPill[] = [
    { label: 'Host auth', value: codexAuthStatus?.host_auth_available ? 'Available' : 'Missing' },
    { label: 'Shared override', value: codexAuthStatus?.override_available ? 'Active' : 'Not set' },
    { label: 'Scope', value: String(codexAuthStatus?.scope || 'system').trim() || 'system' },
  ]
  const opencodeAuthSummaryPills: WorkspaceAuthSummaryPill[] = [
    { label: 'Runtime', value: opencodeAuthSource === 'runtime_builtin' ? 'Built-in' : 'Unavailable' },
    { label: 'Host auth', value: opencodeAuthStatus?.host_auth_available ? 'Available' : 'Not required' },
    { label: 'Shared override', value: opencodeAuthStatus?.override_available ? 'Active' : 'Not required' },
  ]
  const claudeAuthSummaryPills: WorkspaceAuthSummaryPill[] = [
    { label: 'Host auth', value: claudeAuthStatus?.host_auth_available ? 'Available' : 'Missing' },
    { label: 'Shared override', value: claudeAuthStatus?.override_available ? 'Active' : 'Not set' },
    { label: 'Sign-in', value: claudeAuthLoginMethodLabel },
  ]
  const hasWorkspaceAdminTabs = canManageUsers
  const copyInstallationId = React.useCallback(async () => {
    const value = String(license?.installation_id || '').trim()
    if (!value) return
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setInstallationCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(value)
      setInstallationCopyState('copied')
      window.setTimeout(() => setInstallationCopyState('idle'), 1400)
    } catch {
      setInstallationCopyState('error')
      window.setTimeout(() => setInstallationCopyState('idle'), 1800)
    }
  }, [license?.installation_id])
  const copyRuntimeSnapshot = React.useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setRuntimeCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(runtimeSnapshotText)
      setRuntimeCopyState('copied')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1400)
    } catch {
      setRuntimeCopyState('error')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1800)
    }
  }, [runtimeSnapshotText])
  const handleStartCodexDeviceAuth = React.useCallback(async (loginMethod: CodexAuthLoginMethod) => {
    try {
      await onStartCodexDeviceAuth(loginMethod)
      setCodexAuthFeedback(null)
      setCodexAuthDialogOpen(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start Codex sign-in.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onStartCodexDeviceAuth])
  const handleCancelCodexDeviceAuth = React.useCallback(async () => {
    try {
      await onCancelCodexDeviceAuth()
      setCodexAuthFeedback({ tone: 'success', message: 'Codex sign-in was cancelled.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel Codex sign-in.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onCancelCodexDeviceAuth])
  const handleSubmitCodexBrowserCallback = React.useCallback(async () => {
    const callbackUrl = codexAuthManualCallbackInput.trim()
    if (!callbackUrl) {
      setCodexAuthFeedback({ tone: 'error', message: 'Callback URL is required.' })
      return
    }
    const sessionId = String(codexAuthLoginSession?.id || '').trim()
    if (!sessionId) {
      setCodexAuthFeedback({ tone: 'error', message: 'Codex sign-in session is missing.' })
      return
    }
    try {
      await onSubmitCodexBrowserCallback({ sessionId, callbackUrl })
      setCodexAuthManualCallbackInput('')
      setCodexAuthFeedback({ tone: 'success', message: 'Callback URL submitted. Waiting for Codex to finish sign-in.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to submit Codex callback URL.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [codexAuthLoginSession?.id, codexAuthManualCallbackInput, onSubmitCodexBrowserCallback])
  const handleDeleteCodexAuthOverride = React.useCallback(async () => {
    try {
      await onDeleteCodexAuthOverride()
      setCodexAuthFeedback({ tone: 'success', message: 'Shared Codex authentication was removed.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove shared Codex authentication.'
      setCodexAuthFeedback({ tone: 'error', message })
    }
  }, [onDeleteCodexAuthOverride])
  const handleStartClaudeDeviceAuth = React.useCallback(async (loginMethod: ClaudeAuthLoginMethod) => {
    try {
      await onStartClaudeDeviceAuth(loginMethod)
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to start Claude sign-in.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onStartClaudeDeviceAuth])
  const handleCancelClaudeDeviceAuth = React.useCallback(async () => {
    try {
      await onCancelClaudeDeviceAuth()
      setClaudeAuthFeedback({ tone: 'success', message: 'Claude sign-in was cancelled.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to cancel Claude sign-in.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onCancelClaudeDeviceAuth])
  const handleSubmitClaudeDeviceAuthCode = React.useCallback(async () => {
    const code = claudeAuthManualCodeInput.trim()
    if (!code) {
      setClaudeAuthFeedback({ tone: 'error', message: 'Authentication code is required.' })
      return
    }
    try {
      const payload = await onSubmitClaudeDeviceAuthCode(code)
      setClaudeAuthManualCodeInput('')
      if (isFinalClaudeAuthStatus(payload)) {
        setClaudeAuthFeedback(null)
        setClaudeAuthDialogOpen(false)
        return
      }
      setClaudeAuthFeedback({ tone: 'success', message: 'Authentication code submitted. Waiting for Claude to finish sign-in.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to submit Claude authentication code.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [claudeAuthManualCodeInput, onSubmitClaudeDeviceAuthCode])
  const handleDeleteClaudeAuthOverride = React.useCallback(async () => {
    try {
      await onDeleteClaudeAuthOverride()
      setClaudeAuthFeedback({ tone: 'success', message: 'Shared Claude authentication was removed.' })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to remove shared Claude authentication.'
      setClaudeAuthFeedback({ tone: 'error', message })
    }
  }, [onDeleteClaudeAuthOverride])
  const scrollCodexAuthIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const scrollNearestContainer = () => {
      const target = codexAuthFactRef.current
      if (!target) return
      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
    }
    const focusPrimaryAction = () => {
      try {
        codexAuthPrimaryButtonRef.current?.focus({ preventScroll: true })
      } catch {
        codexAuthPrimaryButtonRef.current?.focus()
      }
    }
    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(focusPrimaryAction, 220)
  }, [])
  const scrollClaudeAuthIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const scrollNearestContainer = () => {
      const target = claudeAuthFactRef.current
      if (!target) return
      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
    }
    const focusPrimaryAction = () => {
      try {
        claudeAuthPrimaryButtonRef.current?.focus({ preventScroll: true })
      } catch {
        claudeAuthPrimaryButtonRef.current?.focus()
      }
    }
    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(focusPrimaryAction, 220)
  }, [])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleCodexAuthFocus = () => {
      setWorkspaceTab('connections')
      window.setTimeout(() => {
        scrollCodexAuthIntoView()
      }, 80)
    }
    window.addEventListener('ui:focus-codex-auth', handleCodexAuthFocus)
    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'codex_auth'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (shouldScroll) {
      const frameId = window.requestAnimationFrame(() => {
        handleCodexAuthFocus()
      })
      return () => {
        window.cancelAnimationFrame(frameId)
        window.removeEventListener('ui:focus-codex-auth', handleCodexAuthFocus)
      }
    }
    return () => {
      window.removeEventListener('ui:focus-codex-auth', handleCodexAuthFocus)
    }
  }, [scrollCodexAuthIntoView])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleClaudeAuthFocus = () => {
      setWorkspaceTab('connections')
      window.setTimeout(() => {
        scrollClaudeAuthIntoView()
      }, 80)
    }
    window.addEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)
    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'claude_auth'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (shouldScroll) {
      const frameId = window.requestAnimationFrame(() => {
        handleClaudeAuthFocus()
      })
      return () => {
        window.cancelAnimationFrame(frameId)
        window.removeEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)
      }
    }
    return () => {
      window.removeEventListener('ui:focus-claude-auth', handleClaudeAuthFocus)
    }
  }, [scrollClaudeAuthIntoView])

  React.useEffect(() => {
    if (
      canManageCodexAuth
      && !codexAuthHasSystemOverride
      && codexAuthLoginSession?.status === 'pending'
      && (codexAuthLoginSession.user_code || codexAuthLoginSession.verification_uri)
    ) {
      setCodexAuthDialogOpen(true)
      return
    }
    if (codexAuthLoginSession?.status === 'succeeded') {
      setCodexAuthDialogOpen(false)
    }
    if (codexAuthHasSystemOverride) {
      setCodexAuthFeedback(null)
      setCodexAuthDialogOpen(false)
    }
  }, [
    canManageCodexAuth,
    codexAuthHasSystemOverride,
    codexAuthLoginSession?.status,
    codexAuthLoginSession?.user_code,
    codexAuthLoginSession?.verification_uri,
  ])

  React.useEffect(() => {
    if (
      canManageClaudeAuth
      && !claudeAuthHasSystemOverride
      && claudeAuthLoginSession?.status === 'pending'
      && (claudeAuthLoginSession.user_code || claudeAuthLoginSession.verification_uri)
    ) {
      setClaudeAuthDialogOpen(true)
      return
    }
    if (claudeAuthLoginSession?.status === 'succeeded') {
      setClaudeAuthManualCodeInput('')
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(false)
    }
    if (claudeAuthHasSystemOverride) {
      setClaudeAuthManualCodeInput('')
      setClaudeAuthFeedback(null)
      setClaudeAuthDialogOpen(false)
    }
  }, [
    canManageClaudeAuth,
    claudeAuthHasSystemOverride,
    claudeAuthLoginSession?.status,
    claudeAuthLoginSession?.user_code,
    claudeAuthLoginSession?.verification_uri,
  ])

  return (
    <Tooltip.Provider delayDuration={180}>
      <section className="card profile-panel workspace-panel">
        <div className="profile-panel-head">
          <div className="profile-panel-identity">
            <div className="profile-avatar" aria-hidden="true">
              <Icon path="M4 5h16v12H4zM7 8h10M7 12h7M10 20h4M12 17v3" />
            </div>
            <div className="profile-head-copy">
              <h2>Workspace</h2>
              <p className="meta">{workspaceName || 'Current workspace'} shared connections and runtime settings</p>
            </div>
          </div>
          <div className="profile-head-chips">
            <span className="status-chip">{workspaceRole || 'Member'}</span>
            <span className="status-chip">{licenseStatusLabel}</span>
            <span className="status-chip">{canManageCodexAuth || canManageClaudeAuth ? 'Admin access' : 'Read-only'}</span>
          </div>
        </div>

        <Tabs.Root
          className="profile-tabs"
          value={workspaceTab}
          onValueChange={(nextValue) => {
            if (
              nextValue === 'connections'
              || nextValue === 'runtime'
              || nextValue === 'doctor'
              || nextValue === 'users'
              || nextValue === 'skills'
              || nextValue === 'license'
            ) {
              setWorkspaceTab(nextValue)
            }
          }}
        >
          <Tabs.List className="profile-tabs-list" aria-label="Workspace sections">
            <Tabs.Trigger className="profile-tab-trigger" value="connections">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M7 7h10v4H7zM5 5h14v8H5zM8 15h8M10 19h4" />
              </span>
              <span>Connections</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="runtime">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M4 4h16v12H4zM10 20h4M12 16v4" />
              </span>
              <span>Runtime</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="doctor" data-tour-id="workspace-tab-doctor">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
              </span>
              <span>Doctor</span>
            </Tabs.Trigger>
            {hasWorkspaceAdminTabs ? (
              <Tabs.Trigger className="profile-tab-trigger" value="users">
                <span className="profile-tab-trigger-icon" aria-hidden="true">
                  <Icon path="M16 11c1.66 0 3-1.57 3-3.5S17.66 4 16 4s-3 1.57-3 3.5 1.34 3.5 3 3.5M8 11c1.66 0 3-1.57 3-3.5S9.66 4 8 4 5 5.57 5 7.5 6.34 11 8 11M8 13c-2.67 0-8 1.34-8 4v3h10v-3c0-1.53.82-2.75 2.05-3.73C10.72 13.09 9.32 13 8 13M16 13c-.26 0-.54.02-.83.05 1.43 1 2.33 2.39 2.33 3.95v3H24v-3c0-2.66-5.33-4-8-4" />
                </span>
                <span>Users</span>
                <span className="status-chip admin-tab-count">{workspaceUsersCount}</span>
              </Tabs.Trigger>
            ) : null}
            {hasWorkspaceAdminTabs ? (
              <Tabs.Trigger className="profile-tab-trigger" value="skills">
                <span className="profile-tab-trigger-icon" aria-hidden="true">
                  <Icon path="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 7H20M6.5 7A2.5 2.5 0 0 1 4 9.5v10" />
                </span>
                <span>Skills</span>
                <span className="status-chip admin-tab-count">{workspaceSkillsCount}</span>
              </Tabs.Trigger>
            ) : null}
            <Tabs.Trigger className="profile-tab-trigger" value="license">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
              </span>
              <span>License</span>
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content className="profile-tab-content" value="connections">
            <div className="profile-pane-grid profile-workspace-grid">
              <section className="profile-pane-card workspace-overview-card" aria-label="Workspace overview">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M4 6h16M4 12h16M4 18h10" />
                    </span>
                    <span>Workspace overview</span>
                  </h3>
                  <span className="status-chip">{workspaceRole || 'Member'}</span>
                </div>
                <dl className="profile-facts">
                  <div className="profile-fact">
                    <dt>Workspace</dt>
                    <dd>{workspaceName || 'n/a'}</dd>
                  </div>
                  <div className="profile-fact">
                    <dt>Your role</dt>
                    <dd>{workspaceRole || 'n/a'}</dd>
                  </div>
                  <div className="profile-fact">
                    <dt>Shared auth access</dt>
                    <dd>{canManageCodexAuth || canManageClaudeAuth ? 'Can manage' : 'Read only'}</dd>
                  </div>
                  <div className="profile-fact">
                    <dt>Background runtime scope</dt>
                    <dd>Workspace</dd>
                  </div>
                </dl>
                <p className="meta">
                  Shared bot connections, runtime metadata, workspace users, skills catalog, and license details live here.
                </p>
              </section>

              <WorkspaceAuthCard
                id="workspace-codex-auth"
                containerRef={codexAuthFactRef}
                title="Codex authentication"
                providerLabel="Codex"
                actorUsername={String(codexAuthStatus?.target_actor_username || 'codex-bot').trim() || 'codex-bot'}
                loading={codexAuthLoading}
                loadingText="Loading Codex authentication status..."
                description="Shared workspace connection for codex-bot when Codex is selected for chat or background work."
                statusLabel={codexAuthStatusLabel}
                statusTone={codexAuthSource === 'none' ? 'error' : 'default'}
                sessionStatusLabel={codexAuthSessionStatusLabel}
                summaryPills={codexAuthSummaryPills}
                facts={[
                  { label: 'Effective source', value: codexAuthStatusLabel },
                  { label: 'Auth target', value: String(codexAuthStatus?.target_actor_username || 'codex-bot').trim() || 'codex-bot' },
                  { label: 'Override updated', value: formatDateTime(codexAuthStatus?.override_updated_at || null) },
                ]}
                canManage={canManageCodexAuth}
                manageHint="Only workspace owners and admins can update the shared Codex connection."
                forceDetailsOpen={codexAuthHasPendingSignIn}
                actionSlot={canManageCodexAuth ? (
                  <div className="row wrap profile-actions workspace-auth-inline-actions">
                    {codexAuthHasSystemOverride && !codexAuthHasPendingSignIn ? (
                      <button
                        ref={codexAuthPrimaryButtonRef}
                        className="button-secondary profile-action-button"
                        type="button"
                        onClick={() => setCodexAuthDialogOpen(true)}
                      >
                        Manage connection
                      </button>
                    ) : (
                      <>
                        <button
                          ref={codexAuthPrimaryButtonRef}
                          className="primary profile-action-button"
                          type="button"
                          onClick={() => {
                            void handleStartCodexDeviceAuth('browser')
                          }}
                          disabled={!codexAuthCanConnect}
                        >
                          {startCodexDeviceAuthPending
                            ? 'Starting...'
                            : codexAuthHasPendingSignIn
                              ? 'Continue sign-in'
                              : 'Connect in browser'}
                        </button>
                        {!codexAuthHasPendingSignIn ? (
                          <button
                            className="button-secondary profile-action-button"
                            type="button"
                            onClick={() => {
                              void handleStartCodexDeviceAuth('device_code')
                            }}
                            disabled={!codexAuthCanConnect}
                          >
                            Use device code
                          </button>
                        ) : null}
                        {codexAuthLoginSession ? (
                          <button
                            className="button-secondary profile-action-button"
                            type="button"
                            onClick={() => setCodexAuthDialogOpen(true)}
                          >
                            Show sign-in details
                          </button>
                        ) : null}
                      </>
                    )}
                  </div>
                ) : null}
                feedback={codexAuthFeedback}
              />

              <WorkspaceAuthCard
                id="workspace-opencode-auth"
                title="OpenCode authentication"
                providerLabel="OpenCode"
                actorUsername={String(opencodeAuthStatus?.target_actor_username || 'opencode-bot').trim() || 'opencode-bot'}
                loading={opencodeAuthLoading}
                loadingText="Loading OpenCode runtime status..."
                description="OpenCode uses runtime-built-in access and does not require device sign-in."
                statusLabel={opencodeAuthStatusLabel}
                statusTone={opencodeAuthSource === 'none' ? 'error' : 'default'}
                sessionStatusLabel={null}
                summaryPills={opencodeAuthSummaryPills}
                facts={[
                  { label: 'Effective source', value: opencodeAuthStatusLabel },
                  { label: 'Auth target', value: String(opencodeAuthStatus?.target_actor_username || 'opencode-bot').trim() || 'opencode-bot' },
                  { label: 'Override updated', value: formatDateTime(opencodeAuthStatus?.override_updated_at || null) },
                ]}
                canManage={false}
                manageHint="OpenCode is runtime-managed and does not expose manual sign-in actions."
                forceDetailsOpen={false}
                feedback={null}
              />

              <WorkspaceAuthCard
                id="workspace-claude-auth"
                containerRef={claudeAuthFactRef}
                title="Claude authentication"
                providerLabel="Claude"
                actorUsername={String(claudeAuthStatus?.target_actor_username || 'claude-bot').trim() || 'claude-bot'}
                loading={claudeAuthLoading}
                loadingText="Loading Claude authentication status..."
                description="Shared workspace connection for claude-bot. Anthropic Console uses API billing; Claude subscription uses Pro, Max, Team, or Enterprise."
                statusLabel={claudeAuthStatusLabel}
                statusTone={claudeAuthSource === 'none' ? 'error' : 'default'}
                sessionStatusLabel={claudeAuthSessionStatusLabel}
                summaryPills={claudeAuthSummaryPills}
                facts={[
                  { label: 'Effective source', value: claudeAuthStatusLabel },
                  { label: 'Auth target', value: String(claudeAuthStatus?.target_actor_username || 'claude-bot').trim() || 'claude-bot' },
                  { label: 'Override updated', value: formatDateTime(claudeAuthStatus?.override_updated_at || null) },
                ]}
                canManage={canManageClaudeAuth}
                manageHint="Only workspace owners and admins can update the shared Claude connection."
                forceDetailsOpen={claudeAuthHasPendingSignIn}
                actionSlot={canManageClaudeAuth ? (
                  <div className="row wrap profile-actions workspace-auth-inline-actions">
                    {claudeAuthHasSystemOverride && !claudeAuthHasPendingSignIn ? (
                      <button
                        ref={claudeAuthPrimaryButtonRef}
                        className="button-secondary profile-action-button"
                        type="button"
                        onClick={() => setClaudeAuthDialogOpen(true)}
                      >
                        Manage connection
                      </button>
                    ) : claudeAuthHasPendingSignIn ? (
                      <>
                        <button
                          ref={claudeAuthPrimaryButtonRef}
                          className="primary profile-action-button"
                          type="button"
                          onClick={() => setClaudeAuthDialogOpen(true)}
                          disabled={!claudeAuthCanConnect}
                        >
                          {startClaudeDeviceAuthPending
                            ? 'Starting...'
                            : `Continue ${claudeAuthLoginMethodLabel} sign-in`}
                        </button>
                        <button
                          className="button-secondary profile-action-button"
                          type="button"
                          onClick={() => {
                            void handleCancelClaudeDeviceAuth()
                          }}
                          disabled={cancelClaudeDeviceAuthPending}
                        >
                          {cancelClaudeDeviceAuthPending ? 'Cancelling...' : 'Cancel sign-in'}
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          ref={claudeAuthPrimaryButtonRef}
                          className="primary profile-action-button"
                          type="button"
                          onClick={() => {
                            void handleStartClaudeDeviceAuth('console')
                          }}
                          disabled={!claudeAuthCanConnect}
                        >
                          {startClaudeDeviceAuthPending ? 'Starting...' : 'Connect Anthropic Console'}
                        </button>
                        <button
                          className="button-secondary profile-action-button"
                          type="button"
                          onClick={() => {
                            void handleStartClaudeDeviceAuth('claudeai')
                          }}
                          disabled={!claudeAuthCanConnect}
                        >
                          {startClaudeDeviceAuthPending ? 'Starting...' : 'Connect Claude subscription'}
                        </button>
                      </>
                    )}
                  </div>
                ) : null}
                feedback={claudeAuthFeedback}
              />
            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="doctor">
            <div className="profile-pane-grid profile-workspace-grid">
              <WorkspaceDoctorCard
                doctorStatus={doctorStatus}
                architectureInventorySummary={architectureInventorySummary}
                doctorLoading={doctorLoading}
                doctorError={doctorError}
                canManage={canManageUsers}
                onSeedDoctor={onSeedDoctor}
                seedDoctorPending={seedDoctorPending}
                onRunDoctor={onRunDoctor}
                runDoctorPending={runDoctorPending}
                onResetDoctor={onResetDoctor}
                resetDoctorPending={resetDoctorPending}
              />
            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="runtime">
            <section className="profile-pane-card profile-runtime" aria-label="Workspace runtime">
              <div className="profile-pane-head">
                <h3>
                  <span className="profile-pane-head-icon" aria-hidden="true">
                    <Icon path="M4 4h16v12H4zM10 20h4M12 16v4" />
                  </span>
                  <span>Runtime</span>
                </h3>
                <span className="status-chip">Live</span>
              </div>
              <div className="profile-runtime-chip-row">
                <span className="status-chip">Frontend {frontendVersion}</span>
                <span className="status-chip">Backend {backendVersion}</span>
                <span className="status-chip">{backendBuild ? `Build ${backendBuild}` : 'Build n/a'}</span>
              </div>
              <div className="row wrap profile-actions profile-runtime-actions">
                <button className="button-secondary profile-action-button" type="button" onClick={copyRuntimeSnapshot}>
                  <Icon path="M16 1H4a2 2 0 0 0-2 2v12h2V3h12V1zM19 5H8a2 2 0 0 0-2 2v14h13a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z" />
                  <span>Copy runtime snapshot</span>
                </button>
                {runtimeCopyState === 'copied' ? <span className="status-chip">Copied</span> : null}
                {runtimeCopyState === 'error' ? <span className="status-chip">Copy failed</span> : null}
              </div>
              <Accordion.Root
                className="profile-accordion profile-runtime-accordion"
                type="multiple"
                defaultValue={['versions', 'deployment']}
              >
                <Accordion.Item className="profile-accordion-item" value="versions">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">
                          <span className="profile-accordion-title-icon" aria-hidden="true">
                            <Icon path="M4 5h16M4 12h16M4 19h16" />
                          </span>
                          <span>Version matrix</span>
                        </span>
                        <span className="profile-accordion-meta">Frontend, backend, and build identifiers</span>
                      </span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <dl className="profile-facts profile-runtime-facts">
                      <div className="profile-fact">
                        <dt>Frontend version</dt>
                        <dd>{frontendVersion || 'n/a'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Backend version</dt>
                        <dd>{backendVersion || 'n/a'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Backend build</dt>
                        <dd>{backendBuild || 'n/a'}</dd>
                      </div>
                    </dl>
                  </Accordion.Content>
                </Accordion.Item>
                <Accordion.Item className="profile-accordion-item" value="deployment">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">
                          <span className="profile-accordion-title-icon" aria-hidden="true">
                            <Icon path="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z" />
                          </span>
                          <span>Deployment</span>
                        </span>
                        <span className="profile-accordion-meta">Workspace runtime timestamp and deployment context</span>
                      </span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <dl className="profile-facts profile-runtime-facts">
                      <div className="profile-fact">
                        <dt>Workspace</dt>
                        <dd>{workspaceName || 'n/a'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Deployed (UTC)</dt>
                        <dd>{deployedAtUtc ?? 'unknown'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Deployed (local)</dt>
                        <dd>{formatDateTime(deployedAtUtc)}</dd>
                      </div>
                    </dl>
                  </Accordion.Content>
                </Accordion.Item>
              </Accordion.Root>
            </section>
          </Tabs.Content>

          {hasWorkspaceAdminTabs ? (
            <Tabs.Content className="profile-tab-content" value="users">
              {workspaceUsersContent}
            </Tabs.Content>
          ) : null}

          {hasWorkspaceAdminTabs ? (
            <Tabs.Content className="profile-tab-content" value="skills">
              {workspaceSkillsContent}
            </Tabs.Content>
          ) : null}

          <Tabs.Content className="profile-tab-content" value="license">
            <section className="profile-pane-card profile-license" aria-label="Workspace license">
              <div className="profile-pane-head">
                <h3>
                  <span className="profile-pane-head-icon" aria-hidden="true">
                    <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
                  </span>
                  <span>License</span>
                </h3>
                <span className="status-chip">{licenseStatusLabel}</span>
              </div>
              {licenseLoading ? (
                <p className="meta">Loading license status...</p>
              ) : licenseError ? (
                <div className="notice notice-error">{licenseError}</div>
              ) : !license ? (
                <p className="meta">License status is unavailable.</p>
              ) : (
                <Accordion.Root className="profile-accordion profile-license-accordion" type="multiple" defaultValue={['entitlement', 'lifecycle', 'installation']}>
                  <Accordion.Item className="profile-accordion-item" value="entitlement">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Entitlement</span>
                          <span className="profile-accordion-meta">{entitlementSource}</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Entitlement status</dt>
                          <dd>{formatLabel(license.status)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Subscription status</dt>
                          <dd>{formatLabel(subscriptionStatus)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Entitlement source</dt>
                          <dd>{entitlementSource}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Plan</dt>
                          <dd>{license.plan_code || 'n/a'}</dd>
                        </div>
                      </dl>
                    </Accordion.Content>
                  </Accordion.Item>

                  <Accordion.Item className="profile-accordion-item" value="lifecycle">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Lifecycle dates</span>
                          <span className="profile-accordion-meta">Subscription, trial, and grace windows</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Subscription valid until</dt>
                          <dd>{formatDateTime(subscriptionValidUntil)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Public beta free until</dt>
                          <dd>{formatDateTime(publicBetaFreeUntil)}</dd>
                        </div>
                        {showTrialWindow ? (
                          <div className="profile-fact">
                            <dt>Trial ends</dt>
                            <dd>{formatDateTime(license.trial_ends_at)}</dd>
                          </div>
                        ) : null}
                        {showTrialWindow ? (
                          <div className="profile-fact">
                            <dt>Grace ends</dt>
                            <dd>{formatDateTime(license.grace_ends_at)}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </Accordion.Content>
                  </Accordion.Item>

                  <Accordion.Item className="profile-accordion-item" value="installation">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Installation details</span>
                          <span className="profile-accordion-meta">Local installation and license identity</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Installation ID</dt>
                          <dd>
                            <code>{license.installation_id || 'n/a'}</code>
                          </dd>
                        </div>
                      </dl>
                      <div className="row wrap profile-actions">
                        <button
                          type="button"
                          className="button-secondary profile-action-button"
                          onClick={() => {
                            void copyInstallationId()
                          }}
                          disabled={!String(license.installation_id || '').trim()}
                        >
                          <Icon path="M9 9h11v11H9zM4 4h11v2H6v9H4z" />
                          <span>Copy installation ID</span>
                        </button>
                        {installationCopyState === 'copied' ? <span className="status-chip">Copied</span> : null}
                        {installationCopyState === 'error' ? <span className="status-chip">Copy failed</span> : null}
                      </div>
                    </Accordion.Content>
                  </Accordion.Item>
                </Accordion.Root>
              )}
            </section>
          </Tabs.Content>
        </Tabs.Root>

        <Dialog.Root open={codexAuthDialogOpen} onOpenChange={setCodexAuthDialogOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="codex-chat-alert-overlay" />
            <Dialog.Content className="codex-chat-alert-content profile-codex-auth-dialog">
              <Dialog.Title className="codex-chat-alert-title">
                {codexAuthHasSystemOverride && !codexAuthHasPendingSignIn
                  ? 'Codex connection'
                  : `Connect Codex with ${codexAuthLoginMethodLabel.toLowerCase()}`}
              </Dialog.Title>
              <Dialog.Description className="codex-chat-alert-description">
                {codexAuthHasSystemOverride && !codexAuthHasPendingSignIn
                  ? 'This shared codex-bot connection is active and overrides the host-mounted auth file inside this runtime.'
                  : `Finish the ${codexAuthLoginMethodLabel.toLowerCase()} flow and the shared codex-bot connection will be stored inside this runtime only.`}
              </Dialog.Description>
              <div className="profile-codex-auth-dialog-body">
                {codexAuthHasSystemOverride && !codexAuthHasPendingSignIn ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Connection</div>
                    <span className="status-chip">Connected for codex-bot</span>
                  </div>
                ) : null}
                <div className="profile-codex-auth-dialog-block">
                  <div className="field-label">Sign-in method</div>
                  <span className="status-chip">{codexAuthLoginMethodLabel}</span>
                </div>
                {!codexAuthHasSystemOverride && codexAuthLoginSession?.verification_uri ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Browser step</div>
                    <p className="meta">
                      {codexAuthLoginMethod === 'browser'
                        ? 'Open the browser flow to complete the Codex sign-in.'
                        : 'Open the browser flow and approve the device code sign-in.'}
                    </p>
                    <div className="workspace-auth-inline-actions">
                      <a
                        className="btn btn-primary"
                        href={codexAuthLoginSession.verification_uri}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Continue in browser
                      </a>
                    </div>
                  </div>
                ) : null}
                {!codexAuthHasSystemOverride && codexAuthLoginSession?.user_code ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">One-time code</div>
                    <code className="profile-codex-auth-code">{codexAuthLoginSession.user_code}</code>
                  </div>
                ) : null}
                {codexAuthHasPendingSignIn && codexAuthLoginMethod === 'browser' ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Browser callback URL</div>
                    <p className="meta">
                      After browser approval, paste the full `http://localhost:.../auth/callback?...` URL here so Constructos can finish the login inside the container.
                    </p>
                    <div className="workspace-auth-inline-actions">
                      <input
                        className="search-panel-input"
                        type="text"
                        inputMode="url"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                        placeholder="Paste Codex callback URL"
                        value={codexAuthManualCallbackInput}
                        onChange={(event) => setCodexAuthManualCallbackInput(event.target.value)}
                      />
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => {
                          void handleSubmitCodexBrowserCallback()
                        }}
                        disabled={!codexAuthCanSubmitBrowserCallback}
                      >
                        {submitCodexBrowserCallbackPending ? 'Submitting...' : 'Submit callback URL'}
                      </button>
                    </div>
                  </div>
                ) : null}
                {codexAuthSessionStatusLabel ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Status</div>
                    <span className="status-chip">{codexAuthSessionStatusLabel}</span>
                  </div>
                ) : null}
                {codexAuthLoginSession?.error ? (
                  <div className="notice notice-error">{codexAuthLoginSession.error}</div>
                ) : null}
              </div>
              <div className="row wrap profile-actions">
                {canManageCodexAuth && codexAuthHasPendingSignIn ? (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      void handleCancelCodexDeviceAuth()
                    }}
                    disabled={cancelCodexDeviceAuthPending}
                  >
                    {cancelCodexDeviceAuthPending ? 'Cancelling...' : 'Cancel sign-in'}
                  </button>
                ) : null}
                {codexAuthHasSystemOverride && !codexAuthHasPendingSignIn && codexAuthCanRemoveOverride ? (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      void handleDeleteCodexAuthOverride()
                    }}
                    disabled={!codexAuthCanRemoveOverride}
                  >
                    {deleteCodexAuthOverridePending ? 'Removing...' : 'Remove override'}
                  </button>
                ) : null}
                <Dialog.Close asChild>
                  <button type="button" className="button-secondary">Close</button>
                </Dialog.Close>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        <Dialog.Root open={claudeAuthDialogOpen} onOpenChange={setClaudeAuthDialogOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="codex-chat-alert-overlay" />
            <Dialog.Content className="codex-chat-alert-content profile-codex-auth-dialog">
              <Dialog.Title className="codex-chat-alert-title">
                {claudeAuthHasSystemOverride && !claudeAuthHasPendingSignIn
                  ? 'Claude connection'
                  : `Connect ${claudeAuthLoginMethodLabel}`}
              </Dialog.Title>
              <Dialog.Description className="codex-chat-alert-description">
                {claudeAuthHasSystemOverride && !claudeAuthHasPendingSignIn
                  ? 'This shared claude-bot connection is active and overrides the host-mounted auth file inside this runtime.'
                  : `Finish the ${claudeAuthLoginMethodLabel.toLowerCase()} browser sign-in and the shared claude-bot connection will be stored inside this runtime only.`}
              </Dialog.Description>
              <div className="profile-codex-auth-dialog-body">
                {claudeAuthHasSystemOverride && !claudeAuthHasPendingSignIn ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Connection</div>
                    <span className="status-chip">Connected for claude-bot</span>
                  </div>
                ) : null}
                <div className="profile-codex-auth-dialog-block">
                  <div className="field-label">Sign-in method</div>
                  <span className="status-chip">{claudeAuthLoginMethodLabel}</span>
                </div>
                {!claudeAuthHasSystemOverride && claudeAuthLoginSession?.verification_uri ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Browser step</div>
                    <p className="meta">Open the browser flow first. After approval, copy the code shown by Claude and paste it back below.</p>
                    <div className="workspace-auth-inline-actions">
                      <a
                        className="btn btn-primary"
                        href={claudeAuthLoginSession.verification_uri}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Continue in browser
                      </a>
                    </div>
                  </div>
                ) : null}
                {!claudeAuthHasSystemOverride && claudeAuthLoginSession?.user_code ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">One-time code</div>
                    <code className="profile-codex-auth-code">{claudeAuthLoginSession.user_code}</code>
                  </div>
                ) : null}
                {claudeAuthHasPendingSignIn ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Browser return code</div>
                    <p className="meta">If the browser shows “Paste this into Claude Code”, paste that code here.</p>
                    <div className="workspace-auth-inline-actions">
                      <input
                        className="search-panel-input"
                        type="text"
                        inputMode="text"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                        placeholder="Paste Claude code"
                        value={claudeAuthManualCodeInput}
                        onChange={(event) => setClaudeAuthManualCodeInput(event.target.value)}
                      />
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => {
                          void handleSubmitClaudeDeviceAuthCode()
                        }}
                        disabled={!claudeAuthCanSubmitCode}
                      >
                        {submitClaudeDeviceAuthCodePending ? 'Submitting...' : 'Submit code'}
                      </button>
                    </div>
                  </div>
                ) : null}
                {claudeAuthSessionStatusLabel ? (
                  <div className="profile-codex-auth-dialog-block">
                    <div className="field-label">Status</div>
                    <span className="status-chip">{claudeAuthSessionStatusLabel}</span>
                  </div>
                ) : null}
                {claudeAuthLoginSession?.error ? (
                  <div className="notice notice-error">{claudeAuthLoginSession.error}</div>
                ) : null}
              </div>
              <div className="row wrap profile-actions">
                {canManageClaudeAuth && claudeAuthHasPendingSignIn ? (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      void handleCancelClaudeDeviceAuth()
                    }}
                    disabled={cancelClaudeDeviceAuthPending}
                  >
                    {cancelClaudeDeviceAuthPending ? 'Cancelling...' : 'Cancel sign-in'}
                  </button>
                ) : null}
                {claudeAuthHasSystemOverride && !claudeAuthHasPendingSignIn && claudeAuthCanRemoveOverride ? (
                  <button
                    type="button"
                    className="button-secondary"
                    onClick={() => {
                      void handleDeleteClaudeAuthOverride()
                    }}
                    disabled={!claudeAuthCanRemoveOverride}
                  >
                    {deleteClaudeAuthOverridePending ? 'Removing...' : 'Remove override'}
                  </button>
                ) : null}
                <Dialog.Close asChild>
                  <button type="button" className="button-secondary">Close</button>
                </Dialog.Close>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </section>
    </Tooltip.Provider>
  )
}

export function AdminPanel({
  canManageUsers,
  workspaceRole,
  workspaceId,
  users,
  usersLoading,
  usersError,
  username,
  setUsername,
  fullName,
  setFullName,
  role,
  setRole,
  createPending,
  onCreate,
  lastTempPassword,
  onResetPassword,
  resetPendingUserId,
  onUpdateRole,
  updateRolePendingUserId,
  onUpdateAgentRuntime,
  updateAgentRuntimePendingUserId,
  agentExecutionAvailableModels,
  onDeactivateUser,
  deactivatePendingUserId,
  workspaceSkills,
  workspaceSkillsLoading,
  importWorkspaceSkillPending,
  importWorkspaceSkillFilePending,
  patchWorkspaceSkillPending,
  deleteWorkspaceSkillPending,
  onImportWorkspaceSkill,
  onImportWorkspaceSkillFile,
  onPatchWorkspaceSkill,
  onDeleteWorkspaceSkill,
  embeddedTab,
}: {
  canManageUsers: boolean
  workspaceRole: string
  workspaceId: string
  users: AdminWorkspaceUser[]
  usersLoading: boolean
  usersError: string | null
  username: string
  setUsername: (value: string) => void
  fullName: string
  setFullName: (value: string) => void
  role: string
  setRole: (value: string) => void
  createPending: boolean
  onCreate: () => void
  lastTempPassword: string | null
  onResetPassword: (userId: string) => void
  resetPendingUserId: string | null
  onUpdateRole: (userId: string, role: string) => void
  updateRolePendingUserId: string | null
  onUpdateAgentRuntime: (payload: {
    targetUserId: string
    model?: string | null
    reasoning_effort?: string | null
    use_for_background_processing?: boolean | null
  }) => void
  updateAgentRuntimePendingUserId: string | null
  agentExecutionAvailableModels: string[]
  onDeactivateUser: (userId: string) => void
  deactivatePendingUserId: string | null
  workspaceSkills: WorkspaceSkillsPage | undefined
  workspaceSkillsLoading: boolean
  importWorkspaceSkillPending: boolean
  importWorkspaceSkillFilePending: boolean
  patchWorkspaceSkillPending: boolean
  deleteWorkspaceSkillPending: boolean
  onImportWorkspaceSkill: (payload: {
    source_url: string
    skill_key?: string
    mode?: 'advisory' | 'enforced'
    trust_level?: 'verified' | 'reviewed' | 'untrusted'
  }) => Promise<unknown>
  onImportWorkspaceSkillFile: (payload: {
    file: File
    skill_key?: string
    mode?: 'advisory' | 'enforced'
    trust_level?: 'verified' | 'reviewed' | 'untrusted'
  }) => Promise<unknown>
  onPatchWorkspaceSkill: (payload: {
    skillId: string
    patch: {
      name?: string
      summary?: string
      content?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }
  }) => Promise<unknown>
  onDeleteWorkspaceSkill: (skillId: string) => Promise<unknown>
  embeddedTab?: 'users' | 'skills'
}) {
  const [skillSourceUrl, setSkillSourceUrl] = React.useState('')
  const [skillKey, setSkillKey] = React.useState('')
  const [skillMode, setSkillMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [skillTrustLevel, setSkillTrustLevel] = React.useState<'verified' | 'reviewed' | 'untrusted'>('reviewed')
  const [workspaceSkillContentView, setWorkspaceSkillContentView] = React.useState<'write' | 'preview' | 'split'>('write')
  const [workspaceSkillEditorName, setWorkspaceSkillEditorName] = React.useState('')
  const [workspaceSkillEditorSummary, setWorkspaceSkillEditorSummary] = React.useState('')
  const [workspaceSkillEditorContent, setWorkspaceSkillEditorContent] = React.useState('')
  const [workspaceSkillEditorMode, setWorkspaceSkillEditorMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [workspaceSkillEditorTrustLevel, setWorkspaceSkillEditorTrustLevel] = React.useState<
    'verified' | 'reviewed' | 'untrusted'
  >('reviewed')
  const [adminTab, setAdminTab] = React.useState<'users' | 'skills'>(embeddedTab ?? 'users')
  const [skillsSearchQ, setSkillsSearchQ] = React.useState('')
  const [selectedWorkspaceSkillId, setSelectedWorkspaceSkillId] = React.useState<string | null>(null)
  const workspaceSkillFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const workspaceSkillItems = workspaceSkills?.items ?? []
  const totalUsers = users.length
  const totalSkills = workspaceSkills?.total ?? workspaceSkillItems.length
  const activeUsers = React.useMemo(() => users.filter((item) => Boolean(item.is_active)).length, [users])
  const inactiveUsers = Math.max(0, totalUsers - activeUsers)
  const actorIsOwner = normalizeOptionValue(workspaceRole, ADMIN_ROLE_OPTIONS, 'Member') === 'Owner'
  const createRoleOptions = React.useMemo(
    () => (actorIsOwner ? ADMIN_ROLE_OPTIONS : NON_OWNER_ROLE_OPTIONS),
    [actorIsOwner]
  )
  const normalizedCreateRole = React.useMemo(
    () => normalizeOptionValue(role, createRoleOptions, 'Member'),
    [createRoleOptions, role]
  )
  const getWorkspaceSkillSourceContent = React.useCallback((manifest: Record<string, unknown> | undefined): string => {
    if (!manifest || typeof manifest !== 'object') return ''
    const raw = (manifest as Record<string, unknown>).source_content
    return typeof raw === 'string' ? raw : ''
  }, [])
  const selectedWorkspaceSkill = React.useMemo(
    () => workspaceSkillItems.find((item) => item.id === selectedWorkspaceSkillId) ?? null,
    [selectedWorkspaceSkillId, workspaceSkillItems]
  )
  const filteredWorkspaceSkillItems = React.useMemo(() => {
    const query = String(skillsSearchQ || '').trim().toLowerCase()
    if (!query) return workspaceSkillItems
    return workspaceSkillItems.filter((item) => {
      const haystack = [
        String(item.name || ''),
        String(item.skill_key || ''),
        String(item.summary || ''),
        String(item.source_locator || ''),
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [skillsSearchQ, workspaceSkillItems])
  const workspaceSkillEditorDirty = React.useMemo(() => {
    if (!selectedWorkspaceSkill) return false
    const currentMode = String(selectedWorkspaceSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory'
    const currentTrustLevel =
      String(selectedWorkspaceSkill.trust_level || '').toLowerCase() === 'verified'
        ? 'verified'
        : String(selectedWorkspaceSkill.trust_level || '').toLowerCase() === 'untrusted'
          ? 'untrusted'
          : 'reviewed'
    return (
      workspaceSkillEditorName.trim() !== String(selectedWorkspaceSkill.name || '').trim() ||
      workspaceSkillEditorSummary !== String(selectedWorkspaceSkill.summary || '') ||
      workspaceSkillEditorContent !==
        getWorkspaceSkillSourceContent(selectedWorkspaceSkill?.manifest as Record<string, unknown> | undefined) ||
      workspaceSkillEditorMode !== currentMode ||
      workspaceSkillEditorTrustLevel !== currentTrustLevel
    )
  }, [
    selectedWorkspaceSkill,
    getWorkspaceSkillSourceContent,
    workspaceSkillEditorContent,
    workspaceSkillEditorMode,
    workspaceSkillEditorName,
    workspaceSkillEditorSummary,
    workspaceSkillEditorTrustLevel,
  ])

  React.useEffect(() => {
    if (workspaceSkillItems.length === 0) {
      setSelectedWorkspaceSkillId(null)
      return
    }
    if (!selectedWorkspaceSkillId) return
    if (workspaceSkillItems.some((item) => item.id === selectedWorkspaceSkillId)) return
    setSelectedWorkspaceSkillId(null)
  }, [selectedWorkspaceSkillId, workspaceSkillItems])

  React.useEffect(() => {
    if (!selectedWorkspaceSkill) {
      setWorkspaceSkillEditorName('')
      setWorkspaceSkillEditorSummary('')
      setWorkspaceSkillEditorContent('')
      setWorkspaceSkillEditorMode('advisory')
      setWorkspaceSkillEditorTrustLevel('reviewed')
      return
    }
    setWorkspaceSkillEditorName(String(selectedWorkspaceSkill.name || ''))
    setWorkspaceSkillEditorSummary(String(selectedWorkspaceSkill.summary || ''))
    setWorkspaceSkillEditorContent(
      getWorkspaceSkillSourceContent(selectedWorkspaceSkill?.manifest as Record<string, unknown> | undefined)
    )
    setWorkspaceSkillEditorMode(
      String(selectedWorkspaceSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory'
    )
    const nextTrustLevel = String(selectedWorkspaceSkill.trust_level || '').toLowerCase()
    if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
      setWorkspaceSkillEditorTrustLevel(nextTrustLevel)
    } else {
      setWorkspaceSkillEditorTrustLevel('reviewed')
    }
  }, [getWorkspaceSkillSourceContent, selectedWorkspaceSkill])

  React.useEffect(() => {
    if (embeddedTab && adminTab !== embeddedTab) {
      setAdminTab(embeddedTab)
    }
  }, [adminTab, embeddedTab])

  React.useEffect(() => {
    if (!actorIsOwner && isAdminTierRole(role)) {
      setRole('Member')
    }
  }, [actorIsOwner, role, setRole])

  if (!canManageUsers) {
    return (
      <section className="card">
        <h2>Workspace</h2>
        <p className="meta">Admin access required.</p>
      </section>
    )
  }

  return (
    <Tooltip.Provider delayDuration={180}>
      <section className={`card admin-panel ${embeddedTab ? 'admin-panel-embedded' : ''}`.trim()}>
      {!embeddedTab ? (
        <>
          <div className="admin-panel-head">
            <div>
              <h2>Workspace admin</h2>
              <p className="meta">Create users, assign workspace roles, and maintain the workspace skills catalog.</p>
            </div>
            <span className="status-chip admin-workspace-chip">Workspace: {workspaceId || 'n/a'}</span>
          </div>
          <div className="admin-panel-summary">
            <span className="status-chip admin-summary-chip">
              <Icon path="M16 11c1.66 0 3-1.57 3-3.5S17.66 4 16 4s-3 1.57-3 3.5 1.34 3.5 3 3.5M8 11c1.66 0 3-1.57 3-3.5S9.66 4 8 4 5 5.57 5 7.5 6.34 11 8 11M8 13c-2.67 0-8 1.34-8 4v3h10v-3c0-1.53.82-2.75 2.05-3.73C10.72 13.09 9.32 13 8 13M16 13c-.26 0-.54.02-.83.05 1.43 1 2.33 2.39 2.33 3.95v3H24v-3c0-2.66-5.33-4-8-4" />
              <span>Users: {totalUsers}</span>
            </span>
            <span className="status-chip admin-summary-chip">
              <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
              <span>Active: {activeUsers}</span>
            </span>
            {inactiveUsers > 0 ? (
              <span className="status-chip admin-summary-chip">
                <Icon path="M6 6l12 12M18 6 6 18" />
                <span>Inactive: {inactiveUsers}</span>
              </span>
            ) : null}
            <span className="status-chip admin-summary-chip">
              <Icon path="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 7H20M6.5 7A2.5 2.5 0 0 1 4 9.5v10" />
              <span>Skills: {totalSkills}</span>
            </span>
          </div>
        </>
      ) : null}

      <Tabs.Root
        className="admin-tabs"
        value={adminTab}
        onValueChange={(nextTab) => {
          if (nextTab === 'users' || nextTab === 'skills') setAdminTab(nextTab)
        }}
      >
        {!embeddedTab ? (
          <Tabs.List className="admin-tabs-list" aria-label="Admin sections">
            <Tabs.Trigger className="admin-tab-trigger" value="users">
              <span className="admin-tab-trigger-icon" aria-hidden="true">
                <Icon path="M16 11c1.66 0 3-1.57 3-3.5S17.66 4 16 4s-3 1.57-3 3.5 1.34 3.5 3 3.5M8 11c1.66 0 3-1.57 3-3.5S9.66 4 8 4 5 5.57 5 7.5 6.34 11 8 11M8 13c-2.67 0-8 1.34-8 4v3h10v-3c0-1.53.82-2.75 2.05-3.73C10.72 13.09 9.32 13 8 13M16 13c-.26 0-.54.02-.83.05 1.43 1 2.33 2.39 2.33 3.95v3H24v-3c0-2.66-5.33-4-8-4" />
              </span>
              <span>Users</span>
              <span className="status-chip admin-tab-count">{totalUsers}</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="admin-tab-trigger" value="skills">
              <span className="admin-tab-trigger-icon" aria-hidden="true">
                <Icon path="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 7H20M6.5 7A2.5 2.5 0 0 1 4 9.5v10" />
              </span>
              <span>Skills catalog</span>
              <span className="status-chip admin-tab-count">{totalSkills}</span>
            </Tabs.Trigger>
          </Tabs.List>
        ) : null}

        <Tabs.Content className="admin-tab-content" value="users">
          <Accordion.Root className="profile-accordion admin-accordion" type="single" collapsible defaultValue="create-user">
            <Accordion.Item className="profile-accordion-item" value="create-user">
              <Accordion.Header className="profile-accordion-header">
                <Accordion.Trigger className="profile-accordion-trigger">
                  <span className="profile-accordion-head">
                    <span className="profile-accordion-title">Create user</span>
                    <span className="profile-accordion-meta">Provision a human account with initial workspace role.</span>
                  </span>
                  <span className="status-chip">Workspace</span>
                  <span className="profile-accordion-chevron" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="profile-accordion-content">
                <div className="admin-create">
                  {!actorIsOwner ? (
                    <div className="notice">
                      Admins can create Member and Guest users. Owner and Admin roles require an owner.
                    </div>
                  ) : null}
                  <div className="admin-create-grid">
                    <label className="field-control">
                      <span className="field-label">Username</span>
                      <input
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        placeholder="3-64 chars"
                        autoComplete="off"
                      />
                    </label>
                    <label className="field-control">
                      <span className="field-label">Full name</span>
                      <input
                        value={fullName}
                        onChange={(event) => setFullName(event.target.value)}
                        placeholder="Optional"
                        autoComplete="off"
                      />
                    </label>
                    <label className="field-control">
                      <span className="field-label">Role</span>
                      <AdminSelect
                        value={normalizedCreateRole}
                        onValueChange={setRole}
                        options={createRoleOptions}
                        ariaLabel="New user workspace role"
                        disabled={createPending}
                      />
                    </label>
                    <div className="admin-create-actions">
                      <button className="primary" type="button" onClick={onCreate} disabled={createPending || !username.trim()}>
                        {createPending ? 'Creating...' : 'Create user'}
                      </button>
                    </div>
                  </div>
                </div>
              </Accordion.Content>
            </Accordion.Item>
          </Accordion.Root>

          {lastTempPassword ? (
            <div className="notice admin-temp-password">
              Temporary password: <code>{lastTempPassword}</code>
            </div>
          ) : null}

          <div className="admin-users">
            <div className="admin-users-head">
              <h3>Workspace users</h3>
              <span className="meta">{totalUsers} total</span>
            </div>
            {usersLoading ? (
              <div className="meta">Loading users...</div>
            ) : usersError ? (
              <div className="notice notice-error">{usersError}</div>
            ) : users.length === 0 ? (
              <div className="meta">No users.</div>
            ) : (
              <div className="admin-user-list">
                <Accordion.Root className="admin-user-accordion" type="multiple">
                  {users.map((item) => {
                    const canResetPassword = item.can_reset_password ?? item.user_type === 'human'
                    const canDeactivate = item.can_deactivate ?? (item.user_type === 'human' && item.is_active)
                    const canUpdateRole = item.can_update_role ?? (item.user_type === 'human' && !isAdminTierRole(item.role))
                    const roleUpdatePending = updateRolePendingUserId === item.id
                    const resetPending = resetPendingUserId === item.id
                    const deactivatePending = deactivatePendingUserId === item.id
                    const runtimePending = updateAgentRuntimePendingUserId === item.id
                    const normalizedUserRole = normalizeOptionValue(String(item.role || ''), ADMIN_ROLE_OPTIONS, 'Member')
                    const rowRoleOptions = canUpdateRole
                      ? (actorIsOwner ? ADMIN_ROLE_OPTIONS : NON_OWNER_ROLE_OPTIONS)
                      : [{ value: normalizedUserRole, label: normalizedUserRole }]
                    const botProvider = resolveWorkspaceBotProvider(item)
                    const canConfigureBackgroundRuntime = Boolean(item.can_configure_background_execution && botProvider)
                    const backgroundRuntimeAvailable = item.background_agent_available !== false
                    const runtimeModelOptions = botProvider
                      ? buildProviderModelOptions(
                          [...agentExecutionAvailableModels, String(item.background_agent_model || '')],
                          botProvider
                        )
                      : []
                    const normalizedRuntimeModel = normalizeAgentExecutionModel(item.background_agent_model)
                    const runtimeModelValue = normalizedRuntimeModel || BACKGROUND_RUNTIME_MODEL_DEFAULT_VALUE
                    const runtimeReasoningValue = normalizeChatReasoningEffort(item.background_agent_reasoning_effort)
                    const runtimeReasoningOptions = botProvider ? getChatReasoningOptions(botProvider) : CODEX_CHAT_REASONING_OPTIONS
                    const displayName = item.full_name || item.username
                    const summaryChipLabel = canConfigureBackgroundRuntime && botProvider
                      ? `${getAgentExecutionProviderLabel(botProvider)} runtime`
                      : normalizedUserRole
                    const runtimeSummaryLabel = canConfigureBackgroundRuntime && botProvider
                      ? (
                          normalizedRuntimeModel
                            ? formatAgentExecutionModelLabel(normalizedRuntimeModel)
                            : `${getAgentExecutionProviderLabel(botProvider)} · Workspace default`
                        )
                      : ''
                    const summaryParts: string[] = []
                    if (canConfigureBackgroundRuntime && botProvider) {
                      summaryParts.push(runtimeSummaryLabel)
                      summaryParts.push(`Reasoning ${getChatReasoningLabel(runtimeReasoningValue, botProvider)}`)
                      summaryParts.push(
                        item.is_background_execution_selected
                          ? 'Used for event/classifier processing'
                          : backgroundRuntimeAvailable
                            ? 'Available for event/classifier processing'
                            : 'Unavailable for event/classifier processing'
                      )
                    } else {
                      summaryParts.push(item.is_active ? 'Workspace account' : 'Inactive workspace account')
                      if (!canResetPassword) {
                        summaryParts.push('Service account')
                      } else if (!canUpdateRole && item.user_type === 'human' && isAdminTierRole(item.role)) {
                        summaryParts.push('Owner approval required for role changes')
                      } else if (canUpdateRole) {
                        summaryParts.push('Role and access controls available')
                      }
                    }
                    return (
                      <Accordion.Item key={item.id} className="admin-user-card" value={item.id}>
                        <Accordion.Header className="admin-user-card-header">
                          <Accordion.Trigger className="admin-user-card-trigger">
                            <span
                              className={`admin-user-avatar ${canConfigureBackgroundRuntime ? 'is-bot' : ''}`.trim()}
                              aria-hidden="true"
                            >
                              {getWorkspaceUserMonogram(item)}
                            </span>
                            <span className="admin-user-card-main">
                              <span className="admin-user-title">
                                <span className="admin-user-display-name">{displayName}</span>
                                <span className="admin-user-username">@{item.username}</span>
                              </span>
                              <span className="admin-user-card-meta">{summaryParts.join(' · ')}</span>
                              <span className="admin-user-badges">
                                <span className="status-chip">{item.role}</span>
                                <span className="status-chip">{item.user_type}</span>
                                {canResetPassword && item.must_change_password ? <span className="status-chip">must change password</span> : null}
                                {!canResetPassword ? <span className="status-chip">service account</span> : null}
                                {!canUpdateRole && item.user_type === 'human' && isAdminTierRole(item.role) ? (
                                  <span className="status-chip">owner required</span>
                                ) : null}
                                {item.is_background_execution_selected ? <span className="status-chip">event/classifier runtime</span> : null}
                                {canConfigureBackgroundRuntime && !backgroundRuntimeAvailable ? (
                                  <span className="status-chip">not configured</span>
                                ) : null}
                                {canConfigureBackgroundRuntime && item.background_agent_model_is_fallback ? (
                                  <span className="status-chip">runtime fallback</span>
                                ) : null}
                                {!item.is_active ? <span className="status-chip">inactive</span> : null}
                              </span>
                            </span>
                            <span className="admin-user-card-aside">
                              <span className="status-chip admin-user-card-summary-chip">{summaryChipLabel}</span>
                              <span className="admin-user-card-summary-text">Open controls</span>
                            </span>
                            <span className="admin-user-card-chevron" aria-hidden="true">
                              <Icon path="M6 9l6 6 6-6" />
                            </span>
                          </Accordion.Trigger>
                        </Accordion.Header>
                        <Accordion.Content className="admin-user-card-content">
                          <div className="admin-user-control-grid">
                            <label className="field-control admin-role-field">
                              <span className="field-label">Role</span>
                              <AdminSelect
                                value={normalizedUserRole}
                                onValueChange={(nextRole) => {
                                  if (nextRole === normalizedUserRole) return
                                  onUpdateRole(item.id, nextRole)
                                }}
                                options={rowRoleOptions}
                                disabled={roleUpdatePending || !canUpdateRole}
                                ariaLabel={`Set workspace role for ${item.username}`}
                              />
                            </label>
                            {canConfigureBackgroundRuntime && botProvider ? (
                              <label className="field-control admin-role-field">
                                <span className="field-label">Runtime model</span>
                                <AdminSelect
                                  value={runtimeModelValue}
                                  onValueChange={(nextModel) => {
                                    const resolvedModel = nextModel === BACKGROUND_RUNTIME_MODEL_DEFAULT_VALUE ? '' : nextModel
                                    if (resolvedModel === normalizedRuntimeModel) return
                                    onUpdateAgentRuntime({
                                      targetUserId: item.id,
                                      model: resolvedModel || null,
                                      reasoning_effort: runtimeReasoningValue,
                                    })
                                  }}
                                  options={[
                                    { value: BACKGROUND_RUNTIME_MODEL_DEFAULT_VALUE, label: 'Workspace default' },
                                    ...runtimeModelOptions,
                                  ]}
                                  disabled={runtimePending}
                                  ariaLabel={`Set runtime model for ${item.username}`}
                                />
                              </label>
                            ) : null}
                            {canConfigureBackgroundRuntime && botProvider ? (
                              <label className="field-control admin-role-field">
                                <span className="field-label">Reasoning</span>
                                <AdminSelect
                                  value={runtimeReasoningValue}
                                  onValueChange={(nextReasoning) => {
                                    if (nextReasoning === runtimeReasoningValue) return
                                    onUpdateAgentRuntime({
                                      targetUserId: item.id,
                                      model: normalizedRuntimeModel || null,
                                      reasoning_effort: nextReasoning,
                                    })
                                  }}
                                  options={runtimeReasoningOptions}
                                  disabled={runtimePending}
                                  ariaLabel={`Set runtime reasoning for ${item.username}`}
                                />
                              </label>
                            ) : null}
                          </div>
                          <div className="admin-user-card-actions">
                            {canConfigureBackgroundRuntime && backgroundRuntimeAvailable && !item.is_background_execution_selected ? (
                              <Tooltip.Root>
                                <Tooltip.Trigger asChild>
                                  <button
                                    className="admin-reset-btn"
                                    type="button"
                                    onClick={() =>
                                      onUpdateAgentRuntime({
                                        targetUserId: item.id,
                                        use_for_background_processing: true,
                                      })
                                    }
                                    disabled={runtimePending}
                                  >
                                    <Icon path="M5 13l4 4L19 7" />
                                    <span>{runtimePending ? 'Saving...' : 'Use for event/classifier runtime'}</span>
                                  </button>
                                </Tooltip.Trigger>
                                <Tooltip.Portal>
                                  <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                    Route event storming and classifiers through this bot runtime
                                    <Tooltip.Arrow className="header-tooltip-arrow" />
                                  </Tooltip.Content>
                                </Tooltip.Portal>
                              </Tooltip.Root>
                            ) : null}
                            {item.is_active && canResetPassword ? (
                              <Tooltip.Root>
                                <Tooltip.Trigger asChild>
                                  <button
                                    className="admin-reset-btn"
                                    type="button"
                                    onClick={() => onResetPassword(item.id)}
                                    disabled={resetPending}
                                  >
                                    <Icon path="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" />
                                    <span>{resetPending ? 'Resetting...' : 'Reset password'}</span>
                                  </button>
                                </Tooltip.Trigger>
                                <Tooltip.Portal>
                                  <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                    Generate a temporary password for this user
                                    <Tooltip.Arrow className="header-tooltip-arrow" />
                                  </Tooltip.Content>
                                </Tooltip.Portal>
                              </Tooltip.Root>
                            ) : null}
                            {item.is_active && canDeactivate ? (
                              <Tooltip.Root>
                                <Tooltip.Trigger asChild>
                                  <button
                                    className="admin-deactivate-btn"
                                    type="button"
                                    onClick={() => {
                                      const confirmDeactivate = window.confirm(
                                        `Deactivate ${item.username}? They will be signed out and unable to log in.`
                                      )
                                      if (!confirmDeactivate) return
                                      onDeactivateUser(item.id)
                                    }}
                                    disabled={deactivatePending}
                                  >
                                    <Icon path="M6 6l12 12M18 6 6 18" />
                                    <span>{deactivatePending ? 'Deactivating...' : 'Deactivate user'}</span>
                                  </button>
                                </Tooltip.Trigger>
                                <Tooltip.Portal>
                                  <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                    Disable login and revoke active sessions
                                    <Tooltip.Arrow className="header-tooltip-arrow" />
                                  </Tooltip.Content>
                                </Tooltip.Portal>
                              </Tooltip.Root>
                            ) : null}
                          </div>
                        </Accordion.Content>
                      </Accordion.Item>
                    )
                  })}
                </Accordion.Root>
              </div>
            )}
          </div>
        </Tabs.Content>

        <Tabs.Content className="admin-tab-content" value="skills">
          <div className="admin-skills">
            <Accordion.Root className="profile-accordion admin-accordion" type="single" collapsible defaultValue="import-skill">
              <Accordion.Item className="profile-accordion-item" value="import-skill">
                <Accordion.Header className="profile-accordion-header">
                  <Accordion.Trigger className="profile-accordion-trigger">
                    <span className="profile-accordion-head">
                      <span className="profile-accordion-title">Add new skill</span>
                      <span className="profile-accordion-meta">Import from URL or upload a local file.</span>
                    </span>
                    <span className="status-chip">Catalog</span>
                    <span className="profile-accordion-chevron" aria-hidden="true">
                      <Icon path="M6 9l6 6 6-6" />
                    </span>
                  </Accordion.Trigger>
                </Accordion.Header>
                <Accordion.Content className="profile-accordion-content">
                  <div className="admin-create">
                    <div className="admin-skill-import-grid">
                      <label className="field-control">
                        <span className="field-label">Source URL</span>
                        <input
                          value={skillSourceUrl}
                          onChange={(event) => setSkillSourceUrl(event.target.value)}
                          placeholder="https://example.com/skills/jira-execution.md"
                          autoComplete="off"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Skill key (optional)</span>
                        <input
                          value={skillKey}
                          onChange={(event) => setSkillKey(event.target.value)}
                          placeholder="github_delivery"
                          autoComplete="off"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Mode</span>
                        <AdminSelect
                          value={skillMode}
                          onValueChange={(nextMode) => setSkillMode(nextMode === 'enforced' ? 'enforced' : 'advisory')}
                          options={SKILL_MODE_OPTIONS}
                          ariaLabel="Skill mode"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Trust level</span>
                        <AdminSelect
                          value={skillTrustLevel}
                          onValueChange={(nextTrustLevel) => {
                            if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
                              setSkillTrustLevel(nextTrustLevel)
                            } else {
                              setSkillTrustLevel('reviewed')
                            }
                          }}
                          options={SKILL_TRUST_OPTIONS}
                          ariaLabel="Skill trust level"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                        />
                      </label>
                      <div className="admin-skill-import-actions row wrap">
                        <button
                          className="status-chip admin-skill-action-btn"
                          type="button"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending || !String(skillSourceUrl || '').trim()}
                          title="Add skill from URL"
                          aria-label="Add skill from URL"
                          onClick={() => {
                            const sourceUrl = String(skillSourceUrl || '').trim()
                            if (!sourceUrl) return
                            void onImportWorkspaceSkill({
                              source_url: sourceUrl,
                              skill_key: String(skillKey || '').trim() || undefined,
                              mode: skillMode,
                              trust_level: skillTrustLevel,
                            })
                              .then(() => {
                                setSkillSourceUrl('')
                                setSkillKey('')
                                setSkillMode('advisory')
                                setSkillTrustLevel('reviewed')
                              })
                              .catch(() => {
                                // Error feedback is handled by app-level UI notice.
                              })
                          }}
                        >
                          <Icon path={importWorkspaceSkillPending ? 'M12 5v14M5 12h14' : 'M12 5v10m0 0l4-4m-4 4l-4-4M4 21h16'} />
                          <span>{importWorkspaceSkillPending ? 'Adding...' : 'Add from URL'}</span>
                        </button>
                        <button
                          className="status-chip admin-skill-action-btn"
                          type="button"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                          title="Upload skill file"
                          aria-label="Upload skill file"
                          onClick={() => workspaceSkillFileInputRef.current?.click()}
                        >
                          <Icon
                            path={
                              importWorkspaceSkillFilePending
                                ? 'M12 5v14M5 12h14'
                                : 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6'
                            }
                          />
                          <span>{importWorkspaceSkillFilePending ? 'Uploading...' : 'Upload file'}</span>
                        </button>
                        <input
                          ref={workspaceSkillFileInputRef}
                          type="file"
                          accept=".md,.markdown,.txt,.json,text/plain,text/markdown,application/json"
                          style={{ display: 'none' }}
                          onChange={(event) => {
                            const file = event.target.files?.[0]
                            event.currentTarget.value = ''
                            if (!file) return
                            void onImportWorkspaceSkillFile({
                              file,
                              skill_key: String(skillKey || '').trim() || undefined,
                              mode: skillMode,
                              trust_level: skillTrustLevel,
                            })
                              .then(() => {
                                setSkillSourceUrl('')
                                setSkillKey('')
                                setSkillMode('advisory')
                                setSkillTrustLevel('reviewed')
                              })
                              .catch(() => {
                                // Error feedback is handled by app-level UI notice.
                              })
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </Accordion.Content>
              </Accordion.Item>
            </Accordion.Root>

            <div className="row wrap" style={{ marginTop: 8, marginBottom: 8 }}>
              <input
                value={skillsSearchQ}
                onChange={(event) => setSkillsSearchQ(event.target.value)}
                placeholder="Filter catalog by name, key, summary, or source"
                style={{ flex: 1, minWidth: 240 }}
              />
            </div>
            <div className="rules-list">
              {workspaceSkillsLoading ? (
                <div className="notice">Loading workspace catalog...</div>
              ) : filteredWorkspaceSkillItems.length === 0 ? (
                <div className="notice">No workspace skills found.</div>
              ) : (
                filteredWorkspaceSkillItems.map((skill) => {
                  const isExpanded = selectedWorkspaceSkillId === skill.id
                  const selectedThisSkill = isExpanded && selectedWorkspaceSkill?.id === skill.id
                  return (
                    <div
                      key={skill.id}
                      className={`task-item rule-item ${isExpanded ? 'selected' : ''}`.trim()}
                      onClick={() => setSelectedWorkspaceSkillId((current) => (current === skill.id ? null : skill.id))}
                      role="button"
                      aria-expanded={isExpanded}
                    >
                      <div className="task-main">
                        <div className="task-title">
                          <div className="row" style={{ gap: 6, minWidth: 0 }}>
                            {skill.is_seeded ? <span className="rule-kind-chip">[SEEDED]</span> : null}
                            <strong>{skill.name || skill.skill_key || 'Untitled catalog skill'}</strong>
                          </div>
                          <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                              <button
                                className="action-icon danger-ghost"
                                type="button"
                                disabled={deleteWorkspaceSkillPending}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  const confirmed = window.confirm(`Delete catalog skill "${skill.name || skill.skill_key}"?`)
                                  if (!confirmed) return
                                  void onDeleteWorkspaceSkill(skill.id).catch(() => {
                                    // Error feedback is handled by app-level UI notice.
                                  })
                                }}
                                title="Delete catalog skill"
                                aria-label="Delete catalog skill"
                              >
                                <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                              </button>
                            </Tooltip.Trigger>
                            <Tooltip.Portal>
                              <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                Remove skill from workspace catalog
                                <Tooltip.Arrow className="header-tooltip-arrow" />
                              </Tooltip.Content>
                            </Tooltip.Portal>
                          </Tooltip.Root>
                        </div>
                        <div className="meta">
                          key: {skill.skill_key || '-'} | mode: {skill.mode || '-'} | trust: {skill.trust_level || '-'}
                        </div>
                        <div className="meta">{(skill.summary || '').replace(/\s+/g, ' ').slice(0, 160) || '(no summary)'}</div>
                        <div className="meta">source: {skill.source_locator || '(none)'}</div>
                        {selectedThisSkill ? (
                          <div
                            className="note-accordion"
                            onClick={(event) => event.stopPropagation()}
                            role="region"
                            aria-label="Catalog skill details"
                          >
                            <div className="row rule-title-row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                              <input
                                className="rule-title-input"
                                value={workspaceSkillEditorName}
                                onChange={(event) => setWorkspaceSkillEditorName(event.target.value)}
                                placeholder="Skill name"
                              />
                              <button
                                className="action-icon primary"
                                type="button"
                                disabled={!workspaceSkillEditorName.trim() || !workspaceSkillEditorDirty || patchWorkspaceSkillPending}
                                onClick={() => {
                                  void onPatchWorkspaceSkill({
                                    skillId: skill.id,
                                    patch: {
                                      name: workspaceSkillEditorName.trim(),
                                      summary: workspaceSkillEditorSummary,
                                      content: workspaceSkillEditorContent,
                                      mode: workspaceSkillEditorMode,
                                      trust_level: workspaceSkillEditorTrustLevel,
                                    },
                                  }).catch(() => {
                                    // Error feedback is handled by app-level UI notice.
                                  })
                                }}
                                title="Save skill changes"
                                aria-label="Save skill changes"
                              >
                                <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                              </button>
                            </div>
                            <div className="row wrap" style={{ gap: 8, marginBottom: 8 }}>
                              <label className="field-control admin-inline-field" style={{ minWidth: 150, marginBottom: 0 }}>
                                <span className="field-label">Mode</span>
                                <AdminSelect
                                  value={workspaceSkillEditorMode}
                                  onValueChange={(nextMode) =>
                                    setWorkspaceSkillEditorMode(nextMode === 'enforced' ? 'enforced' : 'advisory')
                                  }
                                  options={SKILL_MODE_OPTIONS}
                                  ariaLabel="Catalog skill mode"
                                  disabled={patchWorkspaceSkillPending}
                                />
                              </label>
                              <label className="field-control admin-inline-field" style={{ minWidth: 170, marginBottom: 0 }}>
                                <span className="field-label">Trust level</span>
                                <AdminSelect
                                  value={workspaceSkillEditorTrustLevel}
                                  onValueChange={(nextTrustLevel) => {
                                    if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
                                      setWorkspaceSkillEditorTrustLevel(nextTrustLevel)
                                    } else {
                                      setWorkspaceSkillEditorTrustLevel('reviewed')
                                    }
                                  }}
                                  options={SKILL_TRUST_OPTIONS}
                                  ariaLabel="Catalog skill trust level"
                                  disabled={patchWorkspaceSkillPending}
                                />
                              </label>
                            </div>
                            <div className="md-editor-surface">
                              <div className="md-editor-content">
                                <textarea
                                  className="md-textarea"
                                  value={workspaceSkillEditorSummary}
                                  onChange={(event) => setWorkspaceSkillEditorSummary(event.target.value)}
                                  placeholder="Skill summary"
                                  style={{ width: '100%', minHeight: 96 }}
                                />
                              </div>
                            </div>
                            <div className="meta" style={{ marginTop: 8 }}>
                              Source: {skill.source_locator || '(none)'}
                            </div>
                            <div className="meta" style={{ marginTop: 8 }}>Skill content</div>
                            <div className="md-editor-surface">
                              <MarkdownModeToggle
                                view={workspaceSkillContentView}
                                onChange={setWorkspaceSkillContentView}
                                ariaLabel="Catalog skill content editor view"
                              />
                              <div className="md-editor-content">
                                {workspaceSkillContentView === 'write' ? (
                                  <textarea
                                    className="md-textarea"
                                    value={workspaceSkillEditorContent}
                                    onChange={(event) => setWorkspaceSkillEditorContent(event.target.value)}
                                    placeholder="Write skill content in Markdown..."
                                    style={{ width: '100%', minHeight: 180 }}
                                  />
                                ) : workspaceSkillContentView === 'split' ? (
                                  <MarkdownSplitPane
                                    left={(
                                      <textarea
                                        className="md-textarea"
                                        value={workspaceSkillEditorContent}
                                        onChange={(event) => setWorkspaceSkillEditorContent(event.target.value)}
                                        placeholder="Write skill content in Markdown..."
                                        style={{ width: '100%', minHeight: 180 }}
                                      />
                                    )}
                                    right={<MarkdownView value={workspaceSkillEditorContent} />}
                                    ariaLabel="Resize workspace skill editor and preview panels"
                                  />
                                ) : (
                                  <MarkdownView value={workspaceSkillEditorContent} />
                                )}
                              </div>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </Tabs.Content>
      </Tabs.Root>
      </section>
    </Tooltip.Provider>
  )
}

export function TaskResultsPanel({
  tasks,
  total,
  showProject,
  projectNames,
  specificationNames,
  onOpenSpecification,
  onOpen,
  onTagClick,
  onRestore,
  onReopen,
  onComplete,
}: {
  tasks: Task[]
  total: number
  showProject: boolean
  projectNames: Record<string, string>
  specificationNames: Record<string, string>
  onOpenSpecification: (specificationId: string, projectId: string) => void
  onOpen: (taskId: string) => void
  onTagClick?: (tag: string) => void
  onRestore: (taskId: string) => void
  onReopen: (taskId: string) => void
  onComplete: (taskId: string) => void
}) {
  return (
    <section className="card">
      <h2>Tasks ({total})</h2>
      <div className="task-list">
        {tasks.map((task) => (
          <TaskListItem
            key={task.id}
            task={task}
            onOpen={onOpen}
            onOpenSpecification={onOpenSpecification}
            onTagClick={onTagClick}
            onRestore={onRestore}
            onReopen={onReopen}
            onComplete={onComplete}
            showProject={showProject}
            projectName={projectNames[task.project_id]}
            specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
          />
        ))}
      </div>
    </section>
  )
}

export function GlobalSearchResultsPanel({
  tasks,
  tasksTotal,
  notes,
  notesTotal,
  specifications,
  specificationsTotal,
  searchQuery,
  semanticMode,
  semanticSearching,
  semanticTaskIds,
  semanticNoteIds,
  semanticSpecificationIds,
  lexicalTaskIds,
  lexicalNoteIds,
  lexicalSpecificationIds,
  projectNames,
  specificationNames,
  onOpenSpecification,
  onOpenTask,
  onTaskTagClick,
  onNoteTagClick,
  onSpecificationTagClick,
  onRestoreTask,
  onReopenTask,
  onCompleteTask,
  onOpenNote,
}: {
  tasks: Task[]
  tasksTotal: number
  notes: Note[]
  notesTotal: number
  specifications: Specification[]
  specificationsTotal: number
  searchQuery: string
  semanticMode: string
  semanticSearching: boolean
  semanticTaskIds: string[]
  semanticNoteIds: string[]
  semanticSpecificationIds: string[]
  lexicalTaskIds: string[]
  lexicalNoteIds: string[]
  lexicalSpecificationIds: string[]
  projectNames: Record<string, string>
  specificationNames: Record<string, string>
  onOpenSpecification: (specificationId: string, projectId: string) => void
  onOpenTask: (taskId: string) => void
  onTaskTagClick: (tag: string) => void
  onNoteTagClick: (tag: string) => void
  onSpecificationTagClick: (tag: string) => void
  onRestoreTask: (taskId: string) => void
  onReopenTask: (taskId: string) => void
  onCompleteTask: (taskId: string) => void
  onOpenNote: (noteId: string, projectId?: string | null) => boolean
}) {
  const normalizedQuery = String(searchQuery || '').trim()
  const normalizedSemanticMode = String(semanticMode || 'empty').trim().toLowerCase()
  const semanticTaskSet = React.useMemo(() => new Set((semanticTaskIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [semanticTaskIds])
  const semanticNoteSet = React.useMemo(() => new Set((semanticNoteIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [semanticNoteIds])
  const semanticSpecificationSet = React.useMemo(
    () => new Set((semanticSpecificationIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)),
    [semanticSpecificationIds]
  )
  const lexicalTaskSet = React.useMemo(() => new Set((lexicalTaskIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [lexicalTaskIds])
  const lexicalNoteSet = React.useMemo(() => new Set((lexicalNoteIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [lexicalNoteIds])
  const lexicalSpecificationSet = React.useMemo(
    () => new Set((lexicalSpecificationIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)),
    [lexicalSpecificationIds]
  )
  const semanticAddedTaskSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticTaskSet) {
      if (!lexicalTaskSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalTaskSet, semanticTaskSet])
  const semanticAddedNoteSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticNoteSet) {
      if (!lexicalNoteSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalNoteSet, semanticNoteSet])
  const semanticAddedSpecificationSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticSpecificationSet) {
      if (!lexicalSpecificationSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalSpecificationSet, semanticSpecificationSet])
  const semanticAddedCount = semanticAddedTaskSet.size + semanticAddedNoteSet.size + semanticAddedSpecificationSet.size
  const totalResults = tasksTotal + notesTotal + specificationsTotal

  const semanticModeLabel = (() => {
    if (normalizedSemanticMode === 'graph+vector') return 'Graph + vector'
    if (normalizedSemanticMode === 'vector-only') return 'Vector only'
    if (normalizedSemanticMode === 'graph-only') return 'Graph only'
    if (normalizedSemanticMode === 'empty') return 'No semantic context'
    return normalizedSemanticMode || 'Unknown'
  })()
  const semanticModeClassSuffix = (() => {
    if (normalizedSemanticMode === 'graph+vector') return 'graph-vector'
    if (normalizedSemanticMode === 'vector-only') return 'vector-only'
    if (normalizedSemanticMode === 'graph-only') return 'graph-only'
    return 'empty'
  })()

  const renderTasksSection = () => (
    <section className="card">
      <h2>Tasks ({tasksTotal})</h2>
      <div className="task-list">
        {tasks.length === 0 ? (
          <div className="notice">No matching tasks.</div>
        ) : (
          tasks.map((task) => (
            <TaskListItem
              key={task.id}
              task={task}
              onOpen={onOpenTask}
              onOpenSpecification={onOpenSpecification}
              onTagClick={onTaskTagClick}
              onRestore={onRestoreTask}
              onReopen={onReopenTask}
              onComplete={onCompleteTask}
              semanticHit={semanticAddedTaskSet.has(String(task.id))}
              showProject
              projectName={projectNames[task.project_id]}
              specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
            />
          ))
        )}
      </div>
    </section>
  )

  const renderNotesSection = () => (
    <section className="card">
      <h2>Notes ({notesTotal})</h2>
      <div className="task-list">
        {notes.length === 0 ? (
          <div className="notice">No matching notes.</div>
        ) : (
          notes.map((note) => {
            const semanticHit = semanticAddedNoteSet.has(String(note.id))
            return (
              <div key={note.id} className="note-row search-result-row">
                <div className="note-title">
                  <div className="note-title-main">
                    {note.archived && <span className="badge">Archived</span>}
                    {note.pinned && <span className="badge">Pinned</span>}
                    <strong>{note.title || 'Untitled'}</strong>
                  </div>
                  <div className="task-title-badges">
                    {semanticHit ? <span className="task-kind-pill task-kind-pill-semantic">SEMANTIC</span> : null}
                  </div>
                  <div className="note-row-actions">
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          className="action-icon note-row-actions-trigger"
                          type="button"
                          title="Note result actions"
                          aria-label="Note result actions"
                        >
                          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                          <DropdownMenu.Item className="task-group-menu-item" onSelect={() => onOpenNote(note.id, note.project_id)}>
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                            <span>Open note</span>
                          </DropdownMenu.Item>
                          {note.specification_id ? (
                            <DropdownMenu.Item
                              className="task-group-menu-item"
                              onSelect={() => onOpenSpecification(note.specification_id as string, note.project_id)}
                            >
                              <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
                              <span>Open specification</span>
                            </DropdownMenu.Item>
                          ) : null}
                          {(note.tags ?? []).length > 0 ? (
                            <>
                              <DropdownMenu.Separator className="task-group-menu-separator" />
                              {(note.tags ?? []).map((tag) => (
                                <DropdownMenu.Item
                                  key={`note-result-tag-${note.id}-${tag}`}
                                  className="task-group-menu-item"
                                  onSelect={() => onNoteTagClick(tag)}
                                >
                                  <Icon path="M20 10V4a1 1 0 0 0-1-1h-6l-9 9 8 8 9-9zM14.5 7.5h.01" />
                                  <span>Filter by #{tag}</span>
                                </DropdownMenu.Item>
                              ))}
                            </>
                          ) : null}
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </div>
                <div className="meta" style={{ marginTop: 6 }}>{projectNames[note.project_id] || 'Unknown project'}</div>
                <div className="note-snippet">{(note.body || '').replace(/\s+/g, ' ').slice(0, 180) || '(empty)'}</div>
                {(note.tags ?? []).length > 0 && (
                  <div className="note-tags" style={{ marginTop: 8 }}>
                    {(note.tags ?? []).map((tag) => (
                      <button
                        key={`${note.id}-${tag}`}
                        type="button"
                        className="tag-mini tag-clickable"
                        onClick={() => onNoteTagClick(tag)}
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
                <div className="row wrap" style={{ marginTop: 8, gap: 6 }}>
                  <button className="status-chip" onClick={() => onOpenNote(note.id, note.project_id)}>
                    Open note
                  </button>
                  {note.specification_id && (
                    <button
                      className="status-chip"
                      onClick={() => onOpenSpecification(note.specification_id as string, note.project_id)}
                    >
                      Open specification
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </section>
  )

  const renderSpecificationsSection = () => (
    <section className="card">
      <h2>Specifications ({specificationsTotal})</h2>
      <div className="task-list">
        {specifications.length === 0 ? (
          <div className="notice">No matching specifications.</div>
        ) : (
          specifications.map((specification) => {
            const semanticHit = semanticAddedSpecificationSet.has(String(specification.id))
            return (
              <div key={specification.id} className="note-row search-result-row">
                <div className="note-title">
                  <div className="note-title-main">
                    {specification.archived && <span className="badge">Archived</span>}
                    <strong>{specification.title || 'Untitled spec'}</strong>
                  </div>
                  <div className="task-title-badges">
                    {semanticHit ? <span className="task-kind-pill task-kind-pill-semantic">SEMANTIC</span> : null}
                  </div>
                  <div className="note-row-actions">
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          className="action-icon note-row-actions-trigger"
                          type="button"
                          title="Specification result actions"
                          aria-label="Specification result actions"
                        >
                          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                          <DropdownMenu.Item
                            className="task-group-menu-item"
                            onSelect={() => onOpenSpecification(specification.id, specification.project_id)}
                          >
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                            <span>Open specification</span>
                          </DropdownMenu.Item>
                          {(specification.tags ?? []).length > 0 ? (
                            <>
                              <DropdownMenu.Separator className="task-group-menu-separator" />
                              {(specification.tags ?? []).map((tag) => (
                                <DropdownMenu.Item
                                  key={`spec-result-tag-${specification.id}-${tag}`}
                                  className="task-group-menu-item"
                                  onSelect={() => onSpecificationTagClick(tag)}
                                >
                                  <Icon path="M20 10V4a1 1 0 0 0-1-1h-6l-9 9 8 8 9-9zM14.5 7.5h.01" />
                                  <span>Filter by #{tag}</span>
                                </DropdownMenu.Item>
                              ))}
                            </>
                          ) : null}
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </div>
                <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
                  <span className="status-chip">{specification.status}</span>
                  <span className="meta">{projectNames[specification.project_id] || 'Unknown project'}</span>
                </div>
                <div className="note-snippet">{(specification.body || '').replace(/\s+/g, ' ').slice(0, 180) || '(empty)'}</div>
                {(specification.tags ?? []).length > 0 && (
                  <div className="task-tags" style={{ marginTop: 8 }}>
                    {(specification.tags ?? []).map((tag) => (
                      <button
                        key={`${specification.id}-${tag}`}
                        type="button"
                        className="tag-mini tag-clickable"
                        onClick={() => onSpecificationTagClick(tag)}
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
                <div className="row wrap" style={{ marginTop: 8 }}>
                  <button
                    className="status-chip"
                    onClick={() => onOpenSpecification(specification.id, specification.project_id)}
                  >
                    Open specification
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>
    </section>
  )

  return (
    <>
      <section className="card search-results-summary-card">
        <div className="search-results-summary-row">
          <div className="search-results-summary-title">
            <h2 style={{ margin: 0 }}>Results ({totalResults})</h2>
            {normalizedQuery ? (
              <span className="meta">Query: "{normalizedQuery}"</span>
            ) : (
              <span className="meta">Enter a query to narrow results.</span>
            )}
          </div>
          <div className="search-results-summary-badges">
            {semanticSearching ? (
              <span className="badge">Semantic: Searching...</span>
            ) : (
              <span className={`badge search-semantic-mode-badge mode-${semanticModeClassSuffix}`}>
                Semantic: {semanticModeLabel}
              </span>
            )}
            {semanticAddedCount > 0 ? <span className="badge">Semantic additions: {semanticAddedCount}</span> : null}
          </div>
        </div>
      </section>

      <Tabs.Root className="search-results-tabs" defaultValue="all">
        <Tabs.List className="search-results-tabs-list" aria-label="Search result sections">
          <Tabs.Trigger className="search-results-tab-trigger" value="all">
            All
            <span className="search-results-tab-count">{totalResults}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="tasks">
            Tasks
            <span className="search-results-tab-count">{tasksTotal}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="notes">
            Notes
            <span className="search-results-tab-count">{notesTotal}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="specifications">
            Specs
            <span className="search-results-tab-count">{specificationsTotal}</span>
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className="search-results-tab-content" value="all">
          {renderTasksSection()}
          {renderNotesSection()}
          {renderSpecificationsSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="tasks">
          {renderTasksSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="notes">
          {renderNotesSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="specifications">
          {renderSpecificationsSection()}
        </Tabs.Content>
      </Tabs.Root>

      {normalizedQuery.length >= 3 && !semanticSearching && semanticAddedCount === 0 ? (
        <section className="card">
          <div className="notice">
            Semantic search is active, but this query currently has no additional semantic matches.
          </div>
        </section>
      ) : null}
    </>
  )
}
