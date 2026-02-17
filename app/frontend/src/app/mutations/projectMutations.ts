import { useMutation } from '@tanstack/react-query'
import { createProject, createProjectRule, deleteProject, deleteProjectRule, patchProjectRule } from '../../api'
import { parseProjectStatusesText, toErrorMessage } from '../../utils/ui'

export function useProjectMutations(c: any) {
  const saveProjectMutation = useMutation({
    mutationFn: () => c.saveProjectNow(),
    onSuccess: () => {
      c.setUiError(null)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Project save failed')),
  })

  const createProjectMutation = useMutation({
    mutationFn: () =>
      createProject(c.userId, {
        workspace_id: c.workspaceId,
        name: c.projectName.trim(),
        description: c.projectDescription,
        custom_statuses: parseProjectStatusesText(c.projectCustomStatusesText),
        external_refs: c.parseExternalRefsText(c.projectExternalRefsText),
        attachment_refs: c.parseAttachmentRefsText(c.projectAttachmentRefsText),
        member_user_ids: Array.from(new Set(c.createProjectMemberIds)),
      }),
    onSuccess: async (createdProject) => {
      c.setUiError(null)
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
      c.setProjectDescription('')
      c.setProjectCustomStatusesText('')
      c.setProjectExternalRefsText('')
      c.setProjectAttachmentRefsText('')
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
