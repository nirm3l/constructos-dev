import React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Icon } from '../shared/uiHelpers'

function _normalizeDoctorActionStatus(value: unknown): 'passed' | 'warning' | 'failed' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'passed') return 'passed'
  if (normalized === 'failed' || normalized === 'failing') return 'failed'
  return 'warning'
}

function _formatDoctorEventTime(value: unknown): string {
  const raw = String(value || '').trim()
  if (!raw) return 'n/a'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  return parsed.toLocaleString()
}

function _toFiniteNumber(value: unknown): number | null {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  return parsed
}

function _formatScoreDelta(value: number | null): string {
  if (value === null) return 'n/a'
  if (value > 0) return `+${value}`
  return String(value)
}

function _isRecentDoctorEvent(value: unknown, withinHours = 24): boolean {
  const raw = String(value || '').trim()
  if (!raw) return false
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return false
  const ageMs = Date.now() - parsed.getTime()
  if (!Number.isFinite(ageMs) || ageMs < 0) return false
  return ageMs <= withinHours * 60 * 60 * 1000
}

function _buildTrendLabel(points: number[], scoreDelta: number | null): string {
  if (scoreDelta !== null) {
    if (scoreDelta >= 1) return 'Improving'
    if (scoreDelta <= -1) return 'Declining'
    return 'Stable'
  }
  if (!Array.isArray(points) || points.length < 2) return 'Unknown'
  const first = points[0] ?? 0
  const last = points[points.length - 1] ?? first
  const drift = last - first
  if (drift >= 1) return 'Improving'
  if (drift <= -1) return 'Declining'
  return 'Stable'
}

