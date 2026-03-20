import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Accordion from '@radix-ui/react-accordion'
import * as Dialog from '@radix-ui/react-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import type { Note, NoteGroup } from '../../types'
import type { ProjectGitRepositoryTarget } from '../../utils/gitRepositoryLinks'
import { parseProjectGitRepositoryExternalRef } from '../../utils/gitRepositoryLinks'
import { MarkdownView } from '../../markdown/MarkdownView'
import { PopularTagFilters } from '../shared/PopularTagFilters'
import { ProjectGitRepositoryDialog } from '../projects/ProjectGitRepositoryDialog'
import {
  AttachmentRefList,
  ExternalRefEditor,
  ExternalRefList,
  Icon,
  MarkdownModeToggle,
  MarkdownSplitPane,
} from '../shared/uiHelpers'

type NoteSection = {
  key: string
  groupId: string | null
  name: string
  color: string | null
  notes: Note[]
  managed: boolean
}

type NoteGroupDialogTarget = {
  id: string
  name: string
}

type NoteDeleteDialogTarget = {
  id: string
  title: string
}

type NoteGroupActionsMenuProps = {
  groupName: string
  busy: boolean
  onRename: () => void
  onDelete: () => void
}

function NoteGroupActionsMenu({
  groupName,
  busy,
  onRename,
  onDelete,
}: NoteGroupActionsMenuProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className="action-icon group-action-icon group-action-menu-trigger"
          type="button"
          title={`Manage group ${groupName}`}
          aria-label={`Manage group ${groupName}`}
          disabled={busy}
        >
          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="task-group-menu-content" sideOffset={8} align="end">
          <DropdownMenu.Item
            className="task-group-menu-item"
            onSelect={onRename}
            disabled={busy}
          >
            <Icon path="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
            <span>Rename group</span>
          </DropdownMenu.Item>
          <DropdownMenu.Item
            className="task-group-menu-item task-group-menu-item-danger"
            onSelect={onDelete}
            disabled={busy}
          >
            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
            <span>Delete group</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
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

  const filteredNotes = React.useMemo(() => noteItems, [noteItems])

  const ungroupedNotes = React.useMemo(
    () => filteredNotes.filter((note) => !note.note_group_id),
    [filteredNotes]
  )

  const noteSections = React.useMemo<NoteSection[]>(() => {
    if (noteGroups.length === 0) return []

    return noteGroups.map((group) => ({
      key: group.id,
      groupId: group.id,
      name: group.name,
      color: group.color,
      notes: filteredNotes.filter((note) => note.note_group_id === group.id),
      managed: true,
    }))
  }, [filteredNotes, noteGroups])

  const hasGroups = noteGroups.length > 0
  const [draggingNoteId, setDraggingNoteId] = React.useState<string | null>(null)
  const [dropTargetKey, setDropTargetKey] = React.useState<string | null>(null)
  const [openSectionKeys, setOpenSectionKeys] = React.useState<string[]>([])
  const [noteEditorOpenSections, setNoteEditorOpenSections] = React.useState<string[]>([])
  const [notePreviewDialog, setNotePreviewDialog] = React.useState<{ title: string, body: string } | null>(null)
  const [gitRepositoryDialogState, setGitRepositoryDialogState] = React.useState<{
    projectId: string
    target: ProjectGitRepositoryTarget | null
  } | null>(null)

  React.useEffect(() => {
    const allKeys = noteSections.map((section) => section.key)
    setOpenSectionKeys((previousOpenKeys) => {
      const allowed = new Set(allKeys)
      const filteredOpenKeys = previousOpenKeys.filter((key) => allowed.has(key))
      const existing = new Set(filteredOpenKeys)
      const missing = allKeys.filter((key) => !existing.has(key))
      const next = [...filteredOpenKeys, ...missing]
      if (next.length === previousOpenKeys.length && next.every((key, index) => key === previousOpenKeys[index])) {
        return previousOpenKeys
      }
      return next
    })
  }, [noteSections])

  React.useEffect(() => {
    setNoteEditorOpenSections([])
  }, [state.selectedNote?.id])
  const openGitRepositoryFromRef = React.useCallback((projectId: string, ref: Note['external_refs'][number]) => {
    const target = parseProjectGitRepositoryExternalRef(ref)
    const normalizedProjectId = String(projectId || '').trim()
    if (!target || !normalizedProjectId) return false
    setGitRepositoryDialogState({ projectId: normalizedProjectId, target })
    return true
  }, [])


  const createGroupBusy = Boolean(state.createNoteGroupMutation?.isPending)
  const updateGroupBusy = Boolean(state.patchNoteGroupMutation?.isPending)
  const deleteGroupBusy = Boolean(state.deleteNoteGroupMutation?.isPending)
  const reorderGroupBusy = Boolean(state.reorderNoteGroupsMutation?.isPending)
  const moveNoteBusy = Boolean(state.moveNoteToGroupMutation?.isPending)
  const groupActionBusy = createGroupBusy || updateGroupBusy || deleteGroupBusy || reorderGroupBusy
  const noteDeleteBusy = Boolean(state.deleteNoteMutation?.isPending)
  const [noteGroupDialogMode, setNoteGroupDialogMode] = React.useState<'create' | 'rename' | null>(null)
  const [noteGroupDialogName, setNoteGroupDialogName] = React.useState('')
  const [noteGroupDialogTarget, setNoteGroupDialogTarget] = React.useState<NoteGroupDialogTarget | null>(null)
  const [deleteNoteGroupPrompt, setDeleteNoteGroupPrompt] = React.useState<NoteGroupDialogTarget | null>(null)
  const [deleteNotePrompt, setDeleteNotePrompt] = React.useState<NoteDeleteDialogTarget | null>(null)

  const closeNoteGroupDialog = React.useCallback(() => {
    setNoteGroupDialogMode(null)
    setNoteGroupDialogName('')
    setNoteGroupDialogTarget(null)
  }, [])

  const openCreateNoteGroupDialog = React.useCallback(() => {
    setNoteGroupDialogMode('create')
    setNoteGroupDialogName('')
    setNoteGroupDialogTarget(null)
  }, [])

  const openRenameNoteGroupDialog = React.useCallback((groupId: string, currentName: string) => {
    setNoteGroupDialogMode('rename')
    setNoteGroupDialogName(currentName)
    setNoteGroupDialogTarget({ id: groupId, name: currentName })
  }, [])

  const submitNoteGroupDialog = React.useCallback(() => {
    const name = noteGroupDialogName.trim()
    if (!name) return

    if (noteGroupDialogMode === 'create') {
      state.createNoteGroupMutation.mutate(
        { name },
        { onSuccess: () => closeNoteGroupDialog() }
      )
      return
    }

    if (noteGroupDialogMode === 'rename' && noteGroupDialogTarget) {
      if (name === noteGroupDialogTarget.name) {
        closeNoteGroupDialog()
        return
      }
      state.patchNoteGroupMutation.mutate(
        { noteGroupId: noteGroupDialogTarget.id, name },
        { onSuccess: () => closeNoteGroupDialog() }
      )
    }
  }, [
    closeNoteGroupDialog,
    noteGroupDialogMode,
    noteGroupDialogName,
    noteGroupDialogTarget,
    state.createNoteGroupMutation,
    state.patchNoteGroupMutation,
  ])

  const requestDeleteNoteGroup = React.useCallback((groupId: string, groupName: string) => {
    setDeleteNoteGroupPrompt({ id: groupId, name: groupName })
  }, [])

  const confirmDeleteNoteGroup = React.useCallback(() => {
    if (!deleteNoteGroupPrompt) return
    state.deleteNoteGroupMutation.mutate(
      deleteNoteGroupPrompt.id,
      { onSuccess: () => setDeleteNoteGroupPrompt(null) }
    )
  }, [deleteNoteGroupPrompt, state.deleteNoteGroupMutation])

  const requestDeleteNote = React.useCallback((note: Pick<Note, 'id' | 'title'>) => {
    setDeleteNotePrompt({
      id: note.id,
      title: (note.title || '').trim() || 'Untitled',
    })
  }, [])

  const confirmDeleteNote = React.useCallback(() => {
    if (!deleteNotePrompt) return
    state.deleteNoteMutation.mutate(
      deleteNotePrompt.id,
      { onSuccess: () => setDeleteNotePrompt(null) }
    )
  }, [deleteNotePrompt, state.deleteNoteMutation])

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

  const createNoteWithGroup = React.useCallback((noteGroupId: string | null) => {
    state.createNoteMutation.mutate({
      note_group_id: noteGroupId,
      force_new: true,
    })
  }, [state.createNoteMutation])

  const openNotePreviewDialog = React.useCallback((note: Note) => {
    const isSelected = String(state.selectedNoteId || '').trim() === String(note.id || '').trim()
    setNotePreviewDialog({
      title: isSelected ? String(state.editNoteTitle || '').trim() || 'Untitled' : String(note.title || '').trim() || 'Untitled',
      body: isSelected ? String(state.editNoteBody || '') : String(note.body || ''),
    })
  }, [state])

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

  const ensureNoteEditorSectionOpen = React.useCallback((sectionKey: string) => {
    setNoteEditorOpenSections((previous) => (
      previous.includes(sectionKey) ? previous : [...previous, sectionKey]
    ))
  }, [])

  const handleNoteFileInputChange = React.useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    event.currentTarget.value = ''
    if (files.length === 0 || !state.selectedNote) return
    const uploadedRefs: any[] = []
    let firstErrorMessage = ''
    for (const file of files) {
      try {
        const ref = await actions.uploadAttachmentRef(file, {
          project_id: state.selectedNote.project_id,
          note_id: state.selectedNote.id,
        })
        uploadedRefs.push(ref)
      } catch (err) {
        if (!firstErrorMessage) firstErrorMessage = state.toErrorMessage(err, 'Upload failed')
      }
    }
    if (uploadedRefs.length > 0) {
      state.setEditNoteAttachmentRefsText((previous: string) => state.attachmentRefsToText([
        ...state.parseAttachmentRefsText(previous),
        ...uploadedRefs,
      ]))
    }
    if (firstErrorMessage) {
      state.setUiError(firstErrorMessage)
    }
  }, [
    actions,
    state.attachmentRefsToText,
    state.parseAttachmentRefsText,
    state.selectedNote,
    state.setEditNoteAttachmentRefsText,
    state.setUiError,
    state.toErrorMessage,
  ])

  const noteGroupDialogOpen = noteGroupDialogMode !== null
  const noteGroupDialogSubmitDisabled =
    groupActionBusy ||
    !noteGroupDialogName.trim() ||
    (noteGroupDialogMode === 'rename' &&
      noteGroupDialogTarget !== null &&
      noteGroupDialogName.trim() === noteGroupDialogTarget.name)
  const noteGroupDialogTitle = noteGroupDialogMode === 'rename' ? 'Rename note group' : 'Create note group'
  const noteGroupDialogDescription = noteGroupDialogMode === 'rename'
    ? 'Set a new name for this note group.'
    : 'Create a new group to organize notes in the list.'
  const noteGroupDialogSubmitLabel = noteGroupDialogMode === 'rename' ? 'Save' : 'Create'

  const renderNoteRow = (n: Note) => {
    const isOpen = state.selectedNoteId === n.id
    const isSelected = state.selectedNote?.id === n.id
    const displayTitle = isSelected ? state.editNoteTitle || 'Untitled' : n.title || 'Untitled'
    const selectedEditorGroupId = String(state.editNoteGroupId || '')
    const selectedEditorGroupValue = selectedEditorGroupId || '__ungrouped__'
    const hasSelectedEditorGroup = selectedEditorGroupId
      ? noteGroups.some((group) => group.id === selectedEditorGroupId)
      : true
    const externalRefCount = n.external_refs?.length ?? 0
    const attachmentRefCount = n.attachment_refs?.length ?? 0
    const hasResources = externalRefCount > 0 || attachmentRefCount > 0
    const openNoteFromMenu = () => {
      if (isOpen) return
      const changed = state.toggleNoteEditor(n.id)
      if (!changed) return
      state.setShowTagPicker(false)
      state.setTagPickerQuery('')
    }
    const togglePinFromMenu = () => {
      if (n.pinned) {
        state.unpinNoteMutation.mutate(n.id)
        return
      }
      state.pinNoteMutation.mutate(n.id)
    }
    const toggleArchiveFromMenu = () => {
      if (n.archived) {
        state.restoreNoteMutation.mutate(n.id)
        return
      }
      state.archiveNoteMutation.mutate(n.id)
    }
    const addNoteTagFromQuery = () => {
      const value = String(state.tagPickerQuery || '').trim()
      if (!value) return
      state.addNoteTag(value)
      state.setTagPickerQuery('')
    }
    const editorExternalRefs = state.parseExternalRefsText(state.editNoteExternalRefsText)
    const editorAttachmentRefs = state.parseAttachmentRefsText(state.editNoteAttachmentRefsText)
    const editorExternalLinksMeta = editorExternalRefs.length > 0
      ? `${editorExternalRefs.length} linked`
      : 'No links added'
    const editorAttachmentsMeta = editorAttachmentRefs.length > 0
      ? `${editorAttachmentRefs.length} files attached`
      : 'No attachments'

    return (
      <div
        key={n.id}
        id={`note-row-${n.id}`}
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
          <div className="note-title-main">
            {n.pinned && (
              <span className="badge icon-badge" title="Pinned" aria-label="Pinned">
                <Icon path="M6 2h12v20l-6-4-6 4V2z" />
              </span>
            )}
            {n.archived && <span className="badge">Archived</span>}
            <strong>{displayTitle}</strong>
          </div>
          <div
            className="note-row-actions"
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <button
              className="action-icon note-row-actions-trigger"
              type="button"
              title="Copy note link"
              aria-label="Copy note link"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation()
                actions.copyShareLink({ tab: 'notes', projectId: n.project_id, noteId: n.id })
              }}
            >
              <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
            </button>
            <button
              className="action-icon note-row-actions-trigger"
              type="button"
              title="Open preview popup"
              aria-label="Open preview popup"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation()
                openNotePreviewDialog(n)
              }}
            >
              <Icon path="M8 3H5a2 2 0 0 0-2 2v3m16 0V5a2 2 0 0 0-2-2h-3M8 21H5a2 2 0 0 1-2-2v-3m16 0v3a2 2 0 0 1-2 2h-3" />
            </button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button
                  className="action-icon note-row-actions-trigger"
                  type="button"
                  title="Note actions"
                  aria-label="Note actions"
                >
                  <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                  <DropdownMenu.Item
                    className="task-group-menu-item"
                    onSelect={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      openNoteFromMenu()
                    }}
                    disabled={isOpen}
                  >
                    <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                    <span>{isOpen ? 'Editor open' : 'Open editor'}</span>
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className="task-group-menu-item"
                    onSelect={(event) => {
                      event.stopPropagation()
                      openNotePreviewDialog(n)
                    }}
                  >
                    <Icon path="M8 3H5a2 2 0 0 0-2 2v3m16 0V5a2 2 0 0 0-2-2h-3M8 21H5a2 2 0 0 1-2-2v-3m16 0v3a2 2 0 0 1-2 2h-3" />
                    <span>Preview popup</span>
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator className="task-group-menu-separator" />
                  <DropdownMenu.Item className="task-group-menu-item" onSelect={togglePinFromMenu}>
                    <Icon path="M6 2h12v20l-6-4-6 4V2z" />
                    <span>{n.pinned ? 'Unpin note' : 'Pin note'}</span>
                  </DropdownMenu.Item>
                  <DropdownMenu.Item className="task-group-menu-item" onSelect={toggleArchiveFromMenu}>
                    <Icon path={n.archived ? 'M20 16v5H4v-5M12 3v12M7 8l5-5 5 5' : 'M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6'} />
                    <span>{n.archived ? 'Restore note' : 'Archive note'}</span>
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator className="task-group-menu-separator" />
                  <DropdownMenu.Item
                    className="task-group-menu-item task-group-menu-item-danger"
                    onSelect={() => requestDeleteNote({ id: n.id, title: n.title })}
                    disabled={noteDeleteBusy}
                  >
                    <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                    <span>Delete note</span>
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
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
              <button
                key={t}
                type="button"
                className="tag-mini tag-clickable"
                onClick={(event) => {
                  event.stopPropagation()
                  state.toggleNoteFilterTag(t)
                }}
                title={`Filter by tag: ${t}`}
                style={{
                  backgroundColor: `hsl(${state.tagHue(t)}, 70%, 92%)`,
                  borderColor: `hsl(${state.tagHue(t)}, 70%, 78%)`,
                  color: `hsl(${state.tagHue(t)}, 55%, 28%)`
                }}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        <div className="note-snippet">{(n.body || '').replace(/\s+/g, ' ').slice(0, 160) || '(empty)'}</div>
        {hasResources && (
          <div className="note-resource-stack" onClick={(e) => e.stopPropagation()}>
            {externalRefCount > 0 && (
              <div className="note-resource-section">
                <span className="note-resource-label">
                  <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                  <span>Links</span>
                </span>
                <ExternalRefList refs={n.external_refs} onOpenRef={(ref) => openGitRepositoryFromRef(n.project_id, ref)} />
              </div>
            )}
            {attachmentRefCount > 0 && (
              <div className="note-resource-section">
                <span className="note-resource-label">
                  <Icon path="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.2a2 2 0 0 1-2.82-2.83l8.49-8.48" />
                  <span>Files</span>
                </span>
                <AttachmentRefList refs={n.attachment_refs} workspaceId={state.workspaceId} userId={state.userId} />
              </div>
            )}
          </div>
        )}

        {isOpen && isSelected && state.selectedNote && (
          <div
            className="note-accordion"
            onClick={(e) => e.stopPropagation()}
            role="region"
            aria-label="Note editor"
          >
            <div className="note-editor-head">
              <input
                className="note-title-input"
                value={state.editNoteTitle}
                onChange={(e) => state.setEditNoteTitle(e.target.value)}
                placeholder="Title"
              />
            </div>

            <label className="field-control" style={{ marginBottom: 8 }}>
              <span className="field-label">Group</span>
              <Select.Root
                value={selectedEditorGroupValue}
                onValueChange={(value) => state.setEditNoteGroupId(value === '__ungrouped__' ? '' : value)}
              >
                <Select.Trigger className="quickadd-project-trigger taskdrawer-select-trigger notes-group-select-trigger" aria-label="Select note group">
                  <Select.Value placeholder="Select note group" />
                  <Select.Icon asChild>
                    <span className="quickadd-project-trigger-icon" aria-hidden="true">
                      <Icon path="M6 9l6 6 6-6" />
                    </span>
                  </Select.Icon>
                </Select.Trigger>
                <Select.Portal>
                  <Select.Content className="quickadd-project-content taskdrawer-select-content" position="popper" sideOffset={6}>
                    <Select.Viewport className="quickadd-project-viewport">
                      <Select.Item value="__ungrouped__" className="quickadd-project-item">
                        <Select.ItemText>Ungrouped</Select.ItemText>
                        <Select.ItemIndicator className="quickadd-project-item-indicator">
                          <Icon path="M5 13l4 4L19 7" />
                        </Select.ItemIndicator>
                      </Select.Item>
                      {!hasSelectedEditorGroup && selectedEditorGroupId && (
                        <Select.Item value={selectedEditorGroupId} className="quickadd-project-item">
                          <Select.ItemText>{`Missing group (${selectedEditorGroupId.slice(0, 8)})`}</Select.ItemText>
                          <Select.ItemIndicator className="quickadd-project-item-indicator">
                            <Icon path="M5 13l4 4L19 7" />
                          </Select.ItemIndicator>
                        </Select.Item>
                      )}
                      {noteGroups.map((group) => (
                        <Select.Item key={group.id} value={group.id} className="quickadd-project-item">
                          <Select.ItemText>{group.name}</Select.ItemText>
                          <Select.ItemIndicator className="quickadd-project-item-indicator">
                            <Icon path="M5 13l4 4L19 7" />
                          </Select.ItemIndicator>
                        </Select.Item>
                      ))}
                    </Select.Viewport>
                  </Select.Content>
                </Select.Portal>
              </Select.Root>
            </label>

            <div
              className="md-editor-surface"
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <MarkdownModeToggle
                view={state.noteEditorView}
                onChange={state.setNoteEditorView}
                ariaLabel="Note editor view"
              />
              <div className="md-editor-content">
                {state.noteEditorView === 'write' ? (
                  <textarea className="md-textarea" value={state.editNoteBody} onChange={(e) => state.setEditNoteBody(e.target.value)} placeholder="Write Markdown..." />
                ) : state.noteEditorView === 'split' ? (
                  <MarkdownSplitPane
                    left={(
                      <textarea
                        className="md-textarea"
                        value={state.editNoteBody}
                        onChange={(e) => state.setEditNoteBody(e.target.value)}
                        placeholder="Write Markdown..."
                      />
                    )}
                    right={<MarkdownView value={state.editNoteBody} />}
                    ariaLabel="Resize note editor and preview panels"
                  />
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
              <Popover.Root
                open={state.showTagPicker && isSelected}
                onOpenChange={(open) => state.setShowTagPicker(open)}
              >
                <Popover.Trigger asChild>
                  <button className="action-icon" title="Edit tags" aria-label="Edit tags">
                    <Icon path="M3 12h8m-8 6h12m-12-12h18" />
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content className="quickadd-tag-popover notes-tag-popover" side="top" align="end" sideOffset={8}>
                    <div className="quickadd-tag-popover-header">
                      <h4 className="quickadd-tag-popover-title">Note Tags</h4>
                      <button
                        className="status-chip"
                        type="button"
                        onClick={() => state.setShowTagPicker(false)}
                        title="Close"
                        aria-label="Close"
                      >
                        Close
                      </button>
                    </div>
                    <div className="tag-picker-input-row">
                      <input
                        value={state.tagPickerQuery}
                        onChange={(e) => state.setTagPickerQuery(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            e.stopPropagation()
                            addNoteTagFromQuery()
                          }
                        }}
                        placeholder="Search or create tag"
                        autoFocus
                      />
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
                        onClick={addNoteTagFromQuery}
                        title="Create tag"
                        aria-label="Create tag"
                      >
                        Add "{state.tagPickerQuery.trim()}"
                      </button>
                    )}
                    <Popover.Arrow className="quickadd-tag-popover-arrow" />
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>
            </div>
            <input
              ref={state.noteFileInputRef}
              type="file"
              multiple
              style={{ display: 'none' }}
              onChange={handleNoteFileInputChange}
            />
            <Accordion.Root
              type="multiple"
              className="taskdrawer-sections"
              value={noteEditorOpenSections}
              onValueChange={setNoteEditorOpenSections}
            >
              <Accordion.Item value="external-links" className="taskdrawer-section-item taskdrawer-section-links">
                <div className="taskdrawer-section-headrow">
                  <Accordion.Header className="taskdrawer-section-header">
                    <Accordion.Trigger className="taskdrawer-section-trigger">
                      <span className="taskdrawer-section-icon" aria-hidden="true">
                        <Icon path="M14 3h7v7m0-7L10 14M5 7v12h12v-5" />
                      </span>
                      <span className="taskdrawer-section-head">
                        <span className="taskdrawer-section-title">External links</span>
                        <span className="taskdrawer-section-meta">{editorExternalLinksMeta}</span>
                      </span>
                      <span className="taskdrawer-section-badge">{editorExternalRefs.length}</span>
                      <span className="taskdrawer-section-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <button
                    className="status-chip taskdrawer-section-quick-action"
                    type="button"
                    onClick={() => ensureNoteEditorSectionOpen('external-links')}
                    aria-label="Edit external links"
                    title="Edit external links"
                  >
                    <Icon path="M12 20h9M4 16l10.5-10.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
                  </button>
                </div>
                <Accordion.Content className="taskdrawer-section-content">
                  <ExternalRefEditor
                    refs={editorExternalRefs}
                    onRemoveIndex={(idx) => state.setEditNoteExternalRefsText((prev: string) => state.removeExternalRefByIndex(prev, idx))}
                    onOpenRef={(ref) => openGitRepositoryFromRef(state.selectedNote?.project_id || '', ref)}
                    onAdd={(ref) =>
                      state.setEditNoteExternalRefsText((prev: string) => state.externalRefsToText([...state.parseExternalRefsText(prev), ref]))
                    }
                  />
                </Accordion.Content>
              </Accordion.Item>

              <Accordion.Item value="attachments" className="taskdrawer-section-item taskdrawer-section-attachments">
                <div className="taskdrawer-section-headrow">
                  <Accordion.Header className="taskdrawer-section-header">
                    <Accordion.Trigger className="taskdrawer-section-trigger">
                      <span className="taskdrawer-section-icon" aria-hidden="true">
                        <Icon path="M21.44 11.05 12 20.5a5 5 0 1 1-7.07-7.07l9.9-9.9a3.5 3.5 0 1 1 4.95 4.95l-9.2 9.19a2 2 0 1 1-2.83-2.83l8.49-8.48" />
                      </span>
                      <span className="taskdrawer-section-head">
                        <span className="taskdrawer-section-title">File attachments</span>
                        <span className="taskdrawer-section-meta">{editorAttachmentsMeta}</span>
                      </span>
                      <span className="taskdrawer-section-badge">{editorAttachmentRefs.length}</span>
                      <span className="taskdrawer-section-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <button
                    className="status-chip taskdrawer-section-quick-action"
                    type="button"
                    onClick={() => state.noteFileInputRef.current?.click()}
                    aria-label="Upload files"
                    title="Upload files"
                  >
                    <Icon path="M12 3v12m0-12-4 4m4-4 4 4M4 17v3h16v-3" />
                  </button>
                </div>
                <Accordion.Content className="taskdrawer-section-content">
                  <div className="row" style={{ marginBottom: 8 }}>
                    <button className="status-chip" type="button" onClick={() => state.noteFileInputRef.current?.click()}>
                      Upload files
                    </button>
                  </div>
                  <AttachmentRefList
                    refs={editorAttachmentRefs}
                    workspaceId={state.workspaceId}
                    userId={state.userId}
                    onRemovePath={(path) => {
                      state.setEditNoteAttachmentRefsText((prev: string) => state.removeAttachmentByPath(prev, path))
                    }}
                  />
                </Accordion.Content>
              </Accordion.Item>
            </Accordion.Root>
            <div className="row wrap resource-meta-row notes-resource-meta-row" style={{ marginTop: 10 }}>
              <div className="meta">Created by: {state.selectedNoteCreator}</div>
              {state.selectedNoteTimeMeta && <div className="meta">{state.selectedNoteTimeMeta.label}: {state.toUserDateTime(state.selectedNoteTimeMeta.value, state.userTimezone)}</div>}
            </div>
            {(state.noteIsDirty || state.saveNoteMutation.isPending) && (
              <div className="project-editor-savebar note-editor-savebar">
                <div className="project-editor-savebar-meta">
                  <span className="badge unsaved-badge">1 unsaved section</span>
                  <span className="meta">Changed: Note</span>
                </div>
                <button
                  className="status-chip on project-editor-savebar-btn"
                  type="button"
                  onClick={() => state.saveNoteMutation.mutate()}
                  disabled={state.saveNoteMutation.isPending || !state.noteIsDirty}
                  title="Save all note changes"
                  aria-label="Save all note changes"
                >
                  <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                  <span className="project-editor-savebar-btn-label">
                    {state.saveNoteMutation.isPending ? 'Saving...' : 'Save all changes'}
                  </span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <section className="card" data-tour-id="notes-panel">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Notes ({state.notes.data?.total ?? 0})</h2>
        <div className="row wrap notes-create-actions" style={{ gap: 6 }}>
          <button
            className="status-chip notes-group-btn"
            type="button"
            onClick={openCreateNoteGroupDialog}
            disabled={groupActionBusy}
            title="Create note group"
            aria-label="Create note group"
          >
            + Group
          </button>
          <div className="row" style={{ gap: 6 }}>
            <button
              className="status-chip notes-new-note-btn"
              type="button"
              onClick={() => createNoteWithGroup(null)}
              disabled={state.createNoteMutation.isPending}
              title="Create note"
              aria-label="Create note"
            >
              <Icon path="M12 5v14M5 12h14" />
              <span>{state.createNoteMutation.isPending ? 'Creating...' : 'Note'}</span>
            </button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button
                  className="action-icon"
                  type="button"
                  title="More note create options"
                  aria-label="More note create options"
                  disabled={state.createNoteMutation.isPending}
                >
                  <Icon path="M6 9l6 6 6-6" />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content className="task-group-menu-content" sideOffset={8} align="end">
                  <DropdownMenu.Item
                    className="task-group-menu-item"
                    onSelect={() => createNoteWithGroup(null)}
                  >
                    <Icon path="M12 5v14M5 12h14" />
                    <span>Ungrouped note</span>
                  </DropdownMenu.Item>
                  {noteGroups.length > 0 && (
                    <>
                      <DropdownMenu.Separator className="task-group-menu-separator" />
                      {noteGroups.map((group) => (
                        <DropdownMenu.Item
                          key={`create-note-in-${group.id}`}
                          className="task-group-menu-item"
                          onSelect={() => createNoteWithGroup(group.id)}
                        >
                          <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
                          <span>{`Note in ${group.name}`}</span>
                        </DropdownMenu.Item>
                      ))}
                    </>
                  )}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
        </div>
      </div>

      <div className="notes-shell">
        <div
          className="row wrap notes-tag-filters"
          style={{ justifyContent: 'flex-end', gap: 8 }}
        >
          <label className="row archived-toggle notes-archived-filter">
            <input type="checkbox" checked={state.noteArchived} onChange={(e) => state.setNoteArchived(e.target.checked)} />
            Archived
          </label>
        </div>

        {(state.noteTagSuggestions?.length ?? 0) > 0 && (
          <div className="row wrap notes-tag-filters">
            <PopularTagFilters
              tags={state.noteTagSuggestions}
              selectedTags={state.noteTags}
              onToggleTag={state.toggleNoteFilterTag}
              onClear={() => state.clearNoteFilterTags()}
              idPrefix="note-filter"
            />
          </div>
        )}

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
              {ungroupedNotes.length > 0 && ungroupedNotes.map((note) => renderNoteRow(note))}
              {ungroupedNotes.length === 0 && (
                <div className="meta" style={{ minHeight: 56, display: 'grid', alignItems: 'center' }}>
                  Drop note here to remove it from a group.
                </div>
              )}
            </div>
          )}

          {!state.notes.isLoading && (
            <Accordion.Root
              type="multiple"
              value={openSectionKeys}
              onValueChange={setOpenSectionKeys}
              className="tasks-sections-accordion"
            >
              {noteSections.length > 0 && (
                noteSections.map((section) => {
                    const sectionGroup = section.groupId
                      ? noteGroups.find((group) => group.id === section.groupId) ?? null
                      : null
                    const sectionIndex = sectionGroup ? noteGroups.findIndex((group) => group.id === sectionGroup.id) : -1
                    const canMoveUp = sectionGroup ? sectionIndex > 0 : false
                    const canMoveDown = sectionGroup ? sectionIndex >= 0 && sectionIndex < noteGroups.length - 1 : false
                    const listDropKey = `notes:${section.key}`
                    const isListDropTarget = dropTargetKey === listDropKey

                    return (
                      <Accordion.Item
                        key={section.key}
                        value={section.key}
                        className="tasks-section-accordion-item"
                        style={{
                          borderLeft: section.color ? `3px solid ${section.color}` : '3px solid transparent',
                          paddingLeft: 8,
                          marginBottom: 10,
                        }}
                      >
                        <div className="row wrap group-section-head">
                          <Accordion.Header className="group-section-accordion-header">
                            <Accordion.Trigger className="pill subtle group-toggle-pill group-toggle-pill-trigger">
                              <span className="group-toggle-pill-chevron">
                                <Icon path="M6 9l6 6 6-6" />
                              </span>
                              <span className="group-toggle-pill-label">{section.name}</span>
                              <span className="meta group-toggle-pill-count">({section.notes.length})</span>
                            </Accordion.Trigger>
                          </Accordion.Header>

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
                              <NoteGroupActionsMenu
                                groupName={sectionGroup.name}
                                busy={groupActionBusy}
                                onRename={() => openRenameNoteGroupDialog(sectionGroup.id, sectionGroup.name)}
                                onDelete={() => requestDeleteNoteGroup(sectionGroup.id, sectionGroup.name)}
                              />
                            </div>
                          )}
                        </div>

                        <Accordion.Content className="tasks-section-accordion-content">
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
                        </Accordion.Content>
                      </Accordion.Item>
                    )
                  })
              )}
            </Accordion.Root>
          )}

          {!state.notes.isLoading && !hasGroups && filteredNotes.length > 0 && (
            <div className="notes-items-stack">
              {filteredNotes.map((note) => renderNoteRow(note))}
            </div>
          )}

          {!state.notes.isLoading && (
            ((hasGroups && noteSections.length === 0 && ungroupedNotes.length === 0) ||
              (!hasGroups && filteredNotes.length === 0)) && (
              <div className="notice">No notes in this project.</div>
            )
          )}

          {!state.notes.isLoading && state.canLoadMoreNotes && (
            <div className="row" style={{ justifyContent: 'center', marginTop: 12 }}>
              <button
                className="pill subtle"
                type="button"
                onClick={state.loadMoreNotes}
                title="Load more notes"
                aria-label="Load more notes"
              >
                Load more notes
              </button>
            </div>
          )}
        </div>
      </div>

      <Dialog.Root open={notePreviewDialog !== null} onOpenChange={(open) => {
        if (!open) setNotePreviewDialog(null)
      }}>
        <Dialog.Portal>
          <Dialog.Overlay className="codex-chat-alert-overlay" />
          <Dialog.Content className="codex-chat-alert-content docker-runtime-dialog markdown-preview-dialog">
            <div className="notification-markdown-header">
              <div>
                <Dialog.Title className="codex-chat-alert-title notification-markdown-title">
                  {notePreviewDialog?.title || 'Untitled'}
                </Dialog.Title>
                <Dialog.Description className="codex-chat-alert-description">
                  Note preview.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="action-icon docker-runtime-dialog-close notification-preview-close"
                  aria-label="Close note preview"
                  title="Close"
                >
                  <Icon path="M6 6l12 12M18 6L6 18" />
                </button>
              </Dialog.Close>
            </div>
            <div className="md-editor-content notification-markdown-content markdown-preview-body">
              <MarkdownView value={notePreviewDialog?.body || ''} />
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <AlertDialog.Root
        open={noteGroupDialogOpen}
        onOpenChange={(open) => {
          if (!open) closeNoteGroupDialog()
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">{noteGroupDialogTitle}</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">{noteGroupDialogDescription}</AlertDialog.Description>
            <div className="field-control">
              <span className="field-label">Group name</span>
              <input
                type="text"
                value={noteGroupDialogName}
                onChange={(event) => setNoteGroupDialogName(event.target.value)}
                placeholder="Enter group name"
                autoFocus
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    if (!noteGroupDialogSubmitDisabled) submitNoteGroupDialog()
                  }
                }}
              />
            </div>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <button
                className="primary"
                type="button"
                onClick={submitNoteGroupDialog}
                disabled={noteGroupDialogSubmitDisabled}
              >
                {noteGroupDialogSubmitLabel}
              </button>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={deleteNotePrompt !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteNotePrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Delete note?</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {deleteNotePrompt
                ? `Delete "${deleteNotePrompt.title}"? This action cannot be undone.`
                : 'Delete selected note? This action cannot be undone.'}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  onClick={confirmDeleteNote}
                  disabled={noteDeleteBusy}
                >
                  Delete
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={deleteNoteGroupPrompt !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteNoteGroupPrompt(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">Delete note group?</AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              {deleteNoteGroupPrompt
                ? `Delete "${deleteNoteGroupPrompt.name}"? Linked notes will become ungrouped.`
                : 'Delete selected note group?'}
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="pill subtle" type="button">
                  Cancel
                </button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  onClick={confirmDeleteNoteGroup}
                  disabled={groupActionBusy}
                >
                  Delete
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
      <ProjectGitRepositoryDialog
        open={gitRepositoryDialogState !== null}
        onOpenChange={(open) => {
          if (!open) setGitRepositoryDialogState(null)
        }}
        userId={state.userId}
        projectId={gitRepositoryDialogState?.projectId || ''}
        target={gitRepositoryDialogState?.target || null}
      />
    </section>
  )
}
