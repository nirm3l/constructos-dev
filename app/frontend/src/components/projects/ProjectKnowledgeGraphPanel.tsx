import React from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { GraphContextPack, GraphProjectOverview, GraphProjectSubgraph, ProjectKnowledgeSearchResult } from '../../types'
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

function formatEvidenceUpdated(value: string | null | undefined): string {
  if (!value) return 'Unknown'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

type GraphCubeTile = {
  key: string
  label: string
  color: string
}

type GraphPackSourceUsage = {
  key: string
  label: string
  color: string
  chars: number
  lines: number
  percent: number
}

const KG_PACK_TILE_COUNT = 360

function estimateTokenCount(charCount: number): number {
  if (!Number.isFinite(charCount) || charCount <= 0) return 0
  return Math.max(1, Math.round(charCount / 4))
}

function countLines(value: string): number {
  if (!value.trim()) return 0
  return value.split(/\r?\n/).length
}

function normalizeChatIndexMode(mode: unknown): 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' {
  const normalized = String(mode || '').trim().toUpperCase()
  if (normalized === 'VECTOR_ONLY' || normalized === 'KG_AND_VECTOR') return normalized
  return 'OFF'
}

function normalizeChatAttachmentIngestionMode(mode: unknown): 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' {
  const normalized = String(mode || '').trim().toUpperCase()
  if (normalized === 'OFF' || normalized === 'FULL_TEXT') return normalized
  if (normalized === 'FULL_TEXT_OCR') return 'FULL_TEXT'
  return 'METADATA_ONLY'
}

function isChatEntityType(entityType: unknown): boolean {
  const normalized = String(entityType || '').trim().toLowerCase().replace(/[_\s-]+/g, '')
  return normalized === 'chatmessage' || normalized === 'chatattachment' || normalized === 'chatsession'
}

function chatIndexModeLabel(mode: 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR'): string {
  if (mode === 'KG_AND_VECTOR') return 'Knowledge Graph + Vector'
  if (mode === 'VECTOR_ONLY') return 'Vector only'
  return 'Off'
}

function chatAttachmentModeLabel(mode: 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT'): string {
  if (mode === 'FULL_TEXT') return 'Full text'
  if (mode === 'METADATA_ONLY') return 'Metadata only'
  return 'Off'
}

function buildGraphCubeTiles(
  slices: Array<{ key: string; label: string; color: string; value: number }>,
  tileCount: number
): GraphCubeTile[] {
  const validSlices = slices.filter((slice) => slice.value > 0)
  if (!validSlices.length || tileCount <= 0) return []

  const totalValue = validSlices.reduce((sum, slice) => sum + slice.value, 0)
  if (totalValue <= 0) return []

  const rawCounts = validSlices.map((slice) => (slice.value / totalValue) * tileCount)
  const counts = rawCounts.map((value) => Math.floor(value))
  const order = rawCounts
    .map((value, idx) => ({
      idx,
      remainder: value - (counts[idx] ?? 0),
      value: validSlices[idx]?.value ?? 0,
    }))
    .sort((a, b) => b.remainder - a.remainder || b.value - a.value)

  const remaining = tileCount - counts.reduce((sum, value) => sum + value, 0)
  for (let i = 0; i < remaining; i += 1) {
    const slot = order[i % order.length]
    if (!slot) continue
    counts[slot.idx] = (counts[slot.idx] ?? 0) + 1
  }

  const output: GraphCubeTile[] = []
  for (let idx = 0; idx < validSlices.length; idx += 1) {
    const slice = validSlices[idx]
    if (!slice) continue
    const tileAmount = counts[idx] ?? 0
    for (let i = 0; i < tileAmount; i += 1) {
      output.push({
        key: `${slice.key}-${i}`,
        label: slice.label,
        color: slice.color,
      })
    }
  }
  return output.slice(0, tileCount)
}