export function AppNotices({ state }: { state: any }) {
  const [incidentModalOpen, setIncidentModalOpen] = React.useState(false)
  const [incidentModalRecoveryFeedback, setIncidentModalRecoveryFeedback] = React.useState<string | null>(null)
  const [recoveryOutcomeToast, setRecoveryOutcomeToast] = React.useState<{
    tone: 'success' | 'error'
    message: string
  } | null>(null)
  const doctorStatus = state.workspaceDoctorQuery?.data ?? null
  const doctorRuntimeHealth = doctorStatus?.runtime_health ?? null
  const doctorIncidentTotal = _toFiniteNumber(doctorStatus?.checks?.recent_executor_worktree_incident_count) ?? 0
  const doctorIncidentOpen = _toFiniteNumber(doctorStatus?.checks?.recent_executor_worktree_open_incident_count) ?? 0
  const doctorCurrentScore = _toFiniteNumber(doctorRuntimeHealth?.health_score)
  const doctorRecentRuns = Array.isArray(doctorStatus?.recent_runs) ? doctorStatus.recent_runs : []
  const doctorPreviousSnapshot = doctorRecentRuns
    .map((item: any) => {
      const summary = item?.summary
      if (!summary || typeof summary !== 'object') return null
      const snapshot = (summary as Record<string, unknown>).runtime_health_snapshot
      return snapshot && typeof snapshot === 'object' ? (snapshot as Record<string, unknown>) : null
    })
    .find((item: Record<string, unknown> | null) => item && _toFiniteNumber(item.health_score) !== null) ?? null
  const doctorPreviousScore = _toFiniteNumber(doctorPreviousSnapshot?.health_score)
  const doctorScoreDelta = doctorCurrentScore !== null && doctorPreviousScore !== null
    ? Math.round((doctorCurrentScore - doctorPreviousScore) * 10) / 10
    : null
  const doctorTrendScores = doctorRecentRuns
    .map((item: any) => {
      const summary = item?.summary
      if (!summary || typeof summary !== 'object') return null
      const snapshot = (summary as Record<string, unknown>).runtime_health_snapshot
      if (!snapshot || typeof snapshot !== 'object') return null
      return _toFiniteNumber((snapshot as Record<string, unknown>).health_score)
    })
    .filter((item: number | null): item is number => item !== null)
    .slice(0, 6)
    .reverse()
  if (doctorCurrentScore !== null && doctorTrendScores.length === 0) {
    doctorTrendScores.push(doctorCurrentScore)
  }
  const doctorTrendLabel = _buildTrendLabel(doctorTrendScores, doctorScoreDelta)
  const doctorRecentActions = Array.isArray(doctorStatus?.recent_actions) ? doctorStatus.recent_actions : []
  const doctorLastFailure = doctorRecentActions.find((item: any) => _normalizeDoctorActionStatus(item?.status) === 'failed') ?? null
  const doctorLastRecovery = doctorRecentActions.find((item: any) => (
    String(item?.id || '').trim().toLowerCase() === 'recovery-sequence'
    && _normalizeDoctorActionStatus(item?.status) === 'passed'
  )) ?? null
  const runtimeHealthStatus = String(state.workspaceDoctorQuery?.data?.runtime_health?.overall_status || '').trim().toLowerCase()
  const previousRuntimeHealthStatusRef = React.useRef<string>('')
  const runtimeHealthNotice = React.useMemo(() => {
    if (runtimeHealthStatus === 'failing') {
      return {
        tone: 'error' as const,
        message: 'ConstructOS runtime health is failing. Immediate intervention is recommended.',
        cta: 'Open Doctor Incident Mode',
      }
    }
    if (runtimeHealthStatus === 'warning') {
      return {
        tone: 'warning' as const,
        message: 'ConstructOS runtime health has warnings. Review and resolve before degradation escalates.',
        cta: 'Review Doctor Health',
      }
    }
    return null
  }, [runtimeHealthStatus])
  const doctorIncidentNotice = React.useMemo(() => {
    const total = Math.max(0, Math.round(doctorIncidentTotal))
    const open = Math.max(0, Math.round(doctorIncidentOpen))
    if (open <= 0) return null
    return {
      tone: 'error' as const,
      message: `Executor worktree incidents are open: ${open} open of ${total} total.`,
    }
  }, [doctorIncidentOpen, doctorIncidentTotal])
  const executeDoctorQuickActionMutation = state.executeDoctorQuickActionMutation
  const replayRecoveryPending = Boolean(
    executeDoctorQuickActionMutation?.isPending
    && String(executeDoctorQuickActionMutation?.variables || '') === 'recovery-sequence'
  )
  const executorDiagnosticsPending = Boolean(
    executeDoctorQuickActionMutation?.isPending
    && String(executeDoctorQuickActionMutation?.variables || '') === 'executor-worktree-guard-diagnostics'
  )
  const effectiveRuntimeHealthNotice = doctorIncidentNotice ? null : runtimeHealthNotice
  const hasRecentDoctorFailure = _isRecentDoctorEvent(doctorLastFailure?.at, 24)
  const showDoctorTimelineEffective = Boolean(
    effectiveRuntimeHealthNotice
    || doctorIncidentNotice
    || replayRecoveryPending
    || executorDiagnosticsPending
    || hasRecentDoctorFailure
  )
  React.useEffect(() => {
    if (!recoveryOutcomeToast) return
    const timer = window.setTimeout(() => setRecoveryOutcomeToast(null), 9000)
    return () => window.clearTimeout(timer)
  }, [recoveryOutcomeToast])
  React.useEffect(() => {
    if (typeof window === 'undefined') {
      previousRuntimeHealthStatusRef.current = runtimeHealthStatus
      return
    }
    const previousStatus = String(previousRuntimeHealthStatusRef.current || '').trim().toLowerCase()
    previousRuntimeHealthStatusRef.current = runtimeHealthStatus
    const workspaceKey = String(state.workspaceId || 'default').trim() || 'default'
    const seenKey = `ui_doctor_incident_modal_seen:${workspaceKey}`
    let seen = false
    try {
      seen = window.sessionStorage.getItem(seenKey) === '1'
    } catch {
      seen = false
    }
    if (runtimeHealthStatus === 'failing' && previousStatus !== 'failing' && !seen) {
      setIncidentModalOpen(true)
      setIncidentModalRecoveryFeedback(null)
      try {
        window.sessionStorage.setItem(seenKey, '1')
      } catch {
        // Ignore session storage failures; modal can re-open in restrictive browsers.
      }
    }
  }, [runtimeHealthStatus, state.workspaceId])

  const runRecoverySequenceWithTelemetry = React.useCallback(async () => {
    if (!executeDoctorQuickActionMutation?.mutateAsync) return
    const startedAt = (typeof performance !== 'undefined' && typeof performance.now === 'function')
      ? performance.now()
      : Date.now()
    const beforeScore = doctorCurrentScore
    setIncidentModalRecoveryFeedback(null)
    try {
      const response = await executeDoctorQuickActionMutation.mutateAsync('recovery-sequence')
      const endedAt = (typeof performance !== 'undefined' && typeof performance.now === 'function')
        ? performance.now()
        : Date.now()
      const elapsedMs = Math.max(0, Math.round(endedAt - startedAt))
      const afterScoreRaw = (response?.status?.runtime_health as Record<string, unknown> | undefined)?.health_score
      const afterScore = _toFiniteNumber(afterScoreRaw)
      const delta = beforeScore !== null && afterScore !== null
        ? Math.round((afterScore - beforeScore) * 10) / 10
        : null
      const statusLabel = String(response?.status?.runtime_health?.overall_status || 'unknown').trim().toLowerCase() || 'unknown'
      const deltaLabel = delta === null ? 'n/a' : _formatScoreDelta(delta)
      const toastMessage = `Recovery complete: ${statusLabel}. Duration ${elapsedMs} ms. Health delta ${deltaLabel}.`
      setIncidentModalRecoveryFeedback('Recovery sequence queued.')
      setRecoveryOutcomeToast({
        tone: response?.ok === false ? 'error' : 'success',
        message: toastMessage,
      })
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Recovery sequence failed to queue.'
      setIncidentModalRecoveryFeedback(message)
      setRecoveryOutcomeToast({
        tone: 'error',
        message: `Recovery failed: ${message}`,
      })
    }
  }, [doctorCurrentScore, executeDoctorQuickActionMutation])
  const runExecutorDiagnosticsWithTelemetry = React.useCallback(async () => {
    if (!executeDoctorQuickActionMutation?.mutateAsync) return
    try {
      const response = await executeDoctorQuickActionMutation.mutateAsync('executor-worktree-guard-diagnostics')
      const healthLabel = String(response?.status?.runtime_health?.overall_status || 'unknown').trim().toLowerCase() || 'unknown'
      setRecoveryOutcomeToast({
        tone: response?.ok === false ? 'error' : 'success',
        message: `Executor diagnostics completed: ${healthLabel}.`,
      })
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Executor diagnostics failed.'
      setRecoveryOutcomeToast({
        tone: 'error',
        message: `Executor diagnostics failed: ${message}`,
      })
    }
  }, [executeDoctorQuickActionMutation])

  return (
    <>
      {recoveryOutcomeToast ? (
        <div className={`notice notice-global ${recoveryOutcomeToast.tone === 'error' ? 'notice-error' : ''}`.trim()} role={recoveryOutcomeToast.tone === 'error' ? 'alert' : 'status'}>
          <span>{recoveryOutcomeToast.message}</span>
          <button className="action-icon" onClick={() => setRecoveryOutcomeToast(null)} title="Dismiss" aria-label="Dismiss">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      ) : null}
      <Dialog.Root open={incidentModalOpen} onOpenChange={setIncidentModalOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="codex-chat-alert-overlay" />
          <Dialog.Content className="codex-chat-alert-content docker-runtime-dialog">
            <div className="codex-chat-alert-head">
              <Dialog.Title className="codex-chat-alert-title">System incident detected</Dialog.Title>
              <Dialog.Description className="codex-chat-alert-description">
                ConstructOS runtime health is currently failing. Start recovery now or open the full incident panel.
              </Dialog.Description>
            </div>
            <div className="row" style={{ gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
              <button
                type="button"
                className="primary"
                disabled={!executeDoctorQuickActionMutation || replayRecoveryPending}
                onClick={() => {
                  void runRecoverySequenceWithTelemetry()
                }}
              >
                {replayRecoveryPending ? 'Running recovery...' : 'Run recovery sequence'}
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={() => {
                  if (typeof state.openWorkspaceDoctorIncident === 'function') {
                    state.openWorkspaceDoctorIncident()
                  }
                  setIncidentModalOpen(false)
                }}
              >
                Open incident view
              </button>
              <Dialog.Close asChild>
                <button type="button" className="button-secondary">
                  Dismiss
                </button>
              </Dialog.Close>
            </div>
            {incidentModalRecoveryFeedback ? (
              <div className="notice" style={{ marginTop: 10 }}>
                {incidentModalRecoveryFeedback}
              </div>
            ) : null}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      {state.uiError && (
        <div className="notice notice-error notice-global" role="alert">
          <span>{state.uiError}</span>
          <button className="action-icon" onClick={() => state.setUiError(null)} title="Dismiss" aria-label="Dismiss">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      )}
      {state.uiInfo && (
        <div className="notice notice-global" role="status">
          <span>{state.uiInfo}</span>
          <button className="action-icon" onClick={() => state.setUiInfo(null)} title="Dismiss" aria-label="Dismiss">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      )}
      {effectiveRuntimeHealthNotice ? (
        <div className={`notice ${effectiveRuntimeHealthNotice.tone === 'error' ? 'notice-error' : ''}`.trim()} role={effectiveRuntimeHealthNotice.tone === 'error' ? 'alert' : 'status'}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span>{effectiveRuntimeHealthNotice.message}</span>
            {typeof state.openWorkspaceDoctorIncident === 'function' ? (
              <button type="button" className="status-chip" onClick={() => state.openWorkspaceDoctorIncident()}>
                {effectiveRuntimeHealthNotice.cta}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {doctorIncidentNotice ? (
        <div className={`notice ${doctorIncidentNotice.tone === 'error' ? 'notice-error' : ''}`.trim()} role="alert">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span>{doctorIncidentNotice.message}</span>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="status-chip"
                disabled={!executeDoctorQuickActionMutation || executorDiagnosticsPending}
                onClick={() => {
                  void runExecutorDiagnosticsWithTelemetry()
                }}
              >
                {executorDiagnosticsPending ? 'Running diagnostics...' : 'Run executor diagnostics'}
              </button>
              {typeof state.openWorkspaceDoctorIncident === 'function' ? (
                <button type="button" className="status-chip" onClick={() => state.openWorkspaceDoctorIncident()}>
                  Open Doctor incidents
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      {showDoctorTimelineEffective ? (
        <div className="notice notice-doctor-timeline" role="status">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <strong>Doctor Incident Timeline</strong>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {doctorLastFailure ? (
                <span className="status-chip" style={{ background: 'rgba(239, 68, 68, 0.14)', borderColor: 'rgba(239, 68, 68, 0.35)', color: '#7f1d1d' }}>
                  Last failure {_formatDoctorEventTime(doctorLastFailure?.at)}
                </span>
              ) : null}
              {doctorLastRecovery ? (
                <span className="status-chip status-chip-recovery">
                  Last recovery {_formatDoctorEventTime(doctorLastRecovery?.at)}
                </span>
              ) : null}
              {doctorCurrentScore !== null ? (
                <span className="status-chip">
                  Health score {Math.round(doctorCurrentScore * 10) / 10}
                  {doctorScoreDelta !== null ? ` (${_formatScoreDelta(doctorScoreDelta)})` : ''}
                </span>
              ) : null}
              <span className="status-chip">Trend: {doctorTrendLabel}</span>
              <button
                type="button"
                className="status-chip"
                disabled={!executeDoctorQuickActionMutation || replayRecoveryPending}
                onClick={() => {
                  void runRecoverySequenceWithTelemetry()
                }}
              >
                {replayRecoveryPending ? 'Replaying...' : 'Replay recovery'}
              </button>
              {typeof state.openWorkspaceDoctorIncident === 'function' ? (
                <button type="button" className="status-chip" onClick={() => state.openWorkspaceDoctorIncident()}>
                  Open incident view
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
