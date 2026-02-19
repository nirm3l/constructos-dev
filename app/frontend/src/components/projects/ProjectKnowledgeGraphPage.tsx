import React from 'react'
import type { GraphContextPack, GraphProjectOverview, GraphProjectSubgraph } from '../../types'
import { ProjectKnowledgeGraphPanel } from './ProjectKnowledgeGraphPanel'

type QueryLike<T> = {
  data?: T
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  error?: unknown
  refetch?: () => void
}

type ProjectKnowledgeGraphPageProps = {
  selectedProjectId: string
  selectedProjectName: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
  subgraphQuery: QueryLike<GraphProjectSubgraph>
  onCreateTaskFromSummary: (payload: { title: string; description: string }) => Promise<void> | void
  onCreateNoteFromSummary: (payload: { title: string; body: string }) => Promise<void> | void
  onLinkFocusTaskToSpecification: (taskId: string, specificationId: string) => Promise<void> | void
}

export function ProjectKnowledgeGraphPage({
  selectedProjectId,
  selectedProjectName,
  overviewQuery,
  contextPackQuery,
  subgraphQuery,
  onCreateTaskFromSummary,
  onCreateNoteFromSummary,
  onLinkFocusTaskToSpecification,
}: ProjectKnowledgeGraphPageProps) {
  if (!selectedProjectId) {
    return (
      <section className="card">
        <h2 style={{ marginTop: 0 }}>Knowledge Graph</h2>
        <div className="notice">Select a project to open the Knowledge Graph page.</div>
      </section>
    )
  }

  return (
    <section className="card">
      <ProjectKnowledgeGraphPanel
        projectName={selectedProjectName || 'Selected project'}
        overviewQuery={overviewQuery}
        contextPackQuery={contextPackQuery}
        subgraphQuery={subgraphQuery}
        onCreateTaskFromSummary={onCreateTaskFromSummary}
        onCreateNoteFromSummary={onCreateNoteFromSummary}
        onLinkFocusTaskToSpecification={onLinkFocusTaskToSpecification}
      />
    </section>
  )
}
