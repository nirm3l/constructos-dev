import React from 'react'
import { parseUrlTab } from '../utils/ui'
import { getThemeBrand, getThemeMode, normalizeTheme } from '../theme'

export function useUiPersistenceEffects(c: any) {
  const applyingHistoryRef = React.useRef(false)
  const lastSyncedSearchRef = React.useRef<string>('')
  const initialUrlAppliedRef = React.useRef(false)

  const applyUrlState = React.useCallback((search: string, fromHistory: boolean) => {
    const params = new URLSearchParams(search)
    const normalizedSearch = search || ''
    lastSyncedSearchRef.current = normalizedSearch
    if (fromHistory) applyingHistoryRef.current = true

    const urlTab = parseUrlTab(params.get('tab'))
    const projectId = params.get('project')
    if (projectId) c.setSelectedProjectId(projectId)

    const taskId = params.get('task')
    const noteId = params.get('note')
    const specificationId = params.get('specification')
    const inferredTab = specificationId ? 'specifications' : noteId ? 'notes' : taskId ? 'tasks' : null
    const resolvedTab = urlTab ?? inferredTab

    if (resolvedTab === 'tasks') {
      c.setSelectedTaskId(taskId || null)
      c.setSelectedNoteId(null)
      c.setSelectedSpecificationId(null)
    } else if (resolvedTab === 'notes') {
      c.setSelectedTaskId(null)
      c.setSelectedNoteId(noteId || null)
      c.setSelectedSpecificationId(null)
    } else if (resolvedTab === 'specifications') {
      c.setSelectedTaskId(null)
      c.setSelectedNoteId(null)
      c.setSelectedSpecificationId(specificationId || null)
    } else {
      c.setSelectedTaskId(taskId || null)
      c.setSelectedNoteId(noteId || null)
      c.setSelectedSpecificationId(specificationId || null)
    }

    if (resolvedTab) c.setTab(resolvedTab)
    if (resolvedTab === 'projects' && projectId) {
      c.setShowProjectCreateForm(false)
      c.setShowProjectEditForm(true)
    }
  }, [
    c.setSelectedNoteId,
    c.setSelectedProjectId,
    c.setSelectedSpecificationId,
    c.setSelectedTaskId,
    c.setShowProjectCreateForm,
    c.setShowProjectEditForm,
    c.setTab,
  ])

  React.useEffect(() => {
    localStorage.setItem('ui_tab', c.tab)
  }, [c.tab])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    applyUrlState(window.location.search, true)
    initialUrlAppliedRef.current = true
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
    const normalizedTheme = normalizeTheme(c.theme)
    document.documentElement.setAttribute('data-theme', getThemeMode(normalizedTheme))
    document.documentElement.setAttribute('data-theme-brand', getThemeBrand(normalizedTheme))
    document.documentElement.setAttribute('data-theme-key', normalizedTheme)
  }, [c.theme])

  React.useLayoutEffect(() => {
    if (typeof window === 'undefined') return
    // Prevent initial URL state from being overwritten before query params are applied.
    if (!initialUrlAppliedRef.current) return
    const params = new URLSearchParams(window.location.search)
    params.set('tab', c.tab)
    if (c.selectedProjectId) params.set('project', c.selectedProjectId)
    else params.delete('project')
    if (c.tab === 'tasks' && c.selectedTaskId) params.set('task', c.selectedTaskId)
    else params.delete('task')
    if (c.tab === 'notes' && c.selectedNoteId) params.set('note', c.selectedNoteId)
    else params.delete('note')
    if (c.tab === 'specifications' && c.selectedSpecificationId) params.set('specification', c.selectedSpecificationId)
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
