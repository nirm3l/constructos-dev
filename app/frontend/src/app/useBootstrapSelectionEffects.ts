import React from 'react'

export function useBootstrapSelectionEffects(c: any) {
  React.useEffect(() => {
    const fromBackend = c.bootstrap.data?.current_user?.theme
    if (fromBackend === 'dark' || fromBackend === 'light') c.setTheme(fromBackend)
  }, [c.bootstrap.data?.current_user?.theme, c.setTheme])

  React.useEffect(() => {
    const firstProjectId = c.bootstrap.data?.projects[0]?.id ?? ''
    const validSelected = Boolean(c.selectedProjectId && (c.bootstrap.data?.projects ?? []).some((p: any) => p.id === c.selectedProjectId))
    if ((!c.selectedProjectId || !validSelected) && firstProjectId) c.setSelectedProjectId(firstProjectId)
  }, [c.bootstrap.data, c.selectedProjectId, c.setSelectedProjectId])

  React.useEffect(() => {
    if (!c.bootstrap.data || c.urlInitAppliedRef.current) return
    c.urlInitAppliedRef.current = true
    const params = new URLSearchParams(window.location.search)
    const urlProject = params.get('project')
    if (urlProject && !(c.bootstrap.data.projects ?? []).some((p: any) => p.id === urlProject)) {
      params.delete('project')
      params.delete('task')
      params.delete('note')
      const next = params.toString()
      window.history.replaceState(null, '', next ? `?${next}` : window.location.pathname)
    }
  }, [c.bootstrap.data, c.urlInitAppliedRef])

  React.useEffect(() => {
    if (!c.showProjectCreateForm) return
    if (c.createProjectMemberIds.length > 0) return
    if (!c.bootstrap.data?.current_user?.id) return
    c.setCreateProjectMemberIds([c.bootstrap.data.current_user.id])
  }, [c.showProjectCreateForm, c.createProjectMemberIds.length, c.bootstrap.data?.current_user?.id, c.setCreateProjectMemberIds])

  React.useEffect(() => {
    if (!c.showProjectEditForm || !c.selectedProjectId) return
    const ids = (c.bootstrap.data?.project_members ?? [])
      .filter((pm: any) => pm.project_id === c.selectedProjectId)
      .map((pm: any) => pm.user_id)
    const uniqueIds = Array.from(new Set(ids))
    c.setEditProjectMemberIds(uniqueIds)
  }, [c.showProjectEditForm, c.selectedProjectId, c.bootstrap.data?.project_members, c.setEditProjectMemberIds])
}
