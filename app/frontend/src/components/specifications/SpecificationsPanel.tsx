import React from 'react'
import type { Specification } from '../../types'
import { MarkdownView } from '../../markdown/MarkdownView'
import {
  AttachmentRefList,
  ExternalRefEditor,
  Icon,
  MarkdownModeToggle,
} from '../shared/uiHelpers'

export function SpecificationsPanel({ state }: { state: any }) {
  const items: Specification[] = state.specifications.data?.items ?? []

  return (
    <section className="card">
      <h2>Specifications ({state.specifications.data?.total ?? 0})</h2>
      <div className="notes-shell">
        <div className="notes-toolbar">
          <div className="notes-search">
            <input
              value={state.specificationQ}
              onChange={(e) => state.setSpecificationQ(e.target.value)}
              placeholder="Search specifications"
            />
          </div>
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
