import React from 'react'
import { attachmentDownloadUrl } from '../../api'
import type { AttachmentRef, ExternalRef } from '../../types'

export function Icon({ path }: { path: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

export function MarkdownModeToggle({
  view,
  onChange,
  ariaLabel,
}: {
  view: 'write' | 'preview'
  onChange: (next: 'write' | 'preview') => void
  ariaLabel: string
}) {
  return (
    <div className="seg md-mode-toggle" role="tablist" aria-label={ariaLabel}>
      <button
        className={`seg-btn ${view === 'write' ? 'active' : ''}`}
        onClick={() => onChange('write')}
        type="button"
      >
        Edit
      </button>
      <button
        className={`seg-btn ${view === 'preview' ? 'active' : ''}`}
        onClick={() => onChange('preview')}
        type="button"
      >
        Preview
      </button>
      <span className="md-chip">MD</span>
    </div>
  )
}

export function ExternalRefList({
  refs,
  onRemoveIndex
}: {
  refs: ExternalRef[] | undefined | null
  onRemoveIndex?: (index: number) => void
}) {
  if (!refs || refs.length === 0) return null
  return (
    <div className="resource-ref-list">
      {refs.map((ref, idx) => {
        const label = ref.title || ref.url
        return (
          <span key={`${ref.url}-${idx}`} className="resource-ref-item">
            <a
              className="status-chip resource-ref-chip"
              href={ref.url}
              target="_blank"
              rel="noreferrer"
              title={ref.source ? `${label} (${ref.source})` : label}
            >
              {ref.source ? `${label} · ${ref.source}` : label}
            </a>
            {onRemoveIndex && (
              <button
                type="button"
                className="action-icon danger-ghost"
                onClick={() => onRemoveIndex(idx)}
                title="Remove link"
                aria-label="Remove link"
              >
                <Icon path="M6 6l12 12M18 6 6 18" />
              </button>
            )}
          </span>
        )}
      )}
    </div>
  )
}

export function ExternalRefEditor({
  refs,
  onAdd,
  onRemoveIndex,
}: {
  refs: ExternalRef[]
  onAdd: (ref: ExternalRef) => void
  onRemoveIndex: (index: number) => void
}) {
  const [url, setUrl] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [source, setSource] = React.useState('')
  return (
    <div style={{ marginTop: 8 }}>
      <ExternalRefList refs={refs} onRemoveIndex={onRemoveIndex} />
      <div className="row wrap" style={{ gap: 8, marginTop: 6 }}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          style={{ minWidth: 240 }}
        />
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          style={{ minWidth: 180 }}
        />
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="Source (optional)"
          style={{ minWidth: 140 }}
        />
        <button
          className="status-chip"
          type="button"
          onClick={() => {
            const cleaned = url.trim()
            if (!cleaned) return
            onAdd({
              url: cleaned,
              ...(title.trim() ? { title: title.trim() } : {}),
              ...(source.trim() ? { source: source.trim() } : {}),
            })
            setUrl('')
            setTitle('')
            setSource('')
          }}
        >
          Add link
        </button>
      </div>
    </div>
  )
}

export function AttachmentRefList({
  refs,
  workspaceId,
  userId,
  onRemovePath
}: {
  refs: AttachmentRef[] | undefined | null
  workspaceId: string
  userId: string
  onRemovePath?: (path: string) => void
}) {
  if (!refs || refs.length === 0) return null
  return (
    <div className="resource-ref-list">
      {refs.map((ref, idx) => (
        <span key={`${ref.path}-${idx}`} className="resource-ref-item">
          <a
            className="status-chip resource-ref-chip"
            title={ref.path}
            href={attachmentDownloadUrl({ user_id: userId, workspace_id: workspaceId, path: ref.path })}
            target="_blank"
            rel="noreferrer"
          >
            {ref.name || ref.path}
          </a>
          {onRemovePath && (
            <button
              type="button"
              className="action-icon danger-ghost"
              onClick={() => onRemovePath(ref.path)}
              title="Remove file"
              aria-label="Remove file"
            >
              <Icon path="M6 6l12 12M18 6 6 18" />
            </button>
          )}
        </span>
      ))}
    </div>
  )
}
