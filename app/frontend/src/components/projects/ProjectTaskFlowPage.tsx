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
  selectedProjectId: string
  selectedProjectName: string
  taskDependencyGraphQuery: QueryLike<ProjectTaskDependencyGraph>
}

export function ProjectTaskFlowPage({
  selectedProjectId,
  selectedProjectName,
  taskDependencyGraphQuery,
}: ProjectTaskFlowPageProps) {
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
    <section className="card">
      <div className="row wrap graph-insights-head">
        <h3 style={{ margin: 0 }}>Task Flow</h3>
        <div className="row" style={{ gap: 6 }}>
          {taskDependencyGraphQuery.isFetching ? <span className="badge">Refreshing</span> : null}
          <button
            className="action-icon graph-refresh-btn"
            type="button"
            title="Refresh task flow"
            aria-label="Refresh task flow"
            onClick={() => taskDependencyGraphQuery.refetch?.()}
          >
            <Icon path="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" />
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
        projectName={selectedProjectName || 'Selected project'}
        graphQuery={taskDependencyGraphQuery}
        showHeader={false}
      />
    </section>
  )
}
