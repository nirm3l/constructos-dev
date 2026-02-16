import React from 'react'
import { ProjectsPanel } from '../projects/ProjectsPanel'
import { SpecificationsPanel } from '../specifications/SpecificationsPanel'
import { NotesPanel } from '../notes/NotesPanel'
import { QuickAddDrawer } from '../tasks/QuickAddDrawer'
import { TasksPanel } from '../tasks/TasksPanel'
import { ProfilePanel, SearchPanel, TaskResultsPanel } from '../auxPanels'

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
          createTaskMutation: state.createTaskMutation,
          bootstrap: state.bootstrap,
          quickDueDate: state.quickDueDate,
          setQuickDueDate: state.setQuickDueDate,
          quickDueDateFocused: state.quickDueDateFocused,
          setQuickDueDateFocused: state.setQuickDueDateFocused,
          quickTaskTags: state.quickTaskTags,
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

      {state.tab === 'tasks' && (
        <TasksPanel
          projectsMode={state.projectsMode}
          setProjectsMode={state.setProjectsMode}
          taskTagSuggestions={state.taskTagSuggestions}
          searchTags={state.searchTags}
          toggleSearchTag={state.toggleSearchTag}
          boardData={state.board.data}
          onOpenTaskEditor={state.openTaskEditor}
          onMoveTaskStatus={state.moveTaskToStatus}
          tasks={state.tasks.data?.items ?? []}
          onRestoreTask={(taskId) => state.restoreTaskMutation.mutate(taskId)}
          onReopenTask={(taskId) => state.reopenTaskMutation.mutate(taskId)}
          onCompleteTask={(taskId) => state.completeTaskMutation.mutate(taskId)}
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
            createProjectMutation: state.createProjectMutation,
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
            saveProjectMutation: state.saveProjectMutation,
            deleteProjectMutation: state.deleteProjectMutation,
            editProjectDescriptionView: state.editProjectDescriptionView,
            setEditProjectDescriptionView: state.setEditProjectDescriptionView,
            editProjectDescriptionRef: state.editProjectDescriptionRef,
            editProjectDescription: state.editProjectDescription,
            setEditProjectDescription: state.setEditProjectDescription,
            projectRules: state.projectRules,
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
            toUserDateTime: state.toUserDateTime,
            userTimezone: state.userTimezone,
            editProjectExternalRefsText: state.editProjectExternalRefsText,
            setEditProjectExternalRefsText: state.setEditProjectExternalRefsText,
            editProjectFileInputRef: state.editProjectFileInputRef,
            uploadAttachmentRef: state.uploadAttachmentRef,
            setUiError: state.setUiError,
            editProjectAttachmentRefsText: state.editProjectAttachmentRefsText,
            setEditProjectAttachmentRefsText: state.setEditProjectAttachmentRefsText,
            editProjectMemberIds: state.editProjectMemberIds,
            toggleEditProjectMember: state.toggleEditProjectMember,
            selectedProjectCreator: state.selectedProjectCreator,
            selectedProjectTimeMeta: state.selectedProjectTimeMeta,
          }}
        />
      )}

      {state.tab === 'specifications' && (
        <SpecificationsPanel
          state={{
            specifications: state.specifications,
            specificationQ: state.specificationQ,
            setSpecificationQ: state.setSpecificationQ,
            specificationStatus: state.specificationStatus,
            setSpecificationStatus: state.setSpecificationStatus,
            specificationArchived: state.specificationArchived,
            setSpecificationArchived: state.setSpecificationArchived,
            createSpecificationMutation: state.createSpecificationMutation,
            selectedSpecificationId: state.selectedSpecificationId,
            toggleSpecificationEditor: state.toggleSpecificationEditor,
            editSpecificationTitle: state.editSpecificationTitle,
            setEditSpecificationTitle: state.setEditSpecificationTitle,
            editSpecificationBody: state.editSpecificationBody,
            setEditSpecificationBody: state.setEditSpecificationBody,
            editSpecificationStatus: state.editSpecificationStatus,
            setEditSpecificationStatus: state.setEditSpecificationStatus,
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
            parseExternalRefsText: state.parseExternalRefsText,
            removeExternalRefByIndex: state.removeExternalRefByIndex,
            externalRefsToText: state.externalRefsToText,
            parseAttachmentRefsText: state.parseAttachmentRefsText,
            removeAttachmentByPath: state.removeAttachmentByPath,
            attachmentRefsToText: state.attachmentRefsToText,
            workspaceId: state.workspaceId,
            userId: state.userId,
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
            noteQ: state.noteQ,
            setNoteQ: state.setNoteQ,
            createNoteMutation: state.createNoteMutation,
            noteArchived: state.noteArchived,
            setNoteArchived: state.setNoteArchived,
            noteTagSuggestions: state.noteTagSuggestions,
            noteTags: state.noteTags,
            toggleNoteFilterTag: state.toggleNoteFilterTag,
            selectedNoteId: state.selectedNoteId,
            selectedNote: state.selectedNote,
            editNoteTitle: state.editNoteTitle,
            toggleNoteEditor: state.toggleNoteEditor,
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
          searchPriority={state.searchPriority}
          setSearchPriority={state.setSearchPriority}
          searchArchived={state.searchArchived}
          setSearchArchived={state.setSearchArchived}
          taskTagSuggestions={state.taskTagSuggestions}
          searchTags={state.searchTags}
          toggleSearchTag={state.toggleSearchTag}
          onClose={() => state.setTab('tasks')}
        />
      )}

      {state.tab === 'profile' ? (
        <ProfilePanel
          userName={state.bootstrap.data.current_user.full_name}
          theme={state.theme}
          frontendVersion={state.frontendVersion}
          backendVersion={state.backendVersion}
          backendBuild={state.backendBuild}
          deployedAtUtc={state.backendDeployedAtUtc}
          onToggleTheme={() => {
            const next = state.theme === 'light' ? 'dark' : 'light'
            state.setTheme(next)
            state.themeMutation.mutate(next)
          }}
        />
      ) : state.tab !== 'tasks' && state.tab !== 'projects' && state.tab !== 'notes' && state.tab !== 'specifications' ? (
        <TaskResultsPanel
          tasks={state.tasks.data?.items ?? []}
          total={state.tasks.data?.total ?? 0}
          showProject={state.tab === 'search'}
          projectNames={state.projectNames}
          onOpen={state.openTaskEditor}
          onRestore={(taskId) => state.restoreTaskMutation.mutate(taskId)}
          onReopen={(taskId) => state.reopenTaskMutation.mutate(taskId)}
          onComplete={(taskId) => state.completeTaskMutation.mutate(taskId)}
        />
      ) : null}
    </>
  )
}
