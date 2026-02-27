import React from 'react'
import { parseCommaTags, parseProjectStatusesText, stableJson, toLocalDateTimeInput } from '../utils/ui'
import {
  buildExecutionTriggersFromEditor,
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

function normalizeExecutionTriggersForDirtyCheck(input: unknown) {
  return normalizeExecutionTriggers(input).map((trigger) => {
    if (trigger.kind !== 'schedule') return trigger
    return {
      ...trigger,
      scheduled_at_utc: normalizeUtcIsoToMinute(trigger.scheduled_at_utc),
    }
  })
}

export function useEditorGuards(c: any) {
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
    return (
      c.editProjectName.trim() !== (c.selectedProject.name ?? '').trim() ||
      c.editProjectDescription !== (c.selectedProject.description ?? '') ||
      stableJson(parseProjectStatusesText(c.editProjectCustomStatusesText)) !==
        stableJson(c.selectedProject.custom_statuses ?? []) ||
      Boolean(c.editProjectEmbeddingEnabled) !== Boolean(c.selectedProject.embedding_enabled) ||
      String(c.editProjectEmbeddingModel || '').trim() !== String(c.selectedProject.embedding_model || '').trim() ||
      String(c.editProjectContextPackEvidenceTopKText || '').trim() !==
        String(c.selectedProject.context_pack_evidence_top_k ?? '').trim() ||
      String(c.editProjectChatIndexMode || 'OFF').trim().toUpperCase() !==
        String(c.selectedProject.chat_index_mode || 'OFF').trim().toUpperCase() ||
      String(c.editProjectChatAttachmentIngestionMode || 'METADATA_ONLY').trim().toUpperCase() !==
        String(c.selectedProject.chat_attachment_ingestion_mode || 'METADATA_ONLY').trim().toUpperCase() ||
      stableJson(c.parseExternalRefsText(c.editProjectExternalRefsText)) !== stableJson(c.selectedProject.external_refs ?? []) ||
      stableJson(c.parseAttachmentRefsText(c.editProjectAttachmentRefsText)) !== stableJson(c.selectedProject.attachment_refs ?? []) ||
      stableJson(Array.from(new Set(c.editProjectMemberIds.filter(Boolean))).sort()) !== stableJson(selectedProjectMemberIds)
    )
  }, [
    c.editProjectAttachmentRefsText,
    c.editProjectCustomStatusesText,
    c.editProjectDescription,
    c.editProjectEmbeddingEnabled,
    c.editProjectEmbeddingModel,
    c.editProjectContextPackEvidenceTopKText,
    c.editProjectChatIndexMode,
    c.editProjectChatAttachmentIngestionMode,
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
      stableJson(c.parseExternalRefsText(c.editNoteExternalRefsText)) !== stableJson(c.selectedNote.external_refs ?? []) ||
      stableJson(c.parseAttachmentRefsText(c.editNoteAttachmentRefsText)) !== stableJson(c.selectedNote.attachment_refs ?? [])
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
      stableJson(c.parseExternalRefsText(c.editSpecificationExternalRefsText)) !== stableJson(c.selectedSpecification.external_refs ?? []) ||
      stableJson(c.parseAttachmentRefsText(c.editSpecificationAttachmentRefsText)) !== stableJson(c.selectedSpecification.attachment_refs ?? [])
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
    if (!c.selectedTask) return false
    const selectedTaskScheduleTimezone = String(c.selectedTask.schedule_timezone || '').trim()
    const fallbackScheduleTimezone = String(c.currentUserTimezone || 'UTC').trim() || 'UTC'
    const editScheduleTimezoneRaw = String(c.editScheduleTimezone || '').trim()
    const scheduleTimezoneForDirty = (
      c.editTaskType === 'scheduled_instruction'
        ? (
            !selectedTaskScheduleTimezone && editScheduleTimezoneRaw === fallbackScheduleTimezone
              ? ''
              : editScheduleTimezoneRaw
          )
        : ''
    )
    const scheduleTriggerIsoForDirty =
      c.editTaskType === 'scheduled_instruction' && c.editScheduledAtUtc
        ? normalizeUtcIsoToMinute(new Date(c.editScheduledAtUtc).toISOString())
        : ''
    const currentExecutionTriggers = buildExecutionTriggersFromEditor({
      taskType: c.editTaskType,
      scheduledAtUtc: scheduleTriggerIsoForDirty,
      scheduleTimezone: scheduleTimezoneForDirty,
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

    const originalExecutionTriggers = normalizeExecutionTriggersForDirtyCheck(c.selectedTask.execution_triggers)
    const normalizedCurrentExecutionTriggers = normalizeExecutionTriggersForDirtyCheck(currentExecutionTriggers)
    const originalScheduleTrigger = extractEnabledScheduleTrigger(originalExecutionTriggers)
    const originalSelfTrigger = extractEnabledStatusTrigger(originalExecutionTriggers, 'self')
    const originalExternalTrigger = extractEnabledStatusTrigger(originalExecutionTriggers, 'external')

    const current = {
      title: (c.editTitle.trim() || 'Untitled'),
      description: c.editDescription,
      status: c.editStatus,
      priority: c.editPriority,
      project_id: c.editProjectId || c.selectedTask.project_id,
      task_group_id: c.editTaskGroupId || null,
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
      execution_triggers: normalizedCurrentExecutionTriggers,
      external_refs: c.parseExternalRefsText(c.editTaskExternalRefsText),
      attachment_refs: c.parseAttachmentRefsText(c.editTaskAttachmentRefsText),
    }
    const original = {
      title: c.selectedTask.title?.trim() || 'Untitled',
      description: c.selectedTask.description ?? '',
      status: c.selectedTask.status ?? 'To do',
      priority: c.selectedTask.priority ?? 'Med',
      project_id: c.selectedTask.project_id ?? '',
      task_group_id: c.selectedTask.task_group_id ?? null,
      labels: c.selectedTask.labels ?? [],
      due_date: toLocalDateTimeInput(c.selectedTask.due_date),
      task_type: c.selectedTask.task_type ?? 'manual',
      scheduled_at_utc: toLocalDateTimeInput(c.selectedTask.scheduled_at_utc),
      schedule_timezone:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction'
          ? (selectedTaskScheduleTimezone || '')
          : '',
      schedule_run_on_statuses:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction'
          ? normalizeScheduleRunOnStatuses(originalScheduleTrigger?.run_on_statuses)
          : [],
      instruction: deriveInstruction(c.selectedTask),
      recurring_rule:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? String(c.selectedTask.recurring_rule ?? '') : '',
      status_trigger_self_enabled: Boolean(originalSelfTrigger),
      status_trigger_self_from: listToCsv(originalSelfTrigger?.from_statuses),
      status_trigger_self_to: listToCsv(originalSelfTrigger?.to_statuses),
      status_trigger_external_enabled: Boolean(originalExternalTrigger),
      status_trigger_external_match_mode: originalExternalTrigger?.match_mode === 'all' ? 'all' : 'any',
      status_trigger_external_task_ids: listToCsv(originalExternalTrigger?.selector?.task_ids),
      status_trigger_external_from: listToCsv(originalExternalTrigger?.from_statuses),
      status_trigger_external_to: listToCsv(originalExternalTrigger?.to_statuses),
      execution_triggers: originalExecutionTriggers,
      external_refs: c.selectedTask.external_refs ?? [],
      attachment_refs: c.selectedTask.attachment_refs ?? [],
    }
    return stableJson(current) !== stableJson(original)
  }, [
    c.editDescription,
    c.editDueDate,
    c.editPriority,
    c.editProjectId,
    c.editTaskGroupId,
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
    c.selectedTask,
  ])

  const confirmDiscardChanges = React.useCallback(() => {
    if (typeof window === 'undefined') return true
    return window.confirm('You have unsaved changes. Discard them?')
  }, [])

  const closeTaskEditor = React.useCallback(() => {
    if (taskIsDirty && !confirmDiscardChanges()) return false
    c.setSelectedTaskId(null)
    c.setTaskEditorError(null)
    return true
  }, [c.setSelectedTaskId, c.setTaskEditorError, confirmDiscardChanges, taskIsDirty])

  const openTaskEditor = React.useCallback((taskId: string) => {
    if (c.selectedTaskId === taskId) return true
    if (c.selectedTaskId && taskIsDirty && !confirmDiscardChanges()) return false
    c.setSelectedTaskId(taskId)
    c.setTaskEditorError(null)
    return true
  }, [c.selectedTaskId, c.setSelectedTaskId, c.setTaskEditorError, confirmDiscardChanges, taskIsDirty])

  const toggleNoteEditor = React.useCallback((noteId: string) => {
    if (c.selectedNoteId === noteId) {
      if (noteIsDirty && !confirmDiscardChanges()) return false
      c.setSelectedNoteId(null)
      return true
    }
    if (c.selectedNoteId && noteIsDirty && !confirmDiscardChanges()) return false
    c.setSelectedNoteId(noteId)
    return true
  }, [c.selectedNoteId, c.setSelectedNoteId, confirmDiscardChanges, noteIsDirty])

  const toggleSpecificationEditor = React.useCallback((specificationId: string) => {
    if (c.selectedSpecificationId === specificationId) {
      if (specificationIsDirty && !confirmDiscardChanges()) return false
      c.setSelectedSpecificationId(null)
      return true
    }
    if (c.selectedSpecificationId && specificationIsDirty && !confirmDiscardChanges()) return false
    c.setSelectedSpecificationId(specificationId)
    return true
  }, [
    c.selectedSpecificationId,
    c.setSelectedSpecificationId,
    specificationIsDirty,
    confirmDiscardChanges,
  ])

  const toggleProjectEditor = React.useCallback((projectId: string) => {
    if (c.selectedProjectId === projectId) {
      if (c.showProjectEditForm) {
        if (projectIsDirty && !confirmDiscardChanges()) return false
        c.setShowProjectEditForm(false)
        return true
      }
      c.setShowProjectCreateForm(false)
      c.setShowProjectEditForm(true)
      return true
    }
    if (c.showProjectEditForm && projectIsDirty && !confirmDiscardChanges()) return false
    c.setSelectedProjectId(projectId)
    c.setShowProjectEditForm(false)
    return true
  }, [c.selectedProjectId, c.showProjectEditForm, c.setShowProjectEditForm, c.setShowProjectCreateForm, c.setSelectedProjectId, confirmDiscardChanges, projectIsDirty])

  return {
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
  }
}
