import { useMutation } from '@tanstack/react-query'
import {
  archiveSpecification,
  bulkCreateSpecificationTasks,
  createSpecification,
  createSpecificationNote,
  createSpecificationTask,
  deleteSpecification,
  linkNoteToSpecification,
  linkTaskToSpecification,
  patchSpecification,
  restoreSpecification,
  unlinkNoteFromSpecification,
  unlinkTaskFromSpecification,
} from '../../api'
import { parseCommaTags, toErrorMessage } from '../../utils/ui'

export function useSpecificationMutations(c: any) {
  const saveSpecificationMutation = useMutation({
    mutationFn: () => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return patchSpecification(c.userId, c.selectedSpecificationId, {
        title: c.editSpecificationTitle.trim() || 'Untitled',
        body: c.editSpecificationBody,
        status: c.editSpecificationStatus,
        tags: parseCommaTags(c.editSpecificationTags),
        external_refs: c.parseExternalRefsText(c.editSpecificationExternalRefsText),
        attachment_refs: c.parseAttachmentRefsText(c.editSpecificationAttachmentRefsText),
      })
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification save failed')),
  })

  const createSpecificationMutation = useMutation({
    mutationFn: (payload?: {
      title?: string
      body?: string
      status?: 'Draft' | 'Ready' | 'In Progress' | 'Implemented' | 'Archived'
      force_new?: boolean
    }) =>
      createSpecification(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        title: payload?.title?.trim() || 'Untitled spec',
        body: payload?.body ?? '',
        status: payload?.status ?? 'Draft',
        tags: [],
        force_new: payload?.force_new ?? true,
      }),
    onSuccess: async (specification) => {
      c.setUiError(null)
      c.setTab('specifications')
      if (typeof c.clearSpecificationFilterTags === 'function') c.clearSpecificationFilterTags()
      if (typeof c.setSpecificationStatus === 'function') c.setSpecificationStatus('')
      await c.invalidateAll()
      c.setSelectedSpecificationId(specification.id)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification create failed')),
  })

  const archiveSpecificationMutation = useMutation({
    mutationFn: (specificationId: string) => archiveSpecification(c.userId, specificationId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification archive failed')),
  })

  const restoreSpecificationMutation = useMutation({
    mutationFn: (specificationId: string) => restoreSpecification(c.userId, specificationId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification restore failed')),
  })

  const deleteSpecificationMutation = useMutation({
    mutationFn: (specificationId: string) => deleteSpecification(c.userId, specificationId),
    onSuccess: async () => {
      c.setUiError(null)
      c.setSelectedSpecificationId(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification delete failed')),
  })

  const createSpecificationTaskMutation = useMutation({
    mutationFn: (payload: { title: string }) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return createSpecificationTask(c.userId, c.selectedSpecificationId, { title: payload.title })
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification task create failed')),
  })

  const bulkCreateSpecificationTasksMutation = useMutation({
    mutationFn: (payload: { titles: string[] }) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return bulkCreateSpecificationTasks(c.userId, c.selectedSpecificationId, { titles: payload.titles })
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification bulk create failed')),
  })

  const createSpecificationNoteMutation = useMutation({
    mutationFn: (payload: { title: string; body?: string }) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return createSpecificationNote(c.userId, c.selectedSpecificationId, payload)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Specification note create failed')),
  })

  const linkTaskToSpecificationMutation = useMutation({
    mutationFn: (taskId: string) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return linkTaskToSpecification(c.userId, c.selectedSpecificationId, taskId)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Task link failed')),
  })

  const unlinkTaskFromSpecificationMutation = useMutation({
    mutationFn: (taskId: string) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return unlinkTaskFromSpecification(c.userId, c.selectedSpecificationId, taskId)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Task unlink failed')),
  })

  const linkNoteToSpecificationMutation = useMutation({
    mutationFn: (noteId: string) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return linkNoteToSpecification(c.userId, c.selectedSpecificationId, noteId)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Note link failed')),
  })

  const unlinkNoteFromSpecificationMutation = useMutation({
    mutationFn: (noteId: string) => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return unlinkNoteFromSpecification(c.userId, c.selectedSpecificationId, noteId)
    },
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Note unlink failed')),
  })

  return {
    saveSpecificationMutation,
    createSpecificationMutation,
    archiveSpecificationMutation,
    restoreSpecificationMutation,
    deleteSpecificationMutation,
    createSpecificationTaskMutation,
    bulkCreateSpecificationTasksMutation,
    createSpecificationNoteMutation,
    linkTaskToSpecificationMutation,
    unlinkTaskFromSpecificationMutation,
    linkNoteToSpecificationMutation,
    unlinkNoteFromSpecificationMutation,
  }
}
