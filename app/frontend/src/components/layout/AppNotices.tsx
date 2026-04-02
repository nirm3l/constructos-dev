import React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Icon } from '../shared/uiHelpers'

type LicenseNoticeState = {
  message: string
  isError: boolean
} | null

function _errorMessage(error: unknown): string {
  if (error instanceof Error) {
    const message = String(error.message || '').trim()
    if (message) return message
  }
  return 'License activation failed.'
}

function _daysRemaining(isoDate: string | null): number | null {
  if (!isoDate) return null
  const date = new Date(isoDate)
  if (Number.isNaN(date.getTime())) return null
  const diffMs = date.getTime() - Date.now()
  return Math.max(0, Math.ceil(diffMs / (24 * 60 * 60 * 1000)))
}

function _buildLicenseNotice(license: any): LicenseNoticeState {
  if (!license || typeof license !== 'object') return null
  const status = String(license.status || '').toLowerCase()
  if (!status || status === 'active') return null

  if (status === 'trial') {
    const days = _daysRemaining(license.trial_ends_at ?? null)
    const suffix = days === null ? '' : ` ${days} day${days === 1 ? '' : 's'} left.`
    return { message: `Trial mode.${suffix}`.trim(), isError: false }
  }

  if (status === 'grace') {
    const days = _daysRemaining(license.grace_ends_at ?? null)
    const suffix = days === null ? '' : ` ${days} day${days === 1 ? '' : 's'} left before write lock.`
    return { message: `Grace mode.${suffix}`.trim(), isError: false }
  }

  if (status === 'expired' || status === 'unlicensed') {
    return { message: 'License is expired. The application is currently in read-only mode.', isError: true }
  }

  return { message: `License status: ${status}.`, isError: false }
}

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

function _buildSparklinePath(points: number[]): string {
  if (!Array.isArray(points) || points.length <= 0) return ''
  if (points.length === 1) return 'M 0 18 L 34 18'
  const max = Math.max(...points)
  const min = Math.min(...points)
  const range = Math.max(1, max - min)
  const width = 34
  const height = 18
  return points
    .map((value, index) => {
      const x = Math.round((index / Math.max(1, points.length - 1)) * width * 100) / 100
      const normalized = (value - min) / range
      const y = Math.round((height - normalized * height) * 100) / 100
      return `${index === 0 ? 'M' : 'L'} ${x} ${y}`
    })
    .join(' ')
}

