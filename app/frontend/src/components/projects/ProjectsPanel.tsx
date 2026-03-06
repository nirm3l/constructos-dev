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
    <section className="card" data-tour-id="projects-panel">
      <ProjectsHeader
        totalProjects={state.bootstrap.data.projects.length}
        showProjectCreateForm={state.showProjectCreateForm}
        showProjectEditForm={state.showProjectEditForm}
        projectIsDirty={Boolean(state.projectIsDirty || state.projectEditorHasUnsavedChanges)}
        confirmDiscardChanges={state.confirmDiscardChanges}
        requestDiscardChanges={state.requestDiscardChanges}
        setShowProjectEditForm={state.setShowProjectEditForm}
        setShowProjectCreateForm={state.setShowProjectCreateForm}
      />
      {state.showProjectCreateForm && (
        <ProjectsCreateForm
          projectName={state.projectName}
          setProjectName={state.setProjectName}
          projectTemplateKey={state.projectTemplateKey}
          setProjectTemplateKey={state.setProjectTemplateKey}
          projectTemplates={state.projectTemplates.data?.items ?? []}
          projectTemplatesLoading={Boolean(state.projectTemplates.isLoading || state.projectTemplates.isFetching)}
          previewProjectFromTemplateMutation={state.previewProjectFromTemplateMutation}
          createProjectMutation={state.createProjectMutation}
          projectCustomStatusesText={state.projectCustomStatusesText}
          setProjectCustomStatusesText={state.setProjectCustomStatusesText}
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
          projectEmbeddingEnabled={state.projectEmbeddingEnabled}
          setProjectEmbeddingEnabled={state.setProjectEmbeddingEnabled}
          projectEmbeddingModel={state.projectEmbeddingModel}
          setProjectEmbeddingModel={state.setProjectEmbeddingModel}
          projectContextPackEvidenceTopKText={state.projectContextPackEvidenceTopKText}
          setProjectContextPackEvidenceTopKText={state.setProjectContextPackEvidenceTopKText}
          projectChatIndexMode={state.projectChatIndexMode}
          setProjectChatIndexMode={state.setProjectChatIndexMode}
          projectChatAttachmentIngestionMode={state.projectChatAttachmentIngestionMode}
          setProjectChatAttachmentIngestionMode={state.setProjectChatAttachmentIngestionMode}
          projectEventStormingEnabled={state.projectEventStormingEnabled}
          setProjectEventStormingEnabled={state.setProjectEventStormingEnabled}
          embeddingAllowedModels={state.embeddingAllowedModels}
          embeddingDefaultModel={state.embeddingDefaultModel}
          vectorStoreEnabled={state.vectorStoreEnabled}
          contextPackEvidenceTopKDefault={state.contextPackEvidenceTopKDefault}
          projectTemplateParametersText={state.projectTemplateParametersText}
          setProjectTemplateParametersText={state.setProjectTemplateParametersText}
          workspaceUsers={state.workspaceUsers}
          createProjectMemberIds={state.createProjectMemberIds}
          createProjectWorkspaceSkillIds={state.createProjectWorkspaceSkillIds}
          setCreateProjectWorkspaceSkillIds={state.setCreateProjectWorkspaceSkillIds}
          workspaceSkills={state.workspaceSkills.data?.items ?? []}
          workspaceSkillsLoading={Boolean(state.workspaceSkills.isLoading || state.workspaceSkills.isFetching)}
          toggleCreateProjectWorkspaceSkill={state.toggleCreateProjectWorkspaceSkill}
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
        onRemoveProject={(projectId) => {
          state.deleteProjectMutation.mutate(projectId)
        }}
        renderInlineEditor={(project) => (
          <ProjectsInlineEditor
            project={project}
            selectedProject={state.selectedProject}
            projectIsDirty={state.projectIsDirty}
            editProjectName={state.editProjectName}
            setEditProjectName={state.setEditProjectName}
            editProjectCustomStatusesText={state.editProjectCustomStatusesText}
            setEditProjectCustomStatusesText={state.setEditProjectCustomStatusesText}
            saveProjectMutation={state.saveProjectMutation}
            deleteProjectMutation={state.deleteProjectMutation}
            editProjectDescriptionView={state.editProjectDescriptionView}
            setEditProjectDescriptionView={state.setEditProjectDescriptionView}
            editProjectDescriptionRef={state.editProjectDescriptionRef}
            editProjectDescription={state.editProjectDescription}
            setEditProjectDescription={state.setEditProjectDescription}
            projectRules={state.projectRules}
            projectSkills={state.projectSkills}
            projectGraphOverview={state.projectGraphOverview}
            projectGraphContextPack={state.projectGraphContextPack}
            projectEventStormingOverview={state.projectEventStormingOverview}
            workspaceSkills={state.workspaceSkills}
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
            importProjectSkillMutation={state.importProjectSkillMutation}
            importProjectSkillFileMutation={state.importProjectSkillFileMutation}
            patchProjectSkillMutation={state.patchProjectSkillMutation}
            applyProjectSkillMutation={state.applyProjectSkillMutation}
            deleteProjectSkillMutation={state.deleteProjectSkillMutation}
            attachWorkspaceSkillToProjectMutation={state.attachWorkspaceSkillToProjectMutation}
            toUserDateTime={state.toUserDateTime}
            userTimezone={state.userTimezone}
            editProjectExternalRefsText={state.editProjectExternalRefsText}
            setEditProjectExternalRefsText={state.setEditProjectExternalRefsText}
            editProjectFileInputRef={state.editProjectFileInputRef}
            uploadAttachmentRef={state.uploadAttachmentRef}
            setUiError={state.setUiError}
            editProjectAttachmentRefsText={state.editProjectAttachmentRefsText}
            setEditProjectAttachmentRefsText={state.setEditProjectAttachmentRefsText}
            editProjectEmbeddingEnabled={state.editProjectEmbeddingEnabled}
            setEditProjectEmbeddingEnabled={state.setEditProjectEmbeddingEnabled}
            editProjectEmbeddingModel={state.editProjectEmbeddingModel}
            setEditProjectEmbeddingModel={state.setEditProjectEmbeddingModel}
            editProjectContextPackEvidenceTopKText={state.editProjectContextPackEvidenceTopKText}
            setEditProjectContextPackEvidenceTopKText={state.setEditProjectContextPackEvidenceTopKText}
            editProjectChatIndexMode={state.editProjectChatIndexMode}
            setEditProjectChatIndexMode={state.setEditProjectChatIndexMode}
            editProjectChatAttachmentIngestionMode={state.editProjectChatAttachmentIngestionMode}
            setEditProjectChatAttachmentIngestionMode={state.setEditProjectChatAttachmentIngestionMode}
            editProjectEventStormingEnabled={state.editProjectEventStormingEnabled}
            setEditProjectEventStormingEnabled={state.setEditProjectEventStormingEnabled}
            embeddingAllowedModels={state.embeddingAllowedModels}
            embeddingDefaultModel={state.embeddingDefaultModel}
            vectorStoreEnabled={state.vectorStoreEnabled}
            contextPackEvidenceTopKDefault={state.contextPackEvidenceTopKDefault}
            contextLimitTokensDefault={state.contextLimitTokensDefault}
            codexChatProjectId={state.codexChatProjectId}
            codexChatTurns={state.codexChatTurns}
            codexChatUsage={state.codexChatUsage}
            codexChatResumeState={state.codexChatResumeState}
            workspaceId={state.workspaceId}
            userId={state.userId}
            workspaceUsers={state.workspaceUsers}
            editProjectMemberIds={state.editProjectMemberIds}
            toggleEditProjectMember={state.toggleEditProjectMember}
            selectedProjectCreator={state.selectedProjectCreator}
            selectedProjectTimeMeta={state.selectedProjectTimeMeta}
            onUnsavedChange={state.setProjectEditorHasUnsavedChanges}
          />
        )}
      />
    </section>
  )
}
