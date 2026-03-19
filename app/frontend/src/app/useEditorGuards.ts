import React from 'react'
import { parseCommaTags, parseProjectStatusesText, stableJson, toLocalDateTimeInput } from '../utils/ui'
import {
  deriveInstruction,
  extractEnabledScheduleTrigger,
  extractEnabledStatusTrigger,
  listToCsv,
  normalizeExecutionTriggers,
  normalizeScheduleRunOnStatuses,
} from '../utils/taskAutomation'

function normalizeUtcIsoToMinute(raw: string): string {
  const value = String(raw || '').trim()
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  parsed.setSeconds(0, 0)
  return parsed.toISOString()
}

function detectBrowserTimezoneForDirty(): string {
  if (typeof Intl === 'undefined' || typeof Intl.DateTimeFormat !== 'function') return 'UTC'
  try {
    const value = String(Intl.DateTimeFormat().resolvedOptions().timeZone || '').trim()
    return value || 'UTC'
  } catch {
    return 'UTC'
  }
}

function normalizeExecutionTriggersForDirtyCheck(input: unknown) {
  return normalizeExecutionTriggers(input).map((trigger) => {
    if (trigger.kind !== 'schedule') return trigger
    return {
      ...trigger,
      scheduled_at_utc: normalizeUtcIsoToMinute(trigger.scheduled_at_utc),
    }
  })
}

function normalizeChatAttachmentIngestionModeForDirty(value: unknown): 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' {
  const mode = String(value || '').trim().toUpperCase()
  if (mode === 'OFF') return 'OFF'
  if (mode === 'FULL_TEXT') return 'FULL_TEXT'
  return 'METADATA_ONLY'
}

function normalizeExternalRefsForDirtyCheck(input: unknown): Array<{ url: string; title?: string; source?: string }> {
  if (!Array.isArray(input)) return []
  return input
    .map((item) => {
      const row = item as Record<string, unknown>
      const url = String(row?.url || '').trim()
      if (!url) return null
      const title = String(row?.title || '').trim()
      const source = String(row?.source || '').trim()
      return {
        url,
        ...(title ? { title } : {}),
        ...(source ? { source } : {}),
      }
    })
    .filter(Boolean) as Array<{ url: string; title?: string; source?: string }>
}

function normalizeAttachmentRefsForDirtyCheck(
  input: unknown
): Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }> {
  if (!Array.isArray(input)) return []
  return input
    .map((item) => {
      const row = item as Record<string, unknown>
      const path = String(row?.path || '').trim()
      if (!path) return null
      const name = String(row?.name || '').trim()
      const mimeType = String(row?.mime_type || '').trim()
      const rawSize = row?.size_bytes
      const sizeBytes =
        typeof rawSize === 'number'
          ? Math.max(0, Math.floor(rawSize))
          : Number.isFinite(Number(rawSize))
            ? Math.max(0, Math.floor(Number(rawSize)))
            : undefined
      return {
        path,
        ...(name ? { name } : {}),
        ...(mimeType ? { mime_type: mimeType } : {}),
        ...(sizeBytes != null ? { size_bytes: sizeBytes } : {}),
      }
    })
    .filter(Boolean) as Array<{ path: string; name?: string; mime_type?: string; size_bytes?: number }>
}

