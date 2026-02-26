import React from 'react'
import { useQuery } from '@tanstack/react-query'
import * as Accordion from '@radix-ui/react-accordion'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
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
  MarkdownSplitPane,
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
  const [specResourceSections, setSpecResourceSections] = React.useState<string[]>(['external-links', 'file-attachments'])

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
    setSpecResourceSections(['external-links', 'file-attachments'])
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
  const addSpecificationTagFromQuery = React.useCallback(() => {
    const cleaned = String(specTagQuery || '').trim()
    if (!cleaned) return
    const suggested = filteredSpecificationTags.find((tag) => tag.toLowerCase() === cleaned.toLowerCase())
    const candidate = suggested || cleaned
    if (currentSpecificationTagsLower.has(candidate.toLowerCase())) {
      setSpecTagQuery('')
      return
    }
    const next = parseCommaTags([...currentSpecificationTags, candidate].join(', '))
    state.setEditSpecificationTags(next.join(', '))
    setSpecTagQuery('')
  }, [currentSpecificationTags, currentSpecificationTagsLower, filteredSpecificationTags, specTagQuery, state])
  const specificationStatuses: Array<Specification['status']> = [
    'Draft',
    'Ready',
    'In progress',
    'Implemented',
    'Archived',
  ]
  const createNewSpecification = React.useCallback(() => {
    state.createSpecificationMutation.mutate({
      status: 'Draft',
      force_new: true,
    })
  }, [state.createSpecificationMutation])
  const createSingleSpecTask = React.useCallback(() => {
    const title = (newTaskTitle || '').trim() || 'Untitled task'
    state.createSpecificationTaskMutation.mutate(
      { title },
      { onSuccess: () => setNewTaskTitle('') }
    )
  }, [newTaskTitle, state.createSpecificationTaskMutation])
  const createBulkSpecTasks = React.useCallback(() => {
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
  }, [bulkTaskText, state.bulkCreateSpecificationTasksMutation, state.setUiError])
  const createSingleSpecNote = React.useCallback(() => {
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
  }, [newNoteBody, newNoteTitle, state.createSpecificationNoteMutation])
  const ensureSpecResourceSectionOpen = React.useCallback((value: string) => {
    setSpecResourceSections((prev) => (prev.includes(value) ? prev : [...prev, value]))
  }, [])

  return (
    <section className="card">
      <div className="row wrap" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>Specifications ({state.specifications.data?.total ?? 0})</h2>
        <div className="row wrap specs-create-actions" style={{ gap: 6 }}>
          <button
            className="status-chip specs-new-spec-btn"
            type="button"
            onClick={createNewSpecification}
            disabled={state.createSpecificationMutation.isPending}
            title="Create specification"
            aria-label="Create specification"
          >
            <Icon path="M12 5v14M5 12h14" />
            <span>{state.createSpecificationMutation.isPending ? 'Creating...' : 'Spec'}</span>
          </button>
        </div>
      </div>

      <div className="notes-shell">
        <div className="row wrap specs-filters-row">
          <Select.Root
            value={state.specificationStatus || '__all__'}
            onValueChange={(value) => state.setSpecificationStatus(value === '__all__' ? '' : value)}
          >
            <Select.Trigger className="quickadd-project-trigger taskdrawer-select-trigger specs-status-select" aria-label="Specification status filter">
              <Select.Value />
              <Select.Icon asChild>
                <Icon path="M6 9l6 6 6-6" />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                <Select.Viewport className="quickadd-project-viewport">
                  <Select.Item value="__all__" className="quickadd-project-item">
                    <Select.ItemText>All statuses</Select.ItemText>
                  </Select.Item>
                  {specificationStatuses.map((status) => (
                    <Select.Item key={`spec-status-filter-${status}`} value={status} className="quickadd-project-item">
                      <Select.ItemText>{status}</Select.ItemText>
                    </Select.Item>
                  ))}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <PopularTagFilters
            tags={state.taskTagSuggestions ?? []}
            selectedTags={state.specificationTags}
            onToggleTag={state.toggleSpecificationFilterTag}
            onClear={() => state.clearSpecificationFilterTags()}
            idPrefix="spec-filter"
          />
        </div>

        <div className="task-list">
          {state.specifications.isLoading && <div className="notice">Loading specifications...</div>}
          {items.map((specification) => {
            const isOpen = state.selectedSpecificationId === specification.id
            const status = isOpen ? state.editSpecificationStatus : specification.status
            const displayTitle = isOpen ? state.editSpecificationTitle || 'Untitled spec' : specification.title || 'Untitled spec'
            const externalRefCount = specification.external_refs?.length ?? 0
            const attachmentRefCount = specification.attachment_refs?.length ?? 0
            const editorExternalRefs = state.parseExternalRefsText(state.editSpecificationExternalRefsText)
            const editorAttachmentRefs = state.parseAttachmentRefsText(state.editSpecificationAttachmentRefsText)
            const editorExternalLinksMeta = editorExternalRefs.length > 0
              ? `${editorExternalRefs.length} linked`
              : 'No links added'
            const editorAttachmentsMeta = editorAttachmentRefs.length > 0
              ? `${editorAttachmentRefs.length} files attached`
              : 'No attachments'
            const openSpecificationFromMenu = () => {
              if (isOpen) return
              state.toggleSpecificationEditor(specification.id)
            }
            const toggleArchiveFromMenu = () => {
              if (specification.archived) {
                state.restoreSpecificationMutation.mutate(specification.id)
                return
              }
              state.archiveSpecificationMutation.mutate(specification.id)
            }
            return (
              <div
                key={specification.id}
                className={`note-row ${isOpen ? 'open selected' : ''}`}
                onClick={() => state.toggleSpecificationEditor(specification.id)}
                role="button"
              >
                <div className="note-title">
                  <div className="note-title-main">
                    {specification.archived && <span className="badge">Archived</span>}
                    <strong>{displayTitle}</strong>
                  </div>
                  <div className="note-row-actions" onClick={(event) => event.stopPropagation()}>
                    <button
                      className="action-icon note-row-actions-trigger"
                      type="button"
                      title="Copy specification link"
                      aria-label="Copy specification link"
                      onClick={() =>
                        state.copyShareLink({
                          tab: 'specifications',
                          projectId: specification.project_id,
                          specificationId: specification.id,
                        })
                      }
                    >
                      <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                    </button>
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          className="action-icon note-row-actions-trigger"
                          type="button"
                          title="Specification actions"
                          aria-label="Specification actions"
                        >
                          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                          <DropdownMenu.Item className="task-group-menu-item" onSelect={openSpecificationFromMenu} disabled={isOpen}>
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                            <span>{isOpen ? 'Editor open' : 'Open editor'}</span>
                          </DropdownMenu.Item>
                          <DropdownMenu.Separator className="task-group-menu-separator" />
                          <DropdownMenu.Item className="task-group-menu-item" onSelect={toggleArchiveFromMenu}>
                            <Icon path={specification.archived ? 'M20 16v5H4v-5M12 3v12M7 8l5-5 5 5' : 'M20 8H4m2-3h12l2 3v13H4V8l2-3zm3 7h6'} />
                            <span>{specification.archived ? 'Restore specification' : 'Archive specification'}</span>
                          </DropdownMenu.Item>
                          <DropdownMenu.Separator className="task-group-menu-separator" />
                          <DropdownMenu.Item
                            className="task-group-menu-item task-group-menu-item-danger"
                            onSelect={() => state.deleteSpecificationMutation.mutate(specification.id)}
                            disabled={state.deleteSpecificationMutation.isPending}
                          >
                            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                            <span>Delete specification</span>
                          </DropdownMenu.Item>
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="status-chip">{status}</span>
                </div>
                {(externalRefCount > 0 || attachmentRefCount > 0) && (
                  <div className="note-meta-row">
                    {externalRefCount > 0 && (
                      <span className="note-meta-chip" title={`${externalRefCount} external links`}>
                        <Icon path="M10 13a5 5 0 0 0 7.07 0l2.83-2.83a5 5 0 0 0-7.07-7.07L11 4m2 7a5 5 0 0 0-7.07 0L3.1 13.83a5 5 0 1 0 7.07 7.07L13 18" />
                        <span>{externalRefCount} links</span>
                      </span>
                    )}
                    {attachmentRefCount > 0 && (
                      <span className="note-meta-chip" title={`${attachmentRefCount} file attachments`}>
                        <Icon path="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.2-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.2a2 2 0 0 1-2.82-2.83l8.49-8.48" />
                        <span>{attachmentRefCount} files</span>
                      </span>
                    )}
                  </div>
                )}
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
                      </div>
                    </div>

                    <div className="row" style={{ marginBottom: 8 }}>
                      <span className="meta">Status</span>
                      <Select.Root
                        value={state.editSpecificationStatus || 'Draft'}
                        onValueChange={state.setEditSpecificationStatus}
                      >
                        <Select.Trigger className="quickadd-project-trigger taskdrawer-select-trigger specs-editor-status-select" aria-label="Specification status">
                          <Select.Value />
                          <Select.Icon asChild>
                            <Icon path="M6 9l6 6 6-6" />
                          </Select.Icon>
                        </Select.Trigger>
                        <Select.Portal>
                          <Select.Content className="quickadd-project-content" position="popper" sideOffset={6}>
                            <Select.Viewport className="quickadd-project-viewport">
                              {specificationStatuses.map((specStatus) => (
                                <Select.Item key={`spec-edit-status-${specStatus}`} value={specStatus} className="quickadd-project-item">
                                  <Select.ItemText>{specStatus}</Select.ItemText>
                                </Select.Item>
                              ))}
                            </Select.Viewport>
                          </Select.Content>
                        </Select.Portal>
                      </Select.Root>
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
                      <Popover.Root open={showSpecTagPicker} onOpenChange={setShowSpecTagPicker}>
                        <Popover.Trigger asChild>
                          <button className="action-icon" title="Edit tags" aria-label="Edit tags">
                            <Icon path="M3 12h8m-8 6h12m-12-12h18" />
                          </button>
                        </Popover.Trigger>
                        <Popover.Portal>
                          <Popover.Content className="quickadd-tag-popover taskdrawer-tag-popover" side="top" align="end" sideOffset={8}>
                            <div className="quickadd-tag-popover-header">
                              <h4 className="quickadd-tag-popover-title">Specification Tags</h4>
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
                            <div className="tag-picker-input-row">
                              <input
                                value={specTagQuery}
                                onChange={(e) => setSpecTagQuery(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    addSpecificationTagFromQuery()
                                  }
                                }}
                                placeholder="Search or create tag"
                                autoFocus
                              />
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
                                onClick={addSpecificationTagFromQuery}
                                title="Create tag"
                                aria-label="Create tag"
                              >
                                Add "{specTagQuery.trim()}"
                              </button>
                            )}
                            <Popover.Arrow className="quickadd-tag-popover-arrow" />
                          </Popover.Content>
                        </Popover.Portal>
                      </Popover.Root>
                    </div>

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
                        ) : state.specificationEditorView === 'split' ? (
                          <MarkdownSplitPane
                            left={(
                              <textarea
                                className="md-textarea"
                                value={state.editSpecificationBody}
                                onChange={(e) => state.setEditSpecificationBody(e.target.value)}
                                placeholder="Write specification in Markdown..."
                              />
                            )}
                            right={<MarkdownView value={state.editSpecificationBody} />}
                            ariaLabel="Resize specification editor and preview panels"
                          />
                        ) : (
                          <MarkdownView value={state.editSpecificationBody} />
                        )}
                      </div>
                    </div>
                    <input
                      ref={state.specFileInputRef}
                      type="file"
                      multiple
                      style={{ display: 'none' }}
                      onChange={async (e) => {
                        const files = Array.from(e.target.files ?? [])
                        e.currentTarget.value = ''
                        if (files.length === 0) return
                        try {
                          const uploaded = await Promise.all(
                            files.map((file) => state.uploadAttachmentRef(file, { project_id: specification.project_id }))
                          )
                          state.setEditSpecificationAttachmentRefsText((prev: string) =>
                            state.attachmentRefsToText([...state.parseAttachmentRefsText(prev), ...uploaded])
                          )
                        } catch (err) {
                          state.setUiError(state.toErrorMessage(err, 'Upload failed'))
                        }
                      }}
                    />
                    <Accordion.Root
                      className="taskdrawer-sections"
                      type="multiple"
                      value={specResourceSections}
                      onValueChange={setSpecResourceSections}
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
                            onClick={() => ensureSpecResourceSectionOpen('external-links')}
                            aria-label="Edit external links"
                            title="Edit external links"
                          >
                            <Icon path="M12 20h9M4 16l10.5-10.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
                          </button>
                        </div>
                        <Accordion.Content className="taskdrawer-section-content">
                          <ExternalRefEditor
                            refs={editorExternalRefs}
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
                        </Accordion.Content>
                      </Accordion.Item>
                      <Accordion.Item value="file-attachments" className="taskdrawer-section-item taskdrawer-section-attachments">
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
                            onClick={() => {
                              ensureSpecResourceSectionOpen('file-attachments')
                              state.specFileInputRef.current?.click()
                            }}
                            aria-label="Upload files"
                            title="Upload files"
                          >
                            <Icon path="M12 3v12m0-12-4 4m4-4 4 4M4 17v3h16v-3" />
                          </button>
                        </div>
                        <Accordion.Content className="taskdrawer-section-content">
                          <div className="row" style={{ marginBottom: 8 }}>
                            <button className="status-chip" type="button" onClick={() => state.specFileInputRef.current?.click()}>
                              Upload files
                            </button>
                          </div>
                          <AttachmentRefList
                            refs={editorAttachmentRefs}
                            workspaceId={state.workspaceId}
                            userId={state.userId}
                            onRemovePath={(path) =>
                              state.setEditSpecificationAttachmentRefsText((prev: string) =>
                                state.removeAttachmentByPath(prev, path)
                              )
                            }
                          />
                        </Accordion.Content>
                      </Accordion.Item>
                    </Accordion.Root>
                    <Accordion.Root
                      className="spec-links-shell spec-links-accordion"
                      type="multiple"
                      defaultValue={['spec-linked-tasks', 'spec-linked-notes']}
                    >
                      <Accordion.Item value="spec-linked-tasks" className="spec-links-section">
                        <Accordion.Trigger className="taskdrawer-section-trigger">
                          <span className="taskdrawer-section-title-wrap">
                            <Icon path="M4 6h16M4 12h16M4 18h16" />
                            <span className="taskdrawer-section-title">Implementation tasks</span>
                          </span>
                          <span className="meta">{linkedTasks.length} linked</span>
                        </Accordion.Trigger>
                        <Accordion.Content className="taskdrawer-section-content">
                          <div className="spec-links-head">
                            <div className="row wrap" style={{ gap: 6 }}>
                              <button
                                className="status-chip"
                                type="button"
                                onClick={createSingleSpecTask}
                                disabled={state.createSpecificationTaskMutation.isPending}
                              >
                                + Task
                              </button>
                              <button
                                className="status-chip"
                                type="button"
                                onClick={createBulkSpecTasks}
                                disabled={state.bulkCreateSpecificationTasksMutation.isPending}
                              >
                                Bulk create
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
                              onKeyDown={(event) => {
                                if (event.key !== 'Enter' || event.shiftKey) return
                                event.preventDefault()
                                createSingleSpecTask()
                              }}
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
                        </Accordion.Content>
                      </Accordion.Item>

                      <Accordion.Item value="spec-linked-notes" className="spec-links-section">
                        <Accordion.Trigger className="taskdrawer-section-trigger">
                          <span className="taskdrawer-section-title-wrap">
                            <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
                            <span className="taskdrawer-section-title">Notes</span>
                          </span>
                          <span className="meta">{linkedNotes.length} linked</span>
                        </Accordion.Trigger>
                        <Accordion.Content className="taskdrawer-section-content">
                          <div className="spec-links-head">
                            <div className="row wrap" style={{ gap: 6 }}>
                              <button
                                className="status-chip"
                                type="button"
                                onClick={createSingleSpecNote}
                                disabled={state.createSpecificationNoteMutation.isPending}
                              >
                                + Note
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
                              onKeyDown={(event) => {
                                if (event.key !== 'Enter' || event.shiftKey) return
                                event.preventDefault()
                                createSingleSpecNote()
                              }}
                              placeholder="Note title"
                            />
                          </div>
                          <textarea
                            className="md-textarea"
                            value={newNoteBody}
                            onChange={(e) => setNewNoteBody(e.target.value)}
                            onKeyDown={(event) => {
                              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                                event.preventDefault()
                                createSingleSpecNote()
                              }
                            }}
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
                        </Accordion.Content>
                      </Accordion.Item>
                    </Accordion.Root>
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
