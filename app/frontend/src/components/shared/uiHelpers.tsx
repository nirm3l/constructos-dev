import React from 'react'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { attachmentDownloadUrl } from '../../api'
import type { AttachmentRef, ExternalRef } from '../../types'

export function Icon({ path }: { path: string }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  )
}

export type MarkdownEditorView = 'write' | 'preview' | 'split'

type MarkdownSplitPaneProps = {
  left: React.ReactNode
  right: React.ReactNode
  ariaLabel?: string
  minLeftPercent?: number
  maxLeftPercent?: number
  defaultLeftPercent?: number
}

export function MarkdownSplitPane({
  left,
  right,
  ariaLabel = 'Resize split editor panels',
  minLeftPercent = 28,
  maxLeftPercent = 72,
  defaultLeftPercent = 50,
}: MarkdownSplitPaneProps) {
  const rootRef = React.useRef<HTMLDivElement | null>(null)
  const activePointerIdRef = React.useRef<number | null>(null)

  const clampPercent = React.useCallback((value: number) => {
    return Math.min(maxLeftPercent, Math.max(minLeftPercent, value))
  }, [maxLeftPercent, minLeftPercent])

  const setSplitPercent = React.useCallback((value: number) => {
    const root = rootRef.current
    if (!root) return
    root.style.setProperty('--md-split-left', `${clampPercent(value)}%`)
  }, [clampPercent])

  const updateFromClientX = React.useCallback((clientX: number) => {
    const root = rootRef.current
    if (!root) return
    const bounds = root.getBoundingClientRect()
    if (bounds.width <= 0) return
    const ratio = ((clientX - bounds.left) / bounds.width) * 100
    setSplitPercent(ratio)
  }, [setSplitPercent])

  const finishDragging = React.useCallback(() => {
    activePointerIdRef.current = null
    rootRef.current?.classList.remove('dragging')
  }, [])

  React.useEffect(() => {
    setSplitPercent(defaultLeftPercent)
  }, [defaultLeftPercent, setSplitPercent])

  const onPointerDown = React.useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches) return
    event.preventDefault()
    activePointerIdRef.current = event.pointerId
    rootRef.current?.classList.add('dragging')
    event.currentTarget.setPointerCapture(event.pointerId)
  }, [])

  const onPointerMove = React.useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (activePointerIdRef.current !== event.pointerId) return
    updateFromClientX(event.clientX)
  }, [updateFromClientX])

  const onPointerUp = React.useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (activePointerIdRef.current !== event.pointerId) return
    finishDragging()
  }, [finishDragging])

  const onPointerCancel = React.useCallback((event: React.PointerEvent<HTMLButtonElement>) => {
    if (activePointerIdRef.current !== event.pointerId) return
    finishDragging()
  }, [finishDragging])

  const onKeyDown = React.useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    const root = rootRef.current
    if (!root) return
    const currentRaw = root.style.getPropertyValue('--md-split-left').replace('%', '').trim()
    const current = Number.parseFloat(currentRaw)
    const fallback = clampPercent(defaultLeftPercent)
    const base = Number.isFinite(current) ? current : fallback
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      setSplitPercent(base - 4)
      return
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      setSplitPercent(base + 4)
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      setSplitPercent(minLeftPercent)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      setSplitPercent(maxLeftPercent)
    }
  }, [clampPercent, defaultLeftPercent, maxLeftPercent, minLeftPercent, setSplitPercent])

  return (
    <div ref={rootRef} className="md-split-pane">
      <div className="md-split-pane-left">{left}</div>
      <button
        type="button"
        className="md-split-divider"
        title={ariaLabel}
        aria-label={ariaLabel}
        role="separator"
        aria-orientation="vertical"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onKeyDown={onKeyDown}
      >
        <span className="md-split-divider-grip" aria-hidden="true" />
      </button>
      <div className="md-split-pane-right">{right}</div>
    </div>
  )
}

