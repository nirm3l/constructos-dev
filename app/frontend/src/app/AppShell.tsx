import React from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { getBootstrap, linkTaskToSpecification } from '../api'
import { useCoreQueries } from './useCoreQueries'
import { useAppMutations } from './useAppMutations'
import { useProjectEditorEffects } from './useProjectEditorEffects'
import { useRealtimeEffects } from './useRealtimeEffects'
import { useTaskNoteEditorEffects } from './useTaskNoteEditorEffects'
import { useAppActions } from './useAppActions'
import { useTagState } from './useTagState'
import { useEditorGuards } from './useEditorGuards'
import { useTaskDetailsQueries } from './useTaskDetailsQueries'
import { useUiPersistenceEffects } from './useUiPersistenceEffects'
import { useBootstrapSelectionEffects } from './useBootstrapSelectionEffects'
import { useAppVersion } from './useAppVersion'
import { useBootstrapDerived } from './useBootstrapDerived'
import { useTaskQueryParams } from './useTaskQueryParams'
import { useEntityDisplayMeta } from './useEntityDisplayMeta'
import { useProjectState } from './useProjectState'
import { useCodexChatState } from './useCodexChatState'
import { useTaskEditorState } from './useTaskEditorState'
import { AppContent } from '../components/layout/AppContent'
import {
  DEFAULT_PROJECT_STATUSES,
  activityTone,
  attachmentRefsToText,
  externalRefsToText,
  formatActivitySummary,
  normalizeStoredUserId,
  parseAttachmentRefsText,
  parseCommaTags,
  parseExternalRefsText,
  parseUrlTab,
  parseStoredTab,
  priorityTone,
  removeAttachmentByPath,
  removeExternalRefByIndex,
  tagHue,
  toErrorMessage,
  toReadableDate,
  toUserDateTime
} from '../utils/ui'
import type { Tab } from '../utils/ui'
import '../styles.css'

const queryClient = new QueryClient()

