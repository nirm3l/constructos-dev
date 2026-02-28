import React from 'react'
import { attachmentRefsToText, externalRefsToText, projectStatusesToText } from '../utils/ui'

function normalizeChatIndexMode(value: unknown): 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' {
  const mode = String(value || '').trim().toUpperCase()
  if (mode === 'VECTOR_ONLY') return 'VECTOR_ONLY'
  if (mode === 'KG_AND_VECTOR') return 'KG_AND_VECTOR'
  return 'OFF'
}

function normalizeChatAttachmentIngestionMode(value: unknown): 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' {
  const mode = String(value || '').trim().toUpperCase()
  if (mode === 'OFF') return 'OFF'
  if (mode === 'FULL_TEXT_OCR') return 'FULL_TEXT'
  if (mode === 'FULL_TEXT') return 'FULL_TEXT'
  return 'METADATA_ONLY'
}

export function useProjectEditorEffects(c: any) {
  React.useEffect(() => {
    if (!c.selectedProject) {
      if (c.selectedProjectId) return
      c.setEditProjectName('')
      c.setEditProjectDescription('')
      c.setEditProjectCustomStatusesText('')
      c.setEditProjectExternalRefsText('')
      c.setEditProjectAttachmentRefsText('')
      c.setEditProjectEmbeddingEnabled(false)
      c.setEditProjectEmbeddingModel('')
      c.setEditProjectContextPackEvidenceTopKText('')
      c.setEditProjectChatIndexMode('OFF')
      c.setEditProjectChatAttachmentIngestionMode('METADATA_ONLY')
      c.setEditProjectEventStormingEnabled(true)
      c.setEditProjectDescriptionView('split')
      c.setShowProjectEditForm(false)
      c.setSelectedProjectRuleId(null)
      c.setProjectRuleTitle('')
      c.setProjectRuleBody('')
      c.setProjectRuleView('split')
      return
    }
    c.setEditProjectName(c.selectedProject.name ?? '')
    c.setEditProjectDescription(c.selectedProject.description ?? '')
    c.setEditProjectCustomStatusesText(projectStatusesToText(c.selectedProject.custom_statuses))
    c.setEditProjectExternalRefsText(externalRefsToText(c.selectedProject.external_refs))
    c.setEditProjectAttachmentRefsText(attachmentRefsToText(c.selectedProject.attachment_refs))
    c.setEditProjectEmbeddingEnabled(Boolean(c.selectedProject.embedding_enabled))
    c.setEditProjectEmbeddingModel(String(c.selectedProject.embedding_model || ''))
    c.setEditProjectContextPackEvidenceTopKText(
      c.selectedProject.context_pack_evidence_top_k == null ? '' : String(c.selectedProject.context_pack_evidence_top_k)
    )
    c.setEditProjectChatIndexMode(normalizeChatIndexMode(c.selectedProject.chat_index_mode))
    c.setEditProjectChatAttachmentIngestionMode(
      normalizeChatAttachmentIngestionMode(c.selectedProject.chat_attachment_ingestion_mode)
    )
    c.setEditProjectEventStormingEnabled(Boolean(c.selectedProject.event_storming_enabled ?? true))
    c.setEditProjectDescriptionView('split')
    c.setSelectedProjectRuleId(null)
    c.setProjectRuleTitle('')
    c.setProjectRuleBody('')
    c.setProjectRuleView('split')
  }, [c.selectedProject?.id, c.selectedProjectId, c.setShowProjectEditForm])

  React.useEffect(() => {
    if (!c.showProjectCreateForm) return
    c.setProjectDescriptionView('split')
    c.setProjectEventStormingEnabled(true)
  }, [c.showProjectCreateForm])

  React.useEffect(() => {
    if (!c.showProjectCreateForm) return
    if (String(c.projectTemplateKey || '').trim()) return
    if (String(c.projectCustomStatusesText || '').trim()) return
    c.setProjectCustomStatusesText(projectStatusesToText(null))
  }, [c.projectCustomStatusesText, c.projectTemplateKey, c.setProjectCustomStatusesText, c.showProjectCreateForm])

  React.useEffect(() => {
    if (!c.selectedProjectRule) return
    c.setProjectRuleTitle(c.selectedProjectRule.title ?? '')
    c.setProjectRuleBody(c.selectedProjectRule.body ?? '')
    c.setProjectRuleView('split')
  }, [c.selectedProjectRule?.id])

  React.useEffect(() => {
    if (!c.selectedDraftProjectRuleId) return
    const selected = c.draftProjectRules.find((r: any) => r.id === c.selectedDraftProjectRuleId)
    if (!selected) return
    c.setDraftProjectRuleTitle(selected.title)
    c.setDraftProjectRuleBody(selected.body)
    c.setDraftProjectRuleView('split')
  }, [c.selectedDraftProjectRuleId, c.draftProjectRules])

  React.useEffect(() => {
    if (!c.showProjectCreateForm || c.projectDescriptionView !== 'write') return
    c.autoResizeTextarea(c.projectDescriptionRef.current)
  }, [c.autoResizeTextarea, c.projectDescription, c.projectDescriptionView, c.showProjectCreateForm])

  React.useEffect(() => {
    if (!c.showProjectEditForm || c.editProjectDescriptionView !== 'write') return
    c.autoResizeTextarea(c.editProjectDescriptionRef.current)
  }, [c.autoResizeTextarea, c.editProjectDescription, c.editProjectDescriptionView, c.showProjectEditForm])
}
