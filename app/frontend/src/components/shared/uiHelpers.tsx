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
  const rootRef = React.useRef<HTMLDivElement | null>(null)
  const [isFullscreen, setIsFullscreen] = React.useState(false)

  const getEditorSurface = React.useCallback((): HTMLElement | null => {
    if (!rootRef.current) return null
    return rootRef.current.closest('.md-editor-surface') as HTMLElement | null
  }, [])

  const syncFullscreenState = React.useCallback(() => {
    const surface = getEditorSurface()
    setIsFullscreen(Boolean(surface?.classList.contains('md-editor-fullscreen')))
  }, [getEditorSurface])

  const broadcastFullscreenChange = React.useCallback(() => {
    window.dispatchEvent(new Event('md-fullscreen-change'))
  }, [])

  React.useEffect(() => {
    syncFullscreenState()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const surface = getEditorSurface()
      if (!surface || !surface.classList.contains('md-editor-fullscreen')) return
      surface.classList.remove('md-editor-fullscreen')
      if (!document.querySelector('.md-editor-surface.md-editor-fullscreen')) {
        document.body.classList.remove('md-fullscreen-open')
      }
      broadcastFullscreenChange()
    }

    const onFullscreenChange = () => syncFullscreenState()

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('md-fullscreen-change', onFullscreenChange)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('md-fullscreen-change', onFullscreenChange)
      const surface = getEditorSurface()
      if (surface && surface.classList.contains('md-editor-fullscreen')) {
        surface.classList.remove('md-editor-fullscreen')
        if (!document.querySelector('.md-editor-surface.md-editor-fullscreen')) {
          document.body.classList.remove('md-fullscreen-open')
        }
        broadcastFullscreenChange()
      }
    }
  }, [broadcastFullscreenChange, getEditorSurface, syncFullscreenState])

  const toggleFullscreen = React.useCallback(() => {
    const surface = getEditorSurface()
    if (!surface) return

    const activeSurface = document.querySelector('.md-editor-surface.md-editor-fullscreen') as HTMLElement | null
    if (activeSurface && activeSurface !== surface) {
      activeSurface.classList.remove('md-editor-fullscreen')
    }

    const nextFullscreen = !surface.classList.contains('md-editor-fullscreen')
    surface.classList.toggle('md-editor-fullscreen', nextFullscreen)

    if (nextFullscreen || document.querySelector('.md-editor-surface.md-editor-fullscreen')) {
      document.body.classList.add('md-fullscreen-open')
    } else {
      document.body.classList.remove('md-fullscreen-open')
    }

    setIsFullscreen(nextFullscreen)
    broadcastFullscreenChange()
  }, [broadcastFullscreenChange, getEditorSurface])

  return (
    <div ref={rootRef} className="seg md-mode-toggle" role="tablist" aria-label={ariaLabel}>
      <button
        className={`seg-btn md-fullscreen-btn ${isFullscreen ? 'active' : ''}`}
        onClick={toggleFullscreen}
        type="button"
        title={isFullscreen ? 'Exit fullscreen editor' : 'Open fullscreen editor'}
        aria-label={isFullscreen ? 'Exit fullscreen editor' : 'Open fullscreen editor'}
      >
        <Icon path={isFullscreen ? 'M9 9H5V5M15 9h4V5M9 15H5v4M15 15h4v4' : 'M9 5H5v4M15 5h4v4M9 19H5v-4M15 19h4v-4'} />
        <span className="md-fullscreen-label">{isFullscreen ? 'Exit' : 'Full'}</span>
      </button>
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
