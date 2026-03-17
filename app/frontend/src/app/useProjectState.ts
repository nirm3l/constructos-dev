import React from 'react'
import { parseStoredProjectId, parseStoredProjectsMode } from '../utils/ui'
import type { DraftProjectRule } from '../components/projects/ProjectsCreateForm'

export function useProjectState() {
  const [projectName, setProjectName] = React.useState('')
  const [projectTemplateKey, setProjectTemplateKey] = React.useState('')
  const [projectDescription, setProjectDescription] = React.useState('')
  const [projectCustomStatusesText, setProjectCustomStatusesText] = React.useState('')
  const [projectExternalRefsText, setProjectExternalRefsText] = React.useState('')
  const [projectAttachmentRefsText, setProjectAttachmentRefsText] = React.useState('')
  const [projectEmbeddingEnabled, setProjectEmbeddingEnabled] = React.useState(true)
  const [projectEmbeddingModel, setProjectEmbeddingModel] = React.useState('')
  const [projectContextPackEvidenceTopKText, setProjectContextPackEvidenceTopKText] = React.useState('')
  const [projectAutomationMaxParallelTasksText, setProjectAutomationMaxParallelTasksText] = React.useState('4')
  const [projectChatIndexMode, setProjectChatIndexMode] = React.useState<'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'>(
    'KG_AND_VECTOR'
  )
  const [projectChatAttachmentIngestionMode, setProjectChatAttachmentIngestionMode] = React.useState<
    'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
  >('METADATA_ONLY')
  const [projectEventStormingEnabled, setProjectEventStormingEnabled] = React.useState(true)
  const [projectTemplateParametersText, setProjectTemplateParametersText] = React.useState('')
  const [projectDescriptionView, setProjectDescriptionView] = React.useState<'write' | 'preview' | 'split'>('split')
  const [showProjectCreateForm, setShowProjectCreateForm] = React.useState(false)
  const [showProjectEditForm, setShowProjectEditForm] = React.useState(false)
  const [editProjectName, setEditProjectName] = React.useState('')
  const [editProjectDescription, setEditProjectDescription] = React.useState('')
  const [editProjectCustomStatusesText, setEditProjectCustomStatusesText] = React.useState('')
  const [editProjectExternalRefsText, setEditProjectExternalRefsText] = React.useState('')
  const [editProjectAttachmentRefsText, setEditProjectAttachmentRefsText] = React.useState('')
  const [editProjectEmbeddingEnabled, setEditProjectEmbeddingEnabled] = React.useState(false)
  const [editProjectEmbeddingModel, setEditProjectEmbeddingModel] = React.useState('')
  const [editProjectVectorIndexDistillEnabled, setEditProjectVectorIndexDistillEnabled] = React.useState(false)
  const [editProjectContextPackEvidenceTopKText, setEditProjectContextPackEvidenceTopKText] = React.useState('')
  const [editProjectAutomationMaxParallelTasksText, setEditProjectAutomationMaxParallelTasksText] = React.useState('4')
  const [editProjectChatIndexMode, setEditProjectChatIndexMode] = React.useState<'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'>(
    'OFF'
  )
  const [editProjectChatAttachmentIngestionMode, setEditProjectChatAttachmentIngestionMode] = React.useState<
    'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'
  >('METADATA_ONLY')
  const [editProjectEventStormingEnabled, setEditProjectEventStormingEnabled] = React.useState(true)
  const [createProjectMemberIds, setCreateProjectMemberIds] = React.useState<string[]>([])
  const [createProjectWorkspaceSkillIds, setCreateProjectWorkspaceSkillIds] = React.useState<string[]>([])
  const [editProjectMemberIds, setEditProjectMemberIds] = React.useState<string[]>([])
  const [editProjectDescriptionView, setEditProjectDescriptionView] = React.useState<'write' | 'preview' | 'split'>('split')
  const [selectedProjectRuleId, setSelectedProjectRuleId] = React.useState<string | null>(null)
  const [projectRuleTitle, setProjectRuleTitle] = React.useState('')
  const [projectRuleBody, setProjectRuleBody] = React.useState('')
  const [projectRuleView, setProjectRuleView] = React.useState<'write' | 'preview' | 'split'>('split')
  const [draftProjectRules, setDraftProjectRules] = React.useState<DraftProjectRule[]>([])
  const [selectedDraftProjectRuleId, setSelectedDraftProjectRuleId] = React.useState<string | null>(null)
  const [draftProjectRuleTitle, setDraftProjectRuleTitle] = React.useState('')
  const [draftProjectRuleBody, setDraftProjectRuleBody] = React.useState('')
  const [draftProjectRuleView, setDraftProjectRuleView] = React.useState<'write' | 'preview' | 'split'>('split')
  const [selectedProjectId, setSelectedProjectId] = React.useState<string>(() => {
    if (typeof window !== 'undefined') {
      const fromUrl = new URLSearchParams(window.location.search).get('project')
      if (fromUrl) return fromUrl
    }
    return parseStoredProjectId(localStorage.getItem('ui_selected_project_id'))
  })
  const [projectsMode, setProjectsMode] = React.useState<'board' | 'list'>(() =>
    parseStoredProjectsMode(localStorage.getItem('ui_projects_mode'))
  )
  const toggleCreateProjectWorkspaceSkill = React.useCallback((skillIdToToggle: string) => {
    const normalized = String(skillIdToToggle || '').trim()
    if (!normalized) return
    setCreateProjectWorkspaceSkillIds((prev) => {
      const normalizedPrev = prev.map((item) => String(item || '').trim()).filter(Boolean)
      if (normalizedPrev.includes(normalized)) return normalizedPrev.filter((item) => item !== normalized)
      return [...normalizedPrev, normalized]
    })
  }, [])

  return {
    projectName,
    setProjectName,
    projectTemplateKey,
    setProjectTemplateKey,
    projectDescription,
    setProjectDescription,
    projectCustomStatusesText,
    setProjectCustomStatusesText,
    projectExternalRefsText,
    setProjectExternalRefsText,
    projectAttachmentRefsText,
    setProjectAttachmentRefsText,
    projectEmbeddingEnabled,
    setProjectEmbeddingEnabled,
    projectEmbeddingModel,
    setProjectEmbeddingModel,
    projectContextPackEvidenceTopKText,
    setProjectContextPackEvidenceTopKText,
    projectAutomationMaxParallelTasksText,
    setProjectAutomationMaxParallelTasksText,
    projectChatIndexMode,
    setProjectChatIndexMode,
    projectChatAttachmentIngestionMode,
    setProjectChatAttachmentIngestionMode,
    projectEventStormingEnabled,
    setProjectEventStormingEnabled,
    projectTemplateParametersText,
    setProjectTemplateParametersText,
    projectDescriptionView,
    setProjectDescriptionView,
    showProjectCreateForm,
    setShowProjectCreateForm,
    showProjectEditForm,
    setShowProjectEditForm,
    editProjectName,
    setEditProjectName,
    editProjectDescription,
    setEditProjectDescription,
    editProjectCustomStatusesText,
    setEditProjectCustomStatusesText,
    editProjectExternalRefsText,
    setEditProjectExternalRefsText,
    editProjectAttachmentRefsText,
    setEditProjectAttachmentRefsText,
    editProjectEmbeddingEnabled,
    setEditProjectEmbeddingEnabled,
    editProjectEmbeddingModel,
    setEditProjectEmbeddingModel,
    editProjectVectorIndexDistillEnabled,
    setEditProjectVectorIndexDistillEnabled,
    editProjectContextPackEvidenceTopKText,
    setEditProjectContextPackEvidenceTopKText,
    editProjectAutomationMaxParallelTasksText,
    setEditProjectAutomationMaxParallelTasksText,
    editProjectChatIndexMode,
    setEditProjectChatIndexMode,
    editProjectChatAttachmentIngestionMode,
    setEditProjectChatAttachmentIngestionMode,
    editProjectEventStormingEnabled,
    setEditProjectEventStormingEnabled,
    createProjectMemberIds,
    setCreateProjectMemberIds,
    createProjectWorkspaceSkillIds,
    setCreateProjectWorkspaceSkillIds,
    toggleCreateProjectWorkspaceSkill,
    editProjectMemberIds,
    setEditProjectMemberIds,
    editProjectDescriptionView,
    setEditProjectDescriptionView,
    selectedProjectRuleId,
    setSelectedProjectRuleId,
    projectRuleTitle,
    setProjectRuleTitle,
    projectRuleBody,
    setProjectRuleBody,
    projectRuleView,
    setProjectRuleView,
    draftProjectRules,
    setDraftProjectRules,
    selectedDraftProjectRuleId,
    setSelectedDraftProjectRuleId,
    draftProjectRuleTitle,
    setDraftProjectRuleTitle,
    draftProjectRuleBody,
    setDraftProjectRuleBody,
    draftProjectRuleView,
    setDraftProjectRuleView,
    selectedProjectId,
    setSelectedProjectId,
    projectsMode,
    setProjectsMode,
  }
}
