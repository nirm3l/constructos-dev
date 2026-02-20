import React from 'react'

export function useTaskEditorState() {
  const [editStatus, setEditStatus] = React.useState('To do')
  const [editTitle, setEditTitle] = React.useState('')
  const [editDescription, setEditDescription] = React.useState('')
  const [editPriority, setEditPriority] = React.useState('Med')
  const [editDueDate, setEditDueDate] = React.useState('')
  const [editProjectId, setEditProjectId] = React.useState('')
  const [editTaskGroupId, setEditTaskGroupId] = React.useState('')
  const [editTaskTags, setEditTaskTags] = React.useState<string[]>([])
  const [editTaskExternalRefsText, setEditTaskExternalRefsText] = React.useState('')
  const [editTaskAttachmentRefsText, setEditTaskAttachmentRefsText] = React.useState('')
  const [showTaskTagPicker, setShowTaskTagPicker] = React.useState(false)
  const [taskTagPickerQuery, setTaskTagPickerQuery] = React.useState('')
  const [editTaskType, setEditTaskType] = React.useState<'manual' | 'scheduled_instruction'>('manual')
  const [editScheduledAtUtc, setEditScheduledAtUtc] = React.useState('')
  const [editScheduleTimezone, setEditScheduleTimezone] = React.useState('')
  const [editScheduledInstruction, setEditScheduledInstruction] = React.useState('')
  const [editRecurringEvery, setEditRecurringEvery] = React.useState('')
  const [editRecurringUnit, setEditRecurringUnit] = React.useState<'m' | 'h' | 'd'>('h')
  const [commentBody, setCommentBody] = React.useState('')
  const [expandedCommentIds, setExpandedCommentIds] = React.useState<Set<string>>(new Set())
  const [automationInstruction, setAutomationInstruction] = React.useState('')
  const [activityExpandedIds, setActivityExpandedIds] = React.useState<Set<number>>(new Set())
  const [activityShowRawDetails, setActivityShowRawDetails] = React.useState(false)
  const [scrollToNewestComment, setScrollToNewestComment] = React.useState(false)
  const [uiError, setUiError] = React.useState<string | null>(null)
  const [uiInfo, setUiInfo] = React.useState<string | null>(null)
  const [taskEditorError, setTaskEditorError] = React.useState<string | null>(null)

  return {
    editStatus, setEditStatus, editTitle, setEditTitle, editDescription, setEditDescription, editPriority, setEditPriority,
    editDueDate, setEditDueDate, editProjectId, setEditProjectId, editTaskGroupId, setEditTaskGroupId, editTaskTags, setEditTaskTags, editTaskExternalRefsText,
    setEditTaskExternalRefsText, editTaskAttachmentRefsText, setEditTaskAttachmentRefsText, showTaskTagPicker,
    setShowTaskTagPicker, taskTagPickerQuery, setTaskTagPickerQuery, editTaskType, setEditTaskType, editScheduledAtUtc,
    setEditScheduledAtUtc, editScheduleTimezone, setEditScheduleTimezone, editScheduledInstruction, setEditScheduledInstruction,
    editRecurringEvery, setEditRecurringEvery, editRecurringUnit, setEditRecurringUnit, commentBody, setCommentBody,
    expandedCommentIds, setExpandedCommentIds, automationInstruction, setAutomationInstruction, activityExpandedIds,
    setActivityExpandedIds, activityShowRawDetails, setActivityShowRawDetails, scrollToNewestComment, setScrollToNewestComment,
    uiError, setUiError, uiInfo, setUiInfo, taskEditorError, setTaskEditorError,
  }
}
