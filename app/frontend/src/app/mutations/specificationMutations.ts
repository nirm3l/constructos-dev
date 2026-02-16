import { useMutation } from '@tanstack/react-query'
import {
  archiveSpecification,
  createSpecification,
  deleteSpecification,
  patchSpecification,
  restoreSpecification,
} from '../../api'
import { toErrorMessage } from '../../utils/ui'

export function useSpecificationMutations(c: any) {
  const saveSpecificationMutation = useMutation({
    mutationFn: () => {
      if (!c.selectedSpecificationId) throw new Error('No specification selected')
      return patchSpecification(c.userId, c.selectedSpecificationId, {
        title: c.editSpecificationTitle.trim() || 'Untitled',
        body: c.editSpecificationBody,
        status: c.editSpecificationStatus,
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
    mutationFn: () =>
      createSpecification(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        title: 'Untitled spec',
        body: '',
        status: 'Draft',
      }),
    onSuccess: async (specification) => {
      c.setUiError(null)
      c.setTab('specifications')
      c.setSelectedSpecificationId(specification.id)
      await c.invalidateAll()
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

  return {
    saveSpecificationMutation,
    createSpecificationMutation,
    archiveSpecificationMutation,
    restoreSpecificationMutation,
    deleteSpecificationMutation,
  }
}
