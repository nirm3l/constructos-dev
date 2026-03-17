import React from 'react'
import type { TaskComment } from '../types'
import { attachmentRefsToText, externalRefsToText, toLocalDateTimeInput } from '../utils/ui'
import {
  deriveInstruction,
  extractEnabledScheduleTrigger,
  extractEnabledStatusTrigger,
  listToCsv,
  normalizeExecutionTriggers,
  normalizeScheduleRunOnStatuses,
  parseRecurringRule,
} from '../utils/taskAutomation'

export function useTaskNoteEditorEffects(c: any) {
  React.useEffect(() => {
    if (!c.selectedTask) {
      // During query refetch, selectedTask may be temporarily undefined while a task is still selected.
      // Only clear editor/live state when no task is selected at all.
      if (!c.selectedTaskId) {
        c.setTaskEditorHydratedTaskId(null)
        c.setTaskEditorBaselineTask(null)
        c.setTaskEditorTouched(false)
        c.setAutomationLiveTaskId(null)
        c.setAutomationLiveRunId(null)
        c.setAutomationLiveActive(false)
        c.setAutomationLiveBuffer('')
        c.setAutomationLiveStatusText('')
        c.setAutomationLiveUpdatedAt(null)
      }
      return
    }
    c.setTaskEditorHydratedTaskId(null)
    c.setEditTitle(c.selectedTask.title ?? '')
    c.setEditStatus(c.selectedTask.status ?? 'To Do')
    c.setEditDescription(c.selectedTask.description ?? '')
    c.setEditPriority(c.selectedTask.priority ?? 'Med')
    c.setEditDueDate(toLocalDateTimeInput(c.selectedTask.due_date))
    c.setEditProjectId(c.selectedTask.project_id ?? '')
    c.setEditTaskGroupId(c.selectedTask.task_group_id ?? '')
    c.setEditAssigneeId(c.selectedTask.assignee_id ?? '')
    c.setEditAssignedAgentCode(c.selectedTask.assigned_agent_code ?? '')
    c.setEditTaskTags(c.selectedTask.labels ?? [])
    c.setEditTaskExternalRefsText(externalRefsToText(c.selectedTask.external_refs))
    c.setEditTaskAttachmentRefsText(attachmentRefsToText(c.selectedTask.attachment_refs))
    c.setShowTaskTagPicker(false)
    c.setTaskTagPickerQuery('')
    c.setEditTaskType((c.selectedTask.task_type ?? 'manual') as 'manual' | 'scheduled_instruction')
    c.setEditScheduledAtUtc(toLocalDateTimeInput(c.selectedTask.scheduled_at_utc))
    c.setEditScheduleTimezone(c.selectedTask.schedule_timezone ?? (c.currentUserTimezone ?? 'UTC'))
    c.setEditScheduledInstruction(deriveInstruction(c.selectedTask))
    ;(() => {
      const parsedRecurring = parseRecurringRule(c.selectedTask.recurring_rule)
      c.setEditRecurringEvery(parsedRecurring.every)
      c.setEditRecurringUnit(parsedRecurring.unit)
    })()
    ;(() => {
      const triggers = normalizeExecutionTriggers(c.selectedTask.execution_triggers)
      const scheduleTrigger = extractEnabledScheduleTrigger(triggers)
      const selfTrigger = extractEnabledStatusTrigger(triggers, 'self')
      const externalTrigger = extractEnabledStatusTrigger(triggers, 'external')

      c.setEditScheduleRunOnStatuses(normalizeScheduleRunOnStatuses(scheduleTrigger?.run_on_statuses))
      c.setEditStatusTriggerSelfEnabled(Boolean(selfTrigger))
      c.setEditStatusTriggerSelfFromStatusesText(listToCsv(selfTrigger?.from_statuses))
      c.setEditStatusTriggerSelfToStatusesText(listToCsv(selfTrigger?.to_statuses))

      c.setEditStatusTriggerExternalEnabled(Boolean(externalTrigger))
      c.setEditStatusTriggerExternalMatchMode(externalTrigger?.match_mode === 'all' ? 'all' : 'any')
      c.setEditStatusTriggerExternalTaskIdsText(listToCsv(externalTrigger?.selector?.task_ids))
      c.setEditStatusTriggerExternalFromStatusesText(listToCsv(externalTrigger?.from_statuses))
      c.setEditStatusTriggerExternalToStatusesText(listToCsv(externalTrigger?.to_statuses))
    })()
    c.setAutomationInstruction('')
    c.setCommentBody('')
    c.setExpandedCommentIds(new Set())
    c.setTaskEditorError(null)
    c.setTaskEditorBaselineTask(JSON.parse(JSON.stringify(c.selectedTask)))
    c.setTaskEditorTouched(false)
    c.setTaskEditorHydratedTaskId(c.selectedTask.id ?? null)
  }, [c.selectedTask?.id, c.selectedTask?.updated_at, c.currentUserTimezone])

  React.useEffect(() => {
    if (!c.taskEditorError) return
    c.setTaskEditorError(null)
  }, [
    c.taskEditorError,
    c.editTaskType,
    c.editScheduledInstruction,
    c.editScheduledAtUtc,
    c.editScheduleTimezone,
    c.editScheduleRunOnStatuses,
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
  ])

  React.useEffect(() => {
    if (!c.selectedNote) return
    c.setEditNoteTitle(c.selectedNote.title ?? '')
    c.setEditNoteBody(c.selectedNote.body ?? '')
    c.setEditNoteGroupId(c.selectedNote.note_group_id ?? '')
    c.setEditNoteTags((c.selectedNote.tags ?? []).join(', '))
    c.setEditNoteExternalRefsText(externalRefsToText(c.selectedNote.external_refs))
    c.setEditNoteAttachmentRefsText(attachmentRefsToText(c.selectedNote.attachment_refs))
    c.setTagPickerQuery('')
    c.setShowTagPicker(false)
    const hasBody = Boolean((c.selectedNote.body ?? '').trim())
    c.setNoteEditorView(c.openNextSelectedNoteInWriteRef.current || !hasBody ? 'write' : 'preview')
    c.openNextSelectedNoteInWriteRef.current = false
  }, [c.selectedNote?.id])

  React.useEffect(() => {
    if (!c.scrollToNewestComment || c.comments.isFetching) return
    const list = c.commentsListRef.current
    if (!list) return
    const newestRecord = ((c.comments.data ?? []) as TaskComment[]).reduce((acc: TaskComment | null, item: TaskComment) => {
      if (!acc) return item
      const itemTs = item.created_at ? Date.parse(item.created_at) : Number.NEGATIVE_INFINITY
      const accTs = acc.created_at ? Date.parse(acc.created_at) : Number.NEGATIVE_INFINITY
      return itemTs >= accTs ? item : acc
    }, null)
    const newestKey = newestRecord ? `${newestRecord.id ?? 'null'}-${newestRecord.created_at ?? ''}-${newestRecord.user_id}` : null
    const newest = newestKey
      ? (list.querySelector(`[data-comment-key="${newestKey}"]`) as HTMLElement | null)
      : null
    if (newest) newest.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    c.setScrollToNewestComment(false)
  }, [c.scrollToNewestComment, c.comments.isFetching, c.comments.data, c.commentsListRef, c.setScrollToNewestComment])
}
