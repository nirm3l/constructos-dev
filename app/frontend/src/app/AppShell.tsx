import React from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { getBootstrap } from '../api'
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
  activityTone,
  attachmentRefsToText,
  externalRefsToText,
  formatActivitySummary,
  normalizeStoredUserId,
  parseAttachmentRefsText,
  parseExternalRefsText,
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
  const [userId] = React.useState<string>(() => normalizeStoredUserId(localStorage.getItem('user_id')))
  const [tab, setTab] = React.useState<Tab>(() => parseStoredTab(localStorage.getItem('ui_tab')))
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light')
  const [taskTitle, setTaskTitle] = React.useState('')
  const [quickDueDate, setQuickDueDate] = React.useState('')
  const [quickDueDateFocused, setQuickDueDateFocused] = React.useState(false)
  const {
    projectName, setProjectName, projectDescription, setProjectDescription, projectExternalRefsText, setProjectExternalRefsText,
    projectAttachmentRefsText, setProjectAttachmentRefsText, projectDescriptionView, setProjectDescriptionView, showProjectCreateForm,
    setShowProjectCreateForm, showProjectEditForm, setShowProjectEditForm, editProjectName, setEditProjectName, editProjectDescription,
    setEditProjectDescription, editProjectExternalRefsText, setEditProjectExternalRefsText, editProjectAttachmentRefsText,
    setEditProjectAttachmentRefsText, createProjectMemberIds, setCreateProjectMemberIds, editProjectMemberIds, setEditProjectMemberIds,
    editProjectDescriptionView, setEditProjectDescriptionView, selectedProjectRuleId, setSelectedProjectRuleId, projectRuleTitle,
    setProjectRuleTitle, projectRuleBody, setProjectRuleBody, projectRuleView, setProjectRuleView, draftProjectRules,
    setDraftProjectRules, selectedDraftProjectRuleId, setSelectedDraftProjectRuleId, draftProjectRuleTitle, setDraftProjectRuleTitle,
    draftProjectRuleBody, setDraftProjectRuleBody, draftProjectRuleView, setDraftProjectRuleView, selectedProjectId,
    setSelectedProjectId, projectsMode, setProjectsMode,
  } = useProjectState()
  const [quickProjectId, setQuickProjectId] = React.useState<string>('')
  const [quickTaskTags, setQuickTaskTags] = React.useState<string[]>([])
  const [quickTaskExternalRefsText, setQuickTaskExternalRefsText] = React.useState('')
  const [quickTaskAttachmentRefsText, setQuickTaskAttachmentRefsText] = React.useState('')
  const [showQuickTaskTagPicker, setShowQuickTaskTagPicker] = React.useState(false)
  const [quickTaskTagQuery, setQuickTaskTagQuery] = React.useState('')
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  const [selectedNoteId, setSelectedNoteId] = React.useState<string | null>(null)
  const [searchQ, setSearchQ] = React.useState('')
  const [searchStatus, setSearchStatus] = React.useState('')
  const [searchPriority, setSearchPriority] = React.useState('')
  const [searchTags, setSearchTags] = React.useState<string[]>([])
  const [searchArchived, setSearchArchived] = React.useState(false)
  const [noteQ, setNoteQ] = React.useState('')
  const [noteTags, setNoteTags] = React.useState<string[]>([])
  const [noteArchived, setNoteArchived] = React.useState(false)
  const [specificationQ, setSpecificationQ] = React.useState('')
  const [specificationStatus, setSpecificationStatus] = React.useState('')
  const [specificationArchived, setSpecificationArchived] = React.useState(false)
  const [selectedSpecificationId, setSelectedSpecificationId] = React.useState<string | null>(null)
  const [editSpecificationTitle, setEditSpecificationTitle] = React.useState('')
  const [editSpecificationBody, setEditSpecificationBody] = React.useState('')
  const [editSpecificationStatus, setEditSpecificationStatus] = React.useState('Draft')
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
    showCodexChat, setShowCodexChat, codexChatProjectId, setCodexChatProjectId, codexChatInstruction, setCodexChatInstruction,
    codexChatTurns, setCodexChatTurns, codexChatSessionId, isCodexChatRunning, setIsCodexChatRunning, codexChatRunStartedAt,
    setCodexChatRunStartedAt, codexChatElapsedSeconds, setCodexChatElapsedSeconds, codexChatLastTaskEventAt, setCodexChatLastTaskEventAt,
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
    retry: 1
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
    notes,
    specifications,
    projectTags,
    projectRules,
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
    searchQ,
    searchStatus,
    searchPriority,
    searchArchived,
    searchTags,
    taskParams,
    noteQ,
    noteArchived,
    noteTags,
    specificationQ,
    specificationStatus,
    specificationArchived,
    projects: bootstrap.data?.projects ?? [],
    projectsMode,
  })

  useRealtimeEffects({
    qc,
    realtimeRefreshTimerRef,
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

  const {
    taskTagSuggestions,
    noteTagSuggestions,
    toggleSearchTag,
    toggleNoteFilterTag,
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
    setSearchTags,
    setNoteTags,
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
    projectExternalRefsText,
    projectAttachmentRefsText,
    createProjectMemberIds,
    draftProjectRules,
    setProjectName,
    setProjectDescription,
    setProjectExternalRefsText,
    setProjectAttachmentRefsText,
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
    setIsCodexChatRunning,
    setCodexChatRunStartedAt,
    setCodexChatElapsedSeconds,
    setCodexChatInstruction,
    selectedSpecificationId,
    setSelectedSpecificationId,
    editSpecificationTitle,
    editSpecificationBody,
    editSpecificationStatus,
    editSpecificationExternalRefsText,
    editSpecificationAttachmentRefsText,
  })

  useProjectEditorEffects({
    selectedProject,
    setEditProjectName,
    setEditProjectDescription,
    setEditProjectExternalRefsText,
    setEditProjectAttachmentRefsText,
    setEditProjectDescriptionView,
    setShowProjectEditForm,
    setSelectedProjectRuleId,
    setProjectRuleTitle,
    setProjectRuleBody,
    setProjectRuleView,
    showProjectCreateForm,
    projectDescription,
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
    const items = specifications.data?.items ?? []
    if (items.length === 0) {
      setSelectedSpecificationId(null)
      return
    }
    if (selectedSpecificationId && !items.some((item: any) => item.id === selectedSpecificationId)) {
      const first = items[0]
      if (first?.id) setSelectedSpecificationId(first.id)
    }
  }, [selectedSpecificationId, specifications.data?.items])

  React.useEffect(() => {
    if (!selectedSpecification) {
      setEditSpecificationTitle('')
      setEditSpecificationBody('')
      setEditSpecificationStatus('Draft')
      setEditSpecificationExternalRefsText('')
      setEditSpecificationAttachmentRefsText('')
      setSpecificationEditorView('preview')
      return
    }
    setEditSpecificationTitle(selectedSpecification.title || '')
    setEditSpecificationBody(selectedSpecification.body || '')
    setEditSpecificationStatus(selectedSpecification.status || 'Draft')
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
      editSpecificationExternalRefsText.trim() !== externalRefsToText(selectedSpecification.external_refs).trim() ||
      editSpecificationAttachmentRefsText.trim() !== attachmentRefsToText(selectedSpecification.attachment_refs).trim()
    )
  }, [
    editSpecificationAttachmentRefsText,
    editSpecificationBody,
    editSpecificationExternalRefsText,
    editSpecificationStatus,
    editSpecificationTitle,
    selectedSpecification,
  ])

  if (bootstrap.isLoading) return <div className="page"><div className="card skeleton">Loading workspace...</div></div>
  if (bootstrap.isError || !bootstrap.data) return <div className="page"><div className="notice">Unable to load bootstrap data.</div></div>

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
      copyShareLink,
      editProjectName,
      setEditProjectName,
      saveProjectMutation,
      deleteProjectMutation,
      editProjectDescriptionView,
      setEditProjectDescriptionView,
      editProjectDescriptionRef,
      editProjectDescription,
      setEditProjectDescription,
      projectRules,
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
      editProjectMemberIds,
      toggleEditProjectMember,
      selectedProjectCreator,
      selectedProjectTimeMeta,
      noteQ,
      notes,
      specifications,
      setNoteQ,
      createNoteMutation,
      noteArchived,
      setNoteArchived,
      noteTagSuggestions,
      noteTags,
      toggleNoteFilterTag,
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
      specificationQ,
      setSpecificationQ,
      specificationStatus,
      setSpecificationStatus,
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
      searchStatus,
      setSearchStatus,
      searchPriority,
      setSearchPriority,
      searchArchived,
      setSearchArchived,
      theme,
      setTheme,
      themeMutation,
      projectNames,
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
      codexChatSessionId,
      codexChatProjectId,
      runAgentChatMutation,
      codexChatHistoryRef,
      codexChatTurns,
      codexChatInstruction,
      setCodexChatInstruction,
      setCodexChatTurns,
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
