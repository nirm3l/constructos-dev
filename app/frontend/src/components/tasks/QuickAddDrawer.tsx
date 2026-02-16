import React from 'react'
import { Icon } from '../shared/uiHelpers'

export function QuickAddDrawer({ state }: { state: any }) {
  return (
    <>
      {state.showQuickAdd && (
        <div className="drawer open" onClick={() => state.setShowQuickAdd(false)}>
          <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>New Task</h3>
              <button className="action-icon" onClick={() => state.setShowQuickAdd(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <div className="quickadd-form">
              <input
                className="quickadd-title"
                value={state.taskTitle}
                onChange={(e) => state.setTaskTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    const title = state.taskTitle.trim()
                    if (!title || !state.quickProjectId || state.createTaskMutation.isPending) return
                    state.createTaskMutation.mutate()
                  }
                }}
                placeholder="Task title"
                autoFocus
              />
              <div className="quickadd-project-field">
                <span className="meta quickadd-project-label">Project</span>
                <select
                  className="quickadd-project-select"
                  value={state.quickProjectId}
                  onChange={(e) => state.setQuickProjectId(e.target.value)}
                  aria-label="Project"
                >
                  {(state.bootstrap.data?.projects ?? []).map((p: any) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className={`quickadd-due ${state.quickDueDate ? 'has-value' : ''} ${state.quickDueDateFocused ? 'focused' : ''}`}>
                <span className="quickadd-due-placeholder">Due Date</span>
                <input
                  id="quick-task-due-date"
                  className={`due-input ${!state.quickDueDate && !state.quickDueDateFocused ? 'due-input-empty' : ''}`}
                  type="datetime-local"
                  value={state.quickDueDate}
                  onChange={(e) => state.setQuickDueDate(e.target.value)}
                  onFocus={() => state.setQuickDueDateFocused(true)}
                  onBlur={() => state.setQuickDueDateFocused(false)}
                  aria-label="Due date"
                />
              </div>
              <button
                className="action-icon primary quickadd-create"
                disabled={!state.taskTitle.trim() || !state.quickProjectId || state.createTaskMutation.isPending}
                onClick={() => state.createTaskMutation.mutate()}
                title="Create task"
                aria-label="Create task"
              >
                <Icon path="M12 5v14M5 12h14" />
              </button>
            </div>
            <div className="tag-bar" aria-label="Task tags" style={{ marginTop: 10 }}>
              <div className="tag-chiplist">
                {state.quickTaskTags.length === 0 ? (
                  <span className="meta">No tags</span>
                ) : (
                  state.quickTaskTags.map((t: string) => (
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
              <button
                className="action-icon"
                onClick={() => state.setShowQuickTaskTagPicker(true)}
                title="Edit tags"
                aria-label="Edit tags"
              >
                <Icon path="M3 12h8m-8 6h12m-12-12h18" />
              </button>
            </div>
            <div className="meta" style={{ marginTop: 10 }}>
              Tip: you can also ask Codex Chat to create tasks in bulk.
            </div>
          </div>
        </div>
      )}

      {state.showQuickTaskTagPicker && (
        <div className="drawer open" onClick={() => state.setShowQuickTaskTagPicker(false)}>
          <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>Task Tags</h3>
              <button className="action-icon" onClick={() => state.setShowQuickTaskTagPicker(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <input
              value={state.quickTaskTagQuery}
              onChange={(e) => state.setQuickTaskTagQuery(e.target.value)}
              placeholder="Search or create tag"
              autoFocus
            />
            <div className="tag-picker-list" role="listbox" aria-label="Tag list">
              {state.filteredQuickTaskTags.map((t: string) => {
                const selected = state.quickTaskTagsLower.has(t.toLowerCase())
                return (
                  <button
                    key={t}
                    className={`tag-picker-item ${selected ? 'selected' : ''}`}
                    onClick={() => state.toggleQuickTaskTag(t)}
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
              {state.filteredQuickTaskTags.length === 0 && <div className="meta">No tags found.</div>}
            </div>
            {state.canCreateQuickTaskTag && (
              <button
                className="primary tag-picker-create"
                onClick={() => {
                  state.toggleQuickTaskTag(state.quickTaskTagQuery)
                  state.setQuickTaskTagQuery('')
                  state.setShowQuickTaskTagPicker(false)
                }}
                title="Create tag"
                aria-label="Create tag"
              >
                Create "{state.quickTaskTagQuery.trim()}"
              </button>
            )}
          </div>
        </div>
      )}
    </>
  )
}
