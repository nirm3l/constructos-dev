import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { GraphContextPack, GraphProjectOverview } from '../../types'
import { Icon } from '../shared/uiHelpers'

type QueryLike<T> = {
  data?: T
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  error?: unknown
  refetch?: () => void
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error && err.message.trim()) return err.message.trim()
  if (typeof err === 'string' && err.trim()) return err.trim()
  return 'Unable to load knowledge graph data.'
}

export function ProjectKnowledgeGraphPanel({
  projectName,
  overviewQuery,
  contextPackQuery,
}: {
  projectName: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
}) {
  const isLoading = Boolean(overviewQuery.isLoading || contextPackQuery.isLoading)
  const isRefreshing = Boolean(!isLoading && (overviewQuery.isFetching || contextPackQuery.isFetching))
  const hasError = Boolean(overviewQuery.isError || contextPackQuery.isError)
  const error = overviewQuery.isError ? overviewQuery.error : contextPackQuery.error

  const overview = overviewQuery.data
  const contextPack = contextPackQuery.data
  const counts = overview?.counts ?? {
    tasks: 0,
    notes: 0,
    specifications: 0,
    project_rules: 0,
  }

  return (
    <section className="graph-insights" aria-live="polite">
      <div className="row wrap graph-insights-head">
        <h3 style={{ margin: 0 }}>Knowledge Graph</h3>
        <div className="row" style={{ gap: 6 }}>
          {isRefreshing && <span className="badge">Refreshing</span>}
          <button
            className="action-icon"
            type="button"
            title="Refresh graph insights"
            aria-label="Refresh graph insights"
            onClick={() => {
              overviewQuery.refetch?.()
              contextPackQuery.refetch?.()
            }}
          >
            <Icon path="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" />
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="meta">Loading graph snapshot for this project...</div>
      ) : hasError ? (
        <div className="notice">
          <strong>Knowledge graph unavailable.</strong>
          <div className="meta" style={{ color: 'inherit', marginTop: 4 }}>{toErrorMessage(error)}</div>
        </div>
      ) : (
        <>
          <div className="meta" style={{ marginBottom: 8 }}>
            Project scope: {String(overview?.project_name || projectName || 'Unknown project')}
          </div>

          <div className="graph-count-grid">
            <div className="graph-stat">
              <span className="meta">Tasks</span>
              <strong>{counts.tasks}</strong>
            </div>
            <div className="graph-stat">
              <span className="meta">Notes</span>
              <strong>{counts.notes}</strong>
            </div>
            <div className="graph-stat">
              <span className="meta">Specifications</span>
              <strong>{counts.specifications}</strong>
            </div>
            <div className="graph-stat">
              <span className="meta">Rules</span>
              <strong>{counts.project_rules}</strong>
            </div>
          </div>

          <div className="graph-chip-block">
            <div className="meta">Top tags</div>
            <div className="graph-chip-row">
              {(overview?.top_tags ?? []).length === 0 ? (
                <span className="meta">No tags yet.</span>
              ) : (
                (overview?.top_tags ?? []).map((item) => (
                  <span key={`kg-tag-${item.tag}`} className="status-chip">
                    {item.tag || '(empty)'} · {item.usage}
                  </span>
                ))
              )}
            </div>
          </div>

          <div className="graph-chip-block">
            <div className="meta">Top relationships</div>
            <div className="graph-chip-row">
              {(overview?.top_relationships ?? []).length === 0 ? (
                <span className="meta">No relationships yet.</span>
              ) : (
                (overview?.top_relationships ?? []).map((item) => (
                  <span key={`kg-rel-${item.relationship}`} className="status-chip">
                    {item.relationship || 'RELATED'} · {item.count}
                  </span>
                ))
              )}
            </div>
          </div>

          <div className="graph-connected-block">
            <div className="meta">Most connected resources</div>
            {(contextPack?.connected_resources ?? []).length === 0 ? (
              <div className="meta">No connected resources yet.</div>
            ) : (
              <div className="graph-connected-list">
                {(contextPack?.connected_resources ?? []).slice(0, 8).map((item) => (
                  <div key={`kg-node-${item.entity_type}-${item.entity_id}`} className="graph-connected-row">
                    <span>
                      <strong>{item.entity_type}</strong> {item.title || item.entity_id}
                    </span>
                    <span className="meta">degree {item.degree}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="graph-markdown-block">
            <div className="meta">Context pack preview</div>
            <div className="graph-markdown-preview">
              <MarkdownView value={contextPack?.markdown || ''} />
            </div>
          </div>
        </>
      )}
    </section>
  )
}
