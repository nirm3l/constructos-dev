import React from 'react'
import { AppHeader } from './AppHeader'
import { AppNotices } from './AppNotices'
import { AppPrimaryPanels } from './AppPrimaryPanels'
import { AppOverlays } from './AppOverlays'

export function AppContent({ state }: { state: any }) {
  const handleHeaderProjectSelect = React.useCallback((projectId: string) => {
    const normalizedProjectId = String(projectId || '').trim()
    if (!normalizedProjectId) return
    if (normalizedProjectId === state.selectedProjectId) return

    const shouldStabilizeScroll = typeof window !== 'undefined'
    const scrollY = shouldStabilizeScroll ? window.scrollY : 0
    const scrollX = shouldStabilizeScroll ? window.scrollX : 0

    if (state.tab === 'projects' && state.showProjectEditForm) {
      if (state.projectIsDirty && !state.confirmDiscardChanges()) return
      state.setShowProjectCreateForm(false)
      state.setShowProjectEditForm(false)
    }
    if (state.tab === 'notes' && state.selectedNoteId) {
      if (state.noteIsDirty && !state.confirmDiscardChanges()) return
      state.setSelectedNoteId(null)
      state.setShowTagPicker(false)
      state.setTagPickerQuery('')
    }

    state.setSelectedProjectId(normalizedProjectId)

    if (shouldStabilizeScroll) {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          window.scrollTo({ top: scrollY, left: scrollX, behavior: 'auto' })
        })
      })
    }
  }, [
    state.confirmDiscardChanges,
    state.noteIsDirty,
    state.selectedNoteId,
    state.projectIsDirty,
    state.selectedProjectId,
    state.setSelectedProjectId,
    state.setSelectedNoteId,
    state.setShowProjectCreateForm,
    state.setShowProjectEditForm,
    state.setShowTagPicker,
    state.setTagPickerQuery,
    state.showProjectEditForm,
    state.tab,
  ])

  return (
    <div className="page">
      <AppHeader
        bootstrapData={state.bootstrap.data}
        tab={state.tab}
        setTab={state.setTab}
        theme={state.theme}
        onToggleTheme={() => {
          const nextTheme = state.theme === 'light' ? 'dark' : 'light'
          state.setTheme(nextTheme)
          state.themeMutation.mutate(nextTheme)
        }}
        searchQ={state.searchQ}
        setSearchQ={state.setSearchQ}
        selectedProjectId={state.selectedProjectId}
        setSelectedProjectId={handleHeaderProjectSelect}
        showNotificationsPanel={state.showNotificationsPanel}
        setShowNotificationsPanel={state.setShowNotificationsPanel}
        notifications={state.notifications.data ?? []}
        unreadCount={state.unreadCount}
        onMarkRead={(notificationId) => state.markReadMutation.mutate(notificationId)}
        onMarkAllRead={() => state.markAllReadMutation.mutate()}
        isMarkAllReadPending={Boolean(state.markAllReadMutation?.isPending)}
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
