import React from 'react'
import {
  addProjectMember,
  deleteAttachment,
  patchNote,
  patchProject,
  patchTask,
  removeProjectMember,
  uploadAttachment,
} from '../api'
import { parseCommaTags, parseProjectEvidenceTopKInput, parseProjectStatusesText, toErrorMessage } from '../utils/ui'
import {
  buildExecutionTriggersFromEditor,
  buildRecurringRule,
  csvToUniqueList,
  hasConfiguredNonManualTrigger,
} from '../utils/taskAutomation'

type SharePayload = {
  tab?: string
  projectId?: string
  taskId?: string
  noteId?: string
  specificationId?: string
}

export function useAppActions(c: any) {
  const invalidateAll = React.useCallback(async () => {
    await c.qc.invalidateQueries({ queryKey: ['tasks'] })
    await c.qc.invalidateQueries({ queryKey: ['task-lookup'] })
    await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    await c.qc.invalidateQueries({ queryKey: ['task-groups'] })
    await c.qc.invalidateQueries({ queryKey: ['notes'] })
    await c.qc.invalidateQueries({ queryKey: ['search-notes'] })
    await c.qc.invalidateQueries({ queryKey: ['note-groups'] })
    await c.qc.invalidateQueries({ queryKey: ['project-tags'] })
    await c.qc.invalidateQueries({ queryKey: ['board'] })
    await c.qc.invalidateQueries({ queryKey: ['bootstrap'] })
    await c.qc.invalidateQueries({ queryKey: ['notifications'] })
    await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    await c.qc.invalidateQueries({ queryKey: ['specifications'] })
    await c.qc.invalidateQueries({ queryKey: ['specification-lookup'] })
    await c.qc.invalidateQueries({ queryKey: ['spec-tasks'] })
    await c.qc.invalidateQueries({ queryKey: ['spec-notes'] })
  }, [c.qc])

  const moveTaskToStatus = React.useCallback(
    (taskId: string, nextStatus: string, nextTaskGroupId?: string | null) => {
      const payload: { status: string; task_group_id?: string | null } = { status: nextStatus }
      if (nextTaskGroupId !== undefined) payload.task_group_id = nextTaskGroupId
      patchTask(c.userId, taskId, payload)
        .then(() => {
          c.setUiError(null)
          return invalidateAll()
        })
        .catch((err) => c.setUiError(toErrorMessage(err, 'Task move failed')))
    },
    [c.setUiError, c.userId, invalidateAll]
  )

  const uploadAttachmentRef = React.useCallback(
    async (file: File, scope: { project_id?: string | null; task_id?: string | null; note_id?: string | null }) => {
      const projectId = scope.project_id ?? undefined
      const taskId = scope.task_id ?? undefined
      const noteId = scope.note_id ?? undefined
      if (!c.workspaceId) throw new Error('Workspace is missing')
      if (!projectId && !taskId && !noteId) throw new Error('Select project/task/note before upload')
      const ref = await uploadAttachment(c.userId, {
        workspace_id: c.workspaceId,
        project_id: projectId,
        task_id: taskId,
        note_id: noteId,
        file,
      })
      c.setUiError(null)
      return ref
    },
    [c.setUiError, c.userId, c.workspaceId]
  )

  const removeUploadedAttachment = React.useCallback(
    async (path: string) => {
      if (!c.workspaceId) throw new Error('Workspace is missing')
      try {
        await deleteAttachment(c.userId, { workspace_id: c.workspaceId, path })
      } catch (err) {
        const message = toErrorMessage(err, '')
        if (!/attachment not found/i.test(message)) throw err
      }
      c.setUiError(null)
    },
    [c.setUiError, c.userId, c.workspaceId]
  )

  const buildShareUrl = React.useCallback(
    (payload: SharePayload) => {
      const u = new URL(window.location.href)
      const tab = payload.tab ?? c.tab
      u.searchParams.set('tab', tab)
      if (payload.projectId) u.searchParams.set('project', payload.projectId)
      else u.searchParams.delete('project')
      if (payload.taskId) u.searchParams.set('task', payload.taskId)
      else u.searchParams.delete('task')
      if (payload.noteId) u.searchParams.set('note', payload.noteId)
      else u.searchParams.delete('note')
      if (payload.specificationId) u.searchParams.set('specification', payload.specificationId)
      else u.searchParams.delete('specification')
      if (tab !== 'tasks') u.searchParams.delete('task')
      if (tab !== 'notes') u.searchParams.delete('note')
      if (tab !== 'specifications') u.searchParams.delete('specification')
      return u.toString()
    },
    [c.tab]
  )

  const copyShareLink = React.useCallback(async (payload: SharePayload) => {
    try {
      const text = buildShareUrl(payload)
      const canUseClipboardApi = typeof navigator !== 'undefined' && !!navigator.clipboard?.writeText
      if (canUseClipboardApi) {
        await navigator.clipboard.writeText(text)
      } else if (typeof document !== 'undefined') {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.setAttribute('readonly', 'true')
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        ta.style.pointerEvents = 'none'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('Clipboard copy is not supported in this browser context')
      } else {
        throw new Error('Clipboard copy is not available')
      }
      c.setUiInfo('Link copied to clipboard')
      setTimeout(() => c.setUiInfo(null), 1800)
    } catch (err) {
      c.setUiError(toErrorMessage(err, 'Copy link failed'))
    }
  }, [buildShareUrl, c])

  const syncProjectMembers = React.useCallback(async (projectId: string, desiredMemberIds: string[]) => {
    const currentMemberIds: string[] = Array.from(
      new Set(
        (c.projectMembers ?? [])
          .filter((pm: any) => pm.project_id === projectId)
          .map((pm: any) => String(pm.user_id))
      )
    )
    const currentSet = new Set(currentMemberIds)
    const desiredSet = new Set(desiredMemberIds)
    const toAdd = desiredMemberIds.filter((uid) => !currentSet.has(uid))
    const toRemove = currentMemberIds.filter((uid) => !desiredSet.has(uid))
    if (toAdd.length > 0 || toRemove.length > 0) {
      await Promise.all([
        ...toAdd.map((uid) => addProjectMember(c.userId, projectId, { user_id: uid })),
        ...toRemove.map((uid) => removeProjectMember(c.userId, projectId, uid)),
      ])
    }
  }, [c.projectMembers, c.userId])

  const saveProjectNow = React.useCallback(async () => {
    if (!c.selectedProjectId) throw new Error('No project selected')
    const name = c.editProjectName.trim()
    if (!name) throw new Error('Project name is required')
    const rawMemberIds: string[] = (c.editProjectMemberIds ?? [])
      .map((value: any) => String(value))
      .filter((value: string) => Boolean(value))
    const memberIds: string[] = Array.from(new Set<string>(rawMemberIds)).sort()
    const contextPackEvidenceTopK = parseProjectEvidenceTopKInput(c.editProjectContextPackEvidenceTopKText)
    const effectiveChatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' = Boolean(c.editProjectEmbeddingEnabled)
      ? c.editProjectChatIndexMode
      : 'OFF'
    const effectiveChatAttachmentMode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' =
      effectiveChatIndexMode === 'OFF' ? 'METADATA_ONLY' : c.editProjectChatAttachmentIngestionMode
    const patchedProject = await patchProject(c.userId, c.selectedProjectId, {
      name,
      description: c.editProjectDescription,
      custom_statuses: parseProjectStatusesText(c.editProjectCustomStatusesText),
      external_refs: c.parseExternalRefsText(c.editProjectExternalRefsText),
      attachment_refs: c.parseAttachmentRefsText(c.editProjectAttachmentRefsText),
      embedding_enabled: Boolean(c.editProjectEmbeddingEnabled),
      embedding_model: String(c.editProjectEmbeddingModel || '').trim() || null,
      context_pack_evidence_top_k: contextPackEvidenceTopK,
      chat_index_mode: effectiveChatIndexMode,
      chat_attachment_ingestion_mode: effectiveChatAttachmentMode,
      event_storming_enabled: Boolean(c.editProjectEventStormingEnabled),
    })
    await syncProjectMembers(c.selectedProjectId, memberIds)
    c.qc.setQueryData(['bootstrap', c.userId], (prev: any) => {
      if (!prev || !Array.isArray(prev.projects)) return prev
      return {
        ...prev,
        projects: prev.projects.map((project: any) =>
          project?.id === patchedProject.id ? { ...project, ...patchedProject } : project
        ),
      }
    })
    await c.qc.invalidateQueries({ queryKey: ['bootstrap', c.userId] })
    await c.qc.invalidateQueries({ queryKey: ['project-graph-context-pack', c.userId, c.selectedProjectId] })
    await c.qc.invalidateQueries({ queryKey: ['project-event-storming-overview', c.userId, c.selectedProjectId] })
    await c.qc.invalidateQueries({ queryKey: ['project-event-storming-subgraph', c.userId, c.selectedProjectId] })
  }, [
    c.editProjectAttachmentRefsText,
    c.editProjectCustomStatusesText,
    c.editProjectDescription,
    c.editProjectEmbeddingEnabled,
    c.editProjectEmbeddingModel,
    c.editProjectContextPackEvidenceTopKText,
    c.editProjectChatIndexMode,
    c.editProjectChatAttachmentIngestionMode,
    c.editProjectEventStormingEnabled,
    c.editProjectExternalRefsText,
    c.editProjectMemberIds,
    c.editProjectName,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.qc,
    c.selectedProjectId,
    c.userId,
    syncProjectMembers,
  ])

  const saveNoteNow = React.useCallback(async () => {
    if (!c.selectedNoteId) throw new Error('No note selected')
    const payload = {
      title: c.editNoteTitle.trim() || 'Untitled',
      body: c.editNoteBody,
      note_group_id: c.editNoteGroupId || null,
      tags: parseCommaTags(c.editNoteTags),
      external_refs: c.parseExternalRefsText(c.editNoteExternalRefsText),
      attachment_refs: c.parseAttachmentRefsText(c.editNoteAttachmentRefsText),
    }
    await patchNote(c.userId, c.selectedNoteId, payload)
    await c.qc.invalidateQueries({ queryKey: ['notes'] })
    await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    await c.qc.invalidateQueries({ queryKey: ['project-tags'] })
  }, [
    c.editNoteAttachmentRefsText,
    c.editNoteBody,
    c.editNoteExternalRefsText,
    c.editNoteGroupId,
    c.editNoteTags,
    c.editNoteTitle,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.qc,
    c.selectedNoteId,
    c.userId,
  ])

  const buildTaskPatchPayload = React.useCallback(() => {
    if (!c.selectedTaskId) throw new Error('No task selected')
    const automationInstruction = c.editScheduledInstruction.trim() || null
    const scheduledAtUtc =
      c.editTaskType === 'scheduled_instruction' && c.editScheduledAtUtc
        ? new Date(c.editScheduledAtUtc).toISOString()
        : ''
    const recurringRule =
      c.editTaskType === 'scheduled_instruction'
        ? buildRecurringRule(c.editRecurringEvery, c.editRecurringUnit)
        : null
    const executionTriggers = buildExecutionTriggersFromEditor({
      taskType: c.editTaskType,
      scheduledAtUtc,
      scheduleTimezone: String(c.editScheduleTimezone || ''),
      scheduleRunOnStatuses: c.editScheduleRunOnStatuses,
      recurringEvery: c.editRecurringEvery,
      recurringUnit: c.editRecurringUnit,
      selfEnabled: Boolean(c.editStatusTriggerSelfEnabled),
      selfFromStatusesText: c.editStatusTriggerSelfFromStatusesText,
      selfToStatusesText: c.editStatusTriggerSelfToStatusesText,
      externalEnabled: Boolean(c.editStatusTriggerExternalEnabled),
      externalMatchMode: c.editStatusTriggerExternalMatchMode === 'all' ? 'all' : 'any',
      externalTaskIdsText: c.editStatusTriggerExternalTaskIdsText,
      externalFromStatusesText: c.editStatusTriggerExternalFromStatusesText,
      externalToStatusesText: c.editStatusTriggerExternalToStatusesText,
    })
    const payload: Parameters<typeof patchTask>[2] = {
      title: c.editTitle.trim() || 'Untitled',
      description: c.editDescription,
      status: c.editStatus,
      priority: c.editPriority,
      project_id: c.editProjectId || c.selectedTask?.project_id,
      task_group_id: c.editTaskGroupId || null,
      assignee_id: c.editAssigneeId || null,
      assigned_agent_code: c.editAssigneeId ? (c.editAssignedAgentCode || null) : null,
      labels: c.editTaskTags,
      external_refs: c.parseExternalRefsText(c.editTaskExternalRefsText),
      attachment_refs: c.parseAttachmentRefsText(c.editTaskAttachmentRefsText),
      due_date: c.editDueDate ? new Date(c.editDueDate).toISOString() : null,
      instruction: automationInstruction,
      execution_triggers: executionTriggers,
      task_type: c.editTaskType,
    }
    if (c.editTaskType === 'scheduled_instruction') {
      payload.scheduled_at_utc = scheduledAtUtc || null
      payload.schedule_timezone = c.editScheduleTimezone || null
      payload.scheduled_instruction = automationInstruction
      payload.recurring_rule = recurringRule
    }
    return { payload }
  }, [
    c.editDescription,
    c.editDueDate,
    c.editPriority,
    c.editProjectId,
    c.editTaskGroupId,
    c.editAssigneeId,
    c.editAssignedAgentCode,
    c.editRecurringEvery,
    c.editRecurringUnit,
    c.editScheduledAtUtc,
    c.editScheduledInstruction,
    c.editScheduleTimezone,
    c.editScheduleRunOnStatuses,
    c.editStatusTriggerSelfEnabled,
    c.editStatusTriggerSelfFromStatusesText,
    c.editStatusTriggerSelfToStatusesText,
    c.editStatusTriggerExternalEnabled,
    c.editStatusTriggerExternalMatchMode,
    c.editStatusTriggerExternalTaskIdsText,
    c.editStatusTriggerExternalFromStatusesText,
    c.editStatusTriggerExternalToStatusesText,
    c.editStatus,
    c.editTaskAttachmentRefsText,
    c.editTaskExternalRefsText,
    c.editTaskTags,
    c.editTaskType,
    c.editTitle,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.selectedTask?.project_id,
    c.selectedTaskId,
  ])

  const saveTaskNow = React.useCallback(async () => {
    if (!c.selectedTaskId) throw new Error('No task selected')
    if (c.editTaskType === 'scheduled_instruction' && !c.editScheduledAtUtc) {
      throw new Error('Set schedule date and time to save.')
    }
    if (c.editTaskType === 'scheduled_instruction' && !String(c.editScheduleTimezone || '').trim()) {
      throw new Error('Set schedule timezone to save.')
    }
    if (c.editTaskType === 'scheduled_instruction' && (!Array.isArray(c.editScheduleRunOnStatuses) || c.editScheduleRunOnStatuses.length === 0)) {
      throw new Error('Pick at least one status for scheduled runs.')
    }
    if (c.editStatusTriggerSelfEnabled && csvToUniqueList(c.editStatusTriggerSelfToStatusesText).length === 0) {
      throw new Error('Add at least one target status for self trigger.')
    }
    if (c.editStatusTriggerExternalEnabled && csvToUniqueList(c.editStatusTriggerExternalToStatusesText).length === 0) {
      throw new Error('Add at least one target status for external trigger.')
    }
    if (c.editStatusTriggerExternalEnabled && csvToUniqueList(c.editStatusTriggerExternalTaskIdsText).length === 0) {
      throw new Error('Add at least one source task ID for external trigger.')
    }
    const executionTriggers = buildExecutionTriggersFromEditor({
      taskType: c.editTaskType,
      scheduledAtUtc:
        c.editTaskType === 'scheduled_instruction' && c.editScheduledAtUtc
          ? new Date(c.editScheduledAtUtc).toISOString()
          : '',
      scheduleTimezone: String(c.editScheduleTimezone || ''),
      scheduleRunOnStatuses: c.editScheduleRunOnStatuses,
      recurringEvery: c.editRecurringEvery,
      recurringUnit: c.editRecurringUnit,
      selfEnabled: Boolean(c.editStatusTriggerSelfEnabled),
      selfFromStatusesText: c.editStatusTriggerSelfFromStatusesText,
      selfToStatusesText: c.editStatusTriggerSelfToStatusesText,
      externalEnabled: Boolean(c.editStatusTriggerExternalEnabled),
      externalMatchMode: c.editStatusTriggerExternalMatchMode === 'all' ? 'all' : 'any',
      externalTaskIdsText: c.editStatusTriggerExternalTaskIdsText,
      externalFromStatusesText: c.editStatusTriggerExternalFromStatusesText,
      externalToStatusesText: c.editStatusTriggerExternalToStatusesText,
    })
    if (hasConfiguredNonManualTrigger(executionTriggers) && !c.editScheduledInstruction.trim()) {
      throw new Error('Add automation instruction to save.')
    }
    const { payload } = buildTaskPatchPayload()
    const savedTask = await patchTask(c.userId, c.selectedTaskId, payload)
    c.qc.setQueryData(['task', c.userId, c.selectedTaskId], savedTask)
    await c.qc.invalidateQueries({ queryKey: ['task', c.userId, c.selectedTaskId] })
    await c.qc.invalidateQueries({ queryKey: ['tasks'] })
    await c.qc.invalidateQueries({ queryKey: ['board'] })
  }, [
    buildTaskPatchPayload,
    c.editScheduledInstruction,
    c.editScheduledAtUtc,
    c.editScheduleTimezone,
    c.editRecurringEvery,
    c.editRecurringUnit,
    c.editStatusTriggerSelfEnabled,
    c.editStatusTriggerSelfFromStatusesText,
    c.editStatusTriggerSelfToStatusesText,
    c.editStatusTriggerExternalEnabled,
    c.editStatusTriggerExternalMatchMode,
    c.editStatusTriggerExternalTaskIdsText,
    c.editStatusTriggerExternalFromStatusesText,
    c.editStatusTriggerExternalToStatusesText,
    c.editTaskType,
    c.editScheduleRunOnStatuses,
    c.qc,
    c.selectedTaskId,
    c.userId,
  ])

  return {
    invalidateAll,
    moveTaskToStatus,
    uploadAttachmentRef,
    removeUploadedAttachment,
    copyShareLink,
    saveProjectNow,
    saveNoteNow,
    saveTaskNow,
  }
}
