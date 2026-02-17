import React from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { GraphContextPack, GraphProjectOverview, GraphProjectSubgraph } from '../../types'
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

type VizNode = {
  id: string
  name: string
  entity_type: string
  degree: number
  color: string
  val: number
}

type VizLink = {
  source: string
  target: string
  relationship: string
}

function getLinkNodeId(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && 'id' in (value as Record<string, unknown>)) {
    const out = (value as { id?: unknown }).id
    return typeof out === 'string' ? out : String(out || '')
  }
  return ''
}

export function ProjectKnowledgeGraphPanel({
  projectName,
  overviewQuery,
  contextPackQuery,
  subgraphQuery,
}: {
  projectName: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
  subgraphQuery: QueryLike<GraphProjectSubgraph>
}) {
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = React.useState<string | null>(null)
  const [isGraphFullscreen, setIsGraphFullscreen] = React.useState(false)
  const graphRef = React.useRef<any>(null)
  const graphShellRef = React.useRef<HTMLDivElement | null>(null)
  const graphCanvasRef = React.useRef<HTMLDivElement | null>(null)
  const [canvasSize, setCanvasSize] = React.useState<{ width: number; height: number }>({
    width: 640,
    height: 320,
  })
  const recalcCanvasSize = React.useCallback(() => {
    const el = graphCanvasRef.current
    if (!el) return
    const width = Math.max(300, Math.floor(el.clientWidth))
    const height = Math.max(240, Math.floor(el.clientHeight))
    setCanvasSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }))
  }, [])

  const isLoading = Boolean(overviewQuery.isLoading || contextPackQuery.isLoading)
  const isRefreshing = Boolean(!isLoading && (overviewQuery.isFetching || contextPackQuery.isFetching || subgraphQuery.isFetching))
  const hasError = Boolean(overviewQuery.isError || contextPackQuery.isError || subgraphQuery.isError)
  const error = overviewQuery.isError
    ? overviewQuery.error
    : contextPackQuery.isError
      ? contextPackQuery.error
      : subgraphQuery.error

  const overview = overviewQuery.data
  const contextPack = contextPackQuery.data
  const subgraph = subgraphQuery.data
  const graphNodes = subgraph?.nodes ?? []
  const graphEdges = subgraph?.edges ?? []
  const counts = overview?.counts ?? {
    tasks: 0,
    notes: 0,
    specifications: 0,
    project_rules: 0,
  }
  const selectedNode = graphNodes.find((node) => node.entity_id === selectedNodeId) ?? null
  const connectedSelectedEdges = selectedNode
    ? graphEdges.filter((edge) => edge.source_entity_id === selectedNode.entity_id || edge.target_entity_id === selectedNode.entity_id)
    : []

  React.useEffect(() => {
    if (!graphNodes.length) {
      setSelectedNodeId(null)
      return
    }
    if (selectedNodeId && graphNodes.some((node) => node.entity_id === selectedNodeId)) return
    setSelectedNodeId(graphNodes[0]?.entity_id ?? null)
  }, [graphNodes, selectedNodeId])

  const nodeColor = React.useCallback((entityType: string) => {
    const key = String(entityType || '').toLowerCase()
    if (key === 'project') return '#2563eb'
    if (key === 'specification') return '#0d9488'
    if (key === 'task') return '#0284c7'
    if (key === 'note') return '#9333ea'
    if (key === 'projectrule') return '#ea580c'
    if (key === 'tag') return '#ca8a04'
    if (key === 'user') return '#4f46e5'
    if (key === 'workspace') return '#6b7280'
    return '#334155'
  }, [])

  const graphData = React.useMemo(() => {
    const nodes: VizNode[] = graphNodes.map((node) => ({
      id: node.entity_id,
      name: node.title || node.entity_id,
      entity_type: node.entity_type || 'Entity',
      degree: Number(node.degree || 0),
      color: nodeColor(node.entity_type || 'Entity'),
      val: Math.max(4, 4 + Math.min(Number(node.degree || 0), 12) * 0.35),
    }))
    const links: VizLink[] = graphEdges.map((edge) => ({
      source: edge.source_entity_id,
      target: edge.target_entity_id,
      relationship: edge.relationship || 'RELATED',
    }))
    return { nodes, links }
  }, [graphNodes, graphEdges, nodeColor])

  React.useEffect(() => {
    const el = graphCanvasRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    recalcCanvasSize()
    const observer = new ResizeObserver(recalcCanvasSize)
    observer.observe(el)
    return () => observer.disconnect()
  }, [recalcCanvasSize])

  React.useEffect(() => {
    const onFullscreenChange = () => {
      const shell = graphShellRef.current
      setIsGraphFullscreen(Boolean(shell && document.fullscreenElement === shell))
      window.setTimeout(() => {
        recalcCanvasSize()
        try {
          graphRef.current?.zoomToFit?.(700, 20)
        } catch {
          // no-op
        }
      }, 80)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [recalcCanvasSize])

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      recalcCanvasSize()
      try {
        graphRef.current?.zoomToFit?.(700, isGraphFullscreen ? 20 : 48)
      } catch {
        // no-op
      }
    }, 90)
    return () => window.clearTimeout(timer)
  }, [isGraphFullscreen, recalcCanvasSize])

  const toggleGraphFullscreen = React.useCallback(async () => {
    const shell = graphShellRef.current
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
      // no-op
    }
  }, [])

  React.useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = window.setTimeout(() => {
      try {
        graphRef.current?.zoomToFit?.(600, 48)
      } catch {
        // no-op
      }
    }, 60)
    return () => window.clearTimeout(timer)
  }, [graphData.nodes.length, graphData.links.length, canvasSize.width, canvasSize.height])

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
              subgraphQuery.refetch?.()
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

          <div className="graph-viz-block">
            <div className="row wrap graph-viz-head">
              <div className="meta">
                Visual graph ({subgraph?.node_count ?? graphNodes.length} nodes, {subgraph?.edge_count ?? graphEdges.length} edges)
              </div>
              <button
                className="action-icon"
                type="button"
                title={isGraphFullscreen ? 'Exit full screen' : 'Open full screen graph'}
                aria-label={isGraphFullscreen ? 'Exit full screen' : 'Open full screen graph'}
                onClick={() => void toggleGraphFullscreen()}
              >
                <Icon path={isGraphFullscreen ? 'M9 9H3V3h6v2H5v4h4v2zm12 0h-6V7h4V3h2v6zM9 21H3v-6h2v4h4v2zm12 0h-6v-2h4v-4h2v6z' : 'M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6'} />
              </button>
            </div>
            {!subgraph ? (
              <div className="meta">Loading graph visualization...</div>
            ) : graphNodes.length <= 1 || graphEdges.length === 0 ? (
              <div className="meta">Not enough connected entities yet for a visual graph.</div>
            ) : (
              <div className="graph-viz-shell" ref={graphShellRef}>
                <div className="graph-viz-canvas" ref={graphCanvasRef}>
                  <ForceGraph2D
                    ref={graphRef}
                    width={canvasSize.width}
                    height={canvasSize.height}
                    graphData={graphData}
                    backgroundColor="rgba(0,0,0,0)"
                    cooldownTicks={120}
                    d3VelocityDecay={0.28}
                    linkColor={(link) => {
                      const source = getLinkNodeId((link as { source?: unknown }).source)
                      const target = getLinkNodeId((link as { target?: unknown }).target)
                      if (!selectedNodeId || source === selectedNodeId || target === selectedNodeId) {
                        return 'rgba(59,130,246,0.72)'
                      }
                      return 'rgba(100,116,139,0.30)'
                    }}
                    linkWidth={(link) => {
                      const source = getLinkNodeId((link as { source?: unknown }).source)
                      const target = getLinkNodeId((link as { target?: unknown }).target)
                      return !selectedNodeId || source === selectedNodeId || target === selectedNodeId ? 1.9 : 1.0
                    }}
                    nodeLabel={(node) => {
                      const n = node as VizNode
                      return `${n.entity_type}: ${n.name} (degree ${n.degree})`
                    }}
                    onNodeClick={(node) => {
                      const n = node as { id?: unknown }
                      if (!n.id) return
                      setSelectedNodeId(String(n.id))
                    }}
                    onNodeHover={(node) => {
                      const n = node as { id?: unknown } | null
                      if (!n?.id) {
                        setHoveredNodeId(null)
                        return
                      }
                      setHoveredNodeId(String(n.id))
                    }}
                    nodeCanvasObject={(node, ctx, globalScale) => {
                      const n = node as VizNode & { x?: number; y?: number }
                      const x = Number(n.x || 0)
                      const y = Number(n.y || 0)
                      const selected = String(n.id) === String(selectedNodeId || '')
                      const hovered = String(n.id) === String(hoveredNodeId || '')
                      const radius = selected ? 10.4 : hovered ? 7.2 : Number(n.val || 5.2)
                      const isDark = typeof document !== 'undefined' && document.documentElement?.dataset?.theme === 'dark'
                      ctx.beginPath()
                      ctx.arc(x, y, radius, 0, 2 * Math.PI, false)
                      ctx.fillStyle = n.color || '#334155'
                      ctx.fill()
                      ctx.lineWidth = selected ? 3.2 : hovered ? 2.0 : 1.2
                      ctx.strokeStyle = selected ? '#22c55e' : isDark ? 'rgba(203,213,225,0.72)' : 'rgba(241,245,249,0.9)'
                      ctx.stroke()

                      const label = String(n.name || n.id || '').slice(0, 34)
                      if (!label) return
                      const baseFontSize = Math.max(1.5, 1.9 / globalScale)
                      const hoverFontSize = Math.max(1.8, 2.2 / globalScale)
                      const selectedFontSize = Math.max(2.5, 3.1 / globalScale)
                      const fontSize = selected ? selectedFontSize : hovered ? hoverFontSize : baseFontSize
                      ctx.font = `${selected ? 700 : hovered ? 600 : 400} ${fontSize}px ui-sans-serif, -apple-system, Segoe UI, Roboto, Helvetica, Arial`
                      ctx.fillStyle = selected
                        ? isDark
                          ? 'rgba(248,250,252,0.98)'
                          : 'rgba(2,6,23,0.96)'
                        : hovered
                          ? isDark
                            ? 'rgba(226,232,240,0.82)'
                            : 'rgba(15,23,42,0.70)'
                          : isDark
                            ? 'rgba(203,213,225,0.38)'
                            : 'rgba(15,23,42,0.26)'
                      ctx.fillText(label, x + radius + 2, y + fontSize / 3)
                    }}
                  />
                </div>
                <aside className="graph-viz-side">
                  <div className="meta">Legend</div>
                  <div className="graph-viz-legend">
                    {Array.from(new Set(graphNodes.map((n) => String(n.entity_type || 'Entity')))).map((type) => (
                      <div key={`legend-${type}`} className="graph-viz-legend-item">
                        <span className="graph-viz-dot" style={{ backgroundColor: nodeColor(type) }} />
                        <span>{type}</span>
                      </div>
                    ))}
                  </div>
                  {selectedNode ? (
                    <div className="graph-viz-selected">
                      <div className="meta">Selected</div>
                      <div><strong>{selectedNode.entity_type}</strong></div>
                      <div>{selectedNode.title}</div>
                      <div className="meta">degree {selectedNode.degree}</div>
                      <div className="meta" style={{ marginTop: 6 }}>
                        Connected edges: {connectedSelectedEdges.length}
                      </div>
                    </div>
                  ) : null}
                </aside>
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
