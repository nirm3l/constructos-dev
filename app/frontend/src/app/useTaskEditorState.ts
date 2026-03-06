import React from 'react'

export function useTaskEditorState() {
  const [editStatus, setEditStatus] = React.useState('To do')
  const [editTitle, setEditTitle] = React.useState('')
  const [editDescription, setEditDescription] = React.useState('')
  const [editPriority, setEditPriority] = React.useState('Med')
  const [editDueDate, setEditDueDate] = React.useState('')
  const [editProjectId, setEditProjectId] = React.useState('')
  const [editTaskGroupId, setEditTaskGroupId] = React.useState('')
  const [editAssigneeId, setEditAssigneeId] = React.useState('')
  const [editAssignedAgentCode, setEditAssignedAgentCode] = React.useState('')
  const [editTaskTags, setEditTaskTags] = React.useState<string[]>([])
  const [editTaskExternalRefsText, setEditTaskExternalRefsText] = React.useState('')
  const [editTaskAttachmentRefsText, setEditTaskAttachmentRefsText] = React.useState('')
  const [showTaskTagPicker, setShowTaskTagPicker] = React.useState(false)
  const [taskTagPickerQuery, setTaskTagPickerQuery] = React.useState('')
  const [editTaskType, setEditTaskType] = React.useState<'manual' | 'scheduled_instruction'>('manual')
  const [editScheduledAtUtc, setEditScheduledAtUtc] = React.useState('')
  const [editScheduleTimezone, setEditScheduleTimezone] = React.useState('')
  const [editScheduleRunOnStatuses, setEditScheduleRunOnStatuses] = React.useState<string[]>(['In progress'])
  const [editScheduledInstruction, setEditScheduledInstruction] = React.useState('')
  const [editRecurringEvery, setEditRecurringEvery] = React.useState('')
  const [editRecurringUnit, setEditRecurringUnit] = React.useState<'m' | 'h' | 'd'>('h')
  const [editStatusTriggerSelfEnabled, setEditStatusTriggerSelfEnabled] = React.useState(false)
  const [editStatusTriggerSelfFromStatusesText, setEditStatusTriggerSelfFromStatusesText] = React.useState('')
  const [editStatusTriggerSelfToStatusesText, setEditStatusTriggerSelfToStatusesText] = React.useState('')
  const [editStatusTriggerExternalEnabled, setEditStatusTriggerExternalEnabled] = React.useState(false)
  const [editStatusTriggerExternalMatchMode, setEditStatusTriggerExternalMatchMode] = React.useState<'any' | 'all'>('any')
  const [editStatusTriggerExternalTaskIdsText, setEditStatusTriggerExternalTaskIdsText] = React.useState('')
  const [editStatusTriggerExternalFromStatusesText, setEditStatusTriggerExternalFromStatusesText] = React.useState('')
  const [editStatusTriggerExternalToStatusesText, setEditStatusTriggerExternalToStatusesText] = React.useState('')
  const [commentBody, setCommentBody] = React.useState('')
  const [expandedCommentIds, setExpandedCommentIds] = React.useState<Set<string>>(new Set())
  const [automationInstruction, setAutomationInstruction] = React.useState('')
  const [automationLiveTaskId, setAutomationLiveTaskId] = React.useState<string | null>(null)
  const [automationLiveRunId, setAutomationLiveRunId] = React.useState<string | null>(null)
  const [automationLiveActive, setAutomationLiveActive] = React.useState(false)
  const [automationLiveBuffer, setAutomationLiveBuffer] = React.useState('')
  const [automationLiveStatusText, setAutomationLiveStatusText] = React.useState('')
  const [automationLiveUpdatedAt, setAutomationLiveUpdatedAt] = React.useState<string | null>(null)
  const [activityExpandedIds, setActivityExpandedIds] = React.useState<Set<number>>(new Set())
  const [activityShowRawDetails, setActivityShowRawDetails] = React.useState(false)
  const [scrollToNewestComment, setScrollToNewestComment] = React.useState(false)
  const [uiError, setUiError] = React.useState<string | null>(null)
  const [uiInfo, setUiInfo] = React.useState<string | null>(null)
  const [taskEditorError, setTaskEditorError] = React.useState<string | null>(null)
  const [taskEditorHydratedTaskId, setTaskEditorHydratedTaskId] = React.useState<string | null>(null)
  const [taskEditorBaselineTask, setTaskEditorBaselineTask] = React.useState<any | null>(null)
  const [taskEditorTouched, setTaskEditorTouched] = React.useState(false)

  return {
    editStatus, setEditStatus, editTitle, setEditTitle, editDescription, setEditDescription, editPriority, setEditPriority,
    editDueDate, setEditDueDate, editProjectId, setEditProjectId, editTaskGroupId, setEditTaskGroupId, editAssigneeId, setEditAssigneeId, editAssignedAgentCode, setEditAssignedAgentCode, editTaskTags, setEditTaskTags, editTaskExternalRefsText,
    setEditTaskExternalRefsText, editTaskAttachmentRefsText, setEditTaskAttachmentRefsText, showTaskTagPicker,
    setShowTaskTagPicker, taskTagPickerQuery, setTaskTagPickerQuery, editTaskType, setEditTaskType, editScheduledAtUtc,
    setEditScheduledAtUtc, editScheduleTimezone, setEditScheduleTimezone, editScheduleRunOnStatuses, setEditScheduleRunOnStatuses,
    editScheduledInstruction, setEditScheduledInstruction,
    editRecurringEvery, setEditRecurringEvery, editRecurringUnit, setEditRecurringUnit,
    editStatusTriggerSelfEnabled, setEditStatusTriggerSelfEnabled,
    editStatusTriggerSelfFromStatusesText, setEditStatusTriggerSelfFromStatusesText,
    editStatusTriggerSelfToStatusesText, setEditStatusTriggerSelfToStatusesText,
    editStatusTriggerExternalEnabled, setEditStatusTriggerExternalEnabled,
    editStatusTriggerExternalMatchMode, setEditStatusTriggerExternalMatchMode,
    editStatusTriggerExternalTaskIdsText, setEditStatusTriggerExternalTaskIdsText,
    editStatusTriggerExternalFromStatusesText, setEditStatusTriggerExternalFromStatusesText,
    editStatusTriggerExternalToStatusesText, setEditStatusTriggerExternalToStatusesText,
    commentBody, setCommentBody,
    expandedCommentIds, setExpandedCommentIds, automationInstruction, setAutomationInstruction,
    automationLiveTaskId, setAutomationLiveTaskId,
    automationLiveRunId, setAutomationLiveRunId,
    automationLiveActive, setAutomationLiveActive,
    automationLiveBuffer, setAutomationLiveBuffer,
    automationLiveStatusText, setAutomationLiveStatusText,
    automationLiveUpdatedAt, setAutomationLiveUpdatedAt,
    activityExpandedIds,
    setActivityExpandedIds, activityShowRawDetails, setActivityShowRawDetails, scrollToNewestComment, setScrollToNewestComment,
    uiError, setUiError, uiInfo, setUiInfo, taskEditorError, setTaskEditorError,
    taskEditorHydratedTaskId, setTaskEditorHydratedTaskId,
    taskEditorBaselineTask, setTaskEditorBaselineTask,
    taskEditorTouched, setTaskEditorTouched,
  }
}
