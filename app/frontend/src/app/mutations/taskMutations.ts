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
  runTaskWithCodex,
} from '../../api'

export function useTaskMutations(c: any) {
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
      due_date?: string | null
      labels?: string[]
      open_task?: boolean
    }) =>
      createTask(c.userId, {
        title: payload?.title?.trim() || c.taskTitle.trim(),
        workspace_id: c.workspaceId,
        project_id: payload?.project_id || c.quickProjectId || c.selectedProjectId,
        task_group_id: payload?.task_group_id ?? null,
        description: payload?.description ?? '',
        due_date:
          payload?.due_date !== undefined
            ? payload.due_date
            : (c.quickDueDate ? new Date(c.quickDueDate).toISOString() : null),
        labels: payload?.labels ?? c.quickTaskTags,
        external_refs: c.parseExternalRefsText(c.quickTaskExternalRefsText),
        attachment_refs: c.parseAttachmentRefsText(c.quickTaskAttachmentRefsText),
      }),
    onSuccess: async (task, payload) => {
      c.setUiError(null)
      if (payload?.open_task) {
        c.setSelectedTaskId(task.id)
        c.setTab('tasks')
      } else {
        c.setTaskTitle('')
        c.setQuickDueDate('')
        c.setQuickTaskTags([])
        c.setQuickTaskExternalRefsText('')
        c.setQuickTaskAttachmentRefsText('')
        c.setShowQuickTaskTagPicker(false)
        c.setQuickTaskTagQuery('')
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
    mutationFn: () => runTaskWithCodex(c.userId, c.selectedTaskId as string, c.automationInstruction.trim()),
    onSuccess: async () => {
      c.setUiError(null)
      c.setAutomationInstruction('')
      await c.qc.invalidateQueries({ queryKey: ['automation-status', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Codex run failed')
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
