import React from 'react'
import { parseStoredProjectId, parseStoredProjectsMode } from '../utils/ui'
import type { DraftProjectRule } from '../components/projects/ProjectsCreateForm'

export function useProjectState() {
  const [projectName, setProjectName] = React.useState('')
  const [projectDescription, setProjectDescription] = React.useState('')
  const [projectCustomStatusesText, setProjectCustomStatusesText] = React.useState('')
  const [projectExternalRefsText, setProjectExternalRefsText] = React.useState('')
  const [projectAttachmentRefsText, setProjectAttachmentRefsText] = React.useState('')
  const [projectDescriptionView, setProjectDescriptionView] = React.useState<'write' | 'preview'>('write')
  const [showProjectCreateForm, setShowProjectCreateForm] = React.useState(false)
  const [showProjectEditForm, setShowProjectEditForm] = React.useState(false)
  const [editProjectName, setEditProjectName] = React.useState('')
  const [editProjectDescription, setEditProjectDescription] = React.useState('')
  const [editProjectCustomStatusesText, setEditProjectCustomStatusesText] = React.useState('')
  const [editProjectExternalRefsText, setEditProjectExternalRefsText] = React.useState('')
  const [editProjectAttachmentRefsText, setEditProjectAttachmentRefsText] = React.useState('')
  const [createProjectMemberIds, setCreateProjectMemberIds] = React.useState<string[]>([])
  const [editProjectMemberIds, setEditProjectMemberIds] = React.useState<string[]>([])
  const [editProjectDescriptionView, setEditProjectDescriptionView] = React.useState<'write' | 'preview'>('write')
  const [selectedProjectRuleId, setSelectedProjectRuleId] = React.useState<string | null>(null)
  const [projectRuleTitle, setProjectRuleTitle] = React.useState('')
  const [projectRuleBody, setProjectRuleBody] = React.useState('')
  const [projectRuleView, setProjectRuleView] = React.useState<'write' | 'preview'>('write')
  const [draftProjectRules, setDraftProjectRules] = React.useState<DraftProjectRule[]>([])
  const [selectedDraftProjectRuleId, setSelectedDraftProjectRuleId] = React.useState<string | null>(null)
  const [draftProjectRuleTitle, setDraftProjectRuleTitle] = React.useState('')
  const [draftProjectRuleBody, setDraftProjectRuleBody] = React.useState('')
  const [draftProjectRuleView, setDraftProjectRuleView] = React.useState<'write' | 'preview'>('write')
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

  return {
    projectName,
    setProjectName,
    projectDescription,
    setProjectDescription,
    projectCustomStatusesText,
    setProjectCustomStatusesText,
    projectExternalRefsText,
    setProjectExternalRefsText,
    projectAttachmentRefsText,
    setProjectAttachmentRefsText,
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
    createProjectMemberIds,
    setCreateProjectMemberIds,
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
