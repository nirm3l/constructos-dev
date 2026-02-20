import { useMutation } from '@tanstack/react-query'
import {
  archiveNote,
  createNote,
  createNoteGroup,
  deleteNote,
  deleteNoteGroup,
  patchNote,
  patchNoteGroup,
  pinNote,
  reorderNoteGroups,
  restoreNote,
  unpinNote,
} from '../../api'
import { toErrorMessage } from '../../utils/ui'

export function useNoteMutations(c: any) {
  const saveNoteMutation = useMutation({
    mutationFn: () => c.saveNoteNow(),
    onSuccess: () => {
      c.setUiError(null)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Note save failed')),
  })

  const createNoteMutation = useMutation({
    mutationFn: (payload?: {
      title?: string
      body?: string
      project_id?: string
      note_group_id?: string | null
      task_id?: string | null
      specification_id?: string | null
    }) =>
      createNote(c.userId, {
        title: payload?.title?.trim() || 'Untitled',
        workspace_id: c.workspaceId,
        project_id: payload?.project_id || c.selectedProjectId,
        note_group_id: payload?.note_group_id ?? null,
        task_id: payload?.task_id ?? null,
        specification_id: payload?.specification_id ?? null,
        body: payload?.body ?? '',
        external_refs: [],
        attachment_refs: [],
      }),
    onSuccess: async (note) => {
      c.setUiError(null)
      c.setTab('notes')
      c.openNextSelectedNoteInWriteRef.current = true
      c.setSelectedNoteId(note.id)
      c.setShowTagPicker(true)
      c.setTagPickerQuery('')
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note create failed')
  })

  const pinNoteMutation = useMutation({
    mutationFn: (id: string) => pinNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Pin failed')
  })

  const unpinNoteMutation = useMutation({
    mutationFn: (id: string) => unpinNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Unpin failed')
  })

  const archiveNoteMutation = useMutation({
    mutationFn: (id: string) => archiveNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Archive note failed')
  })

  const restoreNoteMutation = useMutation({
    mutationFn: (id: string) => restoreNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Restore note failed')
  })

  const deleteNoteMutation = useMutation({
    mutationFn: (id: string) => deleteNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      c.setSelectedNoteId(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Delete note failed')
  })

  const createNoteGroupMutation = useMutation({
    mutationFn: (payload: { name: string; description?: string; color?: string | null }) => {
      const name = String(payload?.name || '').trim()
      if (!name) throw new Error('Note group name is required')
      if (!c.workspaceId || !c.selectedProjectId) throw new Error('Select a project first')
      return createNoteGroup(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        name,
        description: payload?.description ?? '',
        color: payload?.color ?? null,
      })
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['note-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note group create failed'),
  })

  const patchNoteGroupMutation = useMutation({
    mutationFn: (payload: {
      noteGroupId: string
      name?: string
      description?: string
      color?: string | null
    }) => {
      const body: { name?: string; description?: string; color?: string | null } = {}
      if (payload.name !== undefined) {
        const name = String(payload.name).trim()
        if (!name) throw new Error('Note group name is required')
        body.name = name
      }
      if (payload.description !== undefined) body.description = payload.description
      if (payload.color !== undefined) body.color = payload.color
      return patchNoteGroup(c.userId, payload.noteGroupId, body)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['note-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note group update failed'),
  })

  const deleteNoteGroupMutation = useMutation({
    mutationFn: (noteGroupId: string) => deleteNoteGroup(c.userId, noteGroupId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['note-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note group delete failed'),
  })

  const reorderNoteGroupsMutation = useMutation({
    mutationFn: (orderedIds: string[]) => {
      if (!c.workspaceId || !c.selectedProjectId) throw new Error('Select a project first')
      return reorderNoteGroups(c.userId, c.workspaceId, c.selectedProjectId, orderedIds)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['note-groups'] })
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note group reorder failed'),
  })

  const moveNoteToGroupMutation = useMutation({
    mutationFn: (payload: { noteId: string; note_group_id: string | null }) =>
      patchNote(c.userId, payload.noteId, { note_group_id: payload.note_group_id }),
    onSuccess: async (note, payload) => {
      c.setUiError(null)
      if (c.selectedNoteId === payload.noteId) {
        c.setEditNoteGroupId(payload.note_group_id || '')
      }
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
      await c.qc.invalidateQueries({ queryKey: ['task-notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Note move failed'),
  })

  return {
    saveNoteMutation,
    createNoteMutation,
    pinNoteMutation,
    unpinNoteMutation,
    archiveNoteMutation,
    restoreNoteMutation,
    deleteNoteMutation,
    createNoteGroupMutation,
    patchNoteGroupMutation,
    deleteNoteGroupMutation,
    reorderNoteGroupsMutation,
    moveNoteToGroupMutation,
  }
}
