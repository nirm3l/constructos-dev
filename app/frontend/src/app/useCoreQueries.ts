import { useQueries, useQuery } from '@tanstack/react-query'
import {
  getNoteGroups,
  getNotifications,
  getNotes,
  getProjectBoard,
  getProjectGraphContextPack,
  getProjectEventStormingOverview,
  getProjectEventStormingSubgraph,
  getProjectGraphOverview,
  getProjectGraphSubgraph,
  getProjectTaskDependencyGraph,
  getProjectRules,
  getProjectSkills,
  getNote,
  getWorkspaceSkills,
  listProjectTemplates,
  searchProjectKnowledge,
  getSpecification,
  getTaskGroups,
  getTask,
  getSpecifications,
  getProjectTags,
  getTasks,
} from '../api'

export function useCoreQueries(c: any) {
  const normalizedSearchQ = String(c.searchQ || '').trim()
  const canRunSemanticSearch =
    Boolean(c.workspaceId && c.selectedProjectId) &&
    c.tab === 'search' &&
    normalizedSearchQ.length >= 3 &&
    Boolean(c.vectorStoreEnabled) &&
    Boolean(c.selectedProjectEmbeddingEnabled) &&
    (c.selectedProjectEmbeddingIndexStatus === 'ready' || c.selectedProjectEmbeddingIndexStatus === 'stale')

  const tasks = useQuery({
    queryKey: ['tasks', c.userId, c.workspaceId, c.tab, c.selectedProjectId, c.searchQ, c.searchStatus, c.searchPriority, c.searchArchived, c.searchTags.join(','), c.taskParams?.limit, c.taskParams?.offset],
    queryFn: () => getTasks(c.userId, c.workspaceId, c.taskParams),
    enabled: Boolean(c.workspaceId && c.taskParams) && (c.tab === 'inbox' || c.tab === 'tasks' || c.tab === 'search')
  })

  const selectedTask = useQuery({
    queryKey: ['task', c.userId, c.selectedTaskId],
    queryFn: () => getTask(c.userId, c.selectedTaskId),
    enabled: Boolean(c.userId && c.selectedTaskId && c.tab === 'tasks'),
  })

  const taskLookup = useQuery({
    queryKey: ['task-lookup', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getTasks(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        limit: 500,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId),
  })

  const notes = useQuery({
    queryKey: ['notes', c.userId, c.workspaceId, c.selectedProjectId, c.noteGroupFilterId, c.noteArchived, c.noteTags.join(','), c.notesPageLimit],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        note_group_id: c.noteGroupFilterId || undefined,
        tags: c.noteTags,
        archived: c.noteArchived,
        limit: c.notesPageLimit,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'notes'
  })

  const taskGroups = useQuery({
    queryKey: ['task-groups', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getTaskGroups(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId),
  })

  const noteGroups = useQuery({
    queryKey: ['note-groups', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getNoteGroups(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId),
  })

  const noteLookup = useQuery({
    queryKey: ['note-lookup', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        limit: 500,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId),
  })

  const selectedNote = useQuery({
    queryKey: ['note', c.userId, c.selectedNoteId],
    queryFn: () => getNote(c.userId, c.selectedNoteId),
    enabled: Boolean(c.userId && c.selectedNoteId && c.tab === 'notes'),
  })

  const searchNotes = useQuery({
    queryKey: ['search-notes', c.userId, c.workspaceId, c.selectedProjectId, c.searchQ, c.searchArchived, c.searchTags.join(',')],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        q: c.searchQ || undefined,
        tags: c.searchTags,
        archived: c.searchArchived,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'search'
  })

  const taskNotes = useQuery({
    queryKey: ['task-notes', c.userId, c.workspaceId, c.selectedProjectId, c.selectedTaskId],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        task_id: c.selectedTaskId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId && c.selectedTaskId) && c.tab === 'tasks',
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

  const projectSkills = useQuery({
    queryKey: ['project-skills', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getProjectSkills(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'projects'
  })

  const workspaceSkills = useQuery({
    queryKey: ['workspace-skills', c.userId, c.workspaceId],
    queryFn: () => getWorkspaceSkills(c.userId, c.workspaceId),
    enabled: Boolean(c.workspaceId) && (c.tab === 'projects' || c.tab === 'settings'),
  })

  const projectTemplates = useQuery({
    queryKey: ['project-templates', c.userId],
    queryFn: () => listProjectTemplates(c.userId),
    enabled: Boolean(c.workspaceId) && c.tab === 'projects',
  })

  const projectGraphOverview = useQuery({
    queryKey: ['project-graph-overview', c.userId, c.selectedProjectId],
    queryFn: () => getProjectGraphOverview(c.userId, c.selectedProjectId),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'knowledge-graph'),
  })

  const projectGraphContextPack = useQuery({
    queryKey: ['project-graph-context-pack', c.userId, c.selectedProjectId],
    queryFn: () => getProjectGraphContextPack(c.userId, c.selectedProjectId, { limit: 20 }),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'knowledge-graph'),
  })

  const projectGraphSubgraph = useQuery({
    queryKey: ['project-graph-subgraph', c.userId, c.selectedProjectId],
    queryFn: () => getProjectGraphSubgraph(c.userId, c.selectedProjectId, { limit_nodes: 48, limit_edges: 160 }),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'knowledge-graph'),
  })

  const projectEventStormingOverview = useQuery({
    queryKey: ['project-event-storming-overview', c.userId, c.selectedProjectId],
    queryFn: () => getProjectEventStormingOverview(c.userId, c.selectedProjectId),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'knowledge-graph'),
  })

  const projectEventStormingSubgraph = useQuery({
    queryKey: ['project-event-storming-subgraph', c.userId, c.selectedProjectId],
    queryFn: () => getProjectEventStormingSubgraph(c.userId, c.selectedProjectId, { limit_nodes: 120, limit_edges: 220 }),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'knowledge-graph'),
  })

  const projectTaskDependencyGraph = useQuery({
    queryKey: ['project-task-dependency-graph', c.userId, c.selectedProjectId],
    queryFn: () => getProjectTaskDependencyGraph(c.userId, c.selectedProjectId, { limit_nodes: 240, limit_edges: 1600 }),
    enabled: Boolean(c.selectedProjectId) && (c.tab === 'projects' || c.tab === 'task-flow'),
  })
  const specificationArchivedFilter = c.specificationStatus === 'Archived'

  const specifications = useQuery({
    queryKey: [
      'specifications',
      c.userId,
      c.workspaceId,
      c.selectedProjectId,
      c.specificationStatus,
      specificationArchivedFilter,
      c.specificationTags.join(','),
      c.specificationsPageLimit,
    ],
    queryFn: () =>
      getSpecifications(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        status: c.specificationStatus || undefined,
        tags: c.specificationTags,
        archived: specificationArchivedFilter,
        limit: c.specificationsPageLimit,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'specifications',
  })

  const searchSpecifications = useQuery({
    queryKey: [
      'search-specifications',
      c.userId,
      c.workspaceId,
      c.selectedProjectId,
      c.searchQ,
      c.searchArchived,
      c.searchSpecificationStatus,
      c.searchTags.join(','),
    ],
    queryFn: () =>
      getSpecifications(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        q: c.searchQ || undefined,
        status: c.searchSpecificationStatus || undefined,
        tags: c.searchTags,
        archived: c.searchArchived,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId) && c.tab === 'search',
  })

  const searchKnowledge = useQuery({
    queryKey: ['search-knowledge', c.userId, c.selectedProjectId, normalizedSearchQ],
    queryFn: () =>
      searchProjectKnowledge(c.userId, c.selectedProjectId, {
        q: normalizedSearchQ,
        limit: 24,
      }),
    enabled: canRunSemanticSearch,
    retry: 1,
    staleTime: 15_000,
  })

  const specificationLookup = useQuery({
    queryKey: ['specification-lookup', c.userId, c.workspaceId, c.selectedProjectId],
    queryFn: () =>
      getSpecifications(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        limit: 500,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId),
  })

  const selectedSpecification = useQuery({
    queryKey: ['specification', c.userId, c.selectedSpecificationId],
    queryFn: () => getSpecification(c.userId, c.selectedSpecificationId),
    enabled: Boolean(c.userId && c.selectedSpecificationId && c.tab === 'specifications'),
  })

  const specTasks = useQuery({
    queryKey: ['spec-tasks', c.userId, c.workspaceId, c.selectedProjectId, c.selectedSpecificationId],
    queryFn: () =>
      getTasks(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        specification_id: c.selectedSpecificationId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId && c.selectedSpecificationId) && c.tab === 'specifications',
  })

  const specNotes = useQuery({
    queryKey: ['spec-notes', c.userId, c.workspaceId, c.selectedProjectId, c.selectedSpecificationId],
    queryFn: () =>
      getNotes(c.userId, c.workspaceId, {
        project_id: c.selectedProjectId,
        specification_id: c.selectedSpecificationId,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(c.workspaceId && c.selectedProjectId && c.selectedSpecificationId) && c.tab === 'specifications',
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
    queryKey: ['board', c.userId, c.selectedProjectId, c.searchTags.join(',')],
    queryFn: () => getProjectBoard(c.userId, c.selectedProjectId, { tags: c.searchTags }),
    enabled: Boolean(c.selectedProjectId && c.tab === 'tasks' && c.projectsMode === 'board')
  })

  return {
    tasks,
    selectedTask,
    taskLookup,
    notes,
    selectedNote,
    taskGroups,
    noteGroups,
    noteLookup,
    searchNotes,
    taskNotes,
    projectTags,
    projectRules,
    projectSkills,
    workspaceSkills,
    projectTemplates,
    projectGraphOverview,
    projectGraphContextPack,
    projectGraphSubgraph,
    projectEventStormingOverview,
    projectEventStormingSubgraph,
    projectTaskDependencyGraph,
    specifications,
    selectedSpecification,
    searchSpecifications,
    searchKnowledge,
    specificationLookup,
    specTasks,
    specNotes,
    projectTaskCountQueries,
    projectNoteCountQueries,
    projectRuleCountQueries,
    notifications,
    board,
  }
}
