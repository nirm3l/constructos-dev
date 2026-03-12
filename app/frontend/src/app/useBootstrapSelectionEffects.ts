import React from 'react'
import { normalizeAgentExecutionModel } from '../utils/agentExecution'

function normalizeReasoningEffort(value: unknown): 'low' | 'medium' | 'high' | 'xhigh' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'max' || normalized === 'maximum') return 'xhigh'
  if (normalized === 'low' || normalized === 'high' || normalized === 'xhigh') return normalized
  return 'medium'
}

export function useBootstrapSelectionEffects(c: any) {
  React.useEffect(() => {
    const fromBackend = c.bootstrap.data?.current_user?.theme
    if (fromBackend === 'dark' || fromBackend === 'light') c.setTheme(fromBackend)
  }, [c.bootstrap.data?.current_user?.theme, c.setTheme])

  React.useEffect(() => {
    const fromUser = normalizeAgentExecutionModel(c.bootstrap.data?.current_user?.agent_chat_model)
    const fromDefault = normalizeAgentExecutionModel(c.bootstrap.data?.agent_chat_default_model)
    c.setAgentChatModel(fromUser || fromDefault || '')
  }, [c.bootstrap.data?.current_user?.agent_chat_model, c.bootstrap.data?.agent_chat_default_model, c.setAgentChatModel])

  React.useEffect(() => {
    const rawUserValue = String(c.bootstrap.data?.current_user?.agent_chat_reasoning_effort || '').trim()
    const rawDefaultValue = String(c.bootstrap.data?.agent_chat_default_reasoning_effort || '').trim()
    const resolved = rawUserValue
      ? normalizeReasoningEffort(rawUserValue)
      : rawDefaultValue
        ? normalizeReasoningEffort(rawDefaultValue)
        : 'medium'
    c.setAgentChatReasoningEffort(resolved)
  }, [
    c.bootstrap.data?.current_user?.agent_chat_reasoning_effort,
    c.bootstrap.data?.agent_chat_default_reasoning_effort,
    c.setAgentChatReasoningEffort,
  ])

  React.useEffect(() => {
    const firstProjectId = c.bootstrap.data?.projects[0]?.id ?? ''
    const validSelected = Boolean(c.selectedProjectId && (c.bootstrap.data?.projects ?? []).some((p: any) => p.id === c.selectedProjectId))
    if ((!c.selectedProjectId || !validSelected) && firstProjectId) c.setSelectedProjectId(firstProjectId)
  }, [c.bootstrap.data, c.selectedProjectId, c.setSelectedProjectId])

  React.useEffect(() => {
    if (!c.bootstrap.data || c.urlInitAppliedRef.current) return
    c.urlInitAppliedRef.current = true
    const params = new URLSearchParams(window.location.search)
    const urlTab = params.get('tab')
    const urlProject = params.get('project')
    const projectExists = Boolean(urlProject && (c.bootstrap.data.projects ?? []).some((p: any) => p.id === urlProject))
    if (urlProject && !projectExists) {
      params.delete('project')
      params.delete('task')
      params.delete('note')
      params.delete('specification')
      const next = params.toString()
      window.history.replaceState(null, '', next ? `?${next}` : window.location.pathname)
      return
    }
    if (urlTab === 'projects' && projectExists) {
      c.setShowProjectCreateForm(false)
      c.setShowProjectEditForm(true)
    }
  }, [c.bootstrap.data, c.setShowProjectCreateForm, c.setShowProjectEditForm, c.urlInitAppliedRef])

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
