import { useMutation } from '@tanstack/react-query'
import {
  applyProjectSkill,
  attachWorkspaceSkillToProject,
  createProject,
  createProjectFromTemplate,
  createProjectRule,
  deleteProject,
  deleteProjectRule,
  deleteProjectSkill,
  deleteWorkspaceSkill,
  importProjectSkill,
  importProjectSkillFile,
  importWorkspaceSkill,
  importWorkspaceSkillFile,
  patchProject,
  patchProjectRule,
  patchProjectSkill,
  patchWorkspaceSkill,
  previewProjectFromTemplate,
} from '../../api'
import { parseProjectEvidenceTopKInput, parseProjectStatusesText, parseTemplateParametersInput, toErrorMessage } from '../../utils/ui'

function resolveProjectChatPolicy(
  embeddingEnabled: boolean,
  chatIndexMode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR',
  chatAttachmentIngestionMode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
): {
  chat_index_mode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'
  chat_attachment_ingestion_mode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
} {
  if (!embeddingEnabled || chatIndexMode === 'OFF') {
    return {
      chat_index_mode: 'OFF',
      chat_attachment_ingestion_mode: 'METADATA_ONLY',
    }
  }
  return {
    chat_index_mode: chatIndexMode,
    chat_attachment_ingestion_mode: chatAttachmentIngestionMode,
  }
}

