import { useMutation } from '@tanstack/react-query'
import { archiveNote, createNote, deleteNote, pinNote, restoreNote, unpinNote } from '../../api'
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
    mutationFn: () =>
      createNote(c.userId, {
        title: 'Untitled',
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        body: '',
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
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Pin failed')
  })

  const unpinNoteMutation = useMutation({
    mutationFn: (id: string) => unpinNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Unpin failed')
  })

  const archiveNoteMutation = useMutation({
    mutationFn: (id: string) => archiveNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Archive note failed')
  })

  const restoreNoteMutation = useMutation({
    mutationFn: (id: string) => restoreNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Restore note failed')
  })

  const deleteNoteMutation = useMutation({
    mutationFn: (id: string) => deleteNote(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      c.setSelectedNoteId(null)
      await c.qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Delete note failed')
  })

  return {
    saveNoteMutation,
    createNoteMutation,
    pinNoteMutation,
    unpinNoteMutation,
    archiveNoteMutation,
    restoreNoteMutation,
    deleteNoteMutation,
  }
}
