import { useMutation } from '@tanstack/react-query'
import {
  archiveTask,
  completeTask,
  createTask,
  createTaskGroup,
  deleteTaskGroup,
  patchTaskGroup,
  reorderTaskGroups,
  reopenTask,
  restoreTask,
  runTaskAutomationStream,
  runTaskWithCodex,
} from '../../api'

export function useTaskMutations(c: any) {
  const resetQuickTaskComposer = (mode: 'full' | 'title-only' = 'full') => {
    c.setTaskTitle('')
    c.setShowQuickTaskTagPicker(false)
    c.setQuickTaskTagQuery('')
    if (mode === 'title-only') return

    c.setQuickDueDate('')
    c.setQuickDueDateFocused(false)
    c.setQuickTaskGroupId('')
    c.setQuickTaskAssigneeId('')
    c.setQuickTaskTags([])
    c.setQuickTaskExternalRefsText('')
    c.setQuickTaskAttachmentRefsText('')
    c.setQuickTaskPriority('Med')
    c.setQuickTaskType('manual')
    c.setQuickTaskScheduledInstruction('')
    c.setQuickTaskScheduleTimezone(c.quickTaskLocalTimezone || 'UTC')
    c.setQuickTaskCreateAnother(false)
  }

  const saveTaskMutation = useMutation({
    mutationFn: () => c.saveTaskNow(),
    onSuccess: () => {
      c.setUiError(null)
      c.setTaskEditorError(null)
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : 'Task save failed'
      c.setUiError(message)
      c.setTaskEditorError(message)
    },
  })

  const createTaskMutation = useMutation({
    mutationFn: (payload?: {
      title?: string
      description?: string
      project_id?: string
      task_group_id?: string | null
      assignee_id?: string | null
      due_date?: string | null
      priority?: string
      labels?: string[]
      task_type?: 'manual' | 'scheduled_instruction'
      scheduled_instruction?: string | null
      scheduled_at_utc?: string | null
      schedule_timezone?: string | null
      recurring_rule?: string | null
      open_task?: boolean
      keep_open?: boolean
    }) =>
      {
        const normalizeOptionalId = (value: unknown): string | null => {
          const cleaned = String(value ?? '').trim()
          return cleaned || null
        }
        const payloadHasTaskGroupId =
          payload !== undefined && Object.prototype.hasOwnProperty.call(payload, 'task_group_id')
        const payloadHasAssigneeId =
          payload !== undefined && Object.prototype.hasOwnProperty.call(payload, 'assignee_id')
        const resolvedTaskGroupId = payloadHasTaskGroupId
          ? normalizeOptionalId(payload?.task_group_id)
          : normalizeOptionalId(c.quickTaskGroupId)
        const resolvedAssigneeId = payloadHasAssigneeId
          ? normalizeOptionalId(payload?.assignee_id)
          : normalizeOptionalId(c.quickTaskAssigneeId)

        const effectiveTaskType = (payload?.task_type ?? c.quickTaskType ?? 'manual') as 'manual' | 'scheduled_instruction'
        const resolvedTimezone =
          String(c.quickTaskScheduleTimezone || '').trim() ||
          c.quickTaskLocalTimezone ||
          (typeof Intl !== 'undefined' ? Intl.DateTimeFormat().resolvedOptions().timeZone : '') ||
          'UTC'
        const dueDate =
          payload?.due_date !== undefined
            ? payload.due_date
            : effectiveTaskType === 'scheduled_instruction'
              ? null
              : (c.quickDueDate ? new Date(c.quickDueDate).toISOString() : null)
        const scheduledAtUtc =
          payload?.scheduled_at_utc !== undefined
            ? payload.scheduled_at_utc
            : effectiveTaskType === 'scheduled_instruction' && c.quickDueDate
              ? new Date(c.quickDueDate).toISOString()
              : null
        const scheduledInstruction =
          payload?.scheduled_instruction !== undefined
            ? payload.scheduled_instruction
            : effectiveTaskType === 'scheduled_instruction'
              ? (String(c.quickTaskScheduledInstruction || '').trim() || null)
              : null
        const scheduleTimezone =
          payload?.schedule_timezone !== undefined
            ? payload.schedule_timezone
            : effectiveTaskType === 'scheduled_instruction'
              ? resolvedTimezone
              : null

        return createTask(c.userId, {
          title: payload?.title?.trim() || c.taskTitle.trim(),
          workspace_id: c.workspaceId,
          project_id: payload?.project_id || c.quickProjectId || c.selectedProjectId,
          task_group_id: resolvedTaskGroupId,
          assignee_id: resolvedAssigneeId,
          description: payload?.description ?? '',
          priority: payload?.priority ?? c.quickTaskPriority ?? 'Med',
          due_date: dueDate,
          labels: payload?.labels ?? c.quickTaskTags,
          external_refs: c.parseExternalRefsText(c.quickTaskExternalRefsText),
          attachment_refs: c.parseAttachmentRefsText(c.quickTaskAttachmentRefsText),
          recurring_rule: payload?.recurring_rule ?? null,
          task_type: effectiveTaskType,
          scheduled_instruction: scheduledInstruction,
          scheduled_at_utc: scheduledAtUtc,
          schedule_timezone: scheduleTimezone,
        })
      },
    onSuccess: async (task, payload) => {
      c.setUiError(null)
      if (payload?.open_task) {
        c.setSelectedTaskId(task.id)
        c.setTab('tasks')
      } else if (payload?.keep_open) {
        resetQuickTaskComposer('title-only')
      } else {
        resetQuickTaskComposer('full')
        c.setShowQuickAdd(false)
      }
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Task create failed')
  })

  const completeTaskMutation = useMutation({
    mutationFn: (id: string) => completeTask(c.userId, id),
    onSuccess: async (task) => {
      c.setUiError(null)
      if (c.selectedTaskId === task.id) c.setEditStatus(task.status)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Complete failed')
  })

  const reopenTaskMutation = useMutation({
    mutationFn: (id: string) => reopenTask(c.userId, id),
    onSuccess: async (task) => {
      c.setUiError(null)
      if (c.selectedTaskId === task.id) c.setEditStatus(task.status)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Reopen failed')
  })

  const archiveTaskMutation = useMutation({
    mutationFn: (id: string) => archiveTask(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
      c.setSelectedTaskId(null)
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Archive failed')
  })

  const restoreTaskMutation = useMutation({
    mutationFn: (id: string) => restoreTask(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
      c.setSelectedTaskId(null)
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Restore failed')
  })

  const runAutomationMutation = useMutation({
    mutationFn: async () => {
      const taskId = c.selectedTaskId as string
      const rawInstruction = String(c.automationInstruction || '').trim()
      if (!rawInstruction) throw new Error('Instruction is required')
      c.setAutomationLiveTaskId(null)
      c.setAutomationLiveRunId(null)
      c.setAutomationLiveActive(false)
      c.setAutomationLiveBuffer('')
      c.setAutomationLiveStatusText('')
      c.setAutomationLiveUpdatedAt(null)
      const dispatchMatch = rawInstruction.match(/^#dispatch\b\s*/i)
      if (dispatchMatch) {
        const queuedInstruction = rawInstruction.slice(dispatchMatch[0].length).trim() || rawInstruction
        return runTaskWithCodex(c.userId, taskId, queuedInstruction)
      }
      const key = ['automation-status', c.userId, taskId] as const
      await c.qc.cancelQueries({ queryKey: key })
      const runId = globalThis.crypto?.randomUUID?.() ?? `run-${Date.now()}`
      let streamBuffer = ''
      c.setAutomationLiveTaskId(taskId)
      c.setAutomationLiveRunId(runId)
      c.setAutomationLiveActive(true)
      c.setAutomationLiveBuffer('')
      c.setAutomationLiveStatusText('Running...')
      c.setAutomationLiveUpdatedAt(new Date().toISOString())
      c.qc.setQueryData(key, (current: any) => {
        const existing = current && typeof current === 'object' ? current : {}
        const nowIso = new Date().toISOString()
        return {
          ...existing,
          task_id: taskId,
          automation_state: 'running',
          last_agent_progress: '',
          last_agent_comment: null,
          last_agent_error: null,
          last_agent_stream_status: 'Running...',
          last_agent_stream_updated_at: nowIso,
          last_requested_instruction: rawInstruction,
          last_requested_source: 'manual_stream',
        }
      })
      return runTaskAutomationStream(c.userId, taskId, rawInstruction, {
        onAssistantDelta: (delta) => {
          streamBuffer += String(delta || '')
          c.setAutomationLiveBuffer(streamBuffer)
          c.setAutomationLiveUpdatedAt(new Date().toISOString())
        },
        onStatus: (message) => {
          c.setAutomationLiveStatusText(String(message || '').trim() || 'Running...')
          c.setAutomationLiveUpdatedAt(new Date().toISOString())
        },
      })
    },
    onSuccess: async () => {
      c.setUiError(null)
      c.setAutomationInstruction('')
      c.setAutomationLiveActive(false)
      c.setAutomationLiveStatusText('')
      c.setAutomationLiveBuffer('')
      c.setAutomationLiveUpdatedAt(null)
      await c.qc.invalidateQueries({ queryKey: ['automation-status', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: async (err) => {
      c.setUiError(err instanceof Error ? err.message : 'Codex run failed')
      c.setAutomationLiveActive(false)
      c.setAutomationLiveStatusText('')
      c.setAutomationLiveBuffer('')
      c.setAutomationLiveUpdatedAt(null)
      await c.qc.invalidateQueries({ queryKey: ['automation-status', c.userId, c.selectedTaskId] })
    }
  })

  const createTaskGroupMutation = useMutation({
    mutationFn: (payload: { name: string; description?: string; color?: string | null }) => {
      const name = String(payload?.name || '').trim()
      if (!name) throw new Error('Task group name is required')
      if (!c.workspaceId || !c.selectedProjectId) throw new Error('Select a project first')
      return createTaskGroup(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        name,
        description: payload?.description ?? '',
        color: payload?.color ?? null,
      })
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['task-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
      await c.qc.invalidateQueries({ queryKey: ['board'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Task group create failed'),
  })

  const patchTaskGroupMutation = useMutation({
    mutationFn: (payload: {
      taskGroupId: string
      name?: string
      description?: string
      color?: string | null
    }) => {
      const body: { name?: string; description?: string; color?: string | null } = {}
      if (payload.name !== undefined) {
        const name = String(payload.name).trim()
        if (!name) throw new Error('Task group name is required')
        body.name = name
      }
      if (payload.description !== undefined) body.description = payload.description
      if (payload.color !== undefined) body.color = payload.color
      return patchTaskGroup(c.userId, payload.taskGroupId, body)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['task-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
      await c.qc.invalidateQueries({ queryKey: ['board'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Task group update failed'),
  })

  const deleteTaskGroupMutation = useMutation({
    mutationFn: (taskGroupId: string) => deleteTaskGroup(c.userId, taskGroupId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['task-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
      await c.qc.invalidateQueries({ queryKey: ['board'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Task group delete failed'),
  })

  const reorderTaskGroupsMutation = useMutation({
    mutationFn: (orderedIds: string[]) => {
      if (!c.workspaceId || !c.selectedProjectId) throw new Error('Select a project first')
      return reorderTaskGroups(c.userId, c.workspaceId, c.selectedProjectId, orderedIds)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['task-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
      await c.qc.invalidateQueries({ queryKey: ['board'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Task group reorder failed'),
  })

  return {
    saveTaskMutation,
    createTaskMutation,
    completeTaskMutation,
    reopenTaskMutation,
    archiveTaskMutation,
    restoreTaskMutation,
    runAutomationMutation,
    createTaskGroupMutation,
    patchTaskGroupMutation,
    deleteTaskGroupMutation,
    reorderTaskGroupsMutation,
  }
}
