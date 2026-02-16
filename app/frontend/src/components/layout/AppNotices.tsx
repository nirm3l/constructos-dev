import React from 'react'
import { Icon } from '../shared/uiHelpers'

export function AppNotices({ state }: { state: any }) {
  return (
    <>
      {state.uiError && (
        <div className="notice notice-global" role="alert">
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
    </>
  )
}
