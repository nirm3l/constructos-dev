import React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { useQuery } from '@tanstack/react-query'
import {
  getProjectDockerComposeRuntime,
  getProjectDockerComposeRuntimeLogsStreamUrl,
} from '../../api'
import type {
  ProjectDockerComposeRuntimeContainer,
  ProjectDockerComposeRuntimeLogEvent,
  ProjectDockerComposeRuntimeSnapshot,
} from '../../types'
import { Icon } from '../shared/uiHelpers'
import { toErrorMessage } from '../../utils/ui'

type ProjectDockerComposeRuntimeDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  userId: string
  projectId: string
}

type RuntimeLogLine = {
  id: string
  timestamp?: string | null
  message: string
}

function formatContainerTitle(container: ProjectDockerComposeRuntimeContainer): string {
  return container.service || container.name || 'Runtime container'
}

export function ProjectDockerComposeRuntimeDialog({
  open,
  onOpenChange,
  userId,
  projectId,
}: ProjectDockerComposeRuntimeDialogProps) {
  const runtimeQuery = useQuery({
    queryKey: ['project-docker-compose-runtime', userId, projectId],
    queryFn: () => getProjectDockerComposeRuntime(userId, projectId),
    enabled: open && Boolean(userId) && Boolean(projectId),
    refetchInterval: open ? 10000 : false,
  })

  const snapshot = runtimeQuery.data
  const containers = React.useMemo(
    () => (Array.isArray(snapshot?.containers) ? snapshot.containers : []),
    [snapshot?.containers]
  )
  const [selectedContainerName, setSelectedContainerName] = React.useState('')
  const [logLines, setLogLines] = React.useState<RuntimeLogLine[]>([])
  const [logConnected, setLogConnected] = React.useState(false)
  const [logError, setLogError] = React.useState<string | null>(null)
  const [autoScroll, setAutoScroll] = React.useState(true)
  const [showTimestamps, setShowTimestamps] = React.useState(true)
  const logsViewportRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    if (!containers.length) {
      setSelectedContainerName('')
      return
    }
    if (containers.some((item) => item.name === selectedContainerName)) return
    setSelectedContainerName(containers[0]?.name || '')
  }, [containers, selectedContainerName])

  const selectedContainer = React.useMemo(
    () => containers.find((item) => item.name === selectedContainerName) ?? null,
    [containers, selectedContainerName]
  )

  React.useEffect(() => {
    if (!open || !projectId || !selectedContainerName) {
      setLogLines([])
      setLogConnected(false)
      setLogError(null)
      return
    }
    const streamUrl = getProjectDockerComposeRuntimeLogsStreamUrl(projectId, {
      container_name: selectedContainerName,
      tail: 200,
    })
    const source = new EventSource(streamUrl)
    setLogLines([])
    setLogConnected(false)
    setLogError(null)

    source.addEventListener('log', (event) => {
      try {
        const payload = JSON.parse(String((event as MessageEvent).data || '{}')) as ProjectDockerComposeRuntimeLogEvent
        setLogLines((current) => {
          const next = [
            ...current,
            {
              id: `${String(payload.timestamp || '')}-${current.length}-${Math.random().toString(36).slice(2, 8)}`,
              timestamp: payload.timestamp || null,
              message: String(payload.message || ''),
            },
          ]
          return next.length > 500 ? next.slice(next.length - 500) : next
        })
        setLogConnected(true)
      } catch {
        // Ignore malformed log messages and keep stream alive.
      }
    })

    source.addEventListener('end', () => {
      setLogConnected(false)
    })

    source.onerror = () => {
      setLogConnected(false)
      setLogError('Live log stream disconnected.')
    }

    return () => {
      source.close()
    }
  }, [open, projectId, selectedContainerName])

  React.useEffect(() => {
    if (!autoScroll) return
    const viewport = logsViewportRef.current
    if (!viewport) return
    viewport.scrollTop = viewport.scrollHeight
  }, [autoScroll, logLines])

  const health = snapshot?.health as Record<string, unknown> | undefined
  const healthOk = Boolean(health?.ok)
  const runtimeButtonTone = healthOk ? 'ok' : (snapshot?.has_runtime ? 'warn' : 'muted')

  const renderContainerList = () => (
    <div className="docker-runtime-container-list">
      {containers.map((container) => {
        const selected = container.name === selectedContainerName
        return (
          <button
            key={container.name}
            type="button"
            className={`docker-runtime-container-card ${selected ? 'active' : ''}`.trim()}
            onClick={() => setSelectedContainerName(container.name)}
          >
            <div className="docker-runtime-container-card-head">
              <strong>{formatContainerTitle(container)}</strong>
              <span className={`docker-runtime-state-pill tone-${String(container.state || '').toLowerCase() === 'running' ? 'ok' : 'warn'}`.trim()}>
                {container.state || 'unknown'}
              </span>
            </div>
            <div className="meta">{container.name}</div>
            <div className="docker-runtime-container-meta">
              {container.health ? <span className="badge">Health: {container.health}</span> : null}
              {container.publishers[0]?.published_port ? (
                <span className="badge">Port {container.publishers[0].published_port}</span>
              ) : null}
            </div>
          </button>
        )
      })}
    </div>
  )

  const renderSelectedContainerDetail = () => (
    selectedContainer ? (
      <div className="docker-runtime-detail-card">
        <div className="docker-runtime-detail-head">
          <div>
            <div className="meta">Selected container</div>
            <div className="docker-runtime-detail-title">{selectedContainer.name}</div>
          </div>
          <div className="docker-runtime-selected-actions">
            <label className="task-flow-toggle">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(event) => setAutoScroll(event.target.checked)}
              />
              <span>Auto-scroll</span>
            </label>
            <label className="task-flow-toggle">
              <input
                type="checkbox"
                checked={showTimestamps}
                onChange={(event) => setShowTimestamps(event.target.checked)}
              />
              <span>Timestamps</span>
            </label>
          </div>
        </div>
        <div className="docker-runtime-detail-grid">
          <div><span className="meta">Service</span><strong>{selectedContainer.service || 'Unknown'}</strong></div>
          <div><span className="meta">Image</span><strong>{selectedContainer.image || 'Unknown'}</strong></div>
          <div><span className="meta">Status</span><strong>{selectedContainer.status || selectedContainer.state || 'Unknown'}</strong></div>
          <div><span className="meta">Health</span><strong>{selectedContainer.health || 'n/a'}</strong></div>
        </div>
      </div>
    ) : (
      <div className="notice">Select a runtime container to inspect it.</div>
    )
  )

  const renderLogsCard = () => (
    <div className="docker-runtime-logs-card">
      <div className="docker-runtime-logs-head">
        <div>
          <div className="meta">Live logs</div>
          <strong>{logConnected ? 'Connected' : 'Waiting for stream'}</strong>
        </div>
        {logError ? <span className="badge">{logError}</span> : null}
      </div>
      <div ref={logsViewportRef} className="docker-runtime-log-viewport">
        {logLines.length === 0 ? (
          <div className="meta">No logs received yet.</div>
        ) : (
          logLines.map((line) => (
            <div key={line.id} className="docker-runtime-log-line">
              {showTimestamps && line.timestamp ? (
                <span className="docker-runtime-log-timestamp">{line.timestamp}</span>
              ) : null}
              <span className="docker-runtime-log-message">{line.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="codex-chat-alert-overlay" />
        <Dialog.Content className="codex-chat-alert-content docker-runtime-dialog">
          <div className="docker-runtime-dialog-head">
            <div>
              <Dialog.Title className="codex-chat-alert-title">Runtime Inspector</Dialog.Title>
              <Dialog.Description className="codex-chat-alert-description">
                Live Docker Compose runtime state and logs for this project.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button type="button" className="action-icon docker-runtime-dialog-close" aria-label="Close runtime inspector">
                <Icon path="M6 6l12 12M18 6L6 18" />
              </button>
            </Dialog.Close>
          </div>

          {runtimeQuery.isLoading ? (
            <div className="meta">Loading runtime state...</div>
          ) : runtimeQuery.isError ? (
            <div className="notice notice-error">{toErrorMessage(runtimeQuery.error, 'Unable to load runtime state.')}</div>
          ) : !snapshot ? (
            <div className="notice">Runtime data is unavailable.</div>
          ) : (
            <div className="docker-runtime-dialog-body">
              <div className="docker-runtime-summary-grid">
                <div className="docker-runtime-summary-card">
                  <span className="meta">Stack</span>
                  <strong>{snapshot.stack || 'Unknown'}</strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Runtime health</span>
                  <strong className={`docker-runtime-state-pill tone-${runtimeButtonTone}`.trim()}>
                    {healthOk ? 'Healthy' : (snapshot.has_runtime ? 'Running' : 'Not deployed')}
                  </strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Endpoint</span>
                  <strong>
                    {snapshot.port ? `gateway:${snapshot.port}${String(snapshot.health_path || '/health')}` : 'Not configured'}
                  </strong>
                </div>
                <div className="docker-runtime-summary-card">
                  <span className="meta">Containers</span>
                  <strong>{containers.length}</strong>
                </div>
              </div>

              {health ? (
                <div className="docker-runtime-health-row">
                  <span className="badge">Stack running: {health.stack_running ? 'yes' : 'no'}</span>
                  <span className="badge">Port mapped: {health.port_mapped ? 'yes' : 'no'}</span>
                  <span className="badge">HTTP 200: {health.http_200 ? 'yes' : 'no'}</span>
                  <span className="badge">App root: {health.serves_application_root ? 'yes' : 'no'}</span>
                </div>
              ) : null}

              {!containers.length ? (
                <div className="notice">No managed runtime containers are currently running for this project.</div>
              ) : (
                <>
                  <div className="docker-runtime-layout docker-runtime-desktop-layout">
                    {renderContainerList()}
                    <div className="docker-runtime-detail-panel">
                      {renderSelectedContainerDetail()}
                      {renderLogsCard()}
                    </div>
                  </div>

                  <Tabs.Root className="inspector-mobile-tabs" defaultValue="services">
                    <Tabs.List className="inspector-mobile-tab-list" aria-label="Runtime inspector sections">
                      <Tabs.Trigger className="inspector-mobile-tab-trigger" value="services">Services</Tabs.Trigger>
                      <Tabs.Trigger className="inspector-mobile-tab-trigger" value="details">Details</Tabs.Trigger>
                      <Tabs.Trigger className="inspector-mobile-tab-trigger" value="logs">Logs</Tabs.Trigger>
                    </Tabs.List>
                    <Tabs.Content className="inspector-mobile-tab-content" value="services">
                      {renderContainerList()}
                    </Tabs.Content>
                    <Tabs.Content className="inspector-mobile-tab-content" value="details">
                      {renderSelectedContainerDetail()}
                    </Tabs.Content>
                    <Tabs.Content className="inspector-mobile-tab-content" value="logs">
                      {renderLogsCard()}
                    </Tabs.Content>
                  </Tabs.Root>
                </>
              )}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
