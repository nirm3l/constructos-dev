import React from 'react'
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

export function AppNotices({ state }: { state: any }) {
  const [activationCode, setActivationCode] = React.useState('')
  const license = state.licenseStatus?.data?.license
  const status = String(license?.status || '').toLowerCase()
  const licenseNotice = React.useMemo(
    () => _buildLicenseNotice(state.licenseStatus?.data?.license),
    [state.licenseStatus?.data?.license]
  )
  const canActivate = ['trial', 'grace', 'expired', 'unlicensed'].includes(status)
  const activateLicenseMutation = state.activateLicenseMutation
  const seatUsage = activateLicenseMutation?.data?.seat_usage

  React.useEffect(() => {
    if (activateLicenseMutation?.isSuccess) {
      setActivationCode('')
    }
  }, [activateLicenseMutation?.isSuccess])

  const submitActivation = React.useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const code = String(activationCode || '').trim()
      if (!code) return
      activateLicenseMutation?.mutate(code)
    },
    [activationCode, activateLicenseMutation]
  )

  return (
    <>
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
