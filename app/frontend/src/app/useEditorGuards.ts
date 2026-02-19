import React from 'react'
import { parseCommaTags, parseProjectStatusesText, stableJson, toLocalDateTimeInput } from '../utils/ui'

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
      stableJson(parseCommaTags(c.editNoteTags)) !== stableJson(c.selectedNote.tags ?? []) ||
      stableJson(c.parseExternalRefsText(c.editNoteExternalRefsText)) !== stableJson(c.selectedNote.external_refs ?? []) ||
      stableJson(c.parseAttachmentRefsText(c.editNoteAttachmentRefsText)) !== stableJson(c.selectedNote.attachment_refs ?? [])
    )
  }, [
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
    const current = {
      title: (c.editTitle.trim() || 'Untitled'),
      description: c.editDescription,
      status: c.editStatus,
      priority: c.editPriority,
      project_id: c.editProjectId || c.selectedTask.project_id,
      labels: c.editTaskTags,
      due_date: c.editDueDate || '',
      task_type: c.editTaskType,
      scheduled_at_utc: c.editScheduledAtUtc || '',
      schedule_timezone: c.editTaskType === 'scheduled_instruction' ? (c.editScheduleTimezone || '') : '',
      scheduled_instruction: c.editTaskType === 'scheduled_instruction' ? c.editScheduledInstruction : '',
      recurring_rule:
        c.editTaskType === 'scheduled_instruction' && c.editRecurringEvery.trim()
          ? `every:${Math.max(1, Number(c.editRecurringEvery) || 1)}${c.editRecurringUnit}`
          : '',
      external_refs: c.parseExternalRefsText(c.editTaskExternalRefsText),
      attachment_refs: c.parseAttachmentRefsText(c.editTaskAttachmentRefsText),
    }
    const original = {
      title: c.selectedTask.title?.trim() || 'Untitled',
      description: c.selectedTask.description ?? '',
      status: c.selectedTask.status ?? 'To do',
      priority: c.selectedTask.priority ?? 'Med',
      project_id: c.selectedTask.project_id ?? '',
      labels: c.selectedTask.labels ?? [],
      due_date: toLocalDateTimeInput(c.selectedTask.due_date),
      task_type: c.selectedTask.task_type ?? 'manual',
      scheduled_at_utc: toLocalDateTimeInput(c.selectedTask.scheduled_at_utc),
      schedule_timezone:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? (c.selectedTask.schedule_timezone ?? '') : '',
      scheduled_instruction:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? (c.selectedTask.scheduled_instruction ?? '') : '',
      recurring_rule:
        (c.selectedTask.task_type ?? 'manual') === 'scheduled_instruction' ? String(c.selectedTask.recurring_rule ?? '') : '',
      external_refs: c.selectedTask.external_refs ?? [],
      attachment_refs: c.selectedTask.attachment_refs ?? [],
    }
    return stableJson(current) !== stableJson(original)
  }, [
    c.editDescription,
    c.editDueDate,
    c.editPriority,
    c.editProjectId,
    c.editRecurringEvery,
    c.editRecurringUnit,
    c.editScheduledAtUtc,
    c.editScheduledInstruction,
    c.editScheduleTimezone,
    c.editStatus,
    c.editTaskAttachmentRefsText,
    c.editTaskExternalRefsText,
    c.editTaskTags,
    c.editTaskType,
    c.editTitle,
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
