import React from 'react'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  activateLicense,
  authChangePassword,
  deactivateAdminUser,
  authLogin,
  authLogout,
  authMe,
  createAdminUser,
  getBootstrap,
  getLicenseStatus,
  linkTaskToSpecification,
  listAdminUsers,
  resetAdminUserPassword,
  submitBugReport,
  updateAdminUserRole,
} from '../api'
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
const VOICE_LANG_STORAGE_KEY = 'ui_voice_input_lang'
const ALLOWED_VOICE_LANGS = new Set(['bs-BA', 'en-US'])
const SEMANTIC_MIN_FINAL_SCORE = 0.42
const SEMANTIC_RELATIVE_SCORE_FACTOR = 0.72
const SEMANTIC_MIN_TOP_VECTOR_SIMILARITY = 0.34
const SEMANTIC_MIN_VECTOR_SIMILARITY = 0.24
const SEMANTIC_RELATIVE_VECTOR_FACTOR = 0.66
const SEMANTIC_STRONG_VECTOR_SIMILARITY = 0.72
const SEMANTIC_MIN_FALLBACK_VECTOR_SIMILARITY = 0.38
const SEMANTIC_FALLBACK_MAX_ITEMS_WITHOUT_TOKEN_MATCH = 2

function normalizeSemanticText(value: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function resolveInitialSpeechLang(): string {
  const fallback = 'bs-BA'
  if (typeof window !== 'undefined') {
    const stored = String(window.localStorage.getItem(VOICE_LANG_STORAGE_KEY) || '').trim()
    if (ALLOWED_VOICE_LANGS.has(stored)) return stored
  }
  if (typeof navigator === 'undefined') return fallback
  const raw = String(navigator.language || '').trim().toLowerCase()
  if (raw.startsWith('bs') || raw.startsWith('hr') || raw.startsWith('sr')) return 'bs-BA'
  if (raw.startsWith('en')) return 'en-US'
  return fallback
}

function App({ logout }: { logout: () => void }) {
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

  const [userId] = React.useState<string>('session')
  const [tab, setTab] = React.useState<Tab>(() => {
    if (initialUrlState.tab) return initialUrlState.tab
    if (initialUrlState.specificationId) return 'specifications'
    if (initialUrlState.noteId) return 'notes'
    if (initialUrlState.taskId) return 'tasks'
    return parseStoredTab(localStorage.getItem('ui_tab'))
  })
  const [theme, setTheme] = React.useState<'light' | 'dark'>('light')
  const [speechLang, setSpeechLang] = React.useState<string>(resolveInitialSpeechLang)
  const [taskTitle, setTaskTitle] = React.useState('')
  const [quickDueDate, setQuickDueDate] = React.useState('')
  const [quickDueDateFocused, setQuickDueDateFocused] = React.useState(false)
  const {
    projectName, setProjectName, projectTemplateKey, setProjectTemplateKey, projectDescription, setProjectDescription, projectCustomStatusesText, setProjectCustomStatusesText,
    projectExternalRefsText, setProjectExternalRefsText, projectAttachmentRefsText, setProjectAttachmentRefsText,
    projectEmbeddingEnabled, setProjectEmbeddingEnabled, projectEmbeddingModel, setProjectEmbeddingModel,
    projectContextPackEvidenceTopKText, setProjectContextPackEvidenceTopKText,
    projectTemplateParametersText, setProjectTemplateParametersText,
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
  const [taskGroupFilterId, setTaskGroupFilterId] = React.useState('')
  const [noteTags, setNoteTags] = React.useState<string[]>([])
  const [noteArchived, setNoteArchived] = React.useState(false)
  const [noteGroupFilterId, setNoteGroupFilterId] = React.useState('')
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
  const [editNoteGroupId, setEditNoteGroupId] = React.useState('')
  const [editNoteTags, setEditNoteTags] = React.useState('')
  const [editNoteExternalRefsText, setEditNoteExternalRefsText] = React.useState('')
  const [editNoteAttachmentRefsText, setEditNoteAttachmentRefsText] = React.useState('')
  const [showTagPicker, setShowTagPicker] = React.useState(false)
  const [tagPickerQuery, setTagPickerQuery] = React.useState('')
  const [noteEditorView, setNoteEditorView] = React.useState<'write' | 'preview'>('preview')
  const {
    editStatus, setEditStatus, editTitle, setEditTitle, editDescription, setEditDescription, editPriority, setEditPriority,
    editDueDate, setEditDueDate, editProjectId, setEditProjectId, editTaskGroupId, setEditTaskGroupId, editTaskTags, setEditTaskTags, editTaskExternalRefsText,
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

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const normalized = ALLOWED_VOICE_LANGS.has(speechLang) ? speechLang : 'bs-BA'
    window.localStorage.setItem(VOICE_LANG_STORAGE_KEY, normalized)
  }, [speechLang])

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
  const licenseStatus = useQuery({
    queryKey: ['license-status', userId],
    queryFn: () => getLicenseStatus(userId),
    enabled: Boolean(bootstrap.data),
    retry: 1,
  })
  const activateLicenseMutation = useMutation({
    mutationFn: (activationCode: string) =>
      activateLicense(userId, {
        activation_code: activationCode,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['license-status', userId] })
      setUiError(null)
      setUiInfo('License activated successfully.')
      setTimeout(() => setUiInfo(null), 2500)
    },
    onError: (error: unknown) => {
      setUiError(toErrorMessage(error, 'License activation failed'))
    },
  })
  const submitBugReportMutation = useMutation({
    mutationFn: (payload: {
      title: string
      description: string
      steps_to_reproduce?: string | null
      expected_behavior?: string | null
      actual_behavior?: string | null
      severity: 'low' | 'medium' | 'high' | 'critical'
      context?: Record<string, unknown>
      metadata?: Record<string, unknown>
    }) => submitBugReport(userId, payload),
    onSuccess: (result) => {
      setUiError(null)
      if (result.queued) {
        setUiInfo('Control plane unavailable. Bug report queued and will retry automatically.')
      } else {
        setUiInfo('Bug report sent to the control plane.')
      }
      setTimeout(() => setUiInfo(null), 2500)
    },
    onError: (error: unknown) => {
      setUiError(toErrorMessage(error, 'Bug report submission failed'))
    },
  })
  const { frontendVersion, backendVersion, backendBuild, backendDeployedAtUtc } = useAppVersion()
  const workspaceId = bootstrap.data?.workspaces[0]?.id ?? ''
  const userTimezone = bootstrap.data?.current_user?.timezone
  const canManageUsers = React.useMemo(
    () =>
      (bootstrap.data?.memberships ?? []).some((m: any) => {
        const role = String(m?.role || '')
        return role === 'Owner' || role === 'Admin'
      }),
    [bootstrap.data?.memberships]
  )
  const [adminCreateUsername, setAdminCreateUsername] = React.useState('')
  const [adminCreateFullName, setAdminCreateFullName] = React.useState('')
  const [adminCreateRole, setAdminCreateRole] = React.useState('Member')
  const [adminLastTempPassword, setAdminLastTempPassword] = React.useState<string | null>(null)
  const [resetAdminPasswordUserId, setResetAdminPasswordUserId] = React.useState<string | null>(null)
  const [updateAdminRoleUserId, setUpdateAdminRoleUserId] = React.useState<string | null>(null)
  const [deactivateAdminUserId, setDeactivateAdminUserId] = React.useState<string | null>(null)

  const adminUsersQuery = useQuery({
    queryKey: ['admin-users', userId, workspaceId],
    queryFn: () => listAdminUsers(userId, workspaceId),
    enabled: Boolean(workspaceId && canManageUsers && (tab === 'profile' || tab === 'admin')),
  })

  const createAdminUserMutation = useMutation({
    mutationFn: (payload: { workspace_id: string; username: string; full_name?: string; role?: string }) =>
      createAdminUser(userId, payload),
    onSuccess: async (payload) => {
      setAdminCreateUsername('')
      setAdminCreateFullName('')
      setAdminCreateRole('Member')
      setAdminLastTempPassword(payload.temporary_password || null)
      await qc.invalidateQueries({ queryKey: ['admin-users', userId, workspaceId] })
      await qc.invalidateQueries({ queryKey: ['bootstrap', userId] })
    },
    onError: (err: any) => {
      setUiError(err?.message || 'Unable to create user')
    },
  })

  const resetAdminUserPasswordMutation = useMutation({
    mutationFn: (targetUserId: string) => resetAdminUserPassword(userId, targetUserId, { workspace_id: workspaceId }),
    onMutate: (targetUserId: string) => {
      setResetAdminPasswordUserId(targetUserId)
    },
    onSuccess: async (payload) => {
      setAdminLastTempPassword(payload.temporary_password || null)
      await qc.invalidateQueries({ queryKey: ['admin-users', userId, workspaceId] })
    },
    onError: (err: any) => {
      setUiError(err?.message || 'Unable to reset password')
    },
    onSettled: () => {
      setResetAdminPasswordUserId(null)
    },
  })
  const updateAdminUserRoleMutation = useMutation({
    mutationFn: (payload: { targetUserId: string; role: string }) =>
      updateAdminUserRole(userId, payload.targetUserId, { workspace_id: workspaceId, role: payload.role }),
    onMutate: (payload) => {
      setUpdateAdminRoleUserId(payload.targetUserId)
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['admin-users', userId, workspaceId] })
      await qc.invalidateQueries({ queryKey: ['bootstrap', userId] })
    },
    onError: (err: any) => {
      setUiError(err?.message || 'Unable to update role')
    },
    onSettled: () => {
      setUpdateAdminRoleUserId(null)
    },
  })
  const deactivateAdminUserMutation = useMutation({
    mutationFn: (targetUserId: string) => deactivateAdminUser(userId, targetUserId, { workspace_id: workspaceId }),
    onMutate: (targetUserId: string) => {
      setDeactivateAdminUserId(targetUserId)
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['admin-users', userId, workspaceId] })
      await qc.invalidateQueries({ queryKey: ['bootstrap', userId] })
    },
    onError: (err: any) => {
      setUiError(err?.message || 'Unable to deactivate user')
    },
    onSettled: () => {
      setDeactivateAdminUserId(null)
    },
  })
  const adminUsers = adminUsersQuery.data?.items ?? []
  const adminUsersError = adminUsersQuery.isError ? toErrorMessage(adminUsersQuery.error, 'Unable to load users') : null
  const onCreateAdminUser = React.useCallback(() => {
    if (!workspaceId) return
    const username = adminCreateUsername.trim()
    if (!username) return
    createAdminUserMutation.mutate({
      workspace_id: workspaceId,
      username,
      full_name: adminCreateFullName.trim() || undefined,
      role: adminCreateRole,
    })
  }, [adminCreateFullName, adminCreateRole, adminCreateUsername, createAdminUserMutation, workspaceId])
  const onResetAdminUserPassword = React.useCallback((targetUserId: string) => {
    if (!workspaceId) return
    resetAdminUserPasswordMutation.mutate(targetUserId)
  }, [resetAdminUserPasswordMutation, workspaceId])
  const onUpdateAdminUserRole = React.useCallback((targetUserId: string, role: string) => {
    if (!workspaceId) return
    updateAdminUserRoleMutation.mutate({ targetUserId, role })
  }, [updateAdminUserRoleMutation, workspaceId])
  const onDeactivateAdminUser = React.useCallback((targetUserId: string) => {
    if (!workspaceId) return
    deactivateAdminUserMutation.mutate(targetUserId)
  }, [deactivateAdminUserMutation, workspaceId])

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
  const selectedProjectForSearch = React.useMemo(
    () => (bootstrap.data?.projects ?? []).find((project: any) => project.id === selectedProjectId) ?? null,
    [bootstrap.data?.projects, selectedProjectId]
  )

  const {
    tasks,
    taskLookup,
    notes,
    taskGroups,
    noteGroups,
    noteLookup,
    searchNotes,
    taskNotes,
    specifications,
    searchSpecifications,
    searchKnowledge,
    specificationLookup,
    specTasks,
    specNotes,
    projectTags,
    projectRules,
    projectTemplates,
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
    taskGroupFilterId,
    noteGroupFilterId,
    searchQ,
    searchStatus,
    searchSpecificationStatus,
    searchPriority,
    searchArchived,
    searchTags,
    vectorStoreEnabled: Boolean(bootstrap.data?.vector_store_enabled),
    selectedProjectEmbeddingEnabled: Boolean(selectedProjectForSearch?.embedding_enabled),
    selectedProjectEmbeddingIndexStatus: String(selectedProjectForSearch?.embedding_index_status || 'not_indexed'),
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

  React.useEffect(() => {
    setTaskGroupFilterId('')
    setNoteGroupFilterId('')
  }, [selectedProjectId])

  React.useEffect(() => {
    if (!taskGroupFilterId) return
    const exists = (taskGroups.data?.items ?? []).some((group: any) => group.id === taskGroupFilterId)
    if (!exists) setTaskGroupFilterId('')
  }, [taskGroupFilterId, taskGroups.data?.items])

  React.useEffect(() => {
    if (!noteGroupFilterId) return
    const exists = (noteGroups.data?.items ?? []).some((group: any) => group.id === noteGroupFilterId)
    if (!exists) setNoteGroupFilterId('')
  }, [noteGroupFilterId, noteGroups.data?.items])
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

  const semanticQueryTokens = React.useMemo(() => {
    const normalized = normalizeSemanticText(searchQ || '')
    if (!normalized) return []
    return normalized.split(' ').filter((token) => token.length >= 3)
  }, [searchQ])

  const semanticRelevantItems = React.useMemo(() => {
    const payload = searchKnowledge.data
    const mode = String(payload?.mode || 'empty').toLowerCase()
    const items = Array.isArray(payload?.items) ? payload.items : []
    if (items.length === 0) return []
    if (mode !== 'graph+vector' && mode !== 'vector-only') return []
    if (semanticQueryTokens.length === 0) return []

    const scored = items
      .map((item: any) => ({
        item,
        finalScore: Number(item?.final_score || 0),
        vectorSimilarity:
          item?.vector_similarity === null || item?.vector_similarity === undefined
            ? null
            : Number(item.vector_similarity),
      }))
      .filter((entry: any) => Number.isFinite(entry.finalScore))
    if (scored.length === 0) return []

    const scoredWithVector = scored.filter(
      (entry: any) => entry.vectorSimilarity !== null && Number.isFinite(entry.vectorSimilarity)
    )
    if (scoredWithVector.length === 0) return []

    const topScore = Math.max(...scored.map((entry: any) => entry.finalScore))
    const topVectorSimilarity = Math.max(...scoredWithVector.map((entry: any) => Number(entry.vectorSimilarity || 0)))
    if (topVectorSimilarity < SEMANTIC_MIN_TOP_VECTOR_SIMILARITY) return []
    const scoreThreshold = Math.max(SEMANTIC_MIN_FINAL_SCORE, topScore * SEMANTIC_RELATIVE_SCORE_FACTOR)
    const vectorThreshold = Math.max(
      SEMANTIC_MIN_VECTOR_SIMILARITY,
      topVectorSimilarity * SEMANTIC_RELATIVE_VECTOR_FACTOR
    )

    const thresholdPassed = scored.filter((entry: any) => {
      if (entry.finalScore < scoreThreshold) return false
      if (entry.vectorSimilarity === null || !Number.isFinite(entry.vectorSimilarity)) return false
      if (entry.vectorSimilarity < vectorThreshold) return false
      return true
    })
    if (thresholdPassed.length === 0) return []

    const enriched = thresholdPassed.map((entry: any) => {
      const snippet = normalizeSemanticText(String(entry.item?.snippet || ''))
      const hasTokenMatch = semanticQueryTokens.some((token) => snippet.includes(token))
      const hasStrongVectorMatch = Number(entry.vectorSimilarity || 0) >= SEMANTIC_STRONG_VECTOR_SIMILARITY
      return {
        ...entry,
        hasTokenMatch,
        hasStrongVectorMatch,
      }
    })
    const hasAnyTokenMatch = enriched.some((entry: any) => entry.hasTokenMatch)
    if (hasAnyTokenMatch) {
      return enriched
        .filter((entry: any) => entry.hasTokenMatch || entry.hasStrongVectorMatch)
        .map((entry: any) => entry.item)
    }

    return enriched
      .filter((entry: any) => Number(entry.vectorSimilarity || 0) >= SEMANTIC_MIN_FALLBACK_VECTOR_SIMILARITY)
      .sort(
        (a: any, b: any) =>
          Number(b.finalScore || 0) - Number(a.finalScore || 0) ||
          Number(b.vectorSimilarity || 0) - Number(a.vectorSimilarity || 0)
      )
      .slice(0, SEMANTIC_FALLBACK_MAX_ITEMS_WITHOUT_TOKEN_MATCH)
      .map((entry: any) => entry.item)
  }, [searchKnowledge.data, semanticQueryTokens])

  const semanticTaskIds = React.useMemo(() => {
    const out: string[] = []
    const seen = new Set<string>()
    for (const item of semanticRelevantItems) {
      const type = String(item?.entity_type || '').toLowerCase()
      if (!type.includes('task')) continue
      const id = String(item?.entity_id || '').trim()
      if (!id || seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
    return out
  }, [semanticRelevantItems])

  const semanticNoteIds = React.useMemo(() => {
    const out: string[] = []
    const seen = new Set<string>()
    for (const item of semanticRelevantItems) {
      const type = String(item?.entity_type || '').toLowerCase()
      if (!type.includes('note')) continue
      const id = String(item?.entity_id || '').trim()
      if (!id || seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
    return out
  }, [semanticRelevantItems])

  const semanticSpecificationIds = React.useMemo(() => {
    const out: string[] = []
    const seen = new Set<string>()
    for (const item of semanticRelevantItems) {
      const type = String(item?.entity_type || '').toLowerCase()
      if (!(type.includes('specification') || type.includes('spec'))) continue
      const id = String(item?.entity_id || '').trim()
      if (!id || seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
    return out
  }, [semanticRelevantItems])

  const taskSearchLookupMap = React.useMemo(() => {
    const out = new Map<string, any>()
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        const id = String(item?.id || '').trim()
        if (!id) continue
        out.set(id, item)
      }
    }
    attach(taskLookup.data?.items)
    attach(tasks.data?.items)
    return out
  }, [taskLookup.data?.items, tasks.data?.items])

  const noteSearchLookupMap = React.useMemo(() => {
    const out = new Map<string, any>()
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        const id = String(item?.id || '').trim()
        if (!id) continue
        out.set(id, item)
      }
    }
    attach(noteLookup.data?.items)
    attach(searchNotes.data?.items)
    return out
  }, [noteLookup.data?.items, searchNotes.data?.items])

  const specificationSearchLookupMap = React.useMemo(() => {
    const out = new Map<string, any>()
    const attach = (items: any[] | undefined) => {
      for (const item of items ?? []) {
        const id = String(item?.id || '').trim()
        if (!id) continue
        out.set(id, item)
      }
    }
    attach(specificationLookup.data?.items)
    attach(searchSpecifications.data?.items)
    return out
  }, [specificationLookup.data?.items, searchSpecifications.data?.items])

  const mergeSearchItemsWithSemantic = React.useCallback((
    primaryItems: any[],
    semanticIds: string[],
    lookupMap: Map<string, any>
  ): any[] => {
    const merged = [...(primaryItems ?? [])]
    const seen = new Set<string>()
    for (const item of merged) {
      const id = String(item?.id || '').trim()
      if (!id) continue
      seen.add(id)
    }
    for (const id of semanticIds) {
      if (!id || seen.has(id)) continue
      const candidate = lookupMap.get(id)
      if (!candidate) continue
      merged.push(candidate)
      seen.add(id)
    }
    return merged
  }, [])

  const normalizedSearchTagSet = React.useMemo(
    () => new Set(searchTags.map((tag) => String(tag || '').trim().toLowerCase()).filter(Boolean)),
    [searchTags]
  )

  const searchTasksCombined = React.useMemo(() => {
    const merged = mergeSearchItemsWithSemantic(tasks.data?.items ?? [], semanticTaskIds, taskSearchLookupMap)
    return merged.filter((task: any) => {
      if (Boolean(task?.archived) !== Boolean(searchArchived)) return false
      if (searchStatus && String(task?.status || '') !== searchStatus) return false
      if (searchPriority && String(task?.priority || '') !== searchPriority) return false
      if (normalizedSearchTagSet.size > 0) {
        const labels = Array.isArray(task?.labels) ? task.labels : []
        const hasMatchingTag = labels.some((tag: any) => normalizedSearchTagSet.has(String(tag || '').toLowerCase()))
        if (!hasMatchingTag) return false
      }
      return true
    })
  }, [
    mergeSearchItemsWithSemantic,
    normalizedSearchTagSet,
    searchArchived,
    searchPriority,
    searchStatus,
    semanticTaskIds,
    taskSearchLookupMap,
    tasks.data?.items,
  ])

  const searchNotesCombined = React.useMemo(() => {
    const merged = mergeSearchItemsWithSemantic(searchNotes.data?.items ?? [], semanticNoteIds, noteSearchLookupMap)
    return merged.filter((note: any) => {
      if (Boolean(note?.archived) !== Boolean(searchArchived)) return false
      if (normalizedSearchTagSet.size > 0) {
        const tags = Array.isArray(note?.tags) ? note.tags : []
        const hasMatchingTag = tags.some((tag: any) => normalizedSearchTagSet.has(String(tag || '').toLowerCase()))
        if (!hasMatchingTag) return false
      }
      return true
    })
  }, [
    mergeSearchItemsWithSemantic,
    normalizedSearchTagSet,
    noteSearchLookupMap,
    searchArchived,
    searchNotes.data?.items,
    semanticNoteIds,
  ])

  const searchSpecificationsCombined = React.useMemo(() => {
    const merged = mergeSearchItemsWithSemantic(
      searchSpecifications.data?.items ?? [],
      semanticSpecificationIds,
      specificationSearchLookupMap
    )
    return merged.filter((specification: any) => {
      if (Boolean(specification?.archived) !== Boolean(searchArchived)) return false
      if (searchSpecificationStatus && String(specification?.status || '') !== searchSpecificationStatus) return false
      if (normalizedSearchTagSet.size > 0) {
        const tags = Array.isArray(specification?.tags) ? specification.tags : []
        const hasMatchingTag = tags.some((tag: any) => normalizedSearchTagSet.has(String(tag || '').toLowerCase()))
        if (!hasMatchingTag) return false
      }
      return true
    })
  }, [
    mergeSearchItemsWithSemantic,
    normalizedSearchTagSet,
    searchArchived,
    searchSpecificationStatus,
    searchSpecifications.data?.items,
    semanticSpecificationIds,
    specificationSearchLookupMap,
  ])

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
    getTagUsage,
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
    editNoteGroupId,
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
    editTaskGroupId,
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
    setTaskGroupFilterId('')
    setTab('tasks')
    return true
  }, [openTaskEditor, setSelectedProjectId, setTab, setTaskGroupFilterId])

  const openNote = React.useCallback((noteId: string, projectId?: string | null) => {
    if (!noteId) return false
    if (selectedNoteId === noteId) {
      if (projectId) setSelectedProjectId(projectId)
      setNoteGroupFilterId('')
      setTab('notes')
      return true
    }
    const changed = toggleNoteEditor(noteId)
    if (!changed) return false
    if (projectId) setSelectedProjectId(projectId)
    setNoteGroupFilterId('')
    setTab('notes')
    return true
  }, [selectedNoteId, toggleNoteEditor, setSelectedProjectId, setTab, setNoteGroupFilterId])

  

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
    setEditTaskGroupId,
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
    setEditNoteGroupId,
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
    editNoteGroupId,
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
    editTaskGroupId,
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
    createTaskGroupMutation,
    patchTaskGroupMutation,
    deleteTaskGroupMutation,
    reorderTaskGroupsMutation,
    completeTaskMutation,
    reopenTaskMutation,
    archiveTaskMutation,
    restoreTaskMutation,
    previewProjectFromTemplateMutation,
    createProjectMutation,
    deleteProjectMutation,
    createProjectRuleMutation,
    patchProjectRuleMutation,
    deleteProjectRuleMutation,
    createNoteMutation,
    createNoteGroupMutation,
    patchNoteGroupMutation,
    deleteNoteGroupMutation,
    reorderNoteGroupsMutation,
    moveNoteToGroupMutation,
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
    cancelAgentChat,
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
    projectTemplateKey,
    projectDescription,
    projectCustomStatusesText,
    projectExternalRefsText,
    projectAttachmentRefsText,
    projectEmbeddingEnabled,
    projectEmbeddingModel,
    projectContextPackEvidenceTopKText,
    projectTemplateParametersText,
    createProjectMemberIds,
    draftProjectRules,
    setProjectName,
    setProjectTemplateKey,
    setProjectDescription,
    setProjectCustomStatusesText,
    setProjectExternalRefsText,
    setProjectAttachmentRefsText,
    setProjectEmbeddingEnabled,
    setProjectEmbeddingModel,
    setProjectContextPackEvidenceTopKText,
    setProjectTemplateParametersText,
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
    projectTemplateKey,
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
      licenseStatus,
      activateLicenseMutation,
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
      getTagUsage,
      searchTags,
      toggleSearchTag,
      clearSearchTags,
      board,
      openTaskEditor,
      moveTaskToStatus,
      tasks,
      taskGroups,
      taskGroupFilterId,
      setTaskGroupFilterId,
      createTaskGroupMutation,
      patchTaskGroupMutation,
      deleteTaskGroupMutation,
      reorderTaskGroupsMutation,
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
      projectTemplateKey,
      setProjectTemplateKey,
      previewProjectFromTemplateMutation,
      createProjectMutation,
      projectCustomStatusesText,
      setProjectCustomStatusesText,
      projectEmbeddingEnabled,
      setProjectEmbeddingEnabled,
      projectEmbeddingModel,
      setProjectEmbeddingModel,
      projectContextPackEvidenceTopKText,
      setProjectContextPackEvidenceTopKText,
      projectTemplateParametersText,
      setProjectTemplateParametersText,
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
      canManageUsers,
      adminUsers,
      adminUsersLoading: adminUsersQuery.isLoading,
      adminUsersError,
      adminCreateUsername,
      setAdminCreateUsername,
      adminCreateFullName,
      setAdminCreateFullName,
      adminCreateRole,
      setAdminCreateRole,
      adminLastTempPassword,
      createAdminUserMutation,
      onCreateAdminUser,
      onResetAdminUserPassword,
      resetAdminPasswordUserId,
      onUpdateAdminUserRole,
      updateAdminRoleUserId,
      onDeactivateAdminUser,
      deactivateAdminUserId,
      userId,
      logout,
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
      projectTemplates,
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
      searchKnowledge,
      searchTasksCombined,
      searchNotesCombined,
      searchSpecificationsCombined,
      taskNotes,
      specifications,
      searchSpecifications,
      specTasks,
      specNotes,
      createNoteMutation,
      createNoteGroupMutation,
      patchNoteGroupMutation,
      deleteNoteGroupMutation,
      reorderNoteGroupsMutation,
      moveNoteToGroupMutation,
      noteGroups,
      noteArchived,
      setNoteArchived,
      noteGroupFilterId,
      setNoteGroupFilterId,
      noteTagSuggestions,
      noteTags,
      toggleNoteFilterTag,
      clearNoteFilterTags,
      selectedNoteId,
      selectedNote,
      editNoteTitle,
      setEditNoteTitle,
      editNoteGroupId,
      setEditNoteGroupId,
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
      speechLang,
      setTheme,
      setSpeechLang,
      themeMutation,
      submitBugReport: submitBugReportMutation.mutateAsync,
      submitBugReportPending: submitBugReportMutation.isPending,
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
      editTaskGroupId,
      setEditTaskGroupId,
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
      cancelAgentChat,
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

function AuthGate() {
  const [phase, setPhase] = React.useState<'checking' | 'login' | 'change-password' | 'ready'>('checking')
  const [authError, setAuthError] = React.useState<string | null>(null)
  const [pending, setPending] = React.useState(false)
  const [username, setUsername] = React.useState('m4tr1x')
  const [password, setPassword] = React.useState('')
  const [currentPassword, setCurrentPassword] = React.useState('')
  const [newPassword, setNewPassword] = React.useState('')
  const [confirmPassword, setConfirmPassword] = React.useState('')

  const clearClientSessionState = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const keys = ['codex_chat_state_v1', 'ui_tab', 'ui_selected_project_id', 'ui_projects_mode']
    for (const key of keys) {
      window.localStorage.removeItem(key)
    }
  }, [])

  const checkAuth = React.useCallback(async () => {
    setAuthError(null)
    setPhase('checking')
    try {
      const payload = await authMe()
      if (payload.user.must_change_password) {
        setPhase('change-password')
      } else {
        setPhase('ready')
      }
    } catch {
      setPhase('login')
    }
  }, [])

  React.useEffect(() => {
    void checkAuth()
  }, [checkAuth])

  const handleLogin = React.useCallback(async () => {
    if (pending) return
    setPending(true)
    setAuthError(null)
    try {
      const payload = await authLogin({ username: username.trim(), password })
      queryClient.clear()
      clearClientSessionState()
      setCurrentPassword(password)
      setPassword('')
      if (payload.user.must_change_password) {
        setPhase('change-password')
      } else {
        setPhase('ready')
      }
    } catch (err: any) {
      setAuthError(err?.message || 'Login failed')
      setPhase('login')
    } finally {
      setPending(false)
    }
  }, [clearClientSessionState, password, pending, username])

  const handleChangePassword = React.useCallback(async () => {
    if (pending) return
    if (newPassword.trim().length < 8) {
      setAuthError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setAuthError('Password confirmation does not match.')
      return
    }
    setPending(true)
    setAuthError(null)
    try {
      await authChangePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      queryClient.clear()
      setNewPassword('')
      setConfirmPassword('')
      setPhase('ready')
    } catch (err: any) {
      setAuthError(err?.message || 'Password change failed')
      setPhase('change-password')
    } finally {
      setPending(false)
    }
  }, [confirmPassword, currentPassword, newPassword, pending])

  const handleLogout = React.useCallback(() => {
    void authLogout().finally(() => {
      queryClient.clear()
      clearClientSessionState()
      setPhase('login')
      setAuthError(null)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    })
  }, [clearClientSessionState])

  if (phase === 'checking') {
    return <div className="page"><div className="card skeleton">Checking session...</div></div>
  }

  if (phase === 'login') {
    return (
      <div className="page">
        <section className="card" style={{ maxWidth: 520, margin: '10vh auto 0 auto' }}>
          <h2>Login</h2>
          <p className="meta">Sign in using username and password.</p>
          <form
            className="row wrap"
            style={{ marginTop: 10 }}
            onSubmit={(e) => {
              e.preventDefault()
              void handleLogin()
            }}
          >
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Username"
              autoComplete="username"
            />
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              type="password"
              autoComplete="current-password"
            />
            <button type="submit" disabled={pending || !username.trim() || !password}>
              {pending ? 'Logging in...' : 'Login'}
            </button>
          </form>
          {authError && <div className="notice notice-error" style={{ marginTop: 10 }}>{authError}</div>}
        </section>
      </div>
    )
  }

  if (phase === 'change-password') {
    return (
      <div className="page">
        <section className="card" style={{ maxWidth: 620, margin: '10vh auto 0 auto' }}>
          <h2>Change password</h2>
          <p className="meta">Temporary password must be changed before continuing. Minimum is 8 characters.</p>
          <div className="row wrap" style={{ marginTop: 10 }}>
            <input
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              type="password"
              placeholder="Current password"
              autoComplete="current-password"
            />
            <input
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              type="password"
              placeholder="New password"
              autoComplete="new-password"
            />
            <input
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              type="password"
              placeholder="Confirm new password"
              autoComplete="new-password"
            />
            <button onClick={handleChangePassword} disabled={pending || !currentPassword || !newPassword || !confirmPassword}>
              {pending ? 'Saving...' : 'Save new password'}
            </button>
          </div>
          {authError && <div className="notice notice-error" style={{ marginTop: 10 }}>{authError}</div>}
        </section>
      </div>
    )
  }

  return <App logout={handleLogout} />
}

export default function AppRoot() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate />
    </QueryClientProvider>
  )
}
