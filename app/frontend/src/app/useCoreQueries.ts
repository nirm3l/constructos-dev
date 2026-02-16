import { useQueries, useQuery } from '@tanstack/react-query'
import {
  getNotifications,
  getNotes,
  getProjectBoard,
  getProjectRules,
  getProjectTags,
  getTasks,
} from '../api'

export function useCoreQueries(c: any) {
  const tasks = useQuery({
    queryKey: ['tasks', c.userId, c.workspaceId, c.tab, c.selectedProjectId, c.searchQ, c.searchStatus, c.searchPriority, c.searchArchived, c.searchTags.join(',')],
    queryFn: () => getTasks(c.userId, c.workspaceId, c.taskParams),
    enabled: Boolean(c.workspaceId && c.taskParams) && (c.tab === 'today' || c.tab === 'tasks' || c.tab === 'search')
  })

  const notes = useQuery({
    queryKey: ['notes', c.userId, c.workspaceId, c.selectedProjectId, c.noteQ, c.noteArchived, c.noteTags.join(',')],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        q: c.noteQ || undefined,
        tags: c.noteTags,
        archived: c.noteArchived
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'notes'
  })

  const projectTags = useQuery({
    queryKey: ['project-tags', c.userId, c.selectedProjectId],
    queryFn: () => getProjectTags(c.userId, c.selectedProjectId),
    enabled: Boolean(c.selectedProjectId)
  })

  const projectRules = useQuery({
    queryKey: ['project-rules', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getProjectRules(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'projects'
  })

  const projectTaskCountQueries = useQueries({
    queries: (c.projects ?? []).map((project: any) => ({
      queryKey: ['project-task-count', c.userId, c.workspaceId, project.id],
      queryFn: () => getTasks(c.userId, c.workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
      enabled: Boolean(c.workspaceId && c.tab === 'projects')
    }))
  })

  const projectNoteCountQueries = useQueries({
    queries: (c.projects ?? []).map((project: any) => ({
      queryKey: ['project-note-count', c.userId, c.workspaceId, project.id],
      queryFn: () => getNotes(c.userId, c.workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
      enabled: Boolean(c.workspaceId && c.tab === 'projects')
    }))
  })

  const projectRuleCountQueries = useQueries({
    queries: (c.projects ?? []).map((project: any) => ({
      queryKey: ['project-rule-count', c.userId, c.workspaceId, project.id],
      queryFn: () => getProjectRules(c.userId, c.workspaceId, { project_id: project.id, limit: 1, offset: 0 }),
      enabled: Boolean(c.workspaceId && c.tab === 'projects')
    }))
  })

  const notifications = useQuery({
    queryKey: ['notifications', c.userId],
    queryFn: () => getNotifications(c.userId),
    enabled: Boolean(c.userId)
  })

  const board = useQuery({
    queryKey: ['board', c.userId, c.selectedProjectId],
    queryFn: () => getProjectBoard(c.userId, c.selectedProjectId),
    enabled: Boolean(c.selectedProjectId && c.tab === 'tasks' && c.projectsMode === 'board')
  })

  return {
    tasks,
    notes,
    projectTags,
    projectRules,
    projectTaskCountQueries,
    projectNoteCountQueries,
    projectRuleCountQueries,
    notifications,
    board,
  }
}
