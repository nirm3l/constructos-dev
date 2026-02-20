import React from 'react'
import type { Note, NoteGroup } from '../../types'
import { MarkdownView } from '../../markdown/MarkdownView'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import { AttachmentRefList, ExternalRefEditor, ExternalRefList, Icon, MarkdownModeToggle } from '../shared/uiHelpers'

type NoteSection = {
  key: string
  groupId: string | null
  name: string
  color: string | null
  notes: Note[]
  managed: boolean
}

export function NotesPanel({
  state,
  actions,
}: {
  state: any
  actions: any
}) {
  const noteGroups: NoteGroup[] = state.noteGroups?.data?.items ?? []
  const noteItems: Note[] = state.notes.data?.items ?? []
  const selectedGroupFilter = String(state.noteGroupFilterId || '')

  const filteredNotes = React.useMemo(() => {
    if (!selectedGroupFilter) return noteItems
    return noteItems.filter((note) => note.note_group_id === selectedGroupFilter || !note.note_group_id)
  }, [noteItems, selectedGroupFilter])

  const ungroupedNotes = React.useMemo(
    () => filteredNotes.filter((note) => !note.note_group_id),
    [filteredNotes]
  )

  const noteSections = React.useMemo<NoteSection[]>(() => {
    if (noteGroups.length === 0) return []

    const sourceGroups = selectedGroupFilter
      ? noteGroups.filter((group) => group.id === selectedGroupFilter)
      : noteGroups

    return sourceGroups.map((group) => ({
      key: group.id,
      groupId: group.id,
      name: group.name,
      color: group.color,
      notes: filteredNotes.filter((note) => note.note_group_id === group.id),
      managed: true,
    }))
  }, [filteredNotes, noteGroups, selectedGroupFilter])

  const hasGroups = noteGroups.length > 0
  const [draggingNoteId, setDraggingNoteId] = React.useState<string | null>(null)
  const [dropTargetKey, setDropTargetKey] = React.useState<string | null>(null)

  const [collapsedSectionMap, setCollapsedSectionMap] = React.useState<Record<string, boolean>>({})

  React.useEffect(() => {
    setCollapsedSectionMap((prev) => {
      const allowed = new Set(noteSections.map((section) => section.key))
      let changed = false
      const next: Record<string, boolean> = {}
      for (const [key, value] of Object.entries(prev)) {
        if (!allowed.has(key)) {
          changed = true
          continue
        }
        next[key] = value
      }
      return changed ? next : prev
    })
  }, [noteSections])

  const toggleSection = React.useCallback((sectionKey: string) => {
    setCollapsedSectionMap((prev) => ({ ...prev, [sectionKey]: !prev[sectionKey] }))
  }, [])

  const createGroupBusy = Boolean(state.createNoteGroupMutation?.isPending)
  const updateGroupBusy = Boolean(state.patchNoteGroupMutation?.isPending)
  const deleteGroupBusy = Boolean(state.deleteNoteGroupMutation?.isPending)
  const reorderGroupBusy = Boolean(state.reorderNoteGroupsMutation?.isPending)
  const moveNoteBusy = Boolean(state.moveNoteToGroupMutation?.isPending)
  const groupActionBusy = createGroupBusy || updateGroupBusy || deleteGroupBusy || reorderGroupBusy

  const createNoteGroup = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const rawName = window.prompt('New note group name')
    if (rawName == null) return
    const name = rawName.trim()
    if (!name) return
    state.createNoteGroupMutation.mutate({ name })
  }, [state.createNoteGroupMutation])

  const renameNoteGroup = React.useCallback((group: NoteGroup) => {
    if (typeof window === 'undefined') return
    const rawName = window.prompt('Rename note group', group.name)
    if (rawName == null) return
    const name = rawName.trim()
    if (!name || name === group.name) return
    state.patchNoteGroupMutation.mutate({ noteGroupId: group.id, name })
  }, [state.patchNoteGroupMutation])

  const deleteNoteGroupById = React.useCallback((group: NoteGroup) => {
    if (typeof window === 'undefined') return
    const ok = window.confirm(`Delete note group "${group.name}"? Linked notes will become ungrouped.`)
    if (!ok) return
    state.deleteNoteGroupMutation.mutate(group.id)
  }, [state.deleteNoteGroupMutation])

  const moveNoteGroup = React.useCallback((groupId: string, direction: -1 | 1) => {
    const orderedIds = noteGroups.map((group) => group.id)
    const index = orderedIds.indexOf(groupId)
    if (index < 0) return
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= orderedIds.length) return
    const nextOrdered = [...orderedIds]
    const [moved] = nextOrdered.splice(index, 1)
    if (!moved) return
    nextOrdered.splice(nextIndex, 0, moved)
    state.reorderNoteGroupsMutation.mutate(nextOrdered)
  }, [noteGroups, state.reorderNoteGroupsMutation])

  const noteById = React.useMemo(() => {
    const out = new Map<string, Note>()
    for (const note of noteItems) out.set(note.id, note)
    return out
  }, [noteItems])

  const moveDraggedNote = React.useCallback((noteId: string, nextGroupId: string | null) => {
    const note = noteById.get(noteId)
    if (!note || !state.moveNoteToGroupMutation) return
    const currentGroupId = note.note_group_id ?? null
    if (currentGroupId === nextGroupId) return
    state.moveNoteToGroupMutation.mutate({ noteId, note_group_id: nextGroupId })
  }, [noteById, state.moveNoteToGroupMutation])

  const onNoteDragStart = React.useCallback((event: React.DragEvent<HTMLDivElement>, noteId: string) => {
    if (moveNoteBusy) return
    setDraggingNoteId(noteId)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', noteId)
  }, [moveNoteBusy])

  const onNoteDragEnd = React.useCallback(() => {
    setDraggingNoteId(null)
    setDropTargetKey(null)
  }, [])

  const onSectionDrop = React.useCallback((event: React.DragEvent<HTMLDivElement>, nextGroupId: string | null) => {
    event.preventDefault()
    const draggedId = event.dataTransfer.getData('text/plain') || draggingNoteId || ''
    setDropTargetKey(null)
    setDraggingNoteId(null)
    if (!draggedId) return
    moveDraggedNote(draggedId, nextGroupId)
  }, [draggingNoteId, moveDraggedNote])

  const maybeAutoScrollWhileDragging = React.useCallback((event: React.DragEvent) => {
    if (typeof window === 'undefined') return
    const edgeThreshold = 96
    const scrollStep = 20
    const y = event.clientY
    const viewportHeight = window.innerHeight
    if (y > viewportHeight - edgeThreshold) {
      window.scrollBy(0, scrollStep)
      return
    }
    if (y < edgeThreshold) {
      window.scrollBy(0, -scrollStep)
    }
  }, [])

  const renderNoteRow = (n: Note) => {
    const isOpen = state.selectedNoteId === n.id
    const isSelected = state.selectedNote?.id === n.id
    const displayTitle = isSelected ? state.editNoteTitle || 'Untitled' : n.title || 'Untitled'
    const selectedEditorGroupId = String(state.editNoteGroupId || '')
    const hasSelectedEditorGroup = selectedEditorGroupId
      ? noteGroups.some((group) => group.id === selectedEditorGroupId)
      : true

    return (
      <div
        key={n.id}
        className={`note-row note-draggable ${isOpen ? 'open selected' : ''}`}
        onClick={() => {
          const changed = state.toggleNoteEditor(n.id)
          if (!changed) return
          state.setShowTagPicker(false)
          state.setTagPickerQuery('')
        }}
        draggable={!isOpen && !moveNoteBusy}
        onDragStart={(event) => onNoteDragStart(event, n.id)}
        onDragEnd={onNoteDragEnd}
        aria-grabbed={draggingNoteId === n.id}
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
        {(n.specification_id || n.task_id) && (
          <div className="row wrap" onClick={(e) => e.stopPropagation()}>
            {n.task_id && (
              <button
                className="pill subtle task-project-pill"
                onClick={() => state.openTask(n.task_id as string, n.project_id)}
                title="Open linked task"
                aria-label="Open linked task"
              >
                <Icon path="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                <span>{state.taskNameMap[n.task_id] || `Task ${String(n.task_id).slice(0, 8)}`}</span>
              </button>
            )}
            {n.specification_id && (
              <button
                className="pill subtle task-project-pill task-spec-pill"
                onClick={() => state.openSpecification(n.specification_id as string, n.project_id)}
                title="Open linked specification"
                aria-label="Open linked specification"
              >
                <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
                <span>{state.specificationNameMap[n.specification_id] || `Specification ${String(n.specification_id).slice(0, 8)}`}</span>
              </button>
            )}
          </div>
        )}
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
                  <button
                    className="action-icon"
                    onClick={() => state.unpinNoteMutation.mutate(state.selectedNote.id)}
                    disabled={state.unpinNoteMutation.isPending}
                    title="Unpin"
                    aria-label="Unpin"
                  >
                    <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                  </button>
                ) : (
                  <button
                    className="action-icon"
                    onClick={() => state.pinNoteMutation.mutate(state.selectedNote.id)}
                    disabled={state.pinNoteMutation.isPending}
                    title="Pin"
                    aria-label="Pin"
                  >
                    <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                  </button>
                )}
                {state.selectedNote.archived ? (
                  <button
                    className="action-icon"
                    onClick={() => state.restoreNoteMutation.mutate(state.selectedNote.id)}
                    disabled={state.restoreNoteMutation.isPending}
                    title="Restore"
                    aria-label="Restore"
                  >
                    <Icon path="M20 16v5H4v-5M12 3v12M7 8l5-5 5 5" />
                  </button>
                ) : (
                  <button
                    className="action-icon"
                    onClick={() => state.archiveNoteMutation.mutate(state.selectedNote.id)}
                    disabled={state.archiveNoteMutation.isPending}
                    title="Archive"
                    aria-label="Archive"
                  >
                    <Icon path="M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6" />
                  </button>
                )}
                <span className="action-separator" aria-hidden="true" />
                <button
                  className="action-icon danger-ghost"
                  onClick={() => state.deleteNoteMutation.mutate(state.selectedNote.id)}
                  disabled={state.deleteNoteMutation.isPending}
                  title="Delete"
                  aria-label="Delete"
                >
                  <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                </button>
              </div>
            </div>

            <label className="field-control" style={{ marginBottom: 8 }}>
              <span className="field-label">Group</span>
              <select value={state.editNoteGroupId} onChange={(e) => state.setEditNoteGroupId(e.target.value)}>
                <option value="">Ungrouped</option>
                {!hasSelectedEditorGroup && selectedEditorGroupId && (
                  <option value={selectedEditorGroupId}>
                    Missing group ({selectedEditorGroupId.slice(0, 8)})
                  </option>
                )}
                {noteGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>

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
              <div className="tag-picker-input-row">
                <input
                  value={state.tagPickerQuery}
                  onChange={(e) => state.setTagPickerQuery(e.target.value)}
                  placeholder="Search or create tag"
                  autoFocus
                />
                <button
                  className="status-chip"
                  type="button"
                  onClick={() => state.setShowTagPicker(false)}
                  title="Done"
                  aria-label="Done"
                >
                  Done
                </button>
              </div>
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
  }

  return (
    <section className="card">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Notes ({state.notes.data?.total ?? 0})</h2>
        <div className="row" style={{ gap: 6 }}>
          <button
            className="status-chip"
            type="button"
            onClick={createNoteGroup}
            disabled={groupActionBusy}
            title="Create note group"
            aria-label="Create note group"
          >
            + Group
          </button>
          <button
            className="action-icon primary"
            onClick={() => state.createNoteMutation.mutate({ note_group_id: state.noteGroupFilterId || null })}
            disabled={state.createNoteMutation.isPending}
            title="New note"
            aria-label="New note"
          >
            <Icon path="M12 5v14M5 12h14" />
          </button>
        </div>
      </div>

      <div className="notes-shell">
        <div
          className="row wrap notes-tag-filters"
          style={{ justifyContent: noteGroups.length > 0 ? 'space-between' : 'flex-end', gap: 8 }}
        >
          {noteGroups.length > 0 && (
            <label className="row wrap" style={{ gap: 6, alignItems: 'center' }}>
              <span className="meta">Group filter</span>
              <select
                value={state.noteGroupFilterId}
                onChange={(e) => state.setNoteGroupFilterId(e.target.value)}
              >
                <option value="">All groups</option>
                {noteGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="row archived-toggle notes-archived-filter">
            <input type="checkbox" checked={state.noteArchived} onChange={(e) => state.setNoteArchived(e.target.checked)} />
            Archived
          </label>
        </div>

        <div className="row wrap notes-tag-filters">
          <PopularTagFilters
            tags={state.noteTagSuggestions}
            selectedTags={state.noteTags}
            onToggleTag={state.toggleNoteFilterTag}
            onClear={() => state.clearNoteFilterTags()}
            getTagUsage={state.getTagUsage}
            idPrefix="note-filter"
          />
        </div>

        <div className="task-list notes-list">
          {state.notes.isLoading && <div className="notice">Loading notes...</div>}

          {!state.notes.isLoading && hasGroups && (
            <div
              className="task-list-dropzone notes-items-stack"
              style={dropTargetKey === 'notes:plain' ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10, padding: 6, marginBottom: 10 } : { marginBottom: 10 }}
              onDragOver={(event) => {
                event.preventDefault()
                maybeAutoScrollWhileDragging(event)
                setDropTargetKey('notes:plain')
              }}
              onDragLeave={() => {
                setDropTargetKey((prev) => (prev === 'notes:plain' ? null : prev))
              }}
              onDrop={(event) => onSectionDrop(event, null)}
            >
              {ungroupedNotes.map(renderNoteRow)}
              {ungroupedNotes.length === 0 && (
                <div className="meta" style={{ minHeight: 56, display: 'grid', alignItems: 'center' }}>
                  Drop note here to remove it from a group.
                </div>
              )}
            </div>
          )}

          {!state.notes.isLoading && noteSections.map((section) => {
            const collapsed = Boolean(collapsedSectionMap[section.key])
            const sectionGroup = section.groupId
              ? noteGroups.find((group) => group.id === section.groupId) ?? null
              : null
            const sectionIndex = sectionGroup ? noteGroups.findIndex((group) => group.id === sectionGroup.id) : -1
            const canMoveUp = sectionGroup ? sectionIndex > 0 : false
            const canMoveDown = sectionGroup ? sectionIndex >= 0 && sectionIndex < noteGroups.length - 1 : false
            const listDropKey = `notes:${section.key}`
            const isListDropTarget = dropTargetKey === listDropKey

            return (
              <div
                key={section.key}
                style={{
                  borderLeft: section.color ? `3px solid ${section.color}` : '3px solid transparent',
                  paddingLeft: 8,
                  marginBottom: 10,
                }}
              >
                <div className="row wrap group-section-head">
                  <button
                    className="pill subtle group-toggle-pill"
                    type="button"
                    onClick={() => toggleSection(section.key)}
                    aria-expanded={!collapsed}
                    aria-label={collapsed ? `Expand ${section.name}` : `Collapse ${section.name}`}
                  >
                    <span>{collapsed ? '▸' : '▾'}</span>
                    <span>{section.name}</span>
                    <span className="meta">({section.notes.length})</span>
                  </button>

                  {sectionGroup && section.managed && (
                    <div className="group-actions">
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => moveNoteGroup(sectionGroup.id, -1)}
                        disabled={!canMoveUp || groupActionBusy}
                        title="Move group up"
                        aria-label="Move group up"
                      >
                        <Icon path="M12 19V5M5 12l7-7 7 7" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => moveNoteGroup(sectionGroup.id, 1)}
                        disabled={!canMoveDown || groupActionBusy}
                        title="Move group down"
                        aria-label="Move group down"
                      >
                        <Icon path="M12 5v14M5 12l7 7 7-7" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => renameNoteGroup(sectionGroup)}
                        disabled={groupActionBusy}
                        title="Rename group"
                        aria-label="Rename group"
                      >
                        <Icon path="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                      </button>
                      <button
                        className="action-icon group-action-icon"
                        type="button"
                        onClick={() => deleteNoteGroupById(sectionGroup)}
                        disabled={groupActionBusy}
                        title="Delete group"
                        aria-label="Delete group"
                      >
                        <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                      </button>
                    </div>
                  )}
                </div>

                {!collapsed && (
                  <div
                    className="task-list-dropzone notes-items-stack"
                    style={isListDropTarget ? { outline: '2px dashed rgba(59, 130, 246, 0.55)', borderRadius: 10, padding: 6 } : undefined}
                    onDragOver={(event) => {
                      event.preventDefault()
                      maybeAutoScrollWhileDragging(event)
                      setDropTargetKey(listDropKey)
                    }}
                    onDragLeave={() => {
                      setDropTargetKey((prev) => (prev === listDropKey ? null : prev))
                    }}
                    onDrop={(event) => onSectionDrop(event, section.groupId)}
                  >
                    {section.notes.map(renderNoteRow)}
                    {section.notes.length === 0 && (
                      <div className="meta" style={{ minHeight: 56, display: 'grid', alignItems: 'center' }}>
                        Drop note here to move it to this group.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {!state.notes.isLoading && !hasGroups && filteredNotes.length > 0 && (
            <div className="notes-items-stack">
              {filteredNotes.map(renderNoteRow)}
            </div>
          )}

          {!state.notes.isLoading && (
            ((hasGroups && noteSections.length === 0 && ungroupedNotes.length === 0) ||
              (!hasGroups && filteredNotes.length === 0)) && (
              <div className="notice">No notes in this project.</div>
            )
          )}
        </div>
      </div>
    </section>
  )
}
