import React from 'react'
import { ProjectKnowledgeGraphPage } from '../projects/ProjectKnowledgeGraphPage'
import { ProjectsPanel } from '../projects/ProjectsPanel'
import { SpecificationsPanel } from '../specifications/SpecificationsPanel'
import { NotesPanel } from '../notes/NotesPanel'
import { QuickAddDrawer } from '../tasks/QuickAddDrawer'
import { TasksPanel } from '../tasks/TasksPanel'
import { AdminPanel, GlobalSearchResultsPanel, ProfilePanel, SearchPanel } from '../auxPanels'

export function AppPrimaryPanels({ state }: { state: any }) {
  return (
    <>
      <QuickAddDrawer
        state={{
          showQuickAdd: state.showQuickAdd,
          setShowQuickAdd: state.setShowQuickAdd,
          taskTitle: state.taskTitle,
          setTaskTitle: state.setTaskTitle,
          quickProjectId: state.quickProjectId,
          setQuickProjectId: state.setQuickProjectId,
          quickTaskGroupId: state.quickTaskGroupId,
          setQuickTaskGroupId: state.setQuickTaskGroupId,
          quickTaskAssigneeId: state.quickTaskAssigneeId,
          setQuickTaskAssigneeId: state.setQuickTaskAssigneeId,
          createTaskMutation: state.createTaskMutation,
          userId: state.userId,
          workspaceId: state.workspaceId,
          bootstrap: state.bootstrap,
          quickDueDate: state.quickDueDate,
          setQuickDueDate: state.setQuickDueDate,
          quickDueDateFocused: state.quickDueDateFocused,
          setQuickDueDateFocused: state.setQuickDueDateFocused,
          quickTaskPriority: state.quickTaskPriority,
          setQuickTaskPriority: state.setQuickTaskPriority,
          quickTaskType: state.quickTaskType,
          setQuickTaskType: state.setQuickTaskType,
          quickTaskScheduledInstruction: state.quickTaskScheduledInstruction,
          setQuickTaskScheduledInstruction: state.setQuickTaskScheduledInstruction,
          quickTaskScheduleTimezone: state.quickTaskScheduleTimezone,
          setQuickTaskScheduleTimezone: state.setQuickTaskScheduleTimezone,
          quickTaskCreateAnother: state.quickTaskCreateAnother,
          setQuickTaskCreateAnother: state.setQuickTaskCreateAnother,
          quickTaskTags: state.quickTaskTags,
          setQuickTaskTags: state.setQuickTaskTags,
          tagHue: state.tagHue,
          setShowQuickTaskTagPicker: state.setShowQuickTaskTagPicker,
          showQuickTaskTagPicker: state.showQuickTaskTagPicker,
          quickTaskTagQuery: state.quickTaskTagQuery,
          setQuickTaskTagQuery: state.setQuickTaskTagQuery,
          filteredQuickTaskTags: state.filteredQuickTaskTags,
          quickTaskTagsLower: state.quickTaskTagsLower,
          toggleQuickTaskTag: state.toggleQuickTaskTag,
          canCreateQuickTaskTag: state.canCreateQuickTaskTag,
        }}
      />

      {(state.tab === 'tasks' || state.tab === 'inbox') && (
        <TasksPanel
          panelTitle={state.tab === 'inbox' ? 'Inbox' : 'Tasks'}
          allowBoardView={state.tab !== 'inbox'}
          projectsMode={state.tab === 'inbox' ? 'list' : state.projectsMode}
          setProjectsMode={state.tab === 'inbox' ? (() => undefined) : state.setProjectsMode}
          taskGroups={state.taskGroups.data?.items ?? []}
          taskGroupFilterId={state.taskGroupFilterId}
          setTaskGroupFilterId={state.setTaskGroupFilterId}
          createTaskGroupMutation={state.createTaskGroupMutation}
          patchTaskGroupMutation={state.patchTaskGroupMutation}
          deleteTaskGroupMutation={state.deleteTaskGroupMutation}
          reorderTaskGroupsMutation={state.reorderTaskGroupsMutation}
          taskTagSuggestions={state.taskTagSuggestions}
          searchTags={state.searchTags}
          toggleSearchTag={state.toggleSearchTag}
          clearSearchTags={state.clearSearchTags}
          getTagUsage={state.getTagUsage}
          boardData={state.tab === 'inbox' ? undefined : state.board.data}
          onOpenTaskEditor={state.openTaskEditor}
          onOpenSpecification={state.openSpecification}
          specificationNames={state.specificationNameMap}
          onMoveTaskStatus={state.moveTaskToStatus}
          tasks={state.tasks.data?.items ?? []}
          onRestoreTask={(taskId) => state.restoreTaskMutation.mutate(taskId)}
          onReopenTask={(taskId) => state.reopenTaskMutation.mutate(taskId)}
          onCompleteTask={(taskId) => state.completeTaskMutation.mutate(taskId)}
          onNewTask={(taskType) => {
            state.setQuickProjectId(state.selectedProjectId || state.bootstrap.data?.projects?.[0]?.id || '')
            state.setQuickTaskGroupId('')
            state.setQuickTaskAssigneeId('')
            state.setQuickTaskExternalRefsText('')
            state.setQuickTaskAttachmentRefsText('')
            state.setQuickTaskType(taskType === 'scheduled_instruction' ? 'scheduled_instruction' : 'manual')
            state.setShowQuickAdd(true)
          }}
        />
      )}

      {state.tab === 'projects' && (
        <ProjectsPanel
          state={{
            bootstrap: state.bootstrap,
            showProjectCreateForm: state.showProjectCreateForm,
            showProjectEditForm: state.showProjectEditForm,
            projectIsDirty: state.projectIsDirty,
            confirmDiscardChanges: state.confirmDiscardChanges,
            setShowProjectEditForm: state.setShowProjectEditForm,
            setShowProjectCreateForm: state.setShowProjectCreateForm,
            projectName: state.projectName,
            setProjectName: state.setProjectName,
            projectTemplateKey: state.projectTemplateKey,
            setProjectTemplateKey: state.setProjectTemplateKey,
            previewProjectFromTemplateMutation: state.previewProjectFromTemplateMutation,
            createProjectMutation: state.createProjectMutation,
            projectCustomStatusesText: state.projectCustomStatusesText,
            setProjectCustomStatusesText: state.setProjectCustomStatusesText,
            projectDescriptionView: state.projectDescriptionView,
            setProjectDescriptionView: state.setProjectDescriptionView,
            projectDescriptionRef: state.projectDescriptionRef,
            projectDescription: state.projectDescription,
            setProjectDescription: state.setProjectDescription,
            draftProjectRules: state.draftProjectRules,
            setDraftProjectRules: state.setDraftProjectRules,
            selectedDraftProjectRuleId: state.selectedDraftProjectRuleId,
            setSelectedDraftProjectRuleId: state.setSelectedDraftProjectRuleId,
            draftProjectRuleTitle: state.draftProjectRuleTitle,
            setDraftProjectRuleTitle: state.setDraftProjectRuleTitle,
            draftProjectRuleBody: state.draftProjectRuleBody,
            setDraftProjectRuleBody: state.setDraftProjectRuleBody,
            draftProjectRuleView: state.draftProjectRuleView,
            setDraftProjectRuleView: state.setDraftProjectRuleView,
            projectExternalRefsText: state.projectExternalRefsText,
            setProjectExternalRefsText: state.setProjectExternalRefsText,
            projectEmbeddingEnabled: state.projectEmbeddingEnabled,
            setProjectEmbeddingEnabled: state.setProjectEmbeddingEnabled,
            projectEmbeddingModel: state.projectEmbeddingModel,
            setProjectEmbeddingModel: state.setProjectEmbeddingModel,
            embeddingAllowedModels: state.embeddingAllowedModels,
            embeddingDefaultModel: state.embeddingDefaultModel,
            vectorStoreEnabled: state.vectorStoreEnabled,
            contextPackEvidenceTopKDefault: state.contextPackEvidenceTopKDefault,
            contextLimitTokensDefault: state.contextLimitTokensDefault,
            projectTemplateParametersText: state.projectTemplateParametersText,
            setProjectTemplateParametersText: state.setProjectTemplateParametersText,
            workspaceUsers: state.workspaceUsers,
            createProjectMemberIds: state.createProjectMemberIds,
            toggleCreateProjectMember: state.toggleCreateProjectMember,
            selectedProjectId: state.selectedProjectId,
            selectedProject: state.selectedProject,
            projectTaskCountQueries: state.projectTaskCountQueries,
            projectNoteCountQueries: state.projectNoteCountQueries,
            projectRuleCountQueries: state.projectRuleCountQueries,
            projectMemberCounts: state.projectMemberCounts,
            workspaceId: state.workspaceId,
            userId: state.userId,
            toggleProjectEditor: state.toggleProjectEditor,
            copyShareLink: state.copyShareLink,
            editProjectName: state.editProjectName,
            setEditProjectName: state.setEditProjectName,
            editProjectCustomStatusesText: state.editProjectCustomStatusesText,
            setEditProjectCustomStatusesText: state.setEditProjectCustomStatusesText,
            saveProjectMutation: state.saveProjectMutation,
            deleteProjectMutation: state.deleteProjectMutation,
            editProjectDescriptionView: state.editProjectDescriptionView,
            setEditProjectDescriptionView: state.setEditProjectDescriptionView,
            editProjectDescriptionRef: state.editProjectDescriptionRef,
            editProjectDescription: state.editProjectDescription,
            setEditProjectDescription: state.setEditProjectDescription,
            projectRules: state.projectRules,
            projectSkills: state.projectSkills,
            workspaceSkills: state.workspaceSkills,
            projectTemplates: state.projectTemplates,
            projectGraphOverview: state.projectGraphOverview,
            projectGraphContextPack: state.projectGraphContextPack,
            projectGraphSubgraph: state.projectGraphSubgraph,
            selectedProjectRuleId: state.selectedProjectRuleId,
            setSelectedProjectRuleId: state.setSelectedProjectRuleId,
            projectRuleTitle: state.projectRuleTitle,
            setProjectRuleTitle: state.setProjectRuleTitle,
            projectRuleBody: state.projectRuleBody,
            setProjectRuleBody: state.setProjectRuleBody,
            projectRuleView: state.projectRuleView,
            setProjectRuleView: state.setProjectRuleView,
            createProjectRuleMutation: state.createProjectRuleMutation,
            patchProjectRuleMutation: state.patchProjectRuleMutation,
            deleteProjectRuleMutation: state.deleteProjectRuleMutation,
            importProjectSkillMutation: state.importProjectSkillMutation,
            importProjectSkillFileMutation: state.importProjectSkillFileMutation,
            patchProjectSkillMutation: state.patchProjectSkillMutation,
            applyProjectSkillMutation: state.applyProjectSkillMutation,
            deleteProjectSkillMutation: state.deleteProjectSkillMutation,
            attachWorkspaceSkillToProjectMutation: state.attachWorkspaceSkillToProjectMutation,
            canManageUsers: state.canManageUsers,
            toUserDateTime: state.toUserDateTime,
            userTimezone: state.userTimezone,
            editProjectExternalRefsText: state.editProjectExternalRefsText,
            setEditProjectExternalRefsText: state.setEditProjectExternalRefsText,
            editProjectFileInputRef: state.editProjectFileInputRef,
            uploadAttachmentRef: state.uploadAttachmentRef,
            setUiError: state.setUiError,
            editProjectAttachmentRefsText: state.editProjectAttachmentRefsText,
            setEditProjectAttachmentRefsText: state.setEditProjectAttachmentRefsText,
            createTaskFromGraphSummary: state.createTaskFromGraphSummary,
            createNoteFromGraphSummary: state.createNoteFromGraphSummary,
            linkFocusTaskToSpecification: state.linkFocusTaskToSpecification,
            editProjectEmbeddingEnabled: state.editProjectEmbeddingEnabled,
            setEditProjectEmbeddingEnabled: state.setEditProjectEmbeddingEnabled,
            editProjectEmbeddingModel: state.editProjectEmbeddingModel,
            setEditProjectEmbeddingModel: state.setEditProjectEmbeddingModel,
            editProjectContextPackEvidenceTopKText: state.editProjectContextPackEvidenceTopKText,
            setEditProjectContextPackEvidenceTopKText: state.setEditProjectContextPackEvidenceTopKText,
            editProjectChatIndexMode: state.editProjectChatIndexMode,
            setEditProjectChatIndexMode: state.setEditProjectChatIndexMode,
            editProjectChatAttachmentIngestionMode: state.editProjectChatAttachmentIngestionMode,
            setEditProjectChatAttachmentIngestionMode: state.setEditProjectChatAttachmentIngestionMode,
            editProjectMemberIds: state.editProjectMemberIds,
            toggleEditProjectMember: state.toggleEditProjectMember,
            selectedProjectCreator: state.selectedProjectCreator,
            selectedProjectTimeMeta: state.selectedProjectTimeMeta,
            codexChatProjectId: state.codexChatProjectId,
            codexChatTurns: state.codexChatTurns,
          }}
        />
      )}

      {state.tab === 'knowledge-graph' && (
        <ProjectKnowledgeGraphPage
          userId={state.userId}
          selectedProjectId={state.selectedProjectId}
          selectedProjectName={state.selectedProject?.name || ''}
          selectedProjectChatIndexMode={state.selectedProject?.chat_index_mode}
          selectedProjectChatAttachmentIngestionMode={state.selectedProject?.chat_attachment_ingestion_mode}
          overviewQuery={state.projectGraphOverview}
          contextPackQuery={state.projectGraphContextPack}
          subgraphQuery={state.projectGraphSubgraph}
          onCreateTaskFromSummary={state.createTaskFromGraphSummary}
          onCreateNoteFromSummary={state.createNoteFromGraphSummary}
          onLinkFocusTaskToSpecification={state.linkFocusTaskToSpecification}
        />
      )}

      {state.tab === 'specifications' && (
        <SpecificationsPanel
          state={{
            specifications: state.specifications,
            specTasks: state.specTasks,
            specNotes: state.specNotes,
            specificationStatus: state.specificationStatus,
            setSpecificationStatus: state.setSpecificationStatus,
            taskTagSuggestions: state.taskTagSuggestions,
            specificationTags: state.specificationTags,
            toggleSpecificationFilterTag: state.toggleSpecificationFilterTag,
            clearSpecificationFilterTags: state.clearSpecificationFilterTags,
            getTagUsage: state.getTagUsage,
            createSpecificationMutation: state.createSpecificationMutation,
            selectedSpecificationId: state.selectedSpecificationId,
            toggleSpecificationEditor: state.toggleSpecificationEditor,
            editSpecificationTitle: state.editSpecificationTitle,
            setEditSpecificationTitle: state.setEditSpecificationTitle,
            editSpecificationBody: state.editSpecificationBody,
            setEditSpecificationBody: state.setEditSpecificationBody,
            editSpecificationStatus: state.editSpecificationStatus,
            setEditSpecificationStatus: state.setEditSpecificationStatus,
            editSpecificationTags: state.editSpecificationTags,
            setEditSpecificationTags: state.setEditSpecificationTags,
            editSpecificationExternalRefsText: state.editSpecificationExternalRefsText,
            setEditSpecificationExternalRefsText: state.setEditSpecificationExternalRefsText,
            editSpecificationAttachmentRefsText: state.editSpecificationAttachmentRefsText,
            setEditSpecificationAttachmentRefsText: state.setEditSpecificationAttachmentRefsText,
            specificationEditorView: state.specificationEditorView,
            setSpecificationEditorView: state.setSpecificationEditorView,
            specificationIsDirty: state.specificationIsDirty,
            saveSpecificationMutation: state.saveSpecificationMutation,
            archiveSpecificationMutation: state.archiveSpecificationMutation,
            restoreSpecificationMutation: state.restoreSpecificationMutation,
            deleteSpecificationMutation: state.deleteSpecificationMutation,
            createSpecificationTaskMutation: state.createSpecificationTaskMutation,
            bulkCreateSpecificationTasksMutation: state.bulkCreateSpecificationTasksMutation,
            createSpecificationNoteMutation: state.createSpecificationNoteMutation,
            linkTaskToSpecificationMutation: state.linkTaskToSpecificationMutation,
            unlinkTaskFromSpecificationMutation: state.unlinkTaskFromSpecificationMutation,
            linkNoteToSpecificationMutation: state.linkNoteToSpecificationMutation,
            unlinkNoteFromSpecificationMutation: state.unlinkNoteFromSpecificationMutation,
            parseExternalRefsText: state.parseExternalRefsText,
            removeExternalRefByIndex: state.removeExternalRefByIndex,
            externalRefsToText: state.externalRefsToText,
            parseAttachmentRefsText: state.parseAttachmentRefsText,
            removeAttachmentByPath: state.removeAttachmentByPath,
            attachmentRefsToText: state.attachmentRefsToText,
            selectedProjectId: state.selectedProjectId,
            workspaceId: state.workspaceId,
            userId: state.userId,
            tagHue: state.tagHue,
            openTask: state.openTask,
            openNote: state.openNote,
            copyShareLink: state.copyShareLink,
            specFileInputRef: state.specFileInputRef,
            uploadAttachmentRef: state.uploadAttachmentRef,
            toErrorMessage: state.toErrorMessage,
            setUiError: state.setUiError,
          }}
        />
      )}

      {state.tab === 'notes' && (
        <NotesPanel
          state={{
            notes: state.notes,
            createNoteMutation: state.createNoteMutation,
            createNoteGroupMutation: state.createNoteGroupMutation,
            patchNoteGroupMutation: state.patchNoteGroupMutation,
            deleteNoteGroupMutation: state.deleteNoteGroupMutation,
            reorderNoteGroupsMutation: state.reorderNoteGroupsMutation,
            moveNoteToGroupMutation: state.moveNoteToGroupMutation,
            noteGroups: state.noteGroups,
            noteArchived: state.noteArchived,
            setNoteArchived: state.setNoteArchived,
            noteGroupFilterId: state.noteGroupFilterId,
            setNoteGroupFilterId: state.setNoteGroupFilterId,
            noteTagSuggestions: state.noteTagSuggestions,
            noteTags: state.noteTags,
            toggleNoteFilterTag: state.toggleNoteFilterTag,
            clearNoteFilterTags: state.clearNoteFilterTags,
            getTagUsage: state.getTagUsage,
            selectedNoteId: state.selectedNoteId,
            selectedNote: state.selectedNote,
            editNoteTitle: state.editNoteTitle,
            editNoteGroupId: state.editNoteGroupId,
            toggleNoteEditor: state.toggleNoteEditor,
            setEditNoteGroupId: state.setEditNoteGroupId,
            setShowTagPicker: state.setShowTagPicker,
            setTagPickerQuery: state.setTagPickerQuery,
            tagHue: state.tagHue,
            workspaceId: state.workspaceId,
            userId: state.userId,
            noteIsDirty: state.noteIsDirty,
            saveNoteMutation: state.saveNoteMutation,
            unpinNoteMutation: state.unpinNoteMutation,
            pinNoteMutation: state.pinNoteMutation,
            restoreNoteMutation: state.restoreNoteMutation,
            archiveNoteMutation: state.archiveNoteMutation,
            deleteNoteMutation: state.deleteNoteMutation,
            noteEditorView: state.noteEditorView,
            setNoteEditorView: state.setNoteEditorView,
            editNoteBody: state.editNoteBody,
            setEditNoteBody: state.setEditNoteBody,
            currentNoteTags: state.currentNoteTags,
            editNoteExternalRefsText: state.editNoteExternalRefsText,
            setEditNoteExternalRefsText: state.setEditNoteExternalRefsText,
            parseExternalRefsText: state.parseExternalRefsText,
            removeExternalRefByIndex: state.removeExternalRefByIndex,
            externalRefsToText: state.externalRefsToText,
            noteFileInputRef: state.noteFileInputRef,
            setEditNoteAttachmentRefsText: state.setEditNoteAttachmentRefsText,
            attachmentRefsToText: state.attachmentRefsToText,
            parseAttachmentRefsText: state.parseAttachmentRefsText,
            toErrorMessage: state.toErrorMessage,
            setUiError: state.setUiError,
            editNoteAttachmentRefsText: state.editNoteAttachmentRefsText,
            removeAttachmentByPath: state.removeAttachmentByPath,
            selectedNoteCreator: state.selectedNoteCreator,
            selectedNoteTimeMeta: state.selectedNoteTimeMeta,
            toUserDateTime: state.toUserDateTime,
            userTimezone: state.userTimezone,
            showTagPicker: state.showTagPicker,
            tagPickerQuery: state.tagPickerQuery,
            filteredNoteTags: state.filteredNoteTags,
            currentNoteTagsLower: state.currentNoteTagsLower,
            toggleNoteTag: state.toggleNoteTag,
            canCreateTag: state.canCreateTag,
            addNoteTag: state.addNoteTag,
            setEditNoteTitle: state.setEditNoteTitle,
            openSpecification: state.openSpecification,
            specificationNameMap: state.specificationNameMap,
            openTask: state.openTask,
            taskNameMap: state.taskNameMap,
          }}
          actions={{
            copyShareLink: state.copyShareLink,
            uploadAttachmentRef: state.uploadAttachmentRef,
          }}
        />
      )}

      {state.tab === 'search' && (
        <SearchPanel
          searchQ={state.searchQ}
          setSearchQ={state.setSearchQ}
          searchStatus={state.searchStatus}
          setSearchStatus={state.setSearchStatus}
          searchSpecificationStatus={state.searchSpecificationStatus}
          setSearchSpecificationStatus={state.setSearchSpecificationStatus}
          searchPriority={state.searchPriority}
          setSearchPriority={state.setSearchPriority}
          searchArchived={state.searchArchived}
          setSearchArchived={state.setSearchArchived}
          taskTagSuggestions={state.taskTagSuggestions}
          searchTags={state.searchTags}
          toggleSearchTag={state.toggleSearchTag}
          clearSearchTags={state.clearSearchTags}
          getTagUsage={state.getTagUsage}
          onClose={() => state.setTab('tasks')}
        />
      )}

      {state.tab === 'profile' || state.tab === 'admin' ? (
        <div className="profile-stack">
          <ProfilePanel
            userName={state.bootstrap.data.current_user.full_name}
            theme={state.theme}
            speechLang={state.speechLang}
            frontendVersion={state.frontendVersion}
            backendVersion={state.backendVersion}
            backendBuild={state.backendBuild}
            deployedAtUtc={state.backendDeployedAtUtc}
            license={state.licenseStatus?.data?.license ?? null}
            licenseLoading={Boolean(state.licenseStatus?.isLoading)}
            licenseError={state.licenseStatus?.isError ? 'Unable to load license status.' : null}
            onLogout={state.logout}
            onChangeSpeechLang={state.setSpeechLang}
            onToggleTheme={() => {
              const next = state.theme === 'light' ? 'dark' : 'light'
              state.setTheme(next)
              state.themeMutation.mutate(next)
            }}
            changePassword={state.changeMyPassword}
            passwordChangePending={state.changeMyPasswordPending}
            submitFeedback={state.submitFeedback}
            feedbackSubmitting={state.submitFeedbackPending}
          />
          {state.canManageUsers && (
            <AdminPanel
              canManageUsers={state.canManageUsers}
              workspaceId={state.workspaceId}
              users={state.adminUsers}
              usersLoading={state.adminUsersLoading}
              usersError={state.adminUsersError}
              username={state.adminCreateUsername}
              setUsername={state.setAdminCreateUsername}
              fullName={state.adminCreateFullName}
              setFullName={state.setAdminCreateFullName}
              role={state.adminCreateRole}
              setRole={state.setAdminCreateRole}
              createPending={state.createAdminUserMutation.isPending}
              onCreate={state.onCreateAdminUser}
              lastTempPassword={state.adminLastTempPassword}
              onResetPassword={state.onResetAdminUserPassword}
              resetPendingUserId={state.resetAdminPasswordUserId}
              onUpdateRole={state.onUpdateAdminUserRole}
              updateRolePendingUserId={state.updateAdminRoleUserId}
              onDeactivateUser={state.onDeactivateAdminUser}
              deactivatePendingUserId={state.deactivateAdminUserId}
              workspaceSkills={state.workspaceSkills.data}
              workspaceSkillsLoading={Boolean(state.workspaceSkills.isLoading || state.workspaceSkills.isFetching)}
              importWorkspaceSkillPending={state.importWorkspaceSkillMutation.isPending}
              importWorkspaceSkillFilePending={state.importWorkspaceSkillFileMutation.isPending}
              patchWorkspaceSkillPending={state.patchWorkspaceSkillMutation.isPending}
              deleteWorkspaceSkillPending={state.deleteWorkspaceSkillMutation.isPending}
              onImportWorkspaceSkill={(payload) => state.importWorkspaceSkillMutation.mutateAsync(payload)}
              onImportWorkspaceSkillFile={(payload) => state.importWorkspaceSkillFileMutation.mutateAsync(payload)}
              onPatchWorkspaceSkill={(payload) => state.patchWorkspaceSkillMutation.mutateAsync(payload)}
              onDeleteWorkspaceSkill={(skillId) => state.deleteWorkspaceSkillMutation.mutateAsync({ skillId })}
            />
          )}
        </div>
      ) : state.tab === 'search' ? (
        <GlobalSearchResultsPanel
          tasks={state.searchTasksCombined ?? []}
          tasksTotal={state.searchTasksCombined?.length ?? 0}
          notes={state.searchNotesCombined ?? []}
          notesTotal={state.searchNotesCombined?.length ?? 0}
          specifications={state.searchSpecificationsCombined ?? []}
          specificationsTotal={state.searchSpecificationsCombined?.length ?? 0}
          searchQuery={state.searchQ}
          semanticMode={String(state.searchKnowledge?.data?.mode || 'empty')}
          semanticSearching={Boolean(state.searchKnowledge?.isFetching)}
          semanticTaskIds={state.semanticTaskIds ?? []}
          semanticNoteIds={state.semanticNoteIds ?? []}
          semanticSpecificationIds={state.semanticSpecificationIds ?? []}
          lexicalTaskIds={(state.tasks.data?.items ?? []).map((task: any) => String(task?.id || '')).filter(Boolean)}
          lexicalNoteIds={(state.searchNotes.data?.items ?? []).map((note: any) => String(note?.id || '')).filter(Boolean)}
          lexicalSpecificationIds={(state.searchSpecifications.data?.items ?? []).map((spec: any) => String(spec?.id || '')).filter(Boolean)}
          projectNames={state.projectNames}
          specificationNames={state.specificationNameMap}
          onOpenSpecification={state.openSpecification}
          onOpenTask={state.openTaskEditor}
          onTaskTagClick={(tag) => {
            state.toggleSearchTag(tag)
            state.setTab('tasks')
          }}
          onNoteTagClick={(tag) => {
            state.toggleNoteFilterTag(tag)
            state.setTab('notes')
          }}
          onSpecificationTagClick={(tag) => {
            state.toggleSpecificationFilterTag(tag)
            state.setTab('specifications')
          }}
          onRestoreTask={(taskId) => state.restoreTaskMutation.mutate(taskId)}
          onReopenTask={(taskId) => state.reopenTaskMutation.mutate(taskId)}
          onCompleteTask={(taskId) => state.completeTaskMutation.mutate(taskId)}
          onOpenNote={state.openNote}
        />
      ) : null}
    </>
  )
}
