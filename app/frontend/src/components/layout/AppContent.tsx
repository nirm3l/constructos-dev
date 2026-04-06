import React from 'react'
import { AppHeader } from './AppHeader'
import { AppNotices } from './AppNotices'
import { AppPrimaryPanels } from './AppPrimaryPanels'
import { AppOverlays } from './AppOverlays'
import { OnboardingTour } from './OnboardingTour'
import { toggleTheme } from '../../theme'

export function AppContent({ state }: { state: any }) {
  const tourControlsRef = React.useRef<{ startQuick: () => void; startAdvanced: () => void } | null>(null)
  const doctorStatusPayload = state.workspaceDoctorQuery?.data ?? null
  const doctorState = String(doctorStatusPayload?.doctor_state || '').trim().toLowerCase()
  const doctorReady = doctorState === 'ready'

  const handleHeaderProjectSelect = React.useCallback((projectId: string) => {
    const normalizedProjectId = String(projectId || '').trim()
    if (!normalizedProjectId) return
    if (normalizedProjectId === state.selectedProjectId) return

    const shouldStabilizeScroll = typeof window !== 'undefined'
    const scrollY = shouldStabilizeScroll ? window.scrollY : 0
    const scrollX = shouldStabilizeScroll ? window.scrollX : 0

    if (state.tab === 'projects' && state.showProjectEditForm) {
      if (state.projectIsDirty || state.projectEditorHasUnsavedChanges) {
        state.requestDiscardChanges?.('You have unsaved project changes. Discard them?', () => {
          state.setShowProjectCreateForm(false)
          state.setShowProjectEditForm(false)
          state.setProjectEditorHasUnsavedChanges?.(false)
          state.setSelectedProjectId(normalizedProjectId)
          if (shouldStabilizeScroll) {
            window.requestAnimationFrame(() => {
              window.requestAnimationFrame(() => {
                window.scrollTo({ top: scrollY, left: scrollX, behavior: 'auto' })
              })
            })
          }
        })
        return
      }
      state.setShowProjectCreateForm(false)
      state.setShowProjectEditForm(false)
    }
    if (state.tab === 'notes' && state.selectedNoteId) {
      if (state.noteIsDirty) {
        state.requestDiscardChanges?.('You have unsaved note changes. Discard them?', () => {
          state.setSelectedNoteId(null)
          state.setShowTagPicker(false)
          state.setTagPickerQuery('')
          state.setSelectedProjectId(normalizedProjectId)
          if (shouldStabilizeScroll) {
            window.requestAnimationFrame(() => {
              window.requestAnimationFrame(() => {
                window.scrollTo({ top: scrollY, left: scrollX, behavior: 'auto' })
              })
            })
          }
        })
        return
      }
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
          const nextTheme = toggleTheme(state.theme)
          state.setTheme(nextTheme)
          state.themeMutation.mutate(nextTheme)
        }}
        searchQ={state.searchQ}
        setSearchQ={state.setSearchQ}
        selectedProjectId={state.selectedProjectId}
        setSelectedProjectId={handleHeaderProjectSelect}
        showNotificationsPanel={state.showNotificationsPanel}
        setShowNotificationsPanel={state.setShowNotificationsPanel}
        notifications={state.notificationsForHeader ?? state.notifications.data ?? []}
        unreadCount={state.unreadCount}
        onMarkRead={(notificationId) =>
          typeof state.handleMarkNotificationRead === 'function'
            ? state.handleMarkNotificationRead(notificationId)
            : state.markReadMutation.mutate(notificationId)}
        onMarkUnread={(notificationId) =>
          typeof state.handleMarkNotificationUnread === 'function'
            ? state.handleMarkNotificationUnread(notificationId)
            : state.markUnreadMutation.mutate(notificationId)}
        onMarkAllRead={() => state.markAllReadMutation.mutate()}
        isMarkAllReadPending={Boolean(state.markAllReadMutation?.isPending)}
        onOpenTask={state.openTask}
        onOpenNote={state.openNote}
        onOpenSpecification={state.openSpecification}
        onOpenProject={(projectId) => {
          state.setSelectedProjectId(projectId)
          state.setTab('projects')
        }}
        doctorRuntimeStatus={doctorReady ? (doctorStatusPayload?.runtime_health?.overall_status ?? null) : null}
        onOpenDoctorIncident={state.openWorkspaceDoctorIncident}
        onStartQuickTour={() => tourControlsRef.current?.startQuick()}
        onStartAdvancedTour={() => tourControlsRef.current?.startAdvanced()}
      />

      <OnboardingTour
        userId={state.userId}
        workspaceId={state.workspaceId}
        tourPreferencesLoaded={Boolean(state.bootstrap.data?.current_user)}
        quickTourCompleted={state.bootstrap.data?.current_user?.onboarding_quick_tour_completed === true}
        advancedTourCompleted={state.bootstrap.data?.current_user?.onboarding_advanced_tour_completed === true}
        setTab={state.setTab}
        setShowQuickAdd={state.setShowQuickAdd}
        setShowCodexChat={state.setShowCodexChat}
        saveTourProgress={state.saveOnboardingTourProgress}
        registerControls={(controls) => {
          tourControlsRef.current = controls
        }}
      />

      <AppNotices state={state} />
      <AppPrimaryPanels state={state} />
      <AppOverlays state={state} />
    </div>
  )
}
