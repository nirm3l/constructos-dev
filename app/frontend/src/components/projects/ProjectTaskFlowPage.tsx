import React from 'react'
import type { ProjectTaskDependencyGraph } from '../../types'
import { ProjectTaskDependencyGraphPanel } from './ProjectTaskDependencyGraphPanel'
import { Icon } from '../shared/uiHelpers'

type QueryLike<T> = {
  data?: T
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  error?: unknown
  refetch?: () => void
}

type ProjectTaskFlowPageProps = {
  userId: string
  selectedProjectId: string
  selectedProjectName: string
  taskDependencyGraphQuery: QueryLike<ProjectTaskDependencyGraph>
}

export function ProjectTaskFlowPage({
  userId,
  selectedProjectId,
  selectedProjectName,
  taskDependencyGraphQuery,
}: ProjectTaskFlowPageProps) {
  const shellRef = React.useRef<HTMLElement | null>(null)
  const [isFullscreen, setIsFullscreen] = React.useState(false)
  const [fitSignal, setFitSignal] = React.useState(0)

  React.useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(Boolean(shellRef.current && document.fullscreenElement === shellRef.current))
      setFitSignal((current) => current + 1)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [])

  const toggleFullscreen = React.useCallback(async () => {
    const shell = shellRef.current
    if (!shell) return
    try {
      if (document.fullscreenElement === shell) {
        await document.exitFullscreen()
        return
      }
      if (document.fullscreenElement) {
        await document.exitFullscreen()
      }
      await shell.requestFullscreen()
    } catch {
      // Ignore fullscreen API failures and keep the page usable.
    }
  }, [])

  if (!selectedProjectId) {
    return (
      <section className="card">
        <h2 style={{ marginTop: 0 }}>Task Flow</h2>
        <div className="notice">Select a project to open the Task Flow page.</div>
      </section>
    )
  }

  const graph = taskDependencyGraphQuery.data
  const runtimeEdges = Number(graph?.counts?.runtime_edges || 0)
  const structuralEdges = Number(graph?.counts?.structural_edges || 0)
  const runningTasks = Number(graph?.counts?.running_tasks || 0)

  return (
    <section ref={shellRef} className="card task-flow-page-shell">
      <div className="row wrap graph-insights-head">
        <h3 style={{ margin: 0 }}>Task Flow</h3>
        <div className="row" style={{ gap: 6 }}>
          {taskDependencyGraphQuery.isFetching ? <span className="badge">Refreshing</span> : null}
          <button
            className="action-icon graph-refresh-btn"
            type="button"
            title={isFullscreen ? 'Exit fullscreen task flow' : 'Open task flow fullscreen'}
            aria-label={isFullscreen ? 'Exit fullscreen task flow' : 'Open task flow fullscreen'}
            onClick={() => { void toggleFullscreen() }}
          >
            {isFullscreen ? (
              <Icon path="M8 3H5a2 2 0 0 0-2 2v3h2V5h3V3zm11 0h-3v2h3v3h2V5a2 2 0 0 0-2-2zM3 16v3a2 2 0 0 0 2 2h3v-2H5v-3H3zm16 3h-3v2h3a2 2 0 0 0 2-2v-3h-2v3z" />
            ) : (
              <Icon path="M9 3H5a2 2 0 0 0-2 2v4h2V5h4V3zm10 0h-4v2h4v4h2V5a2 2 0 0 0-2-2zM3 15v4a2 2 0 0 0 2 2h4v-2H5v-4H3zm16 4h-4v2h4a2 2 0 0 0 2-2v-4h-2v4z" />
            )}
          </button>
        </div>
      </div>
      <div className="meta" style={{ marginBottom: 8 }}>
        Project scope: {String(graph?.project_name || selectedProjectName || 'Unknown project')}
      </div>
      <div className="graph-insights-meta-row">
        <span className="badge">Nodes: {Number(graph?.node_count || 0)}</span>
        <span className="badge">Edges: {Number(graph?.edge_count || 0)}</span>
        <span className="badge">Runtime: {runtimeEdges}</span>
        <span className="badge">Structural: {structuralEdges}</span>
        <span className="badge">Running: {runningTasks}</span>
      </div>
      <ProjectTaskDependencyGraphPanel
        projectId={selectedProjectId}
        userId={userId}
        projectName={selectedProjectName || 'Selected project'}
        graphQuery={taskDependencyGraphQuery}
        showHeader={false}
        fitSignal={fitSignal}
      />
    </section>
  )
}