export function MarkdownModeToggle({
  view,
  onChange,
  ariaLabel,
  hideEditAndSplit = false,
  previewOnly = false,
  previewOnlyWhenFullscreen = false,
  onFullscreenTriggerMode,
}: {
  view: MarkdownEditorView
  onChange: (next: MarkdownEditorView) => void
  ariaLabel: string
  hideEditAndSplit?: boolean
  previewOnly?: boolean
  previewOnlyWhenFullscreen?: boolean
  onFullscreenTriggerMode?: (mode: 'readonly' | 'regular', nextFullscreen: boolean) => void
}) {
  const rootRef = React.useRef<HTMLDivElement | null>(null)
  const [isFullscreen, setIsFullscreen] = React.useState(false)

  const isNativeFullscreenSurface = React.useCallback((surface: HTMLElement | null): boolean => {
    if (!surface) return false
    const doc = document as Document & { webkitFullscreenElement?: Element | null }
    return document.fullscreenElement === surface || doc.webkitFullscreenElement === surface
  }, [])

  const getEditorSurface = React.useCallback((): HTMLElement | null => {
    if (!rootRef.current) return null
    return rootRef.current.closest('.md-editor-surface') as HTMLElement | null
  }, [])

  const syncFullscreenState = React.useCallback(() => {
    const surface = getEditorSurface()
    const classFullscreen = Boolean(surface?.classList.contains('md-editor-fullscreen'))
    const nativeFullscreen = isNativeFullscreenSurface(surface)
    setIsFullscreen(classFullscreen || nativeFullscreen)
  }, [getEditorSurface, isNativeFullscreenSurface])

  const ensureBodyFullscreenClass = React.useCallback(() => {
    const doc = document as Document & { webkitFullscreenElement?: Element | null }
    const hasAnyFullscreenSurface = Boolean(document.querySelector('.md-editor-surface.md-editor-fullscreen'))
      || Boolean(document.fullscreenElement)
      || Boolean(doc.webkitFullscreenElement)
    if (hasAnyFullscreenSurface) {
      document.body.classList.add('md-fullscreen-open')
    } else {
      document.body.classList.remove('md-fullscreen-open')
    }
  }, [])

  const broadcastFullscreenChange = React.useCallback(() => {
    window.dispatchEvent(new Event('md-fullscreen-change'))
  }, [])

  React.useEffect(() => {
    syncFullscreenState()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const surface = getEditorSurface()
      if (!surface || !surface.classList.contains('md-editor-fullscreen')) return
      const doc = document as Document & { webkitExitFullscreen?: () => Promise<void> | void; webkitFullscreenElement?: Element | null }
      const inNativeFullscreen = document.fullscreenElement === surface || doc.webkitFullscreenElement === surface
      const exitNative = async () => {
        if (!inNativeFullscreen) return
        try {
          if (document.exitFullscreen) {
            await document.exitFullscreen()
          } else if (doc.webkitExitFullscreen) {
            await doc.webkitExitFullscreen()
          }
        } catch {
          // Fallback to class-mode cleanup below.
        }
      }
      void exitNative().finally(() => {
        surface.classList.remove('md-editor-fullscreen')
        ensureBodyFullscreenClass()
        broadcastFullscreenChange()
      })
    }

    const onFullscreenChange = () => {
      const surface = getEditorSurface()
      if (!surface) return
      if (isNativeFullscreenSurface(surface)) {
        surface.classList.add('md-editor-fullscreen')
      } else {
        surface.classList.remove('md-editor-fullscreen')
      }
      ensureBodyFullscreenClass()
      syncFullscreenState()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('md-fullscreen-change', onFullscreenChange)
    document.addEventListener('fullscreenchange', onFullscreenChange)
    document.addEventListener('webkitfullscreenchange', onFullscreenChange as EventListener)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('md-fullscreen-change', onFullscreenChange)
      document.removeEventListener('fullscreenchange', onFullscreenChange)
      document.removeEventListener('webkitfullscreenchange', onFullscreenChange as EventListener)
      const surface = getEditorSurface()
      if (surface && surface.classList.contains('md-editor-fullscreen')) {
        surface.classList.remove('md-editor-fullscreen')
        ensureBodyFullscreenClass()
        broadcastFullscreenChange()
      }
    }
  }, [broadcastFullscreenChange, ensureBodyFullscreenClass, getEditorSurface, isNativeFullscreenSurface, syncFullscreenState])

  const toggleFullscreen = React.useCallback(async () => {
    const surface = getEditorSurface()
    if (!surface) return

    const doc = document as Document & {
      webkitExitFullscreen?: () => Promise<void> | void
      webkitFullscreenElement?: Element | null
    }
    const activeSurface = (
      document.querySelector('.md-editor-surface.md-editor-fullscreen') as HTMLElement | null
    ) || (
      (document.fullscreenElement || doc.webkitFullscreenElement) as HTMLElement | null
    )

    if (activeSurface && activeSurface !== surface) {
      if (document.fullscreenElement || doc.webkitFullscreenElement) {
        try {
          if (document.exitFullscreen) {
            await document.exitFullscreen()
          } else if (doc.webkitExitFullscreen) {
            await doc.webkitExitFullscreen()
          }
        } catch {
          // Continue with class fallback cleanup below.
        }
      }
      activeSurface.classList.remove('md-editor-fullscreen')
    }

    const currentlyNativeFullscreen = isNativeFullscreenSurface(surface)
    const currentlyClassFullscreen = surface.classList.contains('md-editor-fullscreen')
    const nextFullscreen = !(currentlyNativeFullscreen || currentlyClassFullscreen)

    if (nextFullscreen) {
      const element = surface as HTMLElement & {
        webkitRequestFullscreen?: () => Promise<void> | void
      }
      let nativeEntered = false
      if (typeof element.requestFullscreen === 'function' || typeof element.webkitRequestFullscreen === 'function') {
        try {
          if (typeof element.requestFullscreen === 'function') {
            await element.requestFullscreen()
          } else if (typeof element.webkitRequestFullscreen === 'function') {
            await element.webkitRequestFullscreen()
          }
          nativeEntered = true
        } catch {
          nativeEntered = false
        }
      }
      surface.classList.toggle('md-editor-fullscreen', nativeEntered || nextFullscreen)
    } else {
      if (currentlyNativeFullscreen && document.fullscreenElement === surface) {
        try {
          if (document.exitFullscreen) {
            await document.exitFullscreen()
          } else if (doc.webkitExitFullscreen) {
            await doc.webkitExitFullscreen()
          }
        } catch {
          // Ignore and still apply class cleanup.
        }
      }
      surface.classList.remove('md-editor-fullscreen')
    }

    ensureBodyFullscreenClass()
    setIsFullscreen(nextFullscreen)
    broadcastFullscreenChange()
  }, [broadcastFullscreenChange, ensureBodyFullscreenClass, getEditorSurface, isNativeFullscreenSurface])

  const onViewValueChange = React.useCallback((nextValue: string) => {
    if (nextValue === 'write' || nextValue === 'preview' || nextValue === 'split') {
      onChange(nextValue)
    }
  }, [onChange])
  const stopEventPropagation = React.useCallback((event: React.SyntheticEvent) => {
    event.stopPropagation()
  }, [])

  const hideModeToggle = previewOnly || (previewOnlyWhenFullscreen && isFullscreen)

  return (
    <div
      ref={rootRef}
      className="seg md-mode-toggle"
      role="tablist"
      aria-label={ariaLabel}
      onClick={stopEventPropagation}
      onPointerDown={stopEventPropagation}
    >
      {!hideModeToggle && (
        <ToggleGroup.Root
          type="single"
          value={view}
          onValueChange={onViewValueChange}
          className="md-mode-toggle-group"
          aria-label={ariaLabel}
        >
          {!hideEditAndSplit && (
            <ToggleGroup.Item className="seg-btn" value="write" aria-label="Edit">
              Edit
            </ToggleGroup.Item>
          )}
          <ToggleGroup.Item className="seg-btn" value="preview" aria-label="Preview">
            Preview
          </ToggleGroup.Item>
          {!hideEditAndSplit && (
            <ToggleGroup.Item
              className="seg-btn"
              value="split"
              aria-label="Split view"
              title="Split editor and preview"
            >
              Split
            </ToggleGroup.Item>
          )}
        </ToggleGroup.Root>
      )}
      <button
        className={`seg-btn md-fullscreen-btn ${isFullscreen ? 'active' : ''}`}
        onClick={(event) => {
          event.stopPropagation()
          const surface = getEditorSurface()
          const mode = String(surface?.getAttribute('data-md-fullscreen-mode') || '').trim().toLowerCase() === 'readonly'
            ? 'readonly'
            : 'regular'
          onFullscreenTriggerMode?.(mode, !isFullscreen)
          void toggleFullscreen()
        }}
        type="button"
        title={isFullscreen ? 'Exit fullscreen editor' : 'Open fullscreen editor'}
        aria-label={isFullscreen ? 'Exit fullscreen editor' : 'Open fullscreen editor'}
      >
        <Icon path={isFullscreen ? 'M9 9H5V5M15 9h4V5M9 15H5v4M15 15h4v4' : 'M9 5H5v4M15 5h4v4M9 19H5v-4M15 19h4v-4'} />
        <span className="md-fullscreen-label">{isFullscreen ? 'Exit' : 'Full'}</span>
      </button>
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
