import React from 'react'
import type { Note } from '../../types'
import { AttachmentRefList, ExternalRefEditor, Icon } from '../shared/uiHelpers'
import { TaskDrawerInsights } from './TaskDrawerInsights'

export function TaskDrawer({ state }: { state: any }) {
  if (!state.selectedTask) return null
  const linkedNotes: Note[] = state.taskNotes?.data?.items ?? []
  const statusOptions: string[] = (state.taskStatusOptions ?? []).length > 0
    ? state.taskStatusOptions
    : ['To do', 'In progress', 'Done']

  return (
    <div className="drawer open" onClick={() => state.closeTaskEditor()}>
      <div className="drawer-body task-drawer-body" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div className="task-header-main">
            <h3 className="drawer-title">{state.selectedTask.title}</h3>
          </div>
          <div className="row task-header-actions">
            {state.taskIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
            <button
              className="action-icon primary"
              onClick={() => state.saveTaskMutation.mutate()}
              disabled={state.saveTaskMutation.isPending || !state.taskIsDirty}
              title="Save task"
              aria-label="Save task"
            >
              <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
            </button>
            <button
              className="action-icon"
              onClick={() => state.copyShareLink({ tab: 'tasks', projectId: state.selectedTask.project_id, taskId: state.selectedTask.id })}
              title="Copy task link"
              aria-label="Copy task link"
            >
              <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
            </button>
            <span className="action-separator" aria-hidden="true" />
            {state.selectedTask.status === 'Done' ? (
              <button className="action-icon" onClick={() => state.reopenTaskMutation.mutate(state.selectedTask.id)} title="Reopen" aria-label="Reopen">
                <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
              </button>
            ) : (
              <button className="action-icon" onClick={() => state.completeTaskMutation.mutate(state.selectedTask.id)} title="Complete" aria-label="Complete">
                <Icon path="m5 13 4 4L19 7" />
              </button>
            )}
            {state.selectedTask.archived ? (
              <button className="action-icon" onClick={() => state.restoreTaskMutation.mutate(state.selectedTask.id)} title="Restore" aria-label="Restore">
                <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
              </button>
            ) : (
              <button className="action-icon" onClick={() => state.archiveTaskMutation.mutate(state.selectedTask.id)} title="Archive" aria-label="Archive">
                <Icon path="M3 7h18M5 7l1 13h12l1-13M9 7V4h6v3" />
              </button>
            )}
            <span className="action-separator" aria-hidden="true" />
            <button className="action-icon" onClick={() => state.closeTaskEditor()} title="Close" aria-label="Close">
              <Icon path="M6 6l12 12M18 6 6 18" />
            </button>
          </div>
        </div>
        <label className="field-control" style={{ marginTop: 8, marginBottom: 8 }}>
          <span className="field-label">Task name</span>
          <input
            value={state.editTitle}
            onChange={(e) => state.setEditTitle(e.target.value)}
            placeholder="Task title"
            style={{ width: '100%' }}
          />
        </label>
        <div className="field-control" style={{ marginBottom: 8 }}>
          <span className="field-label">Project</span>
          <button
            className="pill subtle task-project-pill"
            onClick={() => {
              if (!state.closeTaskEditor()) return
              state.setSelectedProjectId(state.selectedTask.project_id)
              state.setTab('projects')
            }}
            title="Open project"
            aria-label="Open project"
          >
            <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
            <span>{state.projectNames[state.selectedTask.project_id] || state.selectedTask.project_id}</span>
          </button>
        </div>
        {state.selectedTask.specification_id && (
          <div className="field-control" style={{ marginBottom: 8 }}>
            <span className="field-label">Specification</span>
            <button
              className="pill subtle task-project-pill task-spec-pill"
              onClick={() => state.openSpecification(state.selectedTask.specification_id as string, state.selectedTask.project_id)}
              title="Open linked specification"
              aria-label="Open linked specification"
            >
              <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
              <span>
                {state.specificationNameMap[state.selectedTask.specification_id] ||
                  `Specification ${String(state.selectedTask.specification_id).slice(0, 8)}`}
              </span>
            </button>
          </div>
        )}
        <div className="task-edit-grid task-main-fields" style={{ marginBottom: 8 }}>
          <label className="field-control task-field-half">
            <span className="field-label">Status</span>
            <select value={state.editStatus} onChange={(e) => state.setEditStatus(e.target.value)}>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label className="field-control task-field-half">
            <span className="field-label">Priority</span>
            <select value={state.editPriority} onChange={(e) => state.setEditPriority(e.target.value)}>
              <option value="Low">Low</option>
              <option value="Med">Med</option>
              <option value="High">High</option>
            </select>
          </label>
          <label className="field-control task-field-full">
            <span className="field-label">Due date</span>
            <input className="due-input" type="datetime-local" value={state.editDueDate} onChange={(e) => state.setEditDueDate(e.target.value)} />
          </label>
        </div>
        <label className="field-control" style={{ marginBottom: 10 }}>
          <span className="field-label">Description</span>
          <textarea value={state.editDescription} onChange={(e) => state.setEditDescription(e.target.value)} rows={4} style={{ width: '100%' }} />
        </label>
        <div className="tag-bar" aria-label="Task tags" style={{ marginBottom: 10 }}>
          <div className="tag-chiplist">
            {state.editTaskTags.length === 0 ? (
              <span className="meta">No tags</span>
            ) : (
              state.editTaskTags.map((t: string) => (
                <span
                  key={t}
                  className="tag-chip"
                  style={{
                    background: `linear-gradient(135deg, hsl(${state.tagHue(t)}, 70%, 92%), hsl(${state.tagHue(t)}, 70%, 86%))`,
                    borderColor: `hsl(${state.tagHue(t)}, 70%, 74%)`,
                    color: `hsl(${state.tagHue(t)}, 55%, 22%)`
                  }}
                >
                  <span className="tag-text">{t}</span>
                </span>
              ))
            )}
          </div>
          <button className="action-icon" onClick={() => state.setShowTaskTagPicker(true)} title="Edit tags" aria-label="Edit tags">
            <Icon path="M3 12h8m-8 6h12m-12-12h18" />
          </button>
        </div>
        <div className="task-edit-grid" style={{ marginBottom: 8 }}>
          <label className="field-control">
            <span className="field-label">Task type</span>
            <select value={state.editTaskType} onChange={(e) => state.setEditTaskType(e.target.value as 'manual' | 'scheduled_instruction')}>
              <option value="manual">Manual</option>
              <option value="scheduled_instruction">Scheduled</option>
            </select>
          </label>
        </div>
        {state.taskEditorError && <div className="notice" role="alert" style={{ marginBottom: 8 }}>{state.taskEditorError}</div>}
        {state.editTaskType === 'scheduled_instruction' && (
          <>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <label className="field-control">
                <span className="field-label">Scheduled for</span>
                <input
                  className="due-input"
                  type="datetime-local"
                  value={state.editScheduledAtUtc}
                  onChange={(e) => state.setEditScheduledAtUtc(e.target.value)}
                />
              </label>
              <label className="field-control">
                <span className="field-label">Timezone</span>
                <input
                  value={state.editScheduleTimezone}
                  onChange={(e) => state.setEditScheduleTimezone(e.target.value)}
                  placeholder="e.g. Europe/Sarajevo"
                />
              </label>
            </div>
            <div className="task-edit-grid" style={{ marginBottom: 8 }}>
              <div className="field-control">
                <span className="field-label">Repeat (optional)</span>
                <div className="row wrap">
                  <input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={state.editRecurringEvery}
                    onChange={(e) => state.setEditRecurringEvery(e.target.value)}
                    placeholder="Every"
                    style={{ width: 120 }}
                  />
                  <select
                    value={state.editRecurringUnit}
                    onChange={(e) => state.setEditRecurringUnit(e.target.value as 'm' | 'h' | 'd')}
                  >
                    <option value="m">minutes</option>
                    <option value="h">hours</option>
                    <option value="d">days</option>
                  </select>
                  <button
                    className="action-icon"
                    onClick={() => {
                      state.setEditRecurringEvery('')
                      state.setEditRecurringUnit('h')
                    }}
                    title="Clear repeat"
                    aria-label="Clear repeat"
                  >
                    <Icon path="M6 6l12 12M18 6 6 18" />
                  </button>
                </div>
              </div>
            </div>
            <label className="field-control" style={{ marginBottom: 8 }}>
              <span className="field-label">Instruction</span>
              <textarea
                value={state.editScheduledInstruction}
                onChange={(e) => state.setEditScheduledInstruction(e.target.value)}
                rows={3}
                style={{ width: '100%' }}
                placeholder="Scheduled (executed automatically when due)"
              />
            </label>
          </>
        )}
        {state.selectedTask.schedule_state && state.editTaskType === 'scheduled_instruction' && (
          <div className="row wrap" style={{ marginBottom: 8 }}>
            <span className="badge">Schedule: {state.selectedTask.schedule_state}</span>
            <span className={`prio prio-${state.priorityTone(state.selectedTask.priority)}`} title="Priority">
              {state.selectedTask.priority}
            </span>
            {state.selectedTask.scheduled_at_utc && <span className="meta">Scheduled for: {new Date(state.selectedTask.scheduled_at_utc).toLocaleString()}</span>}
            {state.selectedTask.recurring_rule && <span className="meta">Repeats: {String(state.selectedTask.recurring_rule)}</span>}
            {state.selectedTask.last_schedule_error && <span className="meta">Last error: {state.selectedTask.last_schedule_error}</span>}
          </div>
        )}
        <div className="meta" style={{ marginBottom: 6 }}>External links</div>
        <ExternalRefEditor
          refs={state.parseExternalRefsText(state.editTaskExternalRefsText)}
          onRemoveIndex={(idx) => state.setEditTaskExternalRefsText((prev: string) => state.removeExternalRefByIndex(prev, idx))}
          onAdd={(ref) => state.setEditTaskExternalRefsText((prev: string) => state.externalRefsToText([...state.parseExternalRefsText(prev), ref]))}
        />
        <div className="meta" style={{ marginBottom: 6 }}>File attachments</div>
        <div className="row" style={{ marginBottom: 8 }}>
          <button className="status-chip" type="button" onClick={() => state.taskFileInputRef.current?.click()}>
            Upload file
          </button>
          <input
            ref={state.taskFileInputRef}
            type="file"
            style={{ display: 'none' }}
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.currentTarget.value = ''
              if (!file || !state.selectedTask) return
              try {
                const ref = await state.uploadAttachmentRef(file, { project_id: state.editProjectId || state.selectedTask.project_id, task_id: state.selectedTask.id })
                state.setEditTaskAttachmentRefsText((prev: string) => state.attachmentRefsToText([...state.parseAttachmentRefsText(prev), ref]))
              } catch (err) {
                const message = state.toErrorMessage(err, 'Upload failed')
                state.setUiError(message)
                state.setTaskEditorError(message)
              }
            }}
          />
        </div>
        <AttachmentRefList
          refs={state.parseAttachmentRefsText(state.editTaskAttachmentRefsText)}
          workspaceId={state.workspaceId}
          userId={state.userId}
          onRemovePath={(path) => state.setEditTaskAttachmentRefsText((prev: string) => state.removeAttachmentByPath(prev, path))}
        />
        <div style={{ marginTop: 10, marginBottom: 10 }}>
          <div className="meta">Task ID: <code>{state.selectedTask.id}</code></div>
          <div className="meta">
            Created by: {state.selectedTaskCreator}
            {state.selectedTaskTimeMeta ? ` | ${state.selectedTaskTimeMeta.label}: ${state.toUserDateTime(state.selectedTaskTimeMeta.value, state.userTimezone)}` : ''}
          </div>
        </div>
        <div className="spec-links-section" style={{ marginBottom: 10 }}>
          <div className="spec-links-head">
            <h3 style={{ margin: 0 }}>Linked notes ({linkedNotes.length})</h3>
            <button
              className="status-chip"
              type="button"
              onClick={() => {
                if (!state.closeTaskEditor()) return
                state.createNoteMutation.mutate({
                  title: 'Untitled note',
                  body: '',
                  project_id: state.selectedTask.project_id,
                  task_id: state.selectedTask.id,
                })
              }}
              disabled={state.createNoteMutation.isPending}
            >
              + New
            </button>
          </div>
          {state.taskNotes?.isLoading ? (
            <div className="meta">Loading linked notes...</div>
          ) : linkedNotes.length === 0 ? (
            <div className="meta">No linked notes yet.</div>
          ) : (
            <div className="spec-linked-list">
              {linkedNotes.map((note) => (
                <div key={note.id} className="spec-linked-row">
                  <div style={{ minWidth: 0 }}>
                    <strong>{note.title || 'Untitled note'}</strong>
                    <div className="meta">{(note.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                  </div>
                  <button
                    className="status-chip"
                    type="button"
                    onClick={() => {
                      if (!state.closeTaskEditor()) return
                      state.openNote(note.id, note.project_id)
                    }}
                  >
                    Open
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        {state.showTaskTagPicker && (
          <div className="drawer open" onClick={() => state.setShowTaskTagPicker(false)}>
            <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                <h3 style={{ margin: 0 }}>Task Tags</h3>
                <button className="action-icon" onClick={() => state.setShowTaskTagPicker(false)} title="Close" aria-label="Close">
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              </div>
              <div className="tag-picker-input-row">
                <input
                  value={state.taskTagPickerQuery}
                  onChange={(e) => state.setTaskTagPickerQuery(e.target.value)}
                  placeholder="Search or create tag"
                  autoFocus
                />
                <button
                  className="status-chip"
                  type="button"
                  onClick={() => state.setShowTaskTagPicker(false)}
                  title="Done"
                  aria-label="Done"
                >
                  Done
                </button>
              </div>
              <div className="tag-picker-list" role="listbox" aria-label="Tag list">
                {state.filteredTaskTags.map((t: string) => {
                  const selected = state.taskTagsLower.has(t.toLowerCase())
                  return (
                    <button
                      key={t}
                      className={`tag-picker-item ${selected ? 'selected' : ''}`}
                      onClick={() => state.toggleTaskTag(t)}
                      aria-label={selected ? `Remove tag ${t}` : `Add tag ${t}`}
                      title={selected ? 'Remove tag' : 'Add tag'}
                    >
                      <span className="tag-picker-check" aria-hidden="true">
                        <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
                      </span>
                      <span className="tag-picker-name">{t}</span>
                    </button>
                  )
                })}
                {state.filteredTaskTags.length === 0 && <div className="meta">No tags found.</div>}
              </div>
              {state.canCreateTaskTag && (
                <button
                  className="primary tag-picker-create"
                  onClick={() => {
                    state.toggleTaskTag(state.taskTagPickerQuery)
                    state.setTaskTagPickerQuery('')
                    state.setShowTaskTagPicker(false)
                  }}
                  title="Create tag"
                  aria-label="Create tag"
                >
                  Create "{state.taskTagPickerQuery.trim()}"
                </button>
              )}
            </div>
          </div>
        )}
        <TaskDrawerInsights state={state} />
      </div>
    </div>
  )
}