function App() {
  const initialUrlStateRef = React.useRef<{
    tab: Tab | null
    projectId: string | null
    taskId: string | null
    noteId: string | null
    specificationId: string | null
  } | null>(null)
  if (!initialUrlStateRef.current) {
    if (typeof window === 'undefined') {
      initialUrlStateRef.current = {
        tab: null,
        projectId: null,
        taskId: null,
        noteId: null,
        specificationId: null,
      }
    } else {
      const params = new URLSearchParams(window.location.search)
      initialUrlStateRef.current = {
        tab: parseUrlTab(params.get('tab')),
        projectId: params.get('project'),
        taskId: params.get('task'),
        noteId: params.get('note'),
        specificationId: params.get('specification'),
      }
    }
  }
  const initialUrlState = initialUrlStateRef.current!

  const [userId] = React.useState<string>(() => normalizeStoredUserId(localStorage.getItem('user_id')))
  const [tab, setTab] = React.useState<Tab>(() => {
    if (initialUrlState.tab) return initialUrlState.tab
    if (initialUrlState.specificationId) return 'specifications'
    if (initialUrlState.noteId) return 'notes'
    if (initialUrlState.taskId) return 'tasks'
    return parseStoredTab(localStorage.getItem('ui_tab'))
  })
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light')
  const [taskTitle, setTaskTitle] = React.useState('')
  const [quickDueDate, setQuickDueDate] = React.useState('')
  const [quickDueDateFocused, setQuickDueDateFocused] = React.useState(false)
  const {
    projectName, setProjectName, projectDescription, setProjectDescription, projectCustomStatusesText, setProjectCustomStatusesText,
    projectExternalRefsText, setProjectExternalRefsText, projectAttachmentRefsText, setProjectAttachmentRefsText,
    projectEmbeddingEnabled, setProjectEmbeddingEnabled, projectEmbeddingModel, setProjectEmbeddingModel,
    projectContextPackEvidenceTopKText, setProjectContextPackEvidenceTopKText,
    projectDescriptionView, setProjectDescriptionView, showProjectCreateForm,
    setShowProjectCreateForm, showProjectEditForm, setShowProjectEditForm, editProjectName, setEditProjectName, editProjectDescription,
    setEditProjectDescription, editProjectCustomStatusesText, setEditProjectCustomStatusesText, editProjectExternalRefsText,
    setEditProjectExternalRefsText, editProjectAttachmentRefsText, setEditProjectAttachmentRefsText,
    editProjectEmbeddingEnabled, setEditProjectEmbeddingEnabled, editProjectEmbeddingModel, setEditProjectEmbeddingModel,
    editProjectContextPackEvidenceTopKText, setEditProjectContextPackEvidenceTopKText,
    createProjectMemberIds,
    setCreateProjectMemberIds, editProjectMemberIds, setEditProjectMemberIds, editProjectDescriptionView,
    setEditProjectDescriptionView, selectedProjectRuleId, setSelectedProjectRuleId, projectRuleTitle, setProjectRuleTitle,
    projectRuleBody, setProjectRuleBody, projectRuleView, setProjectRuleView, draftProjectRules, setDraftProjectRules,
    selectedDraftProjectRuleId, setSelectedDraftProjectRuleId, draftProjectRuleTitle, setDraftProjectRuleTitle,
    draftProjectRuleBody, setDraftProjectRuleBody, draftProjectRuleView, setDraftProjectRuleView, selectedProjectId,
    setSelectedProjectId, projectsMode, setProjectsMode,
  } = useProjectState()
  const [quickProjectId, setQuickProjectId] = React.useState<string>('')
  const [quickTaskTags, setQuickTaskTags] = React.useState<string[]>([])
  const [quickTaskExternalRefsText, setQuickTaskExternalRefsText] = React.useState('')
  const [quickTaskAttachmentRefsText, setQuickTaskAttachmentRefsText] = React.useState('')
  const [showQuickTaskTagPicker, setShowQuickTaskTagPicker] = React.useState(false)
  const [quickTaskTagQuery, setQuickTaskTagQuery] = React.useState('')
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(() => initialUrlState.taskId)
  const [selectedNoteId, setSelectedNoteId] = React.useState<string | null>(() => initialUrlState.noteId)
  const [searchQ, setSearchQ] = React.useState('')
  const [searchStatus, setSearchStatus] = React.useState('')
  const [searchSpecificationStatus, setSearchSpecificationStatus] = React.useState('')
  const [searchPriority, setSearchPriority] = React.useState('')
  const [searchTags, setSearchTags] = React.useState<string[]>([])
  const [searchArchived, setSearchArchived] = React.useState(false)
  const [noteTags, setNoteTags] = React.useState<string[]>([])
  const [noteArchived, setNoteArchived] = React.useState(false)
  const [specificationStatus, setSpecificationStatus] = React.useState('')
  const [specificationTags, setSpecificationTags] = React.useState<string[]>([])
  const [specificationArchived, setSpecificationArchived] = React.useState(false)
  const [selectedSpecificationId, setSelectedSpecificationId] = React.useState<string | null>(() => initialUrlState.specificationId)
  const [editSpecificationTitle, setEditSpecificationTitle] = React.useState('')
  const [editSpecificationBody, setEditSpecificationBody] = React.useState('')
  const [editSpecificationStatus, setEditSpecificationStatus] = React.useState('Draft')
  const [editSpecificationTags, setEditSpecificationTags] = React.useState('')
  const [editSpecificationExternalRefsText, setEditSpecificationExternalRefsText] = React.useState('')
  const [editSpecificationAttachmentRefsText, setEditSpecificationAttachmentRefsText] = React.useState('')
  const [specificationEditorView, setSpecificationEditorView] = React.useState<'write' | 'preview'>('preview')
  const [editNoteTitle, setEditNoteTitle] = React.useState('')
  const [editNoteBody, setEditNoteBody] = React.useState('')
  const [editNoteTags, setEditNoteTags] = React.useState('')
  const [editNoteExternalRefsText, setEditNoteExternalRefsText] = React.useState('')
  const [editNoteAttachmentRefsText, setEditNoteAttachmentRefsText] = React.useState('')
  const [showTagPicker, setShowTagPicker] = React.useState(false)
  const [tagPickerQuery, setTagPickerQuery] = React.useState('')
  const [noteEditorView, setNoteEditorView] = React.useState<'write' | 'preview'>('preview')
  const {
    editStatus, setEditStatus, editTitle, setEditTitle, editDescription, setEditDescription, editPriority, setEditPriority,
    editDueDate, setEditDueDate, editProjectId, setEditProjectId, editTaskTags, setEditTaskTags, editTaskExternalRefsText,
    setEditTaskExternalRefsText, editTaskAttachmentRefsText, setEditTaskAttachmentRefsText, showTaskTagPicker,
    setShowTaskTagPicker, taskTagPickerQuery, setTaskTagPickerQuery, editTaskType, setEditTaskType, editScheduledAtUtc,
    setEditScheduledAtUtc, editScheduleTimezone, setEditScheduleTimezone, editScheduledInstruction, setEditScheduledInstruction,
    editRecurringEvery, setEditRecurringEvery, editRecurringUnit, setEditRecurringUnit, commentBody, setCommentBody,
    expandedCommentIds, setExpandedCommentIds, automationInstruction, setAutomationInstruction, activityExpandedIds,
    setActivityExpandedIds, activityShowRawDetails, setActivityShowRawDetails, scrollToNewestComment, setScrollToNewestComment,
    uiError, setUiError, uiInfo, setUiInfo, taskEditorError, setTaskEditorError,
  } = useTaskEditorState()
  const {
    showCodexChat, setShowCodexChat, codexChatSessions, codexChatProjectSessions, codexChatActiveSessionId,
    setCodexChatActiveSessionId, codexChatActiveSessionTitle, createCodexChatSession, selectCodexChatProject,
    deleteCodexChatSession, codexChatProjectId, setCodexChatProjectId, codexChatInstruction, setCodexChatInstruction,
    codexChatTurns, setCodexChatTurns, setCodexChatTurnsForSession, codexChatSessionId, isCodexChatRunning,
    setIsCodexChatRunning, codexChatRunStartedAt, setCodexChatRunStartedAt, codexChatElapsedSeconds,
    setCodexChatElapsedSeconds, codexChatLastTaskEventAt, setCodexChatLastTaskEventAt, codexChatUsage,
    setCodexChatUsage, setCodexChatUsageForSession,
  } = useCodexChatState()
  const [fabHidden, setFabHidden] = React.useState(false)
  const [showNotificationsPanel, setShowNotificationsPanel] = React.useState(false)
  const [showQuickAdd, setShowQuickAdd] = React.useState(false)
  const qc = useQueryClient()
  const realtimeRefreshTimerRef = React.useRef<number | null>(null)
  const codexChatHistoryRef = React.useRef<HTMLDivElement | null>(null)
  const commentInputRef = React.useRef<HTMLTextAreaElement | null>(null)
  const commentsListRef = React.useRef<HTMLDivElement | null>(null)
  const taskFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const noteFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const specFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const editProjectFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const fabIdleTimerRef = React.useRef<number | null>(null)
  const openNextSelectedNoteInWriteRef = React.useRef(false)
  const projectDescriptionRef = React.useRef<HTMLTextAreaElement | null>(null)
  const editProjectDescriptionRef = React.useRef<HTMLTextAreaElement | null>(null)
  const urlInitAppliedRef = React.useRef(false)

  const autoResizeTextarea = React.useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) return
    const minHeight = 96
    const maxHeight = 280
    el.style.height = 'auto'
    const next = Math.max(minHeight, Math.min(el.scrollHeight, maxHeight))
    el.style.height = `${next}px`
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [])

  useUiPersistenceEffects({
    tab,
    setTab,
    selectedProjectId,
    setSelectedProjectId,
    selectedTaskId,
    setSelectedTaskId,
    selectedNoteId,
    setSelectedNoteId,
    selectedSpecificationId,
    setSelectedSpecificationId,
    setFabHidden,
    fabIdleTimerRef,
    projectsMode,
    setShowProjectCreateForm,
    setShowProjectEditForm,
    setShowNotificationsPanel,
    theme,
  })

  const bootstrap = useQuery({
    queryKey: ['bootstrap', userId],
    queryFn: () => getBootstrap(userId),
    retry: 1,
  })
  const { frontendVersion, backendVersion, backendBuild, backendDeployedAtUtc } = useAppVersion()
  const workspaceId = bootstrap.data?.workspaces[0]?.id ?? ''
  const userTimezone = bootstrap.data?.current_user?.timezone

  useBootstrapSelectionEffects({
    bootstrap,
    setTheme,
    selectedProjectId,
    setSelectedProjectId,
    urlInitAppliedRef,
    showProjectCreateForm,
    setShowProjectCreateForm,
    setShowProjectEditForm,
    createProjectMemberIds,
    setCreateProjectMemberIds,
    showProjectEditForm,
    setEditProjectMemberIds,
  })

  const taskParams = useTaskQueryParams({
    tab,
    selectedProjectId,
    searchQ,
    searchStatus,
    searchPriority,
    searchArchived,
    searchTags,
  })

  const {
    tasks,
    taskLookup,
    notes,
    searchNotes,
    taskNotes,
    specifications,
    searchSpecifications,
    specificationLookup,
    specTasks,
    specNotes,
    projectTags,
    projectRules,
    projectGraphOverview,
    projectGraphContextPack,
    projectGraphSubgraph,
    projectTaskCountQueries,
    projectNoteCountQueries,
    projectRuleCountQueries,
    notifications,
    board,
  } = useCoreQueries({
    userId,
    workspaceId,
    tab,
    selectedProjectId,
    selectedTaskId,
    selectedSpecificationId,
    searchQ,
    searchStatus,
    searchSpecificationStatus,
    searchPriority,
    searchArchived,
    searchTags,
    taskParams,
    noteArchived,
    noteTags,
    specificationStatus,
    specificationTags,
    specificationArchived,
    projects: bootstrap.data?.projects ?? [],
    projectsMode,
  })

  useRealtimeEffects({
    qc,
    realtimeRefreshTimerRef,
    tab,
    selectedProjectId,
    selectedTaskId,
    userId,
    workspaceId,
    showCodexChat,
    setCodexChatLastTaskEventAt,
    isCodexChatRunning,
    codexChatRunStartedAt,
    setCodexChatElapsedSeconds,
    codexChatHistoryRef,
    codexChatTurns,
  })

  const selectedTask = React.useMemo(() => tasks.data?.items.find((t) => t.id === selectedTaskId) ?? null, [tasks.data?.items, selectedTaskId])
  const selectedNote = React.useMemo(() => notes.data?.items.find((n) => n.id === selectedNoteId) ?? null, [notes.data?.items, selectedNoteId])
  const selectedSpecification = React.useMemo(
    () => specifications.data?.items.find((s: any) => s.id === selectedSpecificationId) ?? null,
    [specifications.data?.items, selectedSpecificationId]
  )
  const selectedProjectRule = React.useMemo(
    () => projectRules.data?.items.find((r) => r.id === selectedProjectRuleId) ?? null,
    [projectRules.data?.items, selectedProjectRuleId]
  )
  const { workspaceUsers, projectMemberCounts, selectedProject, unreadCount, actorNames, projectNames } =
    useBootstrapDerived({
      bootstrapData: bootstrap.data,
      selectedProjectId,
      notifications: notifications.data ?? [],
    })
  const taskStatusOptions = React.useMemo(() => {
    const projectIdForStatus = editProjectId || selectedTask?.project_id || selectedProjectId
    const project = (bootstrap.data?.projects ?? []).find((item: any) => item.id === projectIdForStatus)
    const base = Array.isArray(project?.custom_statuses) && project.custom_statuses.length > 0
      ? project.custom_statuses
      : DEFAULT_PROJECT_STATUSES
    const out: string[] = []
    const seen = new Set<string>()
    for (const raw of [...base, editStatus, selectedTask?.status]) {
      const status = String(raw || '').trim()
      if (!status) continue
      const key = status.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push(status)
    }
    return out.length > 0 ? out : [...DEFAULT_PROJECT_STATUSES]
  }, [bootstrap.data?.projects, editProjectId, editStatus, selectedProjectId, selectedTask?.project_id, selectedTask?.status])
  const specificationNameMap = React.useMemo(() => {
    const out: Record<string, string> = {}
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        if (!item?.id) continue
        out[String(item.id)] = String(item.title || 'Untitled spec')
      }
    }
    attach(specificationLookup.data?.items)
    attach(specifications.data?.items)
    return out
  }, [specificationLookup.data?.items, specifications.data?.items])

  const taskNameMap = React.useMemo(() => {
    const out: Record<string, string> = {}
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        if (!item?.id) continue
        out[String(item.id)] = String(item.title || 'Untitled task')
      }
    }
    attach(taskLookup.data?.items)
    attach(tasks.data?.items)
    return out
  }, [taskLookup.data?.items, tasks.data?.items])

  const openSpecification = React.useCallback((specificationId: string, projectId?: string | null) => {
    if (projectId) setSelectedProjectId(projectId)
    setSpecificationStatus('')
    setSpecificationArchived(false)
    setSelectedSpecificationId(specificationId)
    setTab('specifications')
  }, [setSelectedProjectId, setSpecificationStatus, setSpecificationArchived, setSelectedSpecificationId, setTab])

  const {
    taskTagSuggestions,
    noteTagSuggestions,
    toggleSearchTag,
    toggleNoteFilterTag,
    toggleSpecificationFilterTag,
    clearSearchTags,
    clearNoteFilterTags,
    clearSpecificationFilterTags,
    addNoteTag,
    currentNoteTags,
    currentNoteTagsLower,
    toggleNoteTag,
    filteredNoteTags,
    canCreateTag,
    toggleTaskTag,
    toggleQuickTaskTag,
    filteredTaskTags,
    taskTagsLower,
    canCreateTaskTag,
    filteredQuickTaskTags,
    quickTaskTagsLower,
    canCreateQuickTaskTag,
  } = useTagState({
    projectTagsData: projectTags.data,
    searchTags,
    noteTags,
    specificationTags,
    setSearchTags,
    setNoteTags,
    setSpecificationTags,
    editNoteTags,
    setEditNoteTags,
    setTagPickerQuery,
    tagPickerQuery,
    editTaskTags,
    setEditTaskTags,
    quickTaskTags,
    setQuickTaskTags,
    taskTagPickerQuery,
    quickTaskTagQuery,
  })
  const {
    toggleCreateProjectMember,
    toggleEditProjectMember,
    projectIsDirty,
    noteIsDirty,
    taskIsDirty,
    confirmDiscardChanges,
    closeTaskEditor,
    openTaskEditor,
    toggleNoteEditor,
    toggleSpecificationEditor,
    toggleProjectEditor,
  } = useEditorGuards({
    setCreateProjectMemberIds,
    setEditProjectMemberIds,
    projectMembers: bootstrap.data?.project_members ?? [],
    selectedProjectId,
    showProjectEditForm,
    selectedProject,
    editProjectName,
    editProjectDescription,
    editProjectCustomStatusesText,
    editProjectEmbeddingEnabled,
    editProjectEmbeddingModel,
    editProjectContextPackEvidenceTopKText,
    parseExternalRefsText,
    editProjectExternalRefsText,
    parseAttachmentRefsText,
    editProjectAttachmentRefsText,
    editProjectMemberIds,
    selectedNote,
    editNoteTitle,
    editNoteBody,
    editNoteTags,
    editNoteExternalRefsText,
    editNoteAttachmentRefsText,
    selectedSpecification,
    editSpecificationTitle,
    editSpecificationBody,
    editSpecificationStatus,
    editSpecificationTags,
    editSpecificationExternalRefsText,
    editSpecificationAttachmentRefsText,
    selectedTask,
    editTitle,
    editDescription,
    editStatus,
    editPriority,
    editProjectId,
    editTaskTags,
    editDueDate,
    editTaskType,
    editScheduledAtUtc,
    editScheduleTimezone,
    editScheduledInstruction,
    editRecurringEvery,
    editRecurringUnit,
    editTaskExternalRefsText,
    editTaskAttachmentRefsText,
    setSelectedTaskId,
    setTaskEditorError,
    selectedTaskId,
    selectedNoteId,
    setSelectedNoteId,
    selectedSpecificationId,
    setSelectedSpecificationId,
    setShowProjectCreateForm,
    setShowProjectEditForm,
    setSelectedProjectId,
  })

  const openTask = React.useCallback((taskId: string, projectId?: string | null) => {
    if (!taskId) return false
    const opened = openTaskEditor(taskId)
    if (!opened) return false
    if (projectId) setSelectedProjectId(projectId)
    setTab('tasks')
    return true
  }, [openTaskEditor, setSelectedProjectId, setTab])

  const openNote = React.useCallback((noteId: string, projectId?: string | null) => {
    if (!noteId) return false
    if (selectedNoteId === noteId) {
      if (projectId) setSelectedProjectId(projectId)
      setTab('notes')
      return true
    }
    const changed = toggleNoteEditor(noteId)
    if (!changed) return false
    if (projectId) setSelectedProjectId(projectId)
    setTab('notes')
    return true
  }, [selectedNoteId, toggleNoteEditor, setSelectedProjectId, setTab])

  

  const { comments, activity, automationStatus } = useTaskDetailsQueries({ userId, selectedTaskId })

  // Notes uses an accordion: do not auto-open a note.
  useTaskNoteEditorEffects({
    selectedTask,
    currentUserTimezone: bootstrap.data?.current_user?.timezone,
    setEditTitle,
    setEditStatus,
    setEditDescription,
    setEditPriority,
    setEditDueDate,
    setEditProjectId,
    setEditTaskTags,
    setEditTaskExternalRefsText,
    setEditTaskAttachmentRefsText,
    setShowTaskTagPicker,
    setTaskTagPickerQuery,
    setEditTaskType,
    setEditScheduledAtUtc,
    setEditScheduleTimezone,
    setEditScheduledInstruction,
    setEditRecurringEvery,
    setEditRecurringUnit,
    setAutomationInstruction,
    setCommentBody,
    setExpandedCommentIds,
    setTaskEditorError,
    taskEditorError,
    editTaskType,
    editScheduledInstruction,
    editScheduledAtUtc,
    editScheduleTimezone,
    editRecurringEvery,
    editRecurringUnit,
    selectedNote,
    setEditNoteTitle,
    setEditNoteBody,
    setEditNoteTags,
    setEditNoteExternalRefsText,
    setEditNoteAttachmentRefsText,
    setTagPickerQuery,
    setShowTagPicker,
    setNoteEditorView,
    openNextSelectedNoteInWriteRef,
    scrollToNewestComment,
    comments,
    commentsListRef,
    setScrollToNewestComment,
  })

  const {
    invalidateAll,
    moveTaskToStatus,
    uploadAttachmentRef,
    removeUploadedAttachment,
    copyShareLink,
    saveProjectNow,
    saveNoteNow,
    saveTaskNow,
  } = useAppActions({
    qc,
    userId,
    workspaceId,
    setUiError,
    tab,
    setUiInfo,
    projectMembers: bootstrap.data?.project_members ?? [],
    selectedProjectId,
    editProjectName,
    editProjectMemberIds,
    editProjectDescription,
    editProjectCustomStatusesText,
    editProjectEmbeddingEnabled,
    editProjectEmbeddingModel,
    editProjectContextPackEvidenceTopKText,
    editProjectExternalRefsText,
    parseExternalRefsText,
    editProjectAttachmentRefsText,
    parseAttachmentRefsText,
    selectedNoteId,
    editNoteTitle,
    editNoteBody,
    editNoteTags,
    editNoteExternalRefsText,
    editNoteAttachmentRefsText,
    selectedTaskId,
    editTaskType,
    editRecurringEvery,
    editRecurringUnit,
    editTitle,
    editDescription,
    editStatus,
    editPriority,
    editProjectId,
    selectedTask,
    editTaskTags,
    editTaskExternalRefsText,
    editTaskAttachmentRefsText,
    editDueDate,
    editScheduledAtUtc,
    editScheduleTimezone,
    editScheduledInstruction,
  })

  const {
    saveProjectMutation,
    saveNoteMutation,
    saveTaskMutation,
    createTaskMutation,
    completeTaskMutation,
    reopenTaskMutation,
    archiveTaskMutation,
    restoreTaskMutation,
    createProjectMutation,
    deleteProjectMutation,
    createProjectRuleMutation,
    patchProjectRuleMutation,
    deleteProjectRuleMutation,
    createNoteMutation,
    pinNoteMutation,
    unpinNoteMutation,
    archiveNoteMutation,
    restoreNoteMutation,
    deleteNoteMutation,
    saveSpecificationMutation,
    createSpecificationMutation,
    archiveSpecificationMutation,
    restoreSpecificationMutation,
    deleteSpecificationMutation,
    createSpecificationTaskMutation,
    bulkCreateSpecificationTasksMutation,
    createSpecificationNoteMutation,
    linkTaskToSpecificationMutation,
    unlinkTaskFromSpecificationMutation,
    linkNoteToSpecificationMutation,
    unlinkNoteFromSpecificationMutation,
    markReadMutation,
    themeMutation,
    addCommentMutation,
    deleteCommentMutation,
    runAutomationMutation,
    runAgentChatMutation,
  } = useAppMutations({
    saveProjectNow,
    saveNoteNow,
    saveTaskNow,
    setUiError,
    setTaskEditorError,
    userId,
    taskTitle,
    workspaceId,
    quickProjectId,
    selectedProjectId,
    quickDueDate,
    quickTaskTags,
    parseExternalRefsText,
    quickTaskExternalRefsText,
    parseAttachmentRefsText,
    quickTaskAttachmentRefsText,
    setTaskTitle,
    setQuickDueDate,
    setQuickTaskTags,
    setQuickTaskExternalRefsText,
    setQuickTaskAttachmentRefsText,
    setShowQuickTaskTagPicker,
    setQuickTaskTagQuery,
    setShowQuickAdd,
    invalidateAll,
    selectedTaskId,
    setEditStatus,
    setSelectedTaskId,
    projectName,
    projectDescription,
    projectCustomStatusesText,
    projectExternalRefsText,
    projectAttachmentRefsText,
    projectEmbeddingEnabled,
    projectEmbeddingModel,
    projectContextPackEvidenceTopKText,
    createProjectMemberIds,
    draftProjectRules,
    setProjectName,
    setProjectDescription,
    setProjectCustomStatusesText,
    setProjectExternalRefsText,
    setProjectAttachmentRefsText,
    setProjectEmbeddingEnabled,
    setProjectEmbeddingModel,
    setProjectContextPackEvidenceTopKText,
    setProjectDescriptionView,
    setCreateProjectMemberIds,
    setDraftProjectRules,
    setSelectedDraftProjectRuleId,
    setDraftProjectRuleTitle,
    setDraftProjectRuleBody,
    setDraftProjectRuleView,
    setShowProjectCreateForm,
    projectRuleTitle,
    projectRuleBody,
    setSelectedProjectRuleId,
    qc,
    selectedProjectRuleId,
    setProjectRuleTitle,
    setProjectRuleBody,
    setTab,
    openNextSelectedNoteInWriteRef,
    setShowTagPicker,
    setTagPickerQuery,
    setSelectedNoteId,
    commentBody,
    setCommentBody,
    setScrollToNewestComment,
    automationInstruction,
    setAutomationInstruction,
    codexChatSessionId,
    setCodexChatTurns,
    setCodexChatTurnsForSession,
    setCodexChatUsage,
    setCodexChatUsageForSession,
    setIsCodexChatRunning,
    setCodexChatRunStartedAt,
    setCodexChatElapsedSeconds,
    setCodexChatInstruction,
    selectedSpecificationId,
    setSelectedSpecificationId,
    editSpecificationTitle,
    editSpecificationBody,
    editSpecificationStatus,
    editSpecificationTags,
    editSpecificationExternalRefsText,
    editSpecificationAttachmentRefsText,
  })

  const createTaskFromGraphSummary = React.useCallback(async (payload: { title: string; description: string }) => {
    if (!selectedProjectId) throw new Error('No project selected')
    await createTaskMutation.mutateAsync({
      title: payload.title,
      description: payload.description,
      project_id: selectedProjectId,
      open_task: true,
    })
  }, [createTaskMutation, selectedProjectId])

  const createNoteFromGraphSummary = React.useCallback(async (payload: { title: string; body: string }) => {
    if (!selectedProjectId) throw new Error('No project selected')
    await createNoteMutation.mutateAsync({
      title: payload.title,
      body: payload.body,
      project_id: selectedProjectId,
      task_id: null,
      specification_id: null,
    })
  }, [createNoteMutation, selectedProjectId])

  const linkFocusTaskToSpecification = React.useCallback(
    async (taskId: string, specificationId: string) => {
      const tid = String(taskId || '').trim()
      const sid = String(specificationId || '').trim()
      if (!tid || !sid) throw new Error('Task and specification are required')
      await linkTaskToSpecification(userId, sid, tid)
      await invalidateAll()
      setUiError(null)
      setUiInfo('Task linked to specification')
      setTimeout(() => setUiInfo(null), 1800)
    },
    [invalidateAll, setUiError, setUiInfo, userId]
  )

  useProjectEditorEffects({
    selectedProject,
    setEditProjectName,
    setEditProjectDescription,
    setEditProjectCustomStatusesText,
    setEditProjectExternalRefsText,
    setEditProjectAttachmentRefsText,
    setEditProjectEmbeddingEnabled,
    setEditProjectEmbeddingModel,
    setEditProjectContextPackEvidenceTopKText,
    setEditProjectDescriptionView,
    setShowProjectEditForm,
    setSelectedProjectRuleId,
    setProjectRuleTitle,
    setProjectRuleBody,
    setProjectRuleView,
    showProjectCreateForm,
    projectDescription,
    projectCustomStatusesText,
    setProjectCustomStatusesText,
    setProjectDescriptionView,
    selectedProjectRule,
    selectedDraftProjectRuleId,
    draftProjectRules,
    setDraftProjectRuleTitle,
    setDraftProjectRuleBody,
    setDraftProjectRuleView,
    autoResizeTextarea,
    projectDescriptionRef,
    projectDescriptionView,
    showProjectEditForm,
    editProjectDescriptionRef,
    editProjectDescriptionView,
    editProjectDescription,
  })

  React.useEffect(() => {
    if (!specifications.data) return
    const items = specifications.data.items ?? []
    if (items.length === 0) {
      if (selectedSpecificationId) setSelectedSpecificationId(null)
      return
    }
    if (selectedSpecificationId && !items.some((item: any) => item.id === selectedSpecificationId)) {
      const first = items[0]
      if (first?.id) setSelectedSpecificationId(first.id)
    }
  }, [selectedSpecificationId, specifications.data, setSelectedSpecificationId])

  React.useEffect(() => {
    if (!selectedSpecification) {
      setEditSpecificationTitle('')
      setEditSpecificationBody('')
      setEditSpecificationStatus('Draft')
      setEditSpecificationTags('')
      setEditSpecificationExternalRefsText('')
      setEditSpecificationAttachmentRefsText('')
      setSpecificationEditorView('preview')
      return
    }
    setEditSpecificationTitle(selectedSpecification.title || '')
    setEditSpecificationBody(selectedSpecification.body || '')
    setEditSpecificationStatus(selectedSpecification.status || 'Draft')
    setEditSpecificationTags((selectedSpecification.tags ?? []).join(', '))
    setEditSpecificationExternalRefsText(externalRefsToText(selectedSpecification.external_refs))
    setEditSpecificationAttachmentRefsText(attachmentRefsToText(selectedSpecification.attachment_refs))
    const hasBody = Boolean((selectedSpecification.body || '').trim())
    setSpecificationEditorView(hasBody ? 'preview' : 'write')
  }, [selectedSpecification])

  const specificationIsDirty = React.useMemo(() => {
    if (!selectedSpecification) return false
    return (
      (editSpecificationTitle || '').trim() !== (selectedSpecification.title || '').trim() ||
      (editSpecificationBody || '') !== (selectedSpecification.body || '') ||
      (editSpecificationStatus || 'Draft') !== (selectedSpecification.status || 'Draft') ||
      parseCommaTags(editSpecificationTags).map((tag) => tag.toLowerCase()).join(',') !==
        (selectedSpecification.tags ?? []).map((tag) => String(tag || '').toLowerCase()).join(',') ||
      editSpecificationExternalRefsText.trim() !== externalRefsToText(selectedSpecification.external_refs).trim() ||
      editSpecificationAttachmentRefsText.trim() !== attachmentRefsToText(selectedSpecification.attachment_refs).trim()
    )
  }, [
    editSpecificationAttachmentRefsText,
    editSpecificationBody,
    editSpecificationExternalRefsText,
    editSpecificationStatus,
    editSpecificationTags,
    editSpecificationTitle,
    selectedSpecification,
  ])

  if (bootstrap.isLoading) return <div className="page"><div className="card skeleton">Loading workspace...</div></div>
  if (bootstrap.isError || !bootstrap.data) return <div className="page"><div className="notice notice-error">Unable to load bootstrap data.</div></div>

  const {
    selectedTaskTimeMeta,
    selectedNoteTimeMeta,
    selectedProjectTimeMeta,
    selectedTaskCreator,
    selectedNoteCreator,
    selectedProjectCreator,
  } = useEntityDisplayMeta({
    actorNames,
    selectedTask,
    selectedNote,
    selectedProject,
  })

  return (
    <AppContent
      state={{
      bootstrap,
      tab,
      setTab,
      searchQ,
      setSearchQ,
      selectedProjectId,
      setSelectedProjectId,
      showNotificationsPanel,
      setShowNotificationsPanel,
      notifications,
      unreadCount,
      markReadMutation,
      uiError,
      setUiError,
      uiInfo,
      setUiInfo,
      showQuickAdd,
      setShowQuickAdd,
      taskTitle,
      setTaskTitle,
      quickProjectId,
      setQuickProjectId,
      createTaskMutation,
      quickDueDate,
      setQuickDueDate,
      quickDueDateFocused,
      setQuickDueDateFocused,
      quickTaskTags,
      tagHue,
      setShowQuickTaskTagPicker,
      showQuickTaskTagPicker,
      quickTaskTagQuery,
      setQuickTaskTagQuery,
      filteredQuickTaskTags,
      quickTaskTagsLower,
      toggleQuickTaskTag,
      canCreateQuickTaskTag,
      projectsMode,
      setProjectsMode,
      taskTagSuggestions,
      searchTags,
      toggleSearchTag,
      clearSearchTags,
      board,
      openTaskEditor,
      moveTaskToStatus,
      tasks,
      restoreTaskMutation,
      reopenTaskMutation,
      completeTaskMutation,
      showProjectCreateForm,
      showProjectEditForm,
      projectIsDirty,
      confirmDiscardChanges,
      setShowProjectEditForm,
      setShowProjectCreateForm,
      projectName,
      setProjectName,
      createProjectMutation,
      projectCustomStatusesText,
      setProjectCustomStatusesText,
      projectEmbeddingEnabled,
      setProjectEmbeddingEnabled,
      projectEmbeddingModel,
      setProjectEmbeddingModel,
      projectContextPackEvidenceTopKText,
      setProjectContextPackEvidenceTopKText,
      projectDescriptionView,
      setProjectDescriptionView,
      projectDescriptionRef,
      projectDescription,
      setProjectDescription,
      draftProjectRules,
      setDraftProjectRules,
      selectedDraftProjectRuleId,
      setSelectedDraftProjectRuleId,
      draftProjectRuleTitle,
      setDraftProjectRuleTitle,
      draftProjectRuleBody,
      setDraftProjectRuleBody,
      draftProjectRuleView,
      setDraftProjectRuleView,
      projectExternalRefsText,
      setProjectExternalRefsText,
      workspaceUsers,
      createProjectMemberIds,
      toggleCreateProjectMember,
      selectedProject,
      projectTaskCountQueries,
      projectNoteCountQueries,
      projectRuleCountQueries,
      projectMemberCounts,
      workspaceId,
      userId,
      toggleProjectEditor,
      createTaskFromGraphSummary,
      createNoteFromGraphSummary,
      linkFocusTaskToSpecification,
      copyShareLink,
      editProjectName,
      setEditProjectName,
      editProjectCustomStatusesText,
      setEditProjectCustomStatusesText,
      saveProjectMutation,
      deleteProjectMutation,
      editProjectDescriptionView,
      setEditProjectDescriptionView,
      editProjectDescriptionRef,
      editProjectDescription,
      setEditProjectDescription,
      projectRules,
      projectGraphOverview,
      projectGraphContextPack,
      projectGraphSubgraph,
      selectedProjectRuleId,
      setSelectedProjectRuleId,
      projectRuleTitle,
      setProjectRuleTitle,
      projectRuleBody,
      setProjectRuleBody,
      projectRuleView,
      setProjectRuleView,
      createProjectRuleMutation,
      patchProjectRuleMutation,
      deleteProjectRuleMutation,
      toUserDateTime,
      userTimezone,
      editProjectExternalRefsText,
      setEditProjectExternalRefsText,
      editProjectFileInputRef,
      uploadAttachmentRef,
      editProjectAttachmentRefsText,
      setEditProjectAttachmentRefsText,
      editProjectEmbeddingEnabled,
      setEditProjectEmbeddingEnabled,
      editProjectEmbeddingModel,
      setEditProjectEmbeddingModel,
      editProjectContextPackEvidenceTopKText,
      setEditProjectContextPackEvidenceTopKText,
      embeddingAllowedModels: bootstrap.data.embedding_allowed_models ?? [],
      embeddingDefaultModel: String(bootstrap.data.embedding_default_model || '').trim(),
      vectorStoreEnabled: Boolean(bootstrap.data.vector_store_enabled),
      contextPackEvidenceTopKDefault: Number(bootstrap.data.context_pack_evidence_top_k_default || 10),
      editProjectMemberIds,
      toggleEditProjectMember,
      selectedProjectCreator,
      selectedProjectTimeMeta,
      notes,
      searchNotes,
      taskNotes,
      specifications,
      searchSpecifications,
      specTasks,
      specNotes,
      createNoteMutation,
      noteArchived,
      setNoteArchived,
      noteTagSuggestions,
      noteTags,
      toggleNoteFilterTag,
      clearNoteFilterTags,
      selectedNoteId,
      selectedNote,
      editNoteTitle,
      setEditNoteTitle,
      toggleNoteEditor,
      setShowTagPicker,
      setTagPickerQuery,
      noteIsDirty,
      saveNoteMutation,
      unpinNoteMutation,
      pinNoteMutation,
      restoreNoteMutation,
      archiveNoteMutation,
      deleteNoteMutation,
      noteEditorView,
      setNoteEditorView,
      editNoteBody,
      setEditNoteBody,
      currentNoteTags,
      editNoteExternalRefsText,
      setEditNoteExternalRefsText,
      parseExternalRefsText,
      removeExternalRefByIndex,
      externalRefsToText,
      noteFileInputRef,
      specFileInputRef,
      setEditNoteAttachmentRefsText,
      attachmentRefsToText,
      parseAttachmentRefsText,
      toErrorMessage,
      editNoteAttachmentRefsText,
      removeAttachmentByPath,
      selectedNoteCreator,
      selectedNoteTimeMeta,
      showTagPicker,
      tagPickerQuery,
      filteredNoteTags,
      currentNoteTagsLower,
      toggleNoteTag,
      canCreateTag,
      addNoteTag,
      specificationStatus,
      setSpecificationStatus,
      specificationTags,
      toggleSpecificationFilterTag,
      clearSpecificationFilterTags,
      specificationArchived,
      setSpecificationArchived,
      selectedSpecificationId,
      setSelectedSpecificationId,
      toggleSpecificationEditor,
      editSpecificationTitle,
      setEditSpecificationTitle,
      editSpecificationBody,
      setEditSpecificationBody,
      editSpecificationStatus,
      setEditSpecificationStatus,
      editSpecificationTags,
      setEditSpecificationTags,
      editSpecificationExternalRefsText,
      setEditSpecificationExternalRefsText,
      editSpecificationAttachmentRefsText,
      setEditSpecificationAttachmentRefsText,
      specificationEditorView,
      setSpecificationEditorView,
      specificationIsDirty,
      saveSpecificationMutation,
      createSpecificationMutation,
      archiveSpecificationMutation,
      restoreSpecificationMutation,
      deleteSpecificationMutation,
      createSpecificationTaskMutation,
      bulkCreateSpecificationTasksMutation,
      createSpecificationNoteMutation,
      linkTaskToSpecificationMutation,
      unlinkTaskFromSpecificationMutation,
      linkNoteToSpecificationMutation,
      unlinkNoteFromSpecificationMutation,
      searchStatus,
      setSearchStatus,
      searchSpecificationStatus,
      setSearchSpecificationStatus,
      searchPriority,
      setSearchPriority,
      searchArchived,
      setSearchArchived,
      theme,
      setTheme,
      themeMutation,
      projectNames,
      taskNameMap,
      specificationNameMap,
      openSpecification,
      openTask,
      openNote,
      fabHidden,
      setQuickTaskExternalRefsText,
      setQuickTaskAttachmentRefsText,
      isCodexChatRunning,
      codexChatElapsedSeconds,
      setCodexChatProjectId,
      setShowCodexChat,
      closeTaskEditor,
      taskIsDirty,
      saveTaskMutation,
      archiveTaskMutation,
      editTitle,
      setEditTitle,
      editStatus,
      setEditStatus,
      taskStatusOptions,
      editPriority,
      setEditPriority,
      editDueDate,
      setEditDueDate,
      editDescription,
      setEditDescription,
      editTaskTags,
      setShowTaskTagPicker,
      editTaskType,
      setEditTaskType,
      taskEditorError,
      editScheduledAtUtc,
      setEditScheduledAtUtc,
      editScheduleTimezone,
      setEditScheduleTimezone,
      editRecurringEvery,
      setEditRecurringEvery,
      editRecurringUnit,
      setEditRecurringUnit,
      editScheduledInstruction,
      setEditScheduledInstruction,
      priorityTone,
      editTaskExternalRefsText,
      setEditTaskExternalRefsText,
      taskFileInputRef,
      editProjectId,
      setTaskEditorError,
      editTaskAttachmentRefsText,
      selectedTaskCreator,
      selectedTaskTimeMeta,
      showTaskTagPicker,
      taskTagPickerQuery,
      setTaskTagPickerQuery,
      filteredTaskTags,
      taskTagsLower,
      toggleTaskTag,
      canCreateTaskTag,
      comments,
      commentsListRef,
      expandedCommentIds,
      setExpandedCommentIds,
      actorNames,
      deleteCommentMutation,
      commentInputRef,
      commentBody,
      setCommentBody,
      addCommentMutation,
      automationStatus,
      automationInstruction,
      setAutomationInstruction,
      runAutomationMutation,
      selectedTaskId,
      activityShowRawDetails,
      setActivityShowRawDetails,
      activity,
      formatActivitySummary,
      activityTone,
      activityExpandedIds,
      setActivityExpandedIds,
      toReadableDate,
      frontendVersion,
      backendVersion,
      backendBuild,
      backendDeployedAtUtc,
      showCodexChat,
      codexChatSessions,
      codexChatProjectSessions,
      codexChatActiveSessionId,
      setCodexChatActiveSessionId,
      codexChatActiveSessionTitle,
      createCodexChatSession,
      selectCodexChatProject,
      deleteCodexChatSession,
      codexChatSessionId,
      codexChatProjectId,
      codexChatUsage,
      runAgentChatMutation,
      codexChatHistoryRef,
      codexChatTurns,
      codexChatInstruction,
      setCodexChatInstruction,
      setCodexChatTurns,
      setCodexChatTurnsForSession,
      setCodexChatUsage,
      setCodexChatUsageForSession,
      setIsCodexChatRunning,
      setCodexChatRunStartedAt,
      setCodexChatElapsedSeconds,
      codexChatLastTaskEventAt,
      selectedTask,
      }}
    />
  )
}

export default function AppRoot() {
  return (
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}
