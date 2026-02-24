import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchProjectKnowledge } from '../../api'
import type { GraphContextPack, GraphProjectOverview, GraphProjectSubgraph, ProjectKnowledgeSearchResult } from '../../types'
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
  userId: string
  selectedProjectId: string
  selectedProjectName: string
  selectedProjectChatIndexMode?: string
  selectedProjectChatAttachmentIngestionMode?: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
  subgraphQuery: QueryLike<GraphProjectSubgraph>
  onCreateTaskFromSummary: (payload: { title: string; description: string }) => Promise<void> | void
  onCreateNoteFromSummary: (payload: { title: string; body: string }) => Promise<void> | void
  onLinkFocusTaskToSpecification: (taskId: string, specificationId: string) => Promise<void> | void
}

export function ProjectKnowledgeGraphPage({
  userId,
  selectedProjectId,
  selectedProjectName,
  selectedProjectChatIndexMode,
  selectedProjectChatAttachmentIngestionMode,
  overviewQuery,
  contextPackQuery,
  subgraphQuery,
  onCreateTaskFromSummary,
  onCreateNoteFromSummary,
  onLinkFocusTaskToSpecification,
}: ProjectKnowledgeGraphPageProps) {
  const [knowledgeSearchQuery, setKnowledgeSearchQuery] = React.useState('')
  const normalizedSearchQuery = String(knowledgeSearchQuery || '').trim()
  const knowledgeSearchResultsQuery = useQuery<ProjectKnowledgeSearchResult>({
    queryKey: ['project-knowledge-search', userId, selectedProjectId, normalizedSearchQuery],
    queryFn: () =>
      searchProjectKnowledge(userId, selectedProjectId, {
        q: normalizedSearchQuery,
        limit: 16,
      }),
    enabled: Boolean(userId && selectedProjectId && normalizedSearchQuery.length >= 2),
  })

  React.useEffect(() => {
    setKnowledgeSearchQuery('')
  }, [selectedProjectId])

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
        projectChatIndexMode={selectedProjectChatIndexMode}
        projectChatAttachmentIngestionMode={selectedProjectChatAttachmentIngestionMode}
        overviewQuery={overviewQuery}
        contextPackQuery={contextPackQuery}
        subgraphQuery={subgraphQuery}
        knowledgeSearchQuery={knowledgeSearchQuery}
        setKnowledgeSearchQuery={setKnowledgeSearchQuery}
        knowledgeSearchResultsQuery={knowledgeSearchResultsQuery}
        onCreateTaskFromSummary={onCreateTaskFromSummary}
        onCreateNoteFromSummary={onCreateNoteFromSummary}
        onLinkFocusTaskToSpecification={onLinkFocusTaskToSpecification}
      />
    </section>
  )
}
