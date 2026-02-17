import React from 'react'
import { parseUrlTab } from '../utils/ui'

export function useUiPersistenceEffects(c: any) {
  const applyingHistoryRef = React.useRef(false)
  const lastSyncedSearchRef = React.useRef<string>('')

  const applyUrlState = React.useCallback((search: string, fromHistory: boolean) => {
    const params = new URLSearchParams(search)
    const normalizedSearch = search || ''
    lastSyncedSearchRef.current = normalizedSearch
    if (fromHistory) applyingHistoryRef.current = true

    const urlTab = parseUrlTab(params.get('tab'))
    if (urlTab) c.setTab(urlTab)

    const projectId = params.get('project')
    if (projectId) c.setSelectedProjectId(projectId)

    const taskId = params.get('task')
    c.setSelectedTaskId(taskId || null)
    if (taskId) c.setTab('tasks')

    const noteId = params.get('note')
    c.setSelectedNoteId(noteId || null)
    if (noteId) c.setTab('notes')

    const specificationId = params.get('specification')
    c.setSelectedSpecificationId(specificationId || null)
    if (specificationId) c.setTab('specifications')
  }, [c.setSelectedNoteId, c.setSelectedProjectId, c.setSelectedSpecificationId, c.setSelectedTaskId, c.setTab])

  React.useEffect(() => {
    localStorage.setItem('ui_tab', c.tab)
  }, [c.tab])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    applyUrlState(window.location.search, true)
    const onPopState = () => applyUrlState(window.location.search, true)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [applyUrlState])

  React.useEffect(() => {
    localStorage.setItem('ui_selected_project_id', c.selectedProjectId)
  }, [c.selectedProjectId])

  React.useEffect(() => {
    let raf = 0
    const onAnyScroll = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        c.setFabHidden(true)
        if (c.fabIdleTimerRef.current) window.clearTimeout(c.fabIdleTimerRef.current)
        c.fabIdleTimerRef.current = window.setTimeout(() => c.setFabHidden(false), 650)
      })
    }
    document.addEventListener('scroll', onAnyScroll, { passive: true, capture: true })
    return () => {
      if (raf) cancelAnimationFrame(raf)
      document.removeEventListener('scroll', onAnyScroll, { capture: true } as any)
      if (c.fabIdleTimerRef.current) window.clearTimeout(c.fabIdleTimerRef.current)
    }
  }, [c.fabIdleTimerRef, c.setFabHidden])

  React.useEffect(() => {
    localStorage.setItem('ui_projects_mode', c.projectsMode)
  }, [c.projectsMode])

  React.useEffect(() => {
    if (c.tab === 'notes') c.setSelectedTaskId(null)
    if (c.tab === 'specifications') {
      c.setSelectedTaskId(null)
      c.setSelectedNoteId(null)
    }
  }, [c.tab, c.setSelectedNoteId, c.setSelectedTaskId])

  React.useEffect(() => {
    if (c.tab !== 'projects') {
      c.setShowProjectCreateForm(false)
      c.setShowProjectEditForm(false)
    }
  }, [c.tab, c.setShowProjectCreateForm, c.setShowProjectEditForm])

  React.useEffect(() => {
    c.setShowNotificationsPanel(false)
  }, [c.tab, c.setShowNotificationsPanel])

  React.useEffect(() => {
    document.documentElement.setAttribute('data-theme', c.theme)
  }, [c.theme])

  React.useLayoutEffect(() => {
    if (typeof window === 'undefined') return
    const params = new URLSearchParams(window.location.search)
    params.set('tab', c.tab)
    if (c.selectedProjectId) params.set('project', c.selectedProjectId)
    else params.delete('project')
    if (c.selectedTaskId) params.set('task', c.selectedTaskId)
    else params.delete('task')
    if (c.selectedNoteId) params.set('note', c.selectedNoteId)
    else params.delete('note')
    if (c.selectedSpecificationId) params.set('specification', c.selectedSpecificationId)
    else params.delete('specification')
    const next = params.toString()
    const nextSearch = next ? `?${next}` : ''
    if (lastSyncedSearchRef.current === nextSearch) {
      if (applyingHistoryRef.current) applyingHistoryRef.current = false
      return
    }
    if (window.location.search === nextSearch) {
      lastSyncedSearchRef.current = nextSearch
      if (applyingHistoryRef.current) applyingHistoryRef.current = false
      return
    }
    if (applyingHistoryRef.current) {
      window.history.replaceState(null, '', `${window.location.pathname}${nextSearch}`)
      lastSyncedSearchRef.current = nextSearch
      applyingHistoryRef.current = false
      return
    }
    window.history.pushState(null, '', `${window.location.pathname}${nextSearch}`)
    lastSyncedSearchRef.current = nextSearch
  }, [c.tab, c.selectedProjectId, c.selectedTaskId, c.selectedNoteId, c.selectedSpecificationId])
}
