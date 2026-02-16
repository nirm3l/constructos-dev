import React from 'react'
import { ProjectsCreateForm } from './ProjectsCreateForm'
import { ProjectsHeader } from './ProjectsHeader'
import { ProjectsInlineEditor } from './ProjectsInlineEditor'
import { ProjectsList } from './ProjectsList'

type ProjectsPanelProps = {
  state: any
}

export function ProjectsPanel({ state }: ProjectsPanelProps) {
  return (
    <section className="card">
      <ProjectsHeader
        totalProjects={state.bootstrap.data.projects.length}
        showProjectCreateForm={state.showProjectCreateForm}
        showProjectEditForm={state.showProjectEditForm}
        projectIsDirty={state.projectIsDirty}
        confirmDiscardChanges={state.confirmDiscardChanges}
        setShowProjectEditForm={state.setShowProjectEditForm}
        setShowProjectCreateForm={state.setShowProjectCreateForm}
      />
      {state.showProjectCreateForm && (
        <ProjectsCreateForm
          projectName={state.projectName}
          setProjectName={state.setProjectName}
          createProjectMutation={state.createProjectMutation}
          projectDescriptionView={state.projectDescriptionView}
          setProjectDescriptionView={state.setProjectDescriptionView}
          projectDescriptionRef={state.projectDescriptionRef}
          projectDescription={state.projectDescription}
          setProjectDescription={state.setProjectDescription}
          draftProjectRules={state.draftProjectRules}
          setDraftProjectRules={state.setDraftProjectRules}
          selectedDraftProjectRuleId={state.selectedDraftProjectRuleId}
          setSelectedDraftProjectRuleId={state.setSelectedDraftProjectRuleId}
          draftProjectRuleTitle={state.draftProjectRuleTitle}
          setDraftProjectRuleTitle={state.setDraftProjectRuleTitle}
          draftProjectRuleBody={state.draftProjectRuleBody}
          setDraftProjectRuleBody={state.setDraftProjectRuleBody}
          draftProjectRuleView={state.draftProjectRuleView}
          setDraftProjectRuleView={state.setDraftProjectRuleView}
          projectExternalRefsText={state.projectExternalRefsText}
          setProjectExternalRefsText={state.setProjectExternalRefsText}
          workspaceUsers={state.workspaceUsers}
          createProjectMemberIds={state.createProjectMemberIds}
          toggleCreateProjectMember={state.toggleCreateProjectMember}
        />
      )}
      <ProjectsList
        projects={state.bootstrap.data.projects}
        selectedProjectId={state.selectedProjectId}
        showProjectEditForm={state.showProjectEditForm}
        selectedProject={state.selectedProject}
        projectTaskCountQueries={state.projectTaskCountQueries}
        projectNoteCountQueries={state.projectNoteCountQueries}
        projectRuleCountQueries={state.projectRuleCountQueries}
        projectMemberCounts={state.projectMemberCounts}
        workspaceId={state.workspaceId}
        userId={state.userId}
        toggleProjectEditor={state.toggleProjectEditor}
        onCopyShareLink={(projectId) => state.copyShareLink({ tab: 'projects', projectId })}
        renderInlineEditor={(project) => (
          <ProjectsInlineEditor
            project={project}
            selectedProject={state.selectedProject}
            projectIsDirty={state.projectIsDirty}
            editProjectName={state.editProjectName}
            setEditProjectName={state.setEditProjectName}
            saveProjectMutation={state.saveProjectMutation}
            deleteProjectMutation={state.deleteProjectMutation}
            editProjectDescriptionView={state.editProjectDescriptionView}
            setEditProjectDescriptionView={state.setEditProjectDescriptionView}
            editProjectDescriptionRef={state.editProjectDescriptionRef}
            editProjectDescription={state.editProjectDescription}
            setEditProjectDescription={state.setEditProjectDescription}
            projectRules={state.projectRules}
            selectedProjectRuleId={state.selectedProjectRuleId}
            setSelectedProjectRuleId={state.setSelectedProjectRuleId}
            projectRuleTitle={state.projectRuleTitle}
            setProjectRuleTitle={state.setProjectRuleTitle}
            projectRuleBody={state.projectRuleBody}
            setProjectRuleBody={state.setProjectRuleBody}
            projectRuleView={state.projectRuleView}
            setProjectRuleView={state.setProjectRuleView}
            createProjectRuleMutation={state.createProjectRuleMutation}
            patchProjectRuleMutation={state.patchProjectRuleMutation}
            deleteProjectRuleMutation={state.deleteProjectRuleMutation}
            toUserDateTime={state.toUserDateTime}
            userTimezone={state.userTimezone}
            editProjectExternalRefsText={state.editProjectExternalRefsText}
            setEditProjectExternalRefsText={state.setEditProjectExternalRefsText}
            editProjectFileInputRef={state.editProjectFileInputRef}
            uploadAttachmentRef={state.uploadAttachmentRef}
            setUiError={state.setUiError}
            editProjectAttachmentRefsText={state.editProjectAttachmentRefsText}
            setEditProjectAttachmentRefsText={state.setEditProjectAttachmentRefsText}
            workspaceId={state.workspaceId}
            userId={state.userId}
            workspaceUsers={state.workspaceUsers}
            editProjectMemberIds={state.editProjectMemberIds}
            toggleEditProjectMember={state.toggleEditProjectMember}
            selectedProjectCreator={state.selectedProjectCreator}
            selectedProjectTimeMeta={state.selectedProjectTimeMeta}
          />
        )}
      />
    </section>
  )
}