export function useEditorGuards(c: any) {
  const requestDiscardChanges = React.useCallback((message: string, onConfirm: () => void): boolean => {
    if (typeof c.requestDiscardChanges === 'function') {
      c.requestDiscardChanges(message, onConfirm)
      return false
    }
    if (typeof window === 'undefined') return true
    if (!window.confirm(message)) return false
    onConfirm()
    return true
  }, [c.requestDiscardChanges])

  const toggleCreateProjectMember = React.useCallback((userIdToToggle: string) => {
    const id = String(userIdToToggle || '').trim()
    if (!id) return
    c.setCreateProjectMemberIds((prev: string[]) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [c.setCreateProjectMemberIds])

  const toggleEditProjectMember = React.useCallback((userIdToToggle: string) => {
    const id = String(userIdToToggle || '').trim()
    if (!id) return
    c.setEditProjectMemberIds((prev: string[]) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))
  }, [c.setEditProjectMemberIds])

  const selectedProjectMemberIds = React.useMemo(
    () =>
      Array.from(
        new Set(
          (c.projectMembers ?? [])
            .filter((pm: any) => pm.project_id === c.selectedProjectId)
            .map((pm: any) => pm.user_id)
        )
      ).sort(),
    [c.projectMembers, c.selectedProjectId]
  )
  const projectIsDirty = React.useMemo(() => {
    if (!c.showProjectEditForm || !c.selectedProject) return false
    const selectedProjectId = String(c.selectedProject.id || '').trim()
    if (!selectedProjectId) return false
    if (String(c.projectEditorHydratedProjectId || '').trim() !== selectedProjectId) return false
    if (String(c.projectEditorMembersHydratedProjectId || '').trim() !== selectedProjectId) return false
    return (
      c.editProjectName.trim() !== (c.selectedProject.name ?? '').trim() ||
      c.editProjectDescription !== (c.selectedProject.description ?? '') ||
      stableJson(parseProjectStatusesText(c.editProjectCustomStatusesText)) !==
        stableJson(c.selectedProject.custom_statuses ?? []) ||
      Boolean(c.editProjectEmbeddingEnabled) !== Boolean(c.selectedProject.embedding_enabled) ||
      String(c.editProjectEmbeddingModel || '').trim() !== String(c.selectedProject.embedding_model || '').trim() ||
      Boolean(c.editProjectVectorIndexDistillEnabled) !== Boolean(c.selectedProject.vector_index_distill_enabled) ||
      String(c.editProjectContextPackEvidenceTopKText || '').trim() !==
        String(c.selectedProject.context_pack_evidence_top_k ?? '').trim() ||
      String(c.editProjectAutomationMaxParallelTasksText || '').trim() !==
        String(c.selectedProject.automation_max_parallel_tasks ?? 4).trim() ||
      String(c.editProjectChatIndexMode || 'OFF').trim().toUpperCase() !==
        String(c.selectedProject.chat_index_mode || 'OFF').trim().toUpperCase() ||
      normalizeChatAttachmentIngestionModeForDirty(c.editProjectChatAttachmentIngestionMode || 'METADATA_ONLY') !==
        normalizeChatAttachmentIngestionModeForDirty(c.selectedProject.chat_attachment_ingestion_mode || 'METADATA_ONLY') ||
      Boolean(c.editProjectEventStormingEnabled) !== Boolean(c.selectedProject.event_storming_enabled ?? true) ||
      stableJson(normalizeExternalRefsForDirtyCheck(c.parseExternalRefsText(c.editProjectExternalRefsText))) !==
        stableJson(normalizeExternalRefsForDirtyCheck(c.selectedProject.external_refs ?? [])) ||
      stableJson(normalizeAttachmentRefsForDirtyCheck(c.parseAttachmentRefsText(c.editProjectAttachmentRefsText))) !==
        stableJson(normalizeAttachmentRefsForDirtyCheck(c.selectedProject.attachment_refs ?? [])) ||
      stableJson(Array.from(new Set(c.editProjectMemberIds.filter(Boolean))).sort()) !== stableJson(selectedProjectMemberIds)
    )
  }, [
    c.editProjectAttachmentRefsText,
    c.editProjectCustomStatusesText,
    c.editProjectDescription,
    c.editProjectEmbeddingEnabled,
    c.editProjectEmbeddingModel,
    c.editProjectVectorIndexDistillEnabled,
    c.projectEditorHydratedProjectId,
    c.projectEditorMembersHydratedProjectId,
    c.editProjectContextPackEvidenceTopKText,
    c.editProjectAutomationMaxParallelTasksText,
    c.editProjectChatIndexMode,
    c.editProjectChatAttachmentIngestionMode,
    c.editProjectEventStormingEnabled,
    c.editProjectExternalRefsText,
    c.editProjectMemberIds,
    c.editProjectName,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.selectedProject,
    c.showProjectEditForm,
    selectedProjectMemberIds,
  ])

  const noteIsDirty = React.useMemo(() => {
    if (!c.selectedNote) return false
    return (
      (c.editNoteTitle.trim() || 'Untitled') !== (c.selectedNote.title?.trim() || 'Untitled') ||
      c.editNoteBody !== (c.selectedNote.body ?? '') ||
      (c.editNoteGroupId || null) !== (c.selectedNote.note_group_id ?? null) ||
      stableJson(parseCommaTags(c.editNoteTags)) !== stableJson(c.selectedNote.tags ?? []) ||
      stableJson(normalizeExternalRefsForDirtyCheck(c.parseExternalRefsText(c.editNoteExternalRefsText))) !==
        stableJson(normalizeExternalRefsForDirtyCheck(c.selectedNote.external_refs ?? [])) ||
      stableJson(normalizeAttachmentRefsForDirtyCheck(c.parseAttachmentRefsText(c.editNoteAttachmentRefsText))) !==
        stableJson(normalizeAttachmentRefsForDirtyCheck(c.selectedNote.attachment_refs ?? []))
    )
  }, [
    c.editNoteGroupId,
    c.editNoteAttachmentRefsText,
    c.editNoteBody,
    c.editNoteExternalRefsText,
    c.editNoteTags,
    c.editNoteTitle,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.selectedNote,
  ])

  const specificationIsDirty = React.useMemo(() => {
    if (!c.selectedSpecification) return false
    return (
      (c.editSpecificationTitle || '').trim() !== (c.selectedSpecification.title || '').trim() ||
      (c.editSpecificationBody || '') !== (c.selectedSpecification.body || '') ||
      (c.editSpecificationStatus || 'Draft') !== (c.selectedSpecification.status || 'Draft') ||
      stableJson(parseCommaTags(c.editSpecificationTags).map((tag) => tag.toLowerCase())) !==
        stableJson((c.selectedSpecification.tags ?? []).map((tag: string) => String(tag || '').toLowerCase())) ||
      stableJson(normalizeExternalRefsForDirtyCheck(c.parseExternalRefsText(c.editSpecificationExternalRefsText))) !==
        stableJson(normalizeExternalRefsForDirtyCheck(c.selectedSpecification.external_refs ?? [])) ||
      stableJson(normalizeAttachmentRefsForDirtyCheck(c.parseAttachmentRefsText(c.editSpecificationAttachmentRefsText))) !==
        stableJson(normalizeAttachmentRefsForDirtyCheck(c.selectedSpecification.attachment_refs ?? []))
    )
  }, [
    c.editSpecificationAttachmentRefsText,
    c.editSpecificationBody,
    c.editSpecificationExternalRefsText,
    c.editSpecificationStatus,
    c.editSpecificationTags,
    c.editSpecificationTitle,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.selectedSpecification,
  ])

  const taskIsDirty = React.useMemo(() => {
    const baselineTask = c.taskEditorBaselineTask ?? c.selectedTask
    if (!baselineTask) return false
    if (!c.taskEditorTouched) return false
    const hydratedTaskId = String(c.taskEditorHydratedTaskId || '')
    const baselineTaskId = String(baselineTask.id || '')
    const selectedTaskId = String(c.selectedTask?.id || '')
    if (hydratedTaskId !== baselineTaskId) {
      return false
    }
    // Prevent stale dirty state from the previously opened task from leaking into
    // the next task before the editor hydration effect finishes for the new task.
    if (selectedTaskId && hydratedTaskId !== selectedTaskId) {
      return false
    }
    const selectedTaskScheduleTimezone = String(baselineTask.schedule_timezone || '').trim()
    const fallbackScheduleTimezone = String(c.currentUserTimezone || 'UTC').trim() || 'UTC'
    const browserScheduleTimezone = detectBrowserTimezoneForDirty()
    const editScheduleTimezoneRaw = String(c.editScheduleTimezone || '').trim()
    const scheduleTimezoneForDirty = (
      c.editTaskType === 'scheduled_instruction'
        ? (
            !selectedTaskScheduleTimezone &&
            (editScheduleTimezoneRaw === fallbackScheduleTimezone || editScheduleTimezoneRaw === browserScheduleTimezone)
              ? ''
              : editScheduleTimezoneRaw
          )
        : ''
    )
    const scheduleTriggerIsoForDirty =
      c.editTaskType === 'scheduled_instruction' && c.editScheduledAtUtc
        ? normalizeUtcIsoToMinute(new Date(c.editScheduledAtUtc).toISOString())
        : ''
    const originalExecutionTriggers = normalizeExecutionTriggersForDirtyCheck(baselineTask.execution_triggers)
    const originalScheduleTrigger = extractEnabledScheduleTrigger(originalExecutionTriggers)
    const originalSelfTrigger = extractEnabledStatusTrigger(originalExecutionTriggers, 'self')
    const originalExternalTrigger = extractEnabledStatusTrigger(originalExecutionTriggers, 'external')

    const current = {
      title: (c.editTitle.trim() || 'Untitled'),
      description: c.editDescription,
      status: c.editStatus,
      priority: c.editPriority,
      project_id: String(c.editProjectId || baselineTask.project_id || ''),
      task_group_id: c.editTaskGroupId || null,
      assignee_id: c.editAssigneeId || null,
      assigned_agent_code: c.editAssigneeId ? (c.editAssignedAgentCode || null) : null,
      labels: c.editTaskTags,
      due_date: c.editDueDate || '',
      task_type: c.editTaskType,
      scheduled_at_utc: c.editScheduledAtUtc || '',
      schedule_timezone: scheduleTimezoneForDirty,
      schedule_run_on_statuses:
        c.editTaskType === 'scheduled_instruction' ? normalizeScheduleRunOnStatuses(c.editScheduleRunOnStatuses) : [],
      instruction: c.editScheduledInstruction.trim(),
      recurring_rule:
        c.editTaskType === 'scheduled_instruction' && c.editRecurringEvery.trim()
          ? `every:${Math.max(1, Number(c.editRecurringEvery) || 1)}${c.editRecurringUnit}`
          : '',
      status_trigger_self_enabled: Boolean(c.editStatusTriggerSelfEnabled),
      status_trigger_self_from: c.editStatusTriggerSelfFromStatusesText,
      status_trigger_self_to: c.editStatusTriggerSelfToStatusesText,
      status_trigger_external_enabled: Boolean(c.editStatusTriggerExternalEnabled),
      status_trigger_external_match_mode: c.editStatusTriggerExternalMatchMode === 'all' ? 'all' : 'any',
      status_trigger_external_task_ids: c.editStatusTriggerExternalTaskIdsText,
      status_trigger_external_from: c.editStatusTriggerExternalFromStatusesText,
      status_trigger_external_to: c.editStatusTriggerExternalToStatusesText,
      external_refs: normalizeExternalRefsForDirtyCheck(c.parseExternalRefsText(c.editTaskExternalRefsText)),
      attachment_refs: normalizeAttachmentRefsForDirtyCheck(c.parseAttachmentRefsText(c.editTaskAttachmentRefsText)),
    }
    const original = {
      title: baselineTask.title?.trim() || 'Untitled',
      description: baselineTask.description ?? '',
      status: baselineTask.status ?? 'To Do',
      priority: baselineTask.priority ?? 'Med',
      project_id: String(baselineTask.project_id || ''),
      task_group_id: baselineTask.task_group_id ?? null,
      assignee_id: baselineTask.assignee_id ?? null,
      assigned_agent_code: baselineTask.assigned_agent_code ?? null,
      labels: baselineTask.labels ?? [],
      due_date: toLocalDateTimeInput(baselineTask.due_date),
      task_type: baselineTask.task_type ?? 'manual',
      scheduled_at_utc: toLocalDateTimeInput(baselineTask.scheduled_at_utc),
      schedule_timezone:
        (baselineTask.task_type ?? 'manual') === 'scheduled_instruction'
          ? (selectedTaskScheduleTimezone || '')
          : '',
      schedule_run_on_statuses:
        (baselineTask.task_type ?? 'manual') === 'scheduled_instruction'
          ? normalizeScheduleRunOnStatuses(originalScheduleTrigger?.run_on_statuses)
          : [],
      instruction: deriveInstruction(baselineTask).trim(),
      recurring_rule:
        (baselineTask.task_type ?? 'manual') === 'scheduled_instruction' ? String(baselineTask.recurring_rule ?? '') : '',
      status_trigger_self_enabled: Boolean(originalSelfTrigger),
      status_trigger_self_from: listToCsv(originalSelfTrigger?.from_statuses),
      status_trigger_self_to: listToCsv(originalSelfTrigger?.to_statuses),
      status_trigger_external_enabled: Boolean(originalExternalTrigger),
      status_trigger_external_match_mode: originalExternalTrigger?.match_mode === 'all' ? 'all' : 'any',
      status_trigger_external_task_ids: listToCsv(originalExternalTrigger?.selector?.task_ids),
      status_trigger_external_from: listToCsv(originalExternalTrigger?.from_statuses),
      status_trigger_external_to: listToCsv(originalExternalTrigger?.to_statuses),
      external_refs: normalizeExternalRefsForDirtyCheck(baselineTask.external_refs ?? []),
      attachment_refs: normalizeAttachmentRefsForDirtyCheck(baselineTask.attachment_refs ?? []),
    }
    return stableJson(current) !== stableJson(original)
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
    c.editStatus,
    c.editStatusTriggerSelfEnabled,
    c.editStatusTriggerSelfFromStatusesText,
    c.editStatusTriggerSelfToStatusesText,
    c.editStatusTriggerExternalEnabled,
    c.editStatusTriggerExternalMatchMode,
    c.editStatusTriggerExternalTaskIdsText,
    c.editStatusTriggerExternalFromStatusesText,
    c.editStatusTriggerExternalToStatusesText,
    c.editTaskAttachmentRefsText,
    c.editTaskExternalRefsText,
    c.editTaskTags,
    c.editTaskType,
    c.editTitle,
    c.currentUserTimezone,
    c.parseAttachmentRefsText,
    c.parseExternalRefsText,
    c.taskEditorTouched,
    c.taskEditorHydratedTaskId,
    c.taskEditorBaselineTask,
    c.selectedTask,
  ])

  const confirmDiscardChanges = React.useCallback(() => {
    return requestDiscardChanges('You have unsaved changes. Discard them?', () => undefined)
  }, [requestDiscardChanges])

  const closeTaskEditor = React.useCallback(() => {
    if (taskIsDirty) {
      return requestDiscardChanges('You have unsaved task changes. Discard them?', () => {
        c.setSelectedTaskId(null)
        c.setTaskEditorError(null)
      })
    }
    c.setSelectedTaskId(null)
    c.setTaskEditorError(null)
    return true
  }, [c.setSelectedTaskId, c.setTaskEditorError, requestDiscardChanges, taskIsDirty])

  const openTaskEditor = React.useCallback((taskId: string) => {
    if (c.selectedTaskId === taskId) return true
    if (c.selectedTaskId && taskIsDirty) {
      return requestDiscardChanges('You have unsaved task changes. Discard them?', () => {
        c.setSelectedTaskId(taskId)
        c.setTaskEditorError(null)
      })
    }
    c.setSelectedTaskId(taskId)
    c.setTaskEditorError(null)
    return true
  }, [c.selectedTaskId, c.setSelectedTaskId, c.setTaskEditorError, requestDiscardChanges, taskIsDirty])

  const toggleNoteEditor = React.useCallback((noteId: string) => {
    if (c.selectedNoteId === noteId) {
      if (noteIsDirty) {
        return requestDiscardChanges('You have unsaved note changes. Discard them?', () => {
          c.setSelectedNoteId(null)
        })
      }
      c.setSelectedNoteId(null)
      return true
    }
    if (c.selectedNoteId && noteIsDirty) {
      return requestDiscardChanges('You have unsaved note changes. Discard them?', () => {
        c.setSelectedNoteId(noteId)
      })
    }
    c.setSelectedNoteId(noteId)
    return true
  }, [c.selectedNoteId, c.setSelectedNoteId, requestDiscardChanges, noteIsDirty])

  const toggleSpecificationEditor = React.useCallback((specificationId: string) => {
    if (c.selectedSpecificationId === specificationId) {
      if (specificationIsDirty) {
        return requestDiscardChanges('You have unsaved specification changes. Discard them?', () => {
          c.setSelectedSpecificationId(null)
        })
      }
      c.setSelectedSpecificationId(null)
      return true
    }
    if (c.selectedSpecificationId && specificationIsDirty) {
      return requestDiscardChanges('You have unsaved specification changes. Discard them?', () => {
        c.setSelectedSpecificationId(specificationId)
      })
    }
    c.setSelectedSpecificationId(specificationId)
    return true
  }, [
    c.selectedSpecificationId,
    c.setSelectedSpecificationId,
    specificationIsDirty,
    requestDiscardChanges,
  ])

  const toggleProjectEditor = React.useCallback((projectId: string) => {
    const hasProjectUnsavedChanges = projectIsDirty || Boolean(c.projectEditorHasUnsavedChanges)
    if (c.selectedProjectId === projectId) {
      if (c.showProjectEditForm) {
        if (hasProjectUnsavedChanges) {
          return requestDiscardChanges('You have unsaved project changes. Discard them?', () => {
            if (typeof c.setProjectEditorHasUnsavedChanges === 'function') c.setProjectEditorHasUnsavedChanges(false)
            c.setShowProjectEditForm(false)
          })
        }
        if (typeof c.setProjectEditorHasUnsavedChanges === 'function') c.setProjectEditorHasUnsavedChanges(false)
        c.setShowProjectEditForm(false)
        return true
      }
      c.setShowProjectCreateForm(false)
      c.setShowProjectEditForm(true)
      return true
    }
    if (c.showProjectEditForm && hasProjectUnsavedChanges) {
      return requestDiscardChanges('You have unsaved project changes. Discard them?', () => {
        if (typeof c.setProjectEditorHasUnsavedChanges === 'function') c.setProjectEditorHasUnsavedChanges(false)
        c.setSelectedProjectId(projectId)
        c.setShowProjectEditForm(false)
      })
    }
    if (typeof c.setProjectEditorHasUnsavedChanges === 'function') c.setProjectEditorHasUnsavedChanges(false)
    c.setSelectedProjectId(projectId)
    c.setShowProjectEditForm(false)
    return true
  }, [
    c.selectedProjectId,
    c.showProjectEditForm,
    c.setShowProjectEditForm,
    c.setShowProjectCreateForm,
    c.setSelectedProjectId,
    c.setProjectEditorHasUnsavedChanges,
    c.projectEditorHasUnsavedChanges,
    requestDiscardChanges,
    projectIsDirty,
  ])

  return {
    toggleCreateProjectMember,
    toggleEditProjectMember,
    projectIsDirty,
    noteIsDirty,
    specificationIsDirty,
    taskIsDirty,
    confirmDiscardChanges,
    closeTaskEditor,
    openTaskEditor,
    toggleNoteEditor,
    toggleSpecificationEditor,
    toggleProjectEditor,
  }
}