function renderGraphSummaryMarkdown(summary: GraphContextPack['summary'] | undefined): string {
  if (!summary) return '_(summary unavailable)_'
  const lines: string[] = []
  const executive = String(summary.executive || '').trim()
  if (executive) {
    lines.push('# Grounded Summary')
    lines.push('')
    lines.push(executive)
  }
  const keyPoints = Array.isArray(summary.key_points) ? summary.key_points : []
  if (keyPoints.length > 0) {
    if (lines.length > 0) lines.push('')
    lines.push('## Key Points')
    for (const point of keyPoints) {
      const claim = String(point?.claim || '').trim()
      if (!claim) continue
      const ids = (point?.evidence_ids ?? []).filter(Boolean)
      lines.push(ids.length > 0 ? `- ${claim} [${ids.join(', ')}]` : `- ${claim}`)
    }
  }
  const gaps = Array.isArray(summary.gaps) ? summary.gaps : []
  if (gaps.length > 0) {
    if (lines.length > 0) lines.push('')
    lines.push('## Gaps')
    for (const gap of gaps) {
      const text = String(gap || '').trim()
      if (text) lines.push(`- ${text}`)
    }
  }
  const out = lines.join('\n').trim()
  return out || '_(summary unavailable)_'
}

export function ProjectKnowledgeGraphPanel({
  projectName,
  projectChatIndexMode,
  projectChatAttachmentIngestionMode,
  overviewQuery,
  contextPackQuery,
  subgraphQuery,
  knowledgeSearchQuery,
  setKnowledgeSearchQuery,
  knowledgeSearchResultsQuery,
  onCreateTaskFromSummary,
  onCreateNoteFromSummary,
  onLinkFocusTaskToSpecification,
}: {
  projectName: string
  projectChatIndexMode?: string
  projectChatAttachmentIngestionMode?: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
  subgraphQuery: QueryLike<GraphProjectSubgraph>
  knowledgeSearchQuery: string
  setKnowledgeSearchQuery: React.Dispatch<React.SetStateAction<string>>
  knowledgeSearchResultsQuery: QueryLike<ProjectKnowledgeSearchResult>
  onCreateTaskFromSummary?: (payload: { title: string; description: string }) => Promise<void> | void
  onCreateNoteFromSummary?: (payload: { title: string; body: string }) => Promise<void> | void
  onLinkFocusTaskToSpecification?: (taskId: string, specificationId: string) => Promise<void> | void
}) {
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = React.useState<string | null>(null)
  const [isGraphFullscreen, setIsGraphFullscreen] = React.useState(false)
  const [selectedEvidenceId, setSelectedEvidenceId] = React.useState<string | null>(null)
  const [actionBusy, setActionBusy] = React.useState<string | null>(null)
  const [actionError, setActionError] = React.useState<string | null>(null)

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
  const structure = contextPack?.structure
  const evidenceItems = contextPack?.evidence ?? []
  const normalizedChatIndexMode = normalizeChatIndexMode(projectChatIndexMode)
  const normalizedChatAttachmentMode = normalizeChatAttachmentIngestionMode(projectChatAttachmentIngestionMode)
  const summary = contextPack?.summary
  const focusNeighbors = structure?.focus_neighbors ?? []
  const dependencyPaths = structure?.dependency_paths ?? []
  const subgraph = subgraphQuery.data
  const graphNodes = subgraph?.nodes ?? []
  const graphEdges = subgraph?.edges ?? []
  const evidenceById = React.useMemo(
    () => new Map(evidenceItems.map((item) => [item.evidence_id, item])),
    [evidenceItems]
  )
  const focusTaskId =
    String(contextPack?.focus?.entity_type || '').toLowerCase() === 'task'
      ? String(contextPack?.focus?.entity_id || '').trim()
      : ''
  const focusSpecificationId =
    String(contextPack?.focus?.entity_type || '').toLowerCase() === 'specification'
      ? String(contextPack?.focus?.entity_id || '').trim()
      : ''
  const dependencySpecificationId = React.useMemo(
    () =>
      String(
        (dependencyPaths.find((item) => String(item.to_entity_type || '').toLowerCase() === 'specification')?.to_entity_id || '')
      ).trim(),
    [dependencyPaths]
  )
  const taskToLinkId = focusTaskId || String(evidenceItems.find((item) => String(item.entity_type || '').toLowerCase() === 'task')?.entity_id || '').trim()
  const specificationToLinkId =
    focusSpecificationId ||
    dependencySpecificationId ||
    String(evidenceItems.find((item) => String(item.entity_type || '').toLowerCase() === 'specification')?.entity_id || '').trim()
  const canLinkTaskToSpecification = Boolean(taskToLinkId && specificationToLinkId && onLinkFocusTaskToSpecification)

  const summaryTaskTitle = React.useMemo(() => {
    const seed = String(summary?.key_points?.[0]?.claim || summary?.executive || '').trim()
    const compact = seed.replace(/\s+/g, ' ').trim()
    if (!compact) return `Follow-up: ${projectName}`
    const clipped = compact.length > 72 ? `${compact.slice(0, 72).trim()}...` : compact
    return `Follow-up: ${clipped}`
  }, [projectName, summary?.executive, summary?.key_points])
  const summaryTaskDescription = React.useMemo(() => {
    const lines: string[] = []
    lines.push(`Project: ${projectName}`)
    if (summary?.executive) lines.push(`Executive: ${summary.executive}`)
    const keyPoints = summary?.key_points ?? []
    if (keyPoints.length > 0) {
      lines.push('Key points:')
      for (const point of keyPoints.slice(0, 4)) {
        const ids = (point.evidence_ids ?? []).filter(Boolean)
        lines.push(`- ${point.claim}${ids.length ? ` [${ids.join(', ')}]` : ''}`)
      }
    }
    const gaps = summary?.gaps ?? contextPack?.gaps ?? []
    if (gaps.length > 0) {
      lines.push('Gaps:')
      for (const gap of gaps.slice(0, 4)) lines.push(`- ${gap}`)
    }
    return lines.join('\n').trim()
  }, [contextPack?.gaps, projectName, summary?.executive, summary?.gaps, summary?.key_points])
  const summaryNoteTitle = React.useMemo(() => {
    const base = String(summaryTaskTitle || '').trim()
    return base ? `${base} (Note)` : `Summary note: ${projectName}`
  }, [projectName, summaryTaskTitle])
  const summaryNoteBody = React.useMemo(() => {
    const head = ['## Summary with citations', '', summaryTaskDescription]
    return head.join('\n')
  }, [summaryTaskDescription])

  const counts = overview?.counts ?? {
    tasks: 0,
    notes: 0,
    specifications: 0,
    project_rules: 0,
    comments: 0,
  }
  const graphPackSnapshot = React.useMemo(() => {
    const graphContextMarkdown = String(contextPack?.markdown || '')
    const chatEvidenceItems = evidenceItems.filter((item) => isChatEntityType(item.entity_type))
    const nonChatEvidenceItems = evidenceItems.filter((item) => !isChatEntityType(item.entity_type))
    const chatEvidenceJson = chatEvidenceItems.length > 0 ? JSON.stringify(chatEvidenceItems) : ''
    const nonChatEvidenceJson = nonChatEvidenceItems.length > 0 ? JSON.stringify(nonChatEvidenceItems) : ''
    const graphSummaryMarkdown = renderGraphSummaryMarkdown(summary)
    const graphMetadataText = JSON.stringify({
      mode: contextPack?.mode || '',
      focus_entity_type: contextPack?.focus?.entity_type || '',
      focus_entity_id: contextPack?.focus?.entity_id || '',
      gaps: contextPack?.gaps ?? [],
      chat_index_mode: normalizedChatIndexMode,
      chat_attachment_ingestion_mode: normalizedChatAttachmentMode,
    })
    const sourceBase: GraphPackSourceUsage[] = [
      {
        key: 'graph-context-markdown',
        label: 'GraphContext.md',
        color: '#2563eb',
        chars: graphContextMarkdown.length,
        lines: countLines(graphContextMarkdown),
        percent: 0,
      },
      {
        key: 'graph-evidence-json-non-chat',
        label: 'GraphEvidence.json (non-chat entities)',
        color: '#0ea5e9',
        chars: nonChatEvidenceJson.length,
        lines: countLines(nonChatEvidenceJson),
        percent: 0,
      },
      {
        key: 'graph-evidence-json-chat',
        label: 'GraphEvidence.json (chat entities)',
        color: '#16a34a',
        chars: chatEvidenceJson.length,
        lines: countLines(chatEvidenceJson),
        percent: 0,
      },
      {
        key: 'graph-summary-markdown',
        label: 'GraphSummary.md',
        color: '#14b8a6',
        chars: graphSummaryMarkdown.length,
        lines: countLines(graphSummaryMarkdown),
        percent: 0,
      },
      {
        key: 'graph-pack-metadata',
        label: 'KG metadata (mode/focus/gaps)',
        color: '#64748b',
        chars: graphMetadataText.length,
        lines: countLines(graphMetadataText),
        percent: 0,
      },
    ]
    const totalChars = sourceBase.reduce((sum, section) => sum + section.chars, 0)
    const sources = sourceBase
      .filter((section) => section.chars > 0)
      .map((section) => ({
        ...section,
        percent: totalChars > 0 ? (section.chars / totalChars) * 100 : 0,
      }))
    const tileCount = KG_PACK_TILE_COUNT
    const tiles = buildGraphCubeTiles(
      sources.map((section) => ({
        key: section.key,
        label: section.label,
        color: section.color,
        value: section.chars,
      })),
      tileCount
    )
    return {
      totalChars,
      approxTokens: estimateTokenCount(totalChars),
      totalLines: sources.reduce((sum, section) => sum + section.lines, 0),
      tileCount,
      charsPerTile: totalChars > 0 ? totalChars / tileCount : 0,
      sources,
      tiles,
      chatEvidenceCount: chatEvidenceItems.length,
      nonChatEvidenceCount: nonChatEvidenceItems.length,
      chatEvidenceSharePct: evidenceItems.length > 0 ? (chatEvidenceItems.length / evidenceItems.length) * 100 : 0,
      chatEvidenceEntityCount: new Set(
        chatEvidenceItems.map((item) => `${String(item.entity_type || '').trim()}:${String(item.entity_id || '').trim()}`)
      ).size,
    }
  }, [
    contextPack?.focus?.entity_id,
    contextPack?.focus?.entity_type,
    contextPack?.gaps,
    contextPack?.markdown,
    contextPack?.mode,
    evidenceItems,
    normalizedChatAttachmentMode,
    normalizedChatIndexMode,
    summary,
  ])

  const filteredGraph = React.useMemo(() => {
    const nodeIds = new Set(graphNodes.map((node) => String(node.entity_id || '')))
    const edges = graphEdges.filter((edge) => {
      const sourceId = String(edge.source_entity_id || '')
      const targetId = String(edge.target_entity_id || '')
      return nodeIds.has(sourceId) && nodeIds.has(targetId)
    })
    return { nodes: graphNodes, edges }
  }, [graphNodes, graphEdges])

  React.useEffect(() => {
    const nodes = filteredGraph.nodes
    if (!nodes.length) {
      setSelectedNodeId(null)
      return
    }
    if (selectedNodeId && nodes.some((node) => node.entity_id === selectedNodeId)) return
    setSelectedNodeId(nodes[0]?.entity_id ?? null)
  }, [filteredGraph.nodes, selectedNodeId])

  React.useEffect(() => {
    if (!evidenceItems.length) {
      setSelectedEvidenceId(null)
      return
    }
    if (selectedEvidenceId && evidenceItems.some((item) => item.evidence_id === selectedEvidenceId)) return
    setSelectedEvidenceId(evidenceItems[0]?.evidence_id ?? null)
  }, [evidenceItems, selectedEvidenceId])

  const nodeColor = React.useCallback((entityType: string) => {
    const key = String(entityType || '').toLowerCase()
    if (key === 'project') return '#2563eb'
    if (key === 'specification') return '#0d9488'
    if (key === 'task') return '#0284c7'
    if (key === 'note') return '#9333ea'
    if (key === 'comment') return '#16a34a'
    if (key === 'projectrule') return '#ea580c'
    if (key === 'tag') return '#ca8a04'
    if (key === 'user') return '#4f46e5'
    if (key === 'workspace') return '#6b7280'
    return '#334155'
  }, [])

  const graphData = React.useMemo(() => {
    const nodes: VizNode[] = filteredGraph.nodes.map((node) => ({
      id: node.entity_id,
      name: node.title || node.entity_id,
      entity_type: node.entity_type || 'Entity',
      degree: Number(node.degree || 0),
      color: nodeColor(node.entity_type || 'Entity'),
      val: Math.max(4, 4 + Math.min(Number(node.degree || 0), 12) * 0.35),
    }))
    const links: VizLink[] = filteredGraph.edges.map((edge) => ({
      source: edge.source_entity_id,
      target: edge.target_entity_id,
      relationship: edge.relationship || 'RELATED',
    }))
    return { nodes, links }
  }, [filteredGraph.nodes, filteredGraph.edges, nodeColor])

  const selectedNode = graphData.nodes.find((node) => node.id === selectedNodeId) ?? null
  const connectedSelectedEdges = selectedNode
    ? graphData.links.filter((edge) => String(edge.source) === selectedNode.id || String(edge.target) === selectedNode.id)
    : []
  const normalizedKnowledgeSearchQuery = String(knowledgeSearchQuery || '').trim()
  const knowledgeSearchActive = normalizedKnowledgeSearchQuery.length >= 2
  const knowledgeSearchItems = knowledgeSearchResultsQuery.data?.items ?? []
  const knowledgeSearchMode = knowledgeSearchResultsQuery.data?.mode ?? 'empty'

  const focusNodeOnCanvas = React.useCallback((nodeId: string, zoomTarget = 2.2) => {
    setSelectedNodeId(nodeId)
    try {
      const data = graphRef.current?.graphData?.()
      const node = data?.nodes?.find((item: any) => String(item?.id || '') === nodeId)
      if (node && Number.isFinite(node.x) && Number.isFinite(node.y)) {
        graphRef.current?.centerAt?.(node.x, node.y, 500)
      }
      graphRef.current?.zoom?.(Math.min(zoomTarget, 8), 380)
    } catch {
      // no-op
    }
  }, [])

  const zoomReset = React.useCallback(() => {
    try {
      graphRef.current?.zoomToFit?.(650, isGraphFullscreen ? 20 : 48)
    } catch {
      // no-op
    }
  }, [isGraphFullscreen])

  const runAction = React.useCallback(async (actionKey: string, fn: () => Promise<void> | void) => {
    setActionBusy(actionKey)
    setActionError(null)
    try {
      await Promise.resolve(fn())
    } catch (err) {
      setActionError(toErrorMessage(err))
    } finally {
      setActionBusy((current) => (current === actionKey ? null : current))
    }
  }, [])

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
        zoomReset()
      }, 80)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [recalcCanvasSize, zoomReset])

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      recalcCanvasSize()
      zoomReset()
    }, 90)
    return () => window.clearTimeout(timer)
  }, [isGraphFullscreen, recalcCanvasSize, zoomReset])

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

  const exitGraphFullscreen = React.useCallback(async () => {
    const shell = graphShellRef.current
    if (!shell) return
    try {
      if (document.fullscreenElement === shell) {
        await document.exitFullscreen()
      }
    } catch {
      // no-op
    }
  }, [])

  React.useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = window.setTimeout(() => {
      zoomReset()
    }, 60)
    return () => window.clearTimeout(timer)
  }, [graphData.nodes.length, graphData.links.length, canvasSize.width, canvasSize.height, zoomReset])

  const noVisibleNodes = Boolean(subgraph) && graphData.nodes.length === 0

  return (
    <section className="graph-insights" aria-live="polite">
      <div className="row wrap graph-insights-head">
        <h3 style={{ margin: 0 }}>Knowledge Graph</h3>
        <div className="row" style={{ gap: 6 }}>
          {isRefreshing && <span className="badge">Refreshing</span>}
          <button
            className="action-icon graph-refresh-btn"
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
        <div className="notice notice-error">
          <strong>Knowledge graph unavailable.</strong>
          <div className="meta" style={{ color: 'inherit', marginTop: 4 }}>{toErrorMessage(error)}</div>
        </div>
      ) : (
        <>
          <div className="meta" style={{ marginBottom: 8 }}>
            Project scope: {String(overview?.project_name || projectName || 'Unknown project')}
          </div>

          <div className="meta" style={{ marginBottom: 8 }}>
            Retrieval mode: {contextPack?.mode ?? 'graph-only'}
          </div>

          <div className="field-control" style={{ marginBottom: 10 }}>
            <span className="field-label">Knowledge search</span>
            <div className="row wrap" style={{ gap: 8, alignItems: 'center' }}>
              <input
                value={knowledgeSearchQuery}
                onChange={(e) => setKnowledgeSearchQuery(e.target.value)}
                placeholder="Search entities, events, commands, readiness, metrics..."
              />
              {knowledgeSearchResultsQuery.isFetching ? <span className="badge">Searching</span> : null}
              {knowledgeSearchActive ? <span className="badge">Mode: {knowledgeSearchMode}</span> : null}
            </div>
            <div className="meta" style={{ marginTop: 6 }}>
              Type at least 2 characters. Click a result to focus its node in the graph.
            </div>
          </div>

          {knowledgeSearchActive ? (
            <div className="graph-connected-block">
              <div className="meta">Knowledge search results</div>
              {knowledgeSearchResultsQuery.isError ? (
                <div className="notice notice-error" style={{ marginTop: 8 }}>
                  {toErrorMessage(knowledgeSearchResultsQuery.error)}
                </div>
              ) : knowledgeSearchItems.length === 0 ? (
                <div className="meta" style={{ marginTop: 8 }}>No matches for this query.</div>
              ) : (
                <div className="graph-evidence-list">
                  {knowledgeSearchItems.slice(0, 10).map((item) => {
                    const graphPath = (item.graph_path ?? []).filter(Boolean).join(' -> ')
                    return (
                      <button
                        key={`kg-search-${item.rank}-${item.entity_type}-${item.entity_id}`}
                        type="button"
                        className="graph-evidence-item"
                        onClick={() => focusNodeOnCanvas(item.entity_id, 2.2)}
                      >
                        <div className="graph-evidence-head">
                          <div className="graph-evidence-badges">
                            <span className="graph-evidence-id">#{item.rank}</span>
                            <span className="status-chip">{item.entity_type}</span>
                            <span className="status-chip">{item.source_type}</span>
                          </div>
                          <span className="graph-evidence-score">Score {item.final_score.toFixed(3)}</span>
                        </div>
                        <div className="graph-evidence-snippet">{item.snippet}</div>
                        <div className="graph-evidence-meta">
                          <span className="meta">Entity {item.entity_id}</span>
                          <span className="meta">Graph {item.graph_score.toFixed(3)}</span>
                          <span className="meta">
                            Vector {item.vector_similarity === null ? 'n/a' : item.vector_similarity.toFixed(3)}
                          </span>
                          {typeof item.template_alignment === 'number' ? (
                            <span className="meta">Template {item.template_alignment.toFixed(3)}</span>
                          ) : null}
                        </div>
                        {graphPath ? <div className="graph-evidence-path">Path {graphPath}</div> : null}
                        {item.why_selected ? <div className="graph-evidence-why">{item.why_selected}</div> : null}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : null}

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
            <div className="graph-stat">
              <span className="meta">Comments</span>
              <strong>{counts.comments}</strong>
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
            <div className="meta">Focus neighbors</div>
            {focusNeighbors.length === 0 ? (
              <div className="meta">No focus neighbors for current selection.</div>
            ) : (
              <div className="graph-connected-list">
                {focusNeighbors.slice(0, 8).map((item) => (
                  <div key={`kg-focus-${item.entity_type}-${item.entity_id}`} className="graph-connected-row">
                    <span>
                      <strong>{item.entity_type}</strong> {item.title || item.entity_id}
                    </span>
                    <span className="meta">{(item.path_types ?? []).join(' -> ') || 'RELATED'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="graph-connected-block">
            <div className="meta">Dependency paths</div>
            {dependencyPaths.length === 0 ? (
              <div className="meta">No dependency paths available.</div>
            ) : (
              <div className="graph-connected-list">
                {dependencyPaths.slice(0, 8).map((item) => (
                  <div key={`kg-path-${item.to_entity_type}-${item.to_entity_id}`} className="graph-connected-row">
                    <span>
                      <strong>{item.to_entity_type}</strong> {item.to_entity_id}
                    </span>
                    <span className="meta">{(item.path ?? []).join(' -> ') || 'RELATED'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="graph-connected-block">
            <div className="meta">Evidence (sorted by score)</div>
            <div className="meta" style={{ marginTop: 4 }}>
              Click an evidence item to focus its node in the visual graph.
            </div>
            {evidenceItems.length === 0 ? (
              <div className="meta">No evidence available for this context pack.</div>
            ) : (
              <div className="graph-evidence-list">
                {evidenceItems.map((item) => {
                  const isSelected = selectedEvidenceId === item.evidence_id
                  const graphPath = (item.graph_path ?? []).filter(Boolean).join(' -> ')
                  return (
                    <button
                      key={item.evidence_id}
                      type="button"
                      className={`graph-evidence-item ${isSelected ? 'selected' : ''}`.trim()}
                      onClick={() => {
                        setSelectedEvidenceId(item.evidence_id)
                        focusNodeOnCanvas(item.entity_id, 2.4)
                      }}
                    >
                      <div className="graph-evidence-head">
                        <div className="graph-evidence-badges">
                          <span className="graph-evidence-id">{item.evidence_id}</span>
                          <span className="status-chip">{item.entity_type}</span>
                          <span className="status-chip">{item.source_type}</span>
                        </div>
                        <span className="graph-evidence-score">Score {item.final_score.toFixed(3)}</span>
                      </div>
                      <div className="graph-evidence-snippet">{item.snippet}</div>
                      <div className="graph-evidence-meta">
                        <span className="meta">Entity {item.entity_id}</span>
                        <span className="meta">Graph {item.graph_score.toFixed(3)}</span>
                        <span className="meta">
                          Vector {item.vector_similarity === null ? 'n/a' : item.vector_similarity.toFixed(3)}
                        </span>
                        <span className="meta">Updated {formatEvidenceUpdated(item.updated_at)}</span>
                      </div>
                      {graphPath ? <div className="graph-evidence-path">Path {graphPath}</div> : null}
                      <div className="graph-evidence-why">Why selected: {item.why_selected}</div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="graph-viz-block">
            <div className="row wrap graph-viz-head">
              <div className="meta">
                Visual graph ({graphData.nodes.length}/{subgraph?.node_count ?? graphNodes.length} nodes, {graphData.links.length}/{subgraph?.edge_count ?? graphEdges.length} edges)
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
              <>
                {noVisibleNodes ? (
                  <div className="meta">No nodes available for visualization.</div>
                ) : (
                  <div className="graph-viz-shell" ref={graphShellRef}>
                    {isGraphFullscreen ? (
                      <button
                        className="action-icon graph-viz-exit-button"
                        type="button"
                        title="Exit full screen"
                        aria-label="Exit full screen"
                        onClick={() => void exitGraphFullscreen()}
                      >
                        <Icon path="M9 9H3V3h6v2H5v4h4v2zm12 0h-6V7h4V3h2v6zM9 21H3v-6h2v4h4v2zm12 0h-6v-2h4v-4h2v6z" />
                      </button>
                    ) : null}
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
                          focusNodeOnCanvas(String(n.id), 2.3)
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
                                ? 'rgba(226,232,240,0.90)'
                                : 'rgba(15,23,42,0.80)'
                              : isDark
                                ? 'rgba(203,213,225,0.54)'
                                : 'rgba(15,23,42,0.44)'
                          ctx.fillText(label, x + radius + 2, y + fontSize / 3)
                        }}
                      />
                    </div>
                    <aside className="graph-viz-side">
                      <div className="meta">Legend</div>
                      <div className="graph-viz-legend">
                        {Array.from(new Set(graphData.nodes.map((n) => String(n.entity_type || 'Entity')))).map((type) => (
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
                          <div>{selectedNode.name}</div>
                          <div className="meta">degree {selectedNode.degree}</div>
                          <div className="meta" style={{ marginTop: 6 }}>
                            Connected edges: {connectedSelectedEdges.length}
                          </div>
                        </div>
                      ) : null}
                    </aside>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="graph-markdown-block">
            <div className="meta">Summary with citations</div>
            <div className="row wrap" style={{ gap: 8, marginTop: 6, marginBottom: 8 }}>
              {onCreateTaskFromSummary ? (
                <button
                  type="button"
                  className="status-chip"
                  disabled={Boolean(actionBusy)}
                  onClick={() =>
                    runAction('summary-create-task', () =>
                      onCreateTaskFromSummary({
                        title: summaryTaskTitle,
                        description: summaryTaskDescription,
                      })
                    )
                  }
                >
                  Create task
                </button>
              ) : null}
              {onCreateNoteFromSummary ? (
                <button
                  type="button"
                  className="status-chip"
                  disabled={Boolean(actionBusy)}
                  onClick={() =>
                    runAction('summary-create-note', () =>
                      onCreateNoteFromSummary({
                        title: summaryNoteTitle,
                        body: summaryNoteBody,
                      })
                    )
                  }
                >
                  Create note
                </button>
              ) : null}
              {canLinkTaskToSpecification ? (
                <button
                  type="button"
                  className="status-chip"
                  disabled={Boolean(actionBusy)}
                  onClick={() =>
                    runAction('summary-link-task-spec', () =>
                      onLinkFocusTaskToSpecification?.(taskToLinkId, specificationToLinkId)
                    )
                  }
                >
                  Link task/spec
                </button>
              ) : null}
              {actionBusy ? <span className="meta">Running action...</span> : null}
            </div>
            {actionError ? <div className="notice notice-error">{actionError}</div> : null}
            {!summary ? (
              <div className="meta">
                Summary is unavailable for this response.
                {(contextPack?.gaps ?? []).length > 0 ? ` ${contextPack?.gaps?.join(' | ')}` : ''}
              </div>
            ) : (
              <div className="graph-summary-layout">
                <div className="graph-summary-card">
                  <div className="meta">Executive</div>
                  <div className="graph-summary-executive">
                    {summary.executive || 'No executive summary available.'}
                  </div>
                </div>

                <div className="graph-summary-card">
                  <div className="meta">Key points</div>
                  {(summary.key_points ?? []).length === 0 ? (
                    <div className="meta">No grounded key points available.</div>
                  ) : (
                    <div className="graph-summary-points">
                      {(summary.key_points ?? []).map((point, idx) => (
                        <div key={`summary-point-${idx}`} className="graph-summary-point">
                          <div className="graph-summary-point-head">
                            <span className="graph-summary-point-index">{idx + 1}</span>
                            <span className="graph-summary-point-claim">{point.claim}</span>
                          </div>
                          <div className="graph-summary-point-evidence">
                            <span className="meta">Evidence</span>
                            <div className="graph-summary-evidence-links">
                              {(point.evidence_ids ?? []).length === 0
                                ? <span className="meta">none</span>
                                : (point.evidence_ids ?? []).map((evidenceId) => {
                                    const evidence = evidenceById.get(evidenceId)
                                    return (
                                      <button
                                        key={evidenceId}
                                        type="button"
                                        className="graph-summary-evidence-link"
                                        onClick={() => {
                                          setSelectedEvidenceId(evidenceId)
                                          if (evidence?.entity_id) {
                                            focusNodeOnCanvas(evidence.entity_id, 2.4)
                                          }
                                        }}
                                        title={evidence?.snippet || `Open ${evidenceId}`}
                                      >
                                        {evidenceId}
                                      </button>
                                    )
                                  })}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {(summary.gaps ?? []).length > 0 ? (
                  <div className="graph-summary-card">
                    <div className="meta">Gaps</div>
                    <div className="graph-summary-gaps">
                      {(summary.gaps ?? []).map((gap, idx) => (
                        <div key={`summary-gap-${idx}`} className="graph-summary-gap-item">
                          {gap}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          <div className="graph-markdown-block">
            <div className="meta">Context pack preview</div>
            <div className="graph-markdown-preview">
              <MarkdownView value={contextPack?.markdown || ''} />
            </div>
          </div>

          <div className="graph-context-cube-block" style={{ marginTop: 12 }}>
            <div className="meta">Knowledge graph pack composition</div>
            {graphPackSnapshot.tiles.length === 0 ? (
              <div className="meta" style={{ marginTop: 6 }}>No knowledge graph context has been produced yet.</div>
            ) : (
              <div className="graph-context-cube-grid graph-context-cube-grid-dense graph-context-cube-grid-entities" role="img" aria-label="Knowledge graph context composition map">
                {graphPackSnapshot.tiles.map((tile, idx) => (
                  <span
                    key={`kg-pack-cube-${idx}-${tile.key}`}
                    className="graph-context-cube"
                    style={{ backgroundColor: tile.color }}
                    title={tile.label}
                  />
                ))}
              </div>
            )}
            <div className="meta">
              ~{graphPackSnapshot.approxTokens.toLocaleString()} tokens · {graphPackSnapshot.totalChars.toLocaleString()} chars · {graphPackSnapshot.totalLines.toLocaleString()} lines
            </div>
            <div className="meta">
              Resolution: {graphPackSnapshot.tileCount.toLocaleString()} cells · ~{Math.max(1, Math.round(graphPackSnapshot.charsPerTile || 0)).toLocaleString()} chars per cell
            </div>
            <div className="meta">
              Chat indexing policy: {chatIndexModeLabel(normalizedChatIndexMode)} · Attachment ingestion: {chatAttachmentModeLabel(normalizedChatAttachmentMode)}
            </div>
            <div className="meta">
              Chat-derived evidence: {graphPackSnapshot.chatEvidenceCount} / {graphPackSnapshot.chatEvidenceCount + graphPackSnapshot.nonChatEvidenceCount} ({graphPackSnapshot.chatEvidenceSharePct.toFixed(1)}%) · Distinct chat entities: {graphPackSnapshot.chatEvidenceEntityCount}
            </div>
            <div className="graph-context-legend">
              {graphPackSnapshot.sources.map((source) => (
                <div key={`kg-pack-source-${source.key}`} className="graph-context-legend-row">
                  <span className="graph-context-legend-swatch" style={{ backgroundColor: source.color }} />
                  <span className="graph-context-legend-label">{source.label}</span>
                  <span className="meta">
                    {source.percent.toFixed(1)}% pack · {source.chars.toLocaleString()} chars
                    {source.lines > 0 ? ` · ${source.lines} lines` : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
