import React from 'react'
import { AppHeader } from './AppHeader'
import { AppNotices } from './AppNotices'
import { AppPrimaryPanels } from './AppPrimaryPanels'
import { AppOverlays } from './AppOverlays'

export function AppContent({ state }: { state: any }) {
  return (
    <div className="page">
      <AppHeader
        bootstrapData={state.bootstrap.data}
        tab={state.tab}
        setTab={state.setTab}
        searchQ={state.searchQ}
        setSearchQ={state.setSearchQ}
        selectedProjectId={state.selectedProjectId}
        setSelectedProjectId={state.setSelectedProjectId}
        showNotificationsPanel={state.showNotificationsPanel}
        setShowNotificationsPanel={state.setShowNotificationsPanel}
        notifications={state.notifications.data ?? []}
        unreadCount={state.unreadCount}
        onMarkRead={(notificationId) => state.markReadMutation.mutate(notificationId)}
        onOpenTask={state.openTask}
        onOpenNote={state.openNote}
        onOpenSpecification={state.openSpecification}
        onOpenProject={(projectId) => {
          state.setSelectedProjectId(projectId)
          state.setTab('projects')
        }}
      />

      <AppNotices state={state} />
      <AppPrimaryPanels state={state} />
      <AppOverlays state={state} />
    </div>
  )
}
