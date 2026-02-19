import { useMutation } from '@tanstack/react-query'
import { createProject, createProjectFromTemplate, createProjectRule, deleteProject, deleteProjectRule, patchProject, patchProjectRule } from '../../api'
import { parseProjectEvidenceTopKInput, parseProjectStatusesText, toErrorMessage } from '../../utils/ui'

export function useProjectMutations(c: any) {
  const saveProjectMutation = useMutation({
    mutationFn: () => c.saveProjectNow(),
    onSuccess: () => {
      c.setUiError(null)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Project save failed')),
  })

  const createProjectMutation = useMutation({
    mutationFn: () => {
      const contextPackEvidenceTopK = parseProjectEvidenceTopKInput(c.projectContextPackEvidenceTopKText)
      const normalizedTemplateKey = String(c.projectTemplateKey || '').trim()
      const hasCustomStatuses = Boolean(String(c.projectCustomStatusesText || '').trim())
      const customStatuses = hasCustomStatuses ? parseProjectStatusesText(c.projectCustomStatusesText) : undefined
      if (normalizedTemplateKey) {
        return createProjectFromTemplate(c.userId, {
          workspace_id: c.workspaceId,
          template_key: normalizedTemplateKey,
          name: c.projectName.trim(),
          description: c.projectDescription,
          custom_statuses: customStatuses,
          member_user_ids: Array.from(new Set(c.createProjectMemberIds)),
          embedding_enabled: Boolean(c.projectEmbeddingEnabled),
          embedding_model: String(c.projectEmbeddingModel || '').trim() || null,
          context_pack_evidence_top_k: contextPackEvidenceTopK,
        })
      }
      return createProject(c.userId, {
        workspace_id: c.workspaceId,
        name: c.projectName.trim(),
        description: c.projectDescription,
        custom_statuses: customStatuses,
        external_refs: c.parseExternalRefsText(c.projectExternalRefsText),
        attachment_refs: c.parseAttachmentRefsText(c.projectAttachmentRefsText),
        embedding_enabled: Boolean(c.projectEmbeddingEnabled),
        embedding_model: String(c.projectEmbeddingModel || '').trim() || null,
        context_pack_evidence_top_k: contextPackEvidenceTopK,
        member_user_ids: Array.from(new Set(c.createProjectMemberIds)),
      })
    },
    onSuccess: async (createdPayload: any) => {
      const createdProject = createdPayload?.project ?? createdPayload
      const createdFromTemplate = Boolean(createdPayload?.template?.key)
      c.setUiError(null)
      if (createdFromTemplate) {
        try {
          const externalRefs = c.parseExternalRefsText(c.projectExternalRefsText)
          const attachmentRefs = c.parseAttachmentRefsText(c.projectAttachmentRefsText)
          if (externalRefs.length > 0 || attachmentRefs.length > 0) {
            await patchProject(c.userId, createdProject.id, {
              external_refs: externalRefs,
              attachment_refs: attachmentRefs,
            })
          }
        } catch (err) {
          c.setUiError(toErrorMessage(err, 'Project created, but external links could not be saved'))
        }
      }
      if (c.draftProjectRules.length > 0) {
        const creations = c.draftProjectRules.map((rule: any) =>
          createProjectRule(c.userId, {
            workspace_id: c.workspaceId,
            project_id: createdProject.id,
            title: rule.title,
            body: rule.body,
          })
        )
        try {
          await Promise.all(creations)
        } catch (err) {
          c.setUiError(toErrorMessage(err, 'Project created, but some rules failed to save'))
        }
      }
      c.setProjectName('')
      c.setProjectTemplateKey('')
      c.setProjectDescription('')
      c.setProjectCustomStatusesText('')
      c.setProjectExternalRefsText('')
      c.setProjectAttachmentRefsText('')
      c.setProjectEmbeddingEnabled(false)
      c.setProjectEmbeddingModel('')
      c.setProjectContextPackEvidenceTopKText('')
      c.setProjectDescriptionView('write')
      c.setCreateProjectMemberIds([])
      c.setDraftProjectRules([])
      c.setSelectedDraftProjectRuleId(null)
      c.setDraftProjectRuleTitle('')
      c.setDraftProjectRuleBody('')
      c.setDraftProjectRuleView('write')
      c.setShowProjectCreateForm(false)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Project create failed')
  })

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: string) => deleteProject(c.userId, projectId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Project delete failed')
  })

  const createProjectRuleMutation = useMutation({
    mutationFn: () =>
      createProjectRule(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        title: c.projectRuleTitle.trim(),
        body: c.projectRuleBody,
      }),
    onSuccess: async (rule) => {
      c.setUiError(null)
      c.setSelectedProjectRuleId(rule.id)
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Rule create failed')
  })

  const patchProjectRuleMutation = useMutation({
    mutationFn: () =>
      patchProjectRule(c.userId, c.selectedProjectRuleId as string, {
        title: c.projectRuleTitle.trim(),
        body: c.projectRuleBody,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Rule update failed')
  })

  const deleteProjectRuleMutation = useMutation({
    mutationFn: (ruleId: string) => deleteProjectRule(c.userId, ruleId),
    onSuccess: async () => {
      c.setUiError(null)
      c.setSelectedProjectRuleId(null)
      c.setProjectRuleTitle('')
      c.setProjectRuleBody('')
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Rule delete failed')
  })

  return {
    saveProjectMutation,
    createProjectMutation,
    deleteProjectMutation,
    createProjectRuleMutation,
    patchProjectRuleMutation,
    deleteProjectRuleMutation,
  }
}
