import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { getNotes, getTasks } from '../../api'
import type { Note, Specification, Task } from '../../types'
import { MarkdownView } from '../../markdown/MarkdownView'
import { parseCommaTags } from '../../utils/ui'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import {
  AttachmentRefList,
  ExternalRefEditor,
  Icon,
  MarkdownModeToggle,
} from '../shared/uiHelpers'

export function SpecificationsPanel({ state }: { state: any }) {
  const items: Specification[] = state.specifications.data?.items ?? []
  const linkedTasks: Task[] = state.specTasks.data?.items ?? []
  const linkedNotes: Note[] = state.specNotes.data?.items ?? []
  const selectedSpecificationId: string | null = state.selectedSpecificationId ?? null
  const [newTaskTitle, setNewTaskTitle] = React.useState('')
  const [bulkTaskText, setBulkTaskText] = React.useState('')
  const [newNoteTitle, setNewNoteTitle] = React.useState('')
  const [newNoteBody, setNewNoteBody] = React.useState('')
  const [taskLinkOpen, setTaskLinkOpen] = React.useState(false)
  const [noteLinkOpen, setNoteLinkOpen] = React.useState(false)
  const [taskLinkQuery, setTaskLinkQuery] = React.useState('')
  const [noteLinkQuery, setNoteLinkQuery] = React.useState('')
  const [showSpecTagPicker, setShowSpecTagPicker] = React.useState(false)
  const [specTagQuery, setSpecTagQuery] = React.useState('')

  React.useEffect(() => {
    setNewTaskTitle('')
    setBulkTaskText('')
    setNewNoteTitle('')
    setNewNoteBody('')
    setTaskLinkOpen(false)
    setNoteLinkOpen(false)
    setTaskLinkQuery('')
    setNoteLinkQuery('')
    setShowSpecTagPicker(false)
    setSpecTagQuery('')
  }, [selectedSpecificationId])

  const taskLinkCandidates = useQuery({
    queryKey: [
      'spec-link-task-candidates',
      state.userId,
      state.workspaceId,
      state.selectedProjectId,
      selectedSpecificationId,
      taskLinkQuery,
    ],
    queryFn: () =>
      getTasks(state.userId, state.workspaceId, {
        project_id: state.selectedProjectId,
        q: taskLinkQuery || undefined,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(taskLinkOpen && state.workspaceId && state.selectedProjectId && selectedSpecificationId),
  })

  const noteLinkCandidates = useQuery({
    queryKey: [
      'spec-link-note-candidates',
      state.userId,
      state.workspaceId,
      state.selectedProjectId,
      selectedSpecificationId,
      noteLinkQuery,
    ],
    queryFn: () =>
      getNotes(state.userId, state.workspaceId, {
        project_id: state.selectedProjectId,
        q: noteLinkQuery || undefined,
        limit: 200,
        offset: 0,
      }),
    enabled: Boolean(noteLinkOpen && state.workspaceId && state.selectedProjectId && selectedSpecificationId),
  })

  const availableTaskCandidates = React.useMemo(
    () => ((taskLinkCandidates.data?.items ?? []) as Task[]).filter((item) => !item.specification_id),
    [taskLinkCandidates.data?.items]
  )
  const availableNoteCandidates = React.useMemo(
    () => ((noteLinkCandidates.data?.items ?? []) as Note[]).filter((item) => !item.specification_id),
    [noteLinkCandidates.data?.items]
  )

  const bulkResult = state.bulkCreateSpecificationTasksMutation.data
  const currentSpecificationTags = React.useMemo(
    () => parseCommaTags(state.editSpecificationTags ?? ''),
    [state.editSpecificationTags]
  )
  const currentSpecificationTagsLower = React.useMemo(
    () => new Set(currentSpecificationTags.map((tag) => tag.toLowerCase())),
    [currentSpecificationTags]
  )
  const allSpecificationTags = React.useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const tag of [...(state.taskTagSuggestions ?? []), ...currentSpecificationTags]) {
      const cleaned = String(tag || '').trim()
      if (!cleaned) continue
      const key = cleaned.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      out.push(cleaned)
    }
    return out
  }, [currentSpecificationTags, state.taskTagSuggestions])
  const filteredSpecificationTags = React.useMemo(() => {
    const query = specTagQuery.trim().toLowerCase()
    const base = query ? allSpecificationTags.filter((tag) => tag.toLowerCase().includes(query)) : allSpecificationTags
    return base.slice(0, 40)
  }, [allSpecificationTags, specTagQuery])
  const canCreateSpecificationTag = React.useMemo(() => {
    const query = specTagQuery.trim()
    if (!query) return false
    return !allSpecificationTags.some((tag) => tag.toLowerCase() === query.toLowerCase())
  }, [allSpecificationTags, specTagQuery])
  const toggleSpecificationTag = React.useCallback(
    (tag: string) => {
      const cleaned = String(tag || '').trim()
      if (!cleaned) return
      const lower = cleaned.toLowerCase()
      const next = currentSpecificationTagsLower.has(lower)
        ? currentSpecificationTags.filter((value) => value.toLowerCase() !== lower)
        : [...currentSpecificationTags, cleaned]
      state.setEditSpecificationTags(parseCommaTags(next.join(', ')).join(', '))
    },
    [currentSpecificationTags, currentSpecificationTagsLower, state]
  )
  const createSpecificationTag = React.useCallback(() => {
    const cleaned = String(specTagQuery || '').trim()
    if (!cleaned) return
    const next = parseCommaTags([...currentSpecificationTags, cleaned].join(', '))
    state.setEditSpecificationTags(next.join(', '))
    setSpecTagQuery('')
    setShowSpecTagPicker(false)
  }, [currentSpecificationTags, specTagQuery, state])

  return (
    <section className="card">
      <h2>Specifications ({state.specifications.data?.total ?? 0})</h2>
      <div className="notes-shell">
        <div className="notes-toolbar">
          <select
            value={state.specificationStatus}
            onChange={(e) => state.setSpecificationStatus(e.target.value)}
            aria-label="Specification status filter"
          >
            <option value="">All statuses</option>
            <option value="Draft">Draft</option>
            <option value="Ready">Ready</option>
            <option value="In progress">In progress</option>
            <option value="Implemented">Implemented</option>
            <option value="Archived">Archived</option>
          </select>
          <button
            className="action-icon primary"
            onClick={() => state.createSpecificationMutation.mutate()}
            disabled={state.createSpecificationMutation.isPending}
            title="New specification"
            aria-label="New specification"
          >
            <Icon path="M12 5v14M5 12h14" />
          </button>
        </div>

        <div className="row wrap notes-tag-filters">
          <label className="row archived-toggle notes-archived-filter">
            <input
              type="checkbox"
              checked={state.specificationArchived}
              onChange={(e) => state.setSpecificationArchived(e.target.checked)}
            />
            Archived
          </label>
          <PopularTagFilters
            tags={state.taskTagSuggestions ?? []}
            selectedTags={state.specificationTags}
            onToggleTag={state.toggleSpecificationFilterTag}
            onClear={() => state.clearSpecificationFilterTags()}
            getTagUsage={state.getTagUsage}
            idPrefix="spec-filter"
          />
        </div>

        <div className="task-list">
          {state.specifications.isLoading && <div className="notice">Loading specifications...</div>}
          {items.map((specification) => {
            const isOpen = state.selectedSpecificationId === specification.id
            const status = isOpen ? state.editSpecificationStatus : specification.status
            return (
              <div
                key={specification.id}
                className={`note-row ${isOpen ? 'open selected' : ''}`}
                onClick={() => state.toggleSpecificationEditor(specification.id)}
                role="button"
              >
                <div className="note-title">
                  {specification.archived && <span className="badge">Archived</span>}
                  <strong>{isOpen ? state.editSpecificationTitle || 'Untitled spec' : specification.title || 'Untitled spec'}</strong>
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="status-chip">{status}</span>
                </div>
                {(specification.tags ?? []).length > 0 && (
                  <div className="task-tags" style={{ marginTop: 8 }}>
                    {(specification.tags ?? []).map((tag) => (
                      <button
                        key={`${specification.id}-${tag}`}
                        type="button"
                        className="tag-mini tag-clickable"
                        onClick={(event) => {
                          event.stopPropagation()
                          state.toggleSpecificationFilterTag(tag)
                        }}
                        title={`Filter by tag: ${tag}`}
                        style={{
                          backgroundColor: `hsl(${state.tagHue(tag)}, 70%, 92%)`,
                          borderColor: `hsl(${state.tagHue(tag)}, 70%, 78%)`,
                          color: `hsl(${state.tagHue(tag)}, 55%, 28%)`
                        }}
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                )}
                <div className="note-snippet">
                  {(specification.body || '').replace(/\s+/g, ' ').slice(0, 180) || '(empty)'}
                </div>

                {isOpen && (
                  <div className="note-accordion" onClick={(e) => e.stopPropagation()} role="region" aria-label="Specification editor">
                    <div className="note-editor-head">
                      <input
                        className="note-title-input"
                        value={state.editSpecificationTitle}
                        onChange={(e) => state.setEditSpecificationTitle(e.target.value)}
                        placeholder="Title"
                      />
                      <div className="note-actions">
                        {state.specificationIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
                        <button
                          className="action-icon primary"
                          onClick={() => state.saveSpecificationMutation.mutate()}
                          disabled={state.saveSpecificationMutation.isPending || !state.specificationIsDirty}
                          title="Save specification"
                          aria-label="Save specification"
                        >
                          <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                        </button>
                        <button
                          className="action-icon"
                          onClick={() =>
                            state.copyShareLink({
                              tab: 'specifications',
                              projectId: specification.project_id,
                              specificationId: specification.id,
                            })
                          }
                          title="Copy specification link"
                          aria-label="Copy specification link"
                        >
                          <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                        </button>
                        <span className="action-separator" aria-hidden="true" />
                        {specification.archived ? (
                          <button
                            className="action-icon"
                            onClick={() => state.restoreSpecificationMutation.mutate(specification.id)}
                            disabled={state.restoreSpecificationMutation.isPending}
                            title="Restore"
                            aria-label="Restore"
                          >
                            <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
                          </button>
                        ) : (
                          <button
                            className="action-icon"
                            onClick={() => state.archiveSpecificationMutation.mutate(specification.id)}
                            disabled={state.archiveSpecificationMutation.isPending}
                            title="Archive"
                            aria-label="Archive"
                          >
                            <Icon path="M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6" />
                          </button>
                        )}
                        <button
                          className="action-icon danger-ghost"
                          onClick={() => state.deleteSpecificationMutation.mutate(specification.id)}
                          disabled={state.deleteSpecificationMutation.isPending}
                          title="Delete"
                          aria-label="Delete"
                        >
                          <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                        </button>
                      </div>
                    </div>

                    <div className="row" style={{ marginBottom: 8 }}>
                      <span className="meta">Status</span>
                      <select
                        value={state.editSpecificationStatus}
                        onChange={(e) => state.setEditSpecificationStatus(e.target.value)}
                        style={{ maxWidth: 220 }}
                      >
                        <option value="Draft">Draft</option>
                        <option value="Ready">Ready</option>
                        <option value="In progress">In progress</option>
                        <option value="Implemented">Implemented</option>
                        <option value="Archived">Archived</option>
                      </select>
                    </div>
                    <div className="tag-bar" aria-label="Specification tags" style={{ marginBottom: 8 }}>
                      <div className="tag-chiplist">
                        {currentSpecificationTags.length === 0 ? (
                          <span className="meta">No tags</span>
                        ) : (
                          currentSpecificationTags.map((tag) => (
                            <span
                              key={`spec-tag-${specification.id}-${tag}`}
                              className="tag-chip"
                              style={{
                                background: `linear-gradient(135deg, hsl(${state.tagHue(tag)}, 70%, 92%), hsl(${state.tagHue(tag)}, 70%, 86%))`,
                                borderColor: `hsl(${state.tagHue(tag)}, 70%, 74%)`,
                                color: `hsl(${state.tagHue(tag)}, 55%, 22%)`
                              }}
                            >
                              <span className="tag-text">{tag}</span>
                            </span>
                          ))
                        )}
                      </div>
                      <button className="action-icon" onClick={() => setShowSpecTagPicker(true)} title="Edit tags" aria-label="Edit tags">
                        <Icon path="M3 12h8m-8 6h12m-12-12h18" />
                      </button>
                    </div>
                    {showSpecTagPicker && (
                      <div className="drawer open" onClick={() => setShowSpecTagPicker(false)}>
                        <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
                          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                            <h3 style={{ margin: 0 }}>Specification tags</h3>
                            <button className="action-icon" onClick={() => setShowSpecTagPicker(false)} title="Close" aria-label="Close">
                              <Icon path="M6 6l12 12M18 6 6 18" />
                            </button>
                          </div>
                          <div className="tag-picker-input-row">
                            <input
                              value={specTagQuery}
                              onChange={(e) => setSpecTagQuery(e.target.value)}
                              placeholder="Search or create tag"
                              autoFocus
                            />
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => setShowSpecTagPicker(false)}
                              title="Done"
                              aria-label="Done"
                            >
                              Done
                            </button>
                          </div>
                          <div className="tag-picker-list" role="listbox" aria-label="Specification tag list">
                            {filteredSpecificationTags.map((tag) => {
                              const selected = currentSpecificationTagsLower.has(tag.toLowerCase())
                              return (
                                <button
                                  key={`spec-picker-${tag}`}
                                  className={`tag-picker-item ${selected ? 'selected' : ''}`}
                                  onClick={() => toggleSpecificationTag(tag)}
                                  aria-label={selected ? `Remove tag ${tag}` : `Add tag ${tag}`}
                                  title={selected ? 'Remove tag' : 'Add tag'}
                                >
                                  <span className="tag-picker-check" aria-hidden="true">
                                    <Icon path={selected ? 'm5 13 4 4L19 7' : 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z'} />
                                  </span>
                                  <span className="tag-picker-name">{tag}</span>
                                </button>
                              )
                            })}
                            {filteredSpecificationTags.length === 0 && <div className="meta">No tags found.</div>}
                          </div>
                          {canCreateSpecificationTag && (
                            <button
                              className="primary tag-picker-create"
                              onClick={createSpecificationTag}
                              title="Create tag"
                              aria-label="Create tag"
                            >
                              Create "{specTagQuery.trim()}"
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    <div className="md-editor-surface">
                      <MarkdownModeToggle
                        view={state.specificationEditorView}
                        onChange={state.setSpecificationEditorView}
                        ariaLabel="Specification editor view"
                      />
                      <div className="md-editor-content">
                        {state.specificationEditorView === 'write' ? (
                          <textarea
                            className="md-textarea"
                            value={state.editSpecificationBody}
                            onChange={(e) => state.setEditSpecificationBody(e.target.value)}
                            placeholder="Write specification in Markdown..."
                          />
                        ) : (
                          <MarkdownView value={state.editSpecificationBody} />
                        )}
                      </div>
                    </div>
                    <div className="meta" style={{ marginTop: 8 }}>External links</div>
                    <ExternalRefEditor
                      refs={state.parseExternalRefsText(state.editSpecificationExternalRefsText)}
                      onRemoveIndex={(idx) =>
                        state.setEditSpecificationExternalRefsText((prev: string) =>
                          state.removeExternalRefByIndex(prev, idx)
                        )
                      }
                      onAdd={(ref) =>
                        state.setEditSpecificationExternalRefsText((prev: string) =>
                          state.externalRefsToText([...state.parseExternalRefsText(prev), ref])
                        )
                      }
                    />
                    <div className="meta" style={{ marginTop: 8 }}>File attachments</div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <button
                        className="status-chip"
                        type="button"
                        onClick={() => state.specFileInputRef.current?.click()}
                      >
                        Upload file
                      </button>
                      <input
                        ref={state.specFileInputRef}
                        type="file"
                        style={{ display: 'none' }}
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          e.currentTarget.value = ''
                          if (!file) return
                          try {
                            const ref = await state.uploadAttachmentRef(file, { project_id: specification.project_id })
                            state.setEditSpecificationAttachmentRefsText((prev: string) =>
                              state.attachmentRefsToText([...state.parseAttachmentRefsText(prev), ref])
                            )
                          } catch (err) {
                            state.setUiError(state.toErrorMessage(err, 'Upload failed'))
                          }
                        }}
                      />
                    </div>
                    <AttachmentRefList
                      refs={state.parseAttachmentRefsText(state.editSpecificationAttachmentRefsText)}
                      workspaceId={state.workspaceId}
                      userId={state.userId}
                      onRemovePath={(path) =>
                        state.setEditSpecificationAttachmentRefsText((prev: string) =>
                          state.removeAttachmentByPath(prev, path)
                        )
                      }
                    />
                    <div className="spec-links-shell">
                      <section className="spec-links-section">
                        <div className="spec-links-head">
                          <h3 style={{ margin: 0 }}>Implementation tasks ({linkedTasks.length})</h3>
                          <div className="row wrap" style={{ gap: 6 }}>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => {
                                const title = (newTaskTitle || '').trim() || 'Untitled task'
                                state.createSpecificationTaskMutation.mutate(
                                  { title },
                                  { onSuccess: () => setNewTaskTitle('') }
                                )
                              }}
                              disabled={state.createSpecificationTaskMutation.isPending}
                            >
                              + New
                            </button>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => {
                                const titles = bulkTaskText
                                  .split('\n')
                                  .map((value) => value.trim())
                                  .filter(Boolean)
                                if (titles.length === 0) {
                                  state.setUiError('Add at least one task title for bulk create.')
                                  return
                                }
                                state.bulkCreateSpecificationTasksMutation.mutate(
                                  { titles },
                                  { onSuccess: () => setBulkTaskText('') }
                                )
                              }}
                              disabled={state.bulkCreateSpecificationTasksMutation.isPending}
                            >
                              Create multiple
                            </button>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => setTaskLinkOpen(true)}
                              disabled={!selectedSpecificationId}
                            >
                              Link existing
                            </button>
                          </div>
                        </div>
                        <div className="spec-links-inline">
                          <input
                            value={newTaskTitle}
                            onChange={(e) => setNewTaskTitle(e.target.value)}
                            placeholder="Task title"
                          />
                        </div>
                        <textarea
                          className="md-textarea"
                          value={bulkTaskText}
                          onChange={(e) => setBulkTaskText(e.target.value)}
                          placeholder="One task title per line"
                          style={{ minHeight: 84 }}
                        />
                        {bulkResult && (
                          <div className="meta">
                            Bulk result: created {bulkResult.created}, failed {bulkResult.failed}
                          </div>
                        )}
                        {state.specTasks.isLoading ? (
                          <div className="meta">Loading linked tasks...</div>
                        ) : linkedTasks.length === 0 ? (
                          <div className="meta">No linked tasks yet.</div>
                        ) : (
                          <div className="spec-linked-list">
                            {linkedTasks.map((task) => (
                              <div key={task.id} className="spec-linked-row">
                                <div className="spec-linked-main">
                                  <strong>{task.title || 'Untitled task'}</strong>
                                  <div className="meta">{task.status}</div>
                                </div>
                                <div className="spec-linked-actions">
                                  <button
                                    className="status-chip"
                                    type="button"
                                    onClick={() => state.openTask(task.id, task.project_id)}
                                  >
                                    Open
                                  </button>
                                  <button
                                    className="status-chip"
                                    type="button"
                                    onClick={() => state.unlinkTaskFromSpecificationMutation.mutate(task.id)}
                                    disabled={state.unlinkTaskFromSpecificationMutation.isPending}
                                  >
                                    Unlink
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </section>

                      <section className="spec-links-section">
                        <div className="spec-links-head">
                          <h3 style={{ margin: 0 }}>Notes ({linkedNotes.length})</h3>
                          <div className="row wrap" style={{ gap: 6 }}>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => {
                                const title = (newNoteTitle || '').trim() || 'Untitled note'
                                state.createSpecificationNoteMutation.mutate(
                                  { title, body: newNoteBody || '' },
                                  {
                                    onSuccess: () => {
                                      setNewNoteTitle('')
                                      setNewNoteBody('')
                                    },
                                  }
                                )
                              }}
                              disabled={state.createSpecificationNoteMutation.isPending}
                            >
                              + New
                            </button>
                            <button
                              className="status-chip"
                              type="button"
                              onClick={() => setNoteLinkOpen(true)}
                              disabled={!selectedSpecificationId}
                            >
                              Link existing
                            </button>
                          </div>
                        </div>
                        <div className="spec-links-inline">
                          <input
                            value={newNoteTitle}
                            onChange={(e) => setNewNoteTitle(e.target.value)}
                            placeholder="Note title"
                          />
                        </div>
                        <textarea
                          className="md-textarea"
                          value={newNoteBody}
                          onChange={(e) => setNewNoteBody(e.target.value)}
                          placeholder="Optional note body"
                          style={{ minHeight: 84 }}
                        />
                        {state.specNotes.isLoading ? (
                          <div className="meta">Loading linked notes...</div>
                        ) : linkedNotes.length === 0 ? (
                          <div className="meta">No linked notes yet.</div>
                        ) : (
                          <div className="spec-linked-list">
                            {linkedNotes.map((note) => (
                              <div key={note.id} className="spec-linked-row">
                                <div className="spec-linked-main">
                                  <strong>{note.title || 'Untitled note'}</strong>
                                  <div className="meta">{(note.body || '').replace(/\s+/g, ' ').slice(0, 120) || '(empty)'}</div>
                                </div>
                                <div className="spec-linked-actions">
                                  <button
                                    className="status-chip"
                                    type="button"
                                    onClick={() => state.openNote(note.id, note.project_id)}
                                  >
                                    Open
                                  </button>
                                  <button
                                    className="status-chip"
                                    type="button"
                                    onClick={() => state.unlinkNoteFromSpecificationMutation.mutate(note.id)}
                                    disabled={state.unlinkNoteFromSpecificationMutation.isPending}
                                  >
                                    Unlink
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </section>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {taskLinkOpen && (
        <div className="drawer open" onClick={() => setTaskLinkOpen(false)}>
          <div className="drawer-body spec-link-body" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>Link Existing Task</h3>
              <button className="action-icon" onClick={() => setTaskLinkOpen(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <input
              value={taskLinkQuery}
              onChange={(e) => setTaskLinkQuery(e.target.value)}
              placeholder="Search tasks in project"
              autoFocus
            />
            <div className="spec-link-list">
              {taskLinkCandidates.isLoading && <div className="meta">Loading tasks...</div>}
              {!taskLinkCandidates.isLoading && availableTaskCandidates.length === 0 && (
                <div className="meta">No unlinked tasks found.</div>
              )}
              {availableTaskCandidates.map((task) => (
                <button
                  key={task.id}
                  className="spec-link-item"
                  onClick={() =>
                    state.linkTaskToSpecificationMutation.mutate(task.id, {
                      onSuccess: () => setTaskLinkOpen(false),
                    })
                  }
                  disabled={state.linkTaskToSpecificationMutation.isPending}
                >
                  <span>{task.title || 'Untitled task'}</span>
                  <span className="meta">{task.status}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {noteLinkOpen && (
        <div className="drawer open" onClick={() => setNoteLinkOpen(false)}>
          <div className="drawer-body spec-link-body" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <h3 style={{ margin: 0 }}>Link Existing Note</h3>
              <button className="action-icon" onClick={() => setNoteLinkOpen(false)} title="Close" aria-label="Close">
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            </div>
            <input
              value={noteLinkQuery}
              onChange={(e) => setNoteLinkQuery(e.target.value)}
              placeholder="Search notes in project"
              autoFocus
            />
            <div className="spec-link-list">
              {noteLinkCandidates.isLoading && <div className="meta">Loading notes...</div>}
              {!noteLinkCandidates.isLoading && availableNoteCandidates.length === 0 && (
                <div className="meta">No unlinked notes found.</div>
              )}
              {availableNoteCandidates.map((note) => (
                <button
                  key={note.id}
                  className="spec-link-item"
                  onClick={() =>
                    state.linkNoteToSpecificationMutation.mutate(note.id, {
                      onSuccess: () => setNoteLinkOpen(false),
                    })
                  }
                  disabled={state.linkNoteToSpecificationMutation.isPending}
                >
                  <span>{note.title || 'Untitled note'}</span>
                  <span className="meta">{(note.body || '').replace(/\s+/g, ' ').slice(0, 90) || '(empty)'}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
