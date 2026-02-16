import React from 'react'
import { Icon } from '../shared/uiHelpers'

export function ProjectsHeader({
  totalProjects,
  showProjectCreateForm,
  showProjectEditForm,
  projectIsDirty,
  confirmDiscardChanges,
  setShowProjectEditForm,
  setShowProjectCreateForm,
}: {
  totalProjects: number
  showProjectCreateForm: boolean
  showProjectEditForm: boolean
  projectIsDirty: boolean
  confirmDiscardChanges: () => boolean
  setShowProjectEditForm: React.Dispatch<React.SetStateAction<boolean>>
  setShowProjectCreateForm: React.Dispatch<React.SetStateAction<boolean>>
}) {
  return (
    <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
      <h2 style={{ margin: 0 }}>Projects ({totalProjects})</h2>
      <div className="row" style={{ gap: 8 }}>
        <button
          className="primary"
          onClick={() => {
            if (showProjectEditForm && projectIsDirty && !confirmDiscardChanges()) return
            setShowProjectEditForm(false)
            setShowProjectCreateForm((v) => !v)
          }}
          title={showProjectCreateForm ? 'Close create' : 'New project'}
          aria-label={showProjectCreateForm ? 'Close create' : 'New project'}
        >
          <Icon path={showProjectCreateForm ? 'M6 6l12 12M18 6L6 18' : 'M12 5v14M5 12h14'} />
        </button>
      </div>
    </div>
  )
}