export function AppNotices({ state }: { state: any }) {
  const [activationCode, setActivationCode] = React.useState('')
  const [incidentModalOpen, setIncidentModalOpen] = React.useState(false)
  const [incidentModalRecoveryFeedback, setIncidentModalRecoveryFeedback] = React.useState<string | null>(null)
  const [recoveryOutcomeToast, setRecoveryOutcomeToast] = React.useState<{
    tone: 'success' | 'error'
    message: string
  } | null>(null)
  const license = state.licenseStatus?.data?.license
  const status = String(license?.status || '').toLowerCase()
  const doctorStatus = state.workspaceDoctorQuery?.data ?? null
  const doctorRuntimeHealth = doctorStatus?.runtime_health ?? null
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
  const doctorTrendPath = _buildSparklinePath(doctorTrendScores)
  const doctorRecentActions = Array.isArray(doctorStatus?.recent_actions) ? doctorStatus.recent_actions : []
  const doctorLastFailure = doctorRecentActions.find((item: any) => _normalizeDoctorActionStatus(item?.status) === 'failed') ?? null
  const doctorLastRecovery = doctorRecentActions.find((item: any) => (
    String(item?.id || '').trim().toLowerCase() === 'recovery-sequence'
    && _normalizeDoctorActionStatus(item?.status) === 'passed'
  )) ?? null
  const runtimeHealthStatus = String(state.workspaceDoctorQuery?.data?.runtime_health?.overall_status || '').trim().toLowerCase()
  const previousRuntimeHealthStatusRef = React.useRef<string>('')
  const licenseNotice = React.useMemo(
    () => _buildLicenseNotice(state.licenseStatus?.data?.license),
    [state.licenseStatus?.data?.license]
  )
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
  const showDoctorTimeline = Boolean(runtimeHealthNotice || doctorLastFailure || doctorLastRecovery)
  const canActivate = ['trial', 'grace', 'expired', 'unlicensed'].includes(status)
  const activateLicenseMutation = state.activateLicenseMutation
  const executeDoctorQuickActionMutation = state.executeDoctorQuickActionMutation
  const replayRecoveryPending = Boolean(
    executeDoctorQuickActionMutation?.isPending
    && String(executeDoctorQuickActionMutation?.variables || '') === 'recovery-sequence'
  )
  const seatUsage = activateLicenseMutation?.data?.seat_usage

  React.useEffect(() => {
    if (activateLicenseMutation?.isSuccess) {
      setActivationCode('')
    }
  }, [activateLicenseMutation?.isSuccess])
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

  const submitActivation = React.useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const code = String(activationCode || '').trim()
      if (!code) return
      activateLicenseMutation?.mutate(code)
    },
    [activationCode, activateLicenseMutation]
  )
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
      {licenseNotice && (
        <div className={`notice ${licenseNotice.isError ? 'notice-error' : ''}`.trim()} role={licenseNotice.isError ? 'alert' : 'status'}>
          <span>{licenseNotice.message}</span>
        </div>
      )}
      {runtimeHealthNotice ? (
        <div className={`notice ${runtimeHealthNotice.tone === 'error' ? 'notice-error' : ''}`.trim()} role={runtimeHealthNotice.tone === 'error' ? 'alert' : 'status'}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span>{runtimeHealthNotice.message}</span>
            {typeof state.openWorkspaceDoctorIncident === 'function' ? (
              <button type="button" className="status-chip" onClick={() => state.openWorkspaceDoctorIncident()}>
                {runtimeHealthNotice.cta}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {showDoctorTimeline ? (
        <div className="notice" role="status">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <strong>Doctor Incident Timeline</strong>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {doctorLastFailure ? (
                <span className="status-chip" style={{ background: 'rgba(239, 68, 68, 0.14)', borderColor: 'rgba(239, 68, 68, 0.35)', color: '#7f1d1d' }}>
                  Last failure {_formatDoctorEventTime(doctorLastFailure?.at)}
                </span>
              ) : null}
              {doctorLastRecovery ? (
                <span className="status-chip" style={{ background: 'rgba(16, 185, 129, 0.16)', borderColor: 'rgba(16, 185, 129, 0.35)', color: '#065f46' }}>
                  Last recovery {_formatDoctorEventTime(doctorLastRecovery?.at)}
                </span>
              ) : null}
              {doctorCurrentScore !== null ? (
                <span className="status-chip">
                  Health score {Math.round(doctorCurrentScore * 10) / 10}
                  {doctorScoreDelta !== null ? ` (${_formatScoreDelta(doctorScoreDelta)})` : ''}
                </span>
              ) : null}
              {doctorTrendPath ? (
                <span className="status-chip" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span>Trend</span>
                  <svg viewBox="0 0 34 18" width="34" height="18" aria-hidden="true">
                    <path d={doctorTrendPath} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                </span>
              ) : null}
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
      {canActivate && (
        <div className="notice notice-license-activate" role="status">
          <div className="license-activate-header">
            <span>Activate subscription with code</span>
            {license?.installation_id && (
              <span className="license-installation-id">
                Installation ID: <code>{String(license.installation_id)}</code>
              </span>
            )}
          </div>
          <form className="license-activate-form" onSubmit={submitActivation}>
            <input
              value={activationCode}
              onChange={(event) => setActivationCode(event.target.value)}
              placeholder="Enter activation code"
              autoComplete="off"
            />
            <button type="submit" disabled={Boolean(activateLicenseMutation?.isPending) || !String(activationCode || '').trim()}>
              {activateLicenseMutation?.isPending ? 'Activating...' : 'Activate'}
            </button>
          </form>
          {activateLicenseMutation?.isError && (
            <p className="license-activate-error">{_errorMessage(activateLicenseMutation.error)}</p>
          )}
          {activateLicenseMutation?.isSuccess && seatUsage && (
            <p className="license-activate-meta">
              Seats in use: {seatUsage.active_installations}/{seatUsage.max_installations} ({seatUsage.customer_ref})
            </p>
          )}
        </div>
      )}
    </>
  )
}