export function useProjectMutations(c: any) {
  const saveProjectMutation = useMutation({
    mutationFn: () => c.saveProjectNow(),
    onSuccess: () => {
      c.setUiError(null)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Project save failed')),
  })

  const previewProjectFromTemplateMutation = useMutation({
    mutationFn: () => {
      const normalizedTemplateKey = String(c.projectTemplateKey || '').trim()
      if (!normalizedTemplateKey) {
        throw new Error('Select a project template to preview')
      }
      const embeddingEnabled = Boolean(c.projectEmbeddingEnabled)
      const chatPolicy = resolveProjectChatPolicy(
        embeddingEnabled,
        c.projectChatIndexMode,
        c.projectChatAttachmentIngestionMode
      )
      const contextPackEvidenceTopK = parseProjectEvidenceTopKInput(c.projectContextPackEvidenceTopKText)
      const hasCustomStatuses = Boolean(String(c.projectCustomStatusesText || '').trim())
      const customStatuses = hasCustomStatuses ? parseProjectStatusesText(c.projectCustomStatusesText) : undefined
      const parameters = parseTemplateParametersInput(c.projectTemplateParametersText)
      return previewProjectFromTemplate(c.userId, {
        workspace_id: c.workspaceId,
        template_key: normalizedTemplateKey,
        name: c.projectName.trim(),
        description: c.projectDescription,
        custom_statuses: customStatuses,
        member_user_ids: Array.from(new Set(c.createProjectMemberIds)),
        embedding_enabled: embeddingEnabled,
        embedding_model: String(c.projectEmbeddingModel || '').trim() || null,
        context_pack_evidence_top_k: contextPackEvidenceTopK,
        ...chatPolicy,
        parameters,
      })
    },
    onSuccess: () => {
      c.setUiError(null)
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Template preview failed'))
  })

  const createProjectMutation = useMutation({
    mutationFn: () => {
      const embeddingEnabled = Boolean(c.projectEmbeddingEnabled)
      const chatPolicy = resolveProjectChatPolicy(
        embeddingEnabled,
        c.projectChatIndexMode,
        c.projectChatAttachmentIngestionMode
      )
      const contextPackEvidenceTopK = parseProjectEvidenceTopKInput(c.projectContextPackEvidenceTopKText)
      const normalizedTemplateKey = String(c.projectTemplateKey || '').trim()
      const hasCustomStatuses = Boolean(String(c.projectCustomStatusesText || '').trim())
      const customStatuses = hasCustomStatuses ? parseProjectStatusesText(c.projectCustomStatusesText) : undefined
      const parameters = parseTemplateParametersInput(c.projectTemplateParametersText)
      if (normalizedTemplateKey) {
        return createProjectFromTemplate(c.userId, {
          workspace_id: c.workspaceId,
          template_key: normalizedTemplateKey,
          name: c.projectName.trim(),
          description: c.projectDescription,
          custom_statuses: customStatuses,
          member_user_ids: Array.from(new Set(c.createProjectMemberIds)),
          embedding_enabled: embeddingEnabled,
          embedding_model: String(c.projectEmbeddingModel || '').trim() || null,
          context_pack_evidence_top_k: contextPackEvidenceTopK,
          ...chatPolicy,
          parameters,
        })
      }
      return createProject(c.userId, {
        workspace_id: c.workspaceId,
        name: c.projectName.trim(),
        description: c.projectDescription,
        custom_statuses: customStatuses,
        external_refs: c.parseExternalRefsText(c.projectExternalRefsText),
        attachment_refs: c.parseAttachmentRefsText(c.projectAttachmentRefsText),
        embedding_enabled: embeddingEnabled,
        embedding_model: String(c.projectEmbeddingModel || '').trim() || null,
        context_pack_evidence_top_k: contextPackEvidenceTopK,
        ...chatPolicy,
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
      c.setProjectChatIndexMode('OFF')
      c.setProjectChatAttachmentIngestionMode('METADATA_ONLY')
      c.setProjectTemplateParametersText('')
      c.setProjectDescriptionView('write')
      c.setCreateProjectMemberIds([])
      c.setDraftProjectRules([])
      c.setSelectedDraftProjectRuleId(null)
      c.setDraftProjectRuleTitle('')
      c.setDraftProjectRuleBody('')
      c.setDraftProjectRuleView('write')
      c.setShowProjectCreateForm(false)
      previewProjectFromTemplateMutation.reset()
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

  const importProjectSkillMutation = useMutation({
    mutationFn: (payload: {
      source_url: string
      name?: string
      skill_key?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }) =>
      importProjectSkill(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        source_url: payload.source_url,
        name: payload.name,
        skill_key: payload.skill_key,
        mode: payload.mode,
        trust_level: payload.trust_level,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Skill import failed')),
  })

  const importProjectSkillFileMutation = useMutation({
    mutationFn: (payload: {
      file: File
      name?: string
      skill_key?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }) =>
      importProjectSkillFile(c.userId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
        file: payload.file,
        name: payload.name,
        skill_key: payload.skill_key,
        mode: payload.mode,
        trust_level: payload.trust_level,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Skill file import failed')),
  })

  const patchProjectSkillMutation = useMutation({
    mutationFn: (payload: {
      skillId: string
      patch: {
        name?: string
        summary?: string
        content?: string
        mode?: 'advisory' | 'enforced'
        trust_level?: 'verified' | 'reviewed' | 'untrusted'
        sync_project_rule?: boolean
      }
    }) => patchProjectSkill(c.userId, payload.skillId, payload.patch),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Skill update failed')),
  })

  const applyProjectSkillMutation = useMutation({
    mutationFn: (payload: { skillId: string }) => applyProjectSkill(c.userId, payload.skillId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Skill apply failed')),
  })

  const deleteProjectSkillMutation = useMutation({
    mutationFn: (payload: { skillId: string; delete_linked_rule?: boolean }) =>
      deleteProjectSkill(c.userId, payload.skillId, {
        delete_linked_rule: payload.delete_linked_rule ?? true,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
      await c.qc.invalidateQueries({ queryKey: ['project-rules'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Skill delete failed')),
  })

  const importWorkspaceSkillMutation = useMutation({
    mutationFn: (payload: {
      source_url: string
      name?: string
      skill_key?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }) =>
      importWorkspaceSkill(c.userId, {
        workspace_id: c.workspaceId,
        source_url: payload.source_url,
        name: payload.name,
        skill_key: payload.skill_key,
        mode: payload.mode,
        trust_level: payload.trust_level,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['workspace-skills'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Workspace skill import failed')),
  })

  const importWorkspaceSkillFileMutation = useMutation({
    mutationFn: (payload: {
      file: File
      name?: string
      skill_key?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }) =>
      importWorkspaceSkillFile(c.userId, {
        workspace_id: c.workspaceId,
        file: payload.file,
        name: payload.name,
        skill_key: payload.skill_key,
        mode: payload.mode,
        trust_level: payload.trust_level,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['workspace-skills'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Workspace skill file import failed')),
  })

  const patchWorkspaceSkillMutation = useMutation({
    mutationFn: (payload: {
      skillId: string
      patch: {
        name?: string
        summary?: string
        content?: string
        mode?: 'advisory' | 'enforced'
        trust_level?: 'verified' | 'reviewed' | 'untrusted'
      }
    }) => patchWorkspaceSkill(c.userId, payload.skillId, payload.patch),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['workspace-skills'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Workspace skill update failed')),
  })

  const deleteWorkspaceSkillMutation = useMutation({
    mutationFn: (payload: { skillId: string }) => deleteWorkspaceSkill(c.userId, payload.skillId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['workspace-skills'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Workspace skill delete failed')),
  })

  const attachWorkspaceSkillToProjectMutation = useMutation({
    mutationFn: (payload: { skillId: string }) =>
      attachWorkspaceSkillToProject(c.userId, payload.skillId, {
        workspace_id: c.workspaceId,
        project_id: c.selectedProjectId,
      }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['project-skills'] })
    },
    onError: (err) => c.setUiError(toErrorMessage(err, 'Attach catalog skill failed')),
  })

  return {
    saveProjectMutation,
    previewProjectFromTemplateMutation,
    createProjectMutation,
    deleteProjectMutation,
    createProjectRuleMutation,
    patchProjectRuleMutation,
    deleteProjectRuleMutation,
    importProjectSkillMutation,
    importProjectSkillFileMutation,
    patchProjectSkillMutation,
    applyProjectSkillMutation,
    deleteProjectSkillMutation,
    importWorkspaceSkillMutation,
    importWorkspaceSkillFileMutation,
    patchWorkspaceSkillMutation,
    deleteWorkspaceSkillMutation,
    attachWorkspaceSkillToProjectMutation,
  }
}
