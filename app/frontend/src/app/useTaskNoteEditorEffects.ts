import React from 'react'
import type { TaskComment } from '../types'
import { attachmentRefsToText, externalRefsToText, toLocalDateTimeInput } from '../utils/ui'

export function useTaskNoteEditorEffects(c: any) {
  React.useEffect(() => {
    if (!c.selectedTask) return
    c.setEditTitle(c.selectedTask.title ?? '')
    c.setEditStatus(c.selectedTask.status)
    c.setEditDescription(c.selectedTask.description)
    c.setEditPriority(c.selectedTask.priority)
    c.setEditDueDate(toLocalDateTimeInput(c.selectedTask.due_date))
    c.setEditProjectId(c.selectedTask.project_id)
    c.setEditTaskTags(c.selectedTask.labels ?? [])
    c.setEditTaskExternalRefsText(externalRefsToText(c.selectedTask.external_refs))
    c.setEditTaskAttachmentRefsText(attachmentRefsToText(c.selectedTask.attachment_refs))
    c.setShowTaskTagPicker(false)
    c.setTaskTagPickerQuery('')
    c.setEditTaskType((c.selectedTask.task_type ?? 'manual') as 'manual' | 'scheduled_instruction')
    c.setEditScheduledAtUtc(toLocalDateTimeInput(c.selectedTask.scheduled_at_utc))
    c.setEditScheduleTimezone(c.selectedTask.schedule_timezone ?? (c.currentUserTimezone ?? 'UTC'))
    c.setEditScheduledInstruction(c.selectedTask.scheduled_instruction ?? '')
    ;(() => {
      const raw = String(c.selectedTask.recurring_rule ?? '').trim()
      const m = raw.match(/^(?:every:)?\s*(\d+)\s*([mhd])\s*$/i)
      if (!m) {
        c.setEditRecurringEvery('')
        c.setEditRecurringUnit('h')
        return
      }
      c.setEditRecurringEvery(String(m[1] || ''))
      const unit = String(m[2] || 'h').toLowerCase()
      c.setEditRecurringUnit(unit === 'm' || unit === 'h' || unit === 'd' ? unit : 'h')
    })()
    c.setAutomationInstruction('')
    c.setCommentBody('')
    c.setExpandedCommentIds(new Set())
    c.setTaskEditorError(null)
  }, [c.selectedTask?.id, c.currentUserTimezone])

  React.useEffect(() => {
    if (!c.taskEditorError) return
    c.setTaskEditorError(null)
  }, [c.taskEditorError, c.editTaskType, c.editScheduledInstruction, c.editScheduledAtUtc, c.editScheduleTimezone, c.editRecurringEvery, c.editRecurringUnit])

  React.useEffect(() => {
    if (!c.selectedNote) return
    c.setEditNoteTitle(c.selectedNote.title ?? '')
    c.setEditNoteBody(c.selectedNote.body ?? '')
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
