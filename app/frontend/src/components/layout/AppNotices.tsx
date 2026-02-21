import React from 'react'
import { Icon } from '../shared/uiHelpers'

type LicenseNoticeState = {
  message: string
  isError: boolean
} | null

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
  const licenseNotice = React.useMemo(
    () => _buildLicenseNotice(state.licenseStatus?.data?.license),
    [state.licenseStatus?.data?.license]
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
    </>
  )
}
