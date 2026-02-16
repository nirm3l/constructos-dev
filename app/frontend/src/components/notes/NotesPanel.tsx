import React from 'react'
import type { Note } from '../../types'
import { MarkdownView } from '../../markdown/MarkdownView'
import { AttachmentRefList, ExternalRefEditor, ExternalRefList, Icon, MarkdownModeToggle } from '../shared/uiHelpers'

export function NotesPanel({
  state,
  actions,
}: {
  state: any
  actions: any
}) {
  return (
    <section className="card">
      <h2>Notes ({state.notes.data?.total ?? 0})</h2>
      <div className="notes-shell">
        <div className="notes-toolbar">
          <div className="notes-search">
            <input value={state.noteQ} onChange={(e) => state.setNoteQ(e.target.value)} placeholder="Search notes" />
          </div>
          <button className="action-icon primary" onClick={() => state.createNoteMutation.mutate()} title="New note" aria-label="New note">
            <Icon path="M12 5v14M5 12h14" />
          </button>
        </div>
        <div className="row wrap notes-tag-filters">
          <label className="row archived-toggle notes-archived-filter">
            <input type="checkbox" checked={state.noteArchived} onChange={(e) => state.setNoteArchived(e.target.checked)} />
            Archived
          </label>
          {state.noteTagSuggestions.slice(0, 8).map((tag: string) => (
            <button
              key={`note-filter-${tag}`}
              className={`status-chip tag-filter-chip ${state.noteTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
              onClick={() => state.toggleNoteFilterTag(tag)}
              aria-pressed={state.noteTags.includes(tag.toLowerCase())}
            >
              #{tag}
            </button>
          ))}
        </div>

        <div className="task-list">
          {state.notes.isLoading && <div className="notice">Loading notes...</div>}
          {state.notes.data?.items.map((n: Note) => {
            const isOpen = state.selectedNoteId === n.id
            const isSelected = state.selectedNote?.id === n.id
            const displayTitle = isSelected ? state.editNoteTitle || 'Untitled' : n.title || 'Untitled'
            return (
              <div
                key={n.id}
                className={`note-row ${isOpen ? 'open selected' : ''}`}
                onClick={() => {
                  const changed = state.toggleNoteEditor(n.id)
                  if (!changed) return
                  state.setShowTagPicker(false)
                  state.setTagPickerQuery('')
                }}
                role="button"
              >
                <div className="note-title">
                  {n.pinned && (
                    <span className="badge icon-badge" title="Pinned" aria-label="Pinned">
                      <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                    </span>
                  )}
                  {n.archived && <span className="badge">Archived</span>}
                  <strong>{displayTitle}</strong>
                </div>
                {(n.tags ?? []).length > 0 && (
                  <div className="note-tags">
                    {(n.tags ?? []).map((t) => (
                      <span
                        key={t}
                        className="tag-mini"
                        style={{
                          backgroundColor: `hsl(${state.tagHue(t)}, 70%, 92%)`,
                          borderColor: `hsl(${state.tagHue(t)}, 70%, 78%)`,
                          color: `hsl(${state.tagHue(t)}, 55%, 28%)`
                        }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="note-snippet">{(n.body || '').replace(/\s+/g, ' ').slice(0, 160) || '(empty)'}</div>
                {((n.external_refs?.length ?? 0) > 0 || (n.attachment_refs?.length ?? 0) > 0) && (
                  <div className="row wrap" style={{ gap: 6 }} onClick={(e) => e.stopPropagation()}>
                    <ExternalRefList refs={n.external_refs} />
                    <AttachmentRefList refs={n.attachment_refs} workspaceId={state.workspaceId} userId={state.userId} />
                  </div>
                )}

                {isOpen && isSelected && state.selectedNote && (
                  <div className="note-accordion" onClick={(e) => e.stopPropagation()} role="region" aria-label="Note editor">
                    <div className="note-editor-head">
                      <input
                        className="note-title-input"
                        value={state.editNoteTitle}
                        onChange={(e) => state.setEditNoteTitle(e.target.value)}
                        placeholder="Title"
                      />
                      <div className="note-actions">
                        {state.noteIsDirty && <span className="badge unsaved-badge">Unsaved</span>}
                        <button
                          className="action-icon primary"
                          onClick={() => state.saveNoteMutation.mutate()}
                          disabled={state.saveNoteMutation.isPending || !state.noteIsDirty}
                          title="Save note"
                          aria-label="Save note"
                        >
                          <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                        </button>
                        <button
                          className="action-icon"
                          onClick={() => actions.copyShareLink({ tab: 'notes', projectId: state.selectedNote.project_id, noteId: state.selectedNote.id })}
                          title="Copy note link"
                          aria-label="Copy note link"
                        >
                          <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                        </button>
                        <span className="action-separator" aria-hidden="true" />
                        {state.selectedNote.pinned ? (
                          <button className="action-icon" onClick={() => state.unpinNoteMutation.mutate(state.selectedNote.id)} title="Unpin" aria-label="Unpin">
                            <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                          </button>
                        ) : (
                          <button className="action-icon" onClick={() => state.pinNoteMutation.mutate(state.selectedNote.id)} title="Pin" aria-label="Pin">
                            <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                          </button>
                        )}
                        {state.selectedNote.archived ? (
                          <button className="action-icon" onClick={() => state.restoreNoteMutation.mutate(state.selectedNote.id)} title="Restore" aria-label="Restore">
                            <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
                          </button>
                        ) : (
                          <button className="action-icon" onClick={() => state.archiveNoteMutation.mutate(state.selectedNote.id)} title="Archive" aria-label="Archive">
                            <Icon path="M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6" />
                          </button>
                        )}
                        <span className="action-separator" aria-hidden="true" />
                        <button className="action-icon danger-ghost" onClick={() => state.deleteNoteMutation.mutate(state.selectedNote.id)} title="Delete" aria-label="Delete">
                          <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                        </button>
                      </div>
                    </div>

                    <div className="md-editor-surface">
                      <MarkdownModeToggle
                        view={state.noteEditorView}
                        onChange={state.setNoteEditorView}
                        ariaLabel="Note editor view"
                      />
                      <div className="md-editor-content">
                        {state.noteEditorView === 'write' ? (
                          <textarea className="md-textarea" value={state.editNoteBody} onChange={(e) => state.setEditNoteBody(e.target.value)} placeholder="Write Markdown..." />
                        ) : (
                          <MarkdownView value={state.editNoteBody} />
                        )}
                      </div>
                    </div>
                    <div className="tag-bar" aria-label="Tags">
                      <div className="tag-chiplist">
                        {state.currentNoteTags.length === 0 ? (
                          <span className="meta">No tags</span>
                        ) : (
                          state.currentNoteTags.map((t: string) => (
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
                      <button className="action-icon" onClick={() => state.setShowTagPicker(true)} title="Edit tags" aria-label="Edit tags">
                        <Icon path="M3 12h8m-8 6h12m-12-12h18" />
                      </button>
                    </div>
                    <div className="meta" style={{ marginTop: 8 }}>External links</div>
                    <ExternalRefEditor
                      refs={state.parseExternalRefsText(state.editNoteExternalRefsText)}
                      onRemoveIndex={(idx) => state.setEditNoteExternalRefsText((prev: string) => state.removeExternalRefByIndex(prev, idx))}
                      onAdd={(ref) =>
                        state.setEditNoteExternalRefsText((prev: string) => state.externalRefsToText([...state.parseExternalRefsText(prev), ref]))
                      }
                    />
                    <div className="meta" style={{ marginTop: 8 }}>File attachments</div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <button
                        className="status-chip"
                        type="button"
                        onClick={() => state.noteFileInputRef.current?.click()}
                      >
                        Upload file
                      </button>
                      <input
                        ref={state.noteFileInputRef}
                        type="file"
                        style={{ display: 'none' }}
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          e.currentTarget.value = ''
                          if (!file || !state.selectedNote) return
                          try {
                            const ref = await actions.uploadAttachmentRef(file, { project_id: state.selectedNote.project_id, note_id: state.selectedNote.id })
                            state.setEditNoteAttachmentRefsText((prev: string) => state.attachmentRefsToText([...state.parseAttachmentRefsText(prev), ref]))
                          } catch (err) {
                            state.setUiError(state.toErrorMessage(err, 'Upload failed'))
                          }
                        }}
                      />
                    </div>
                    <AttachmentRefList
                      refs={state.parseAttachmentRefsText(state.editNoteAttachmentRefsText)}
                      workspaceId={state.workspaceId}
                      userId={state.userId}
                      onRemovePath={(path) => {
                        state.setEditNoteAttachmentRefsText((prev: string) => state.removeAttachmentByPath(prev, path))
                      }}
                    />
                    <div className="row wrap resource-meta-row" style={{ marginTop: 10 }}>
                      <div className="meta">Created by: {state.selectedNoteCreator}</div>
                      {state.selectedNoteTimeMeta && <div className="meta">{state.selectedNoteTimeMeta.label}: {state.toUserDateTime(state.selectedNoteTimeMeta.value, state.userTimezone)}</div>}
                    </div>
                  </div>
                )}

                {state.showTagPicker && isSelected && (
                  <div className="drawer open" onClick={() => state.setShowTagPicker(false)}>
                    <div className="drawer-body tag-picker-body" onClick={(e) => e.stopPropagation()}>
                      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
                        <h3 style={{ margin: 0 }}>Tags</h3>
                        <button className="action-icon" onClick={() => state.setShowTagPicker(false)} title="Close" aria-label="Close">
                          <Icon path="M6 6l12 12M18 6 6 18" />
                        </button>
                      </div>
                      <input
                        value={state.tagPickerQuery}
                        onChange={(e) => state.setTagPickerQuery(e.target.value)}
                        placeholder="Search or create tag"
                        autoFocus
                      />
                      <div className="tag-picker-list" role="listbox" aria-label="Tag list">
                        {state.filteredNoteTags.map((t: string) => {
                          const selected = state.currentNoteTagsLower.has(t.toLowerCase())
                          return (
                            <button
                              key={t}
                              className={`tag-picker-item ${selected ? 'selected' : ''}`}
                              onClick={() => state.toggleNoteTag(t)}
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
                        {state.filteredNoteTags.length === 0 && <div className="meta">No tags found.</div>}
                      </div>
                      {state.canCreateTag && (
                        <button
                          className="primary tag-picker-create"
                          onClick={() => {
                            state.addNoteTag(state.tagPickerQuery)
                            state.setShowTagPicker(false)
                          }}
                          title="Create tag"
                          aria-label="Create tag"
                        >
                          Create "{state.tagPickerQuery.trim()}"
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
