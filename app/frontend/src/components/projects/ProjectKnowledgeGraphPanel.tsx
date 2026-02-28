import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ForceGraph2D from 'react-force-graph-2d'
import * as Accordion from '@radix-ui/react-accordion'
import * as Tabs from '@radix-ui/react-tabs'
import { Background, Controls, MarkerType, MiniMap, Position, ReactFlow, type Edge as FlowEdge, type Node as FlowNode, type ReactFlowInstance } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  getProjectEventStormingComponentLinks,
  getProjectEventStormingEntityLinks,
  patchProject,
  patchProjectEventStormingLinkReview,
} from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import type {
  EventStormingComponentLinks,
  EventStormingEntityLinks,
  EventStormingOverview,
  EventStormingSubgraph,
  GraphContextPack,
  GraphProjectOverview,
  GraphProjectSubgraph,
  ProjectKnowledgeSearchResult,
} from '../../types'
import { Icon } from '../shared/uiHelpers'

type QueryLike<T> = {
  data?: T
  isLoading?: boolean
  isFetching?: boolean
  isError?: boolean
  error?: unknown
  refetch?: () => void
}

type KnowledgeGraphTab = 'overview' | 'explore' | 'pack'

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

type ReactFlowNodeData = {
  label: string
  entityType: string
  contextLabel?: string
}

type EventStormingTypeKey =
  | 'boundedcontext'
  | 'aggregate'
  | 'command'
  | 'domainevent'
  | 'policy'
  | 'readmodel'
  | 'task'
  | 'specification'
  | 'note'
  | 'other'

type EventStormingTypeMeta = {
  label: string
  sticky: string
  text: string
  border: string
  lane: 'core' | 'artifact' | 'context'
}

const EVENT_STORMING_LANE_START_X = 18
const EVENT_STORMING_LANE_WIDTH = 216
const EVENT_STORMING_LANE_GAP = 8

const EVENT_STORMING_TYPE_META: Record<EventStormingTypeKey, EventStormingTypeMeta> = {
  boundedcontext: {
    label: 'Bounded Context',
    sticky: '#d5f5f1',
    text: '#134e4a',
    border: '#14b8a6',
    lane: 'context',
  },
  aggregate: {
    label: 'Aggregate',
    sticky: '#fde68a',
    text: '#78350f',
    border: '#f59e0b',
    lane: 'core',
  },
  command: {
    label: 'Command',
    sticky: '#bfdbfe',
    text: '#1e3a8a',
    border: '#2563eb',
    lane: 'core',
  },
  domainevent: {
    label: 'Domain Event',
    sticky: '#fed7aa',
    text: '#9a3412',
    border: '#ea580c',
    lane: 'core',
  },
  policy: {
    label: 'Policy',
    sticky: '#e9d5ff',
    text: '#581c87',
    border: '#7c3aed',
    lane: 'core',
  },
  readmodel: {
    label: 'Read Model',
    sticky: '#bbf7d0',
    text: '#14532d',
    border: '#16a34a',
    lane: 'core',
  },
  task: {
    label: 'Task',
    sticky: '#e2e8f0',
    text: '#0f172a',
    border: '#64748b',
    lane: 'artifact',
  },
  specification: {
    label: 'Specification',
    sticky: '#e2e8f0',
    text: '#0f172a',
    border: '#64748b',
    lane: 'artifact',
  },
  note: {
    label: 'Note',
    sticky: '#e2e8f0',
    text: '#0f172a',
    border: '#64748b',
    lane: 'artifact',
  },
  other: {
    label: 'Entity',
    sticky: '#e2e8f0',
    text: '#0f172a',
    border: '#64748b',
    lane: 'artifact',
  },
}

const EVENT_STORMING_STAGE_ORDER: EventStormingTypeKey[] = [
  'command',
  'aggregate',
  'domainevent',
  'policy',
  'readmodel',
  'task',
  'specification',
  'note',
]

function normalizeEventStormingTypeKey(entityType: string): EventStormingTypeKey {
  const normalized = String(entityType || '').trim().toLowerCase()
  if (normalized === 'boundedcontext') return 'boundedcontext'
  if (normalized === 'aggregate') return 'aggregate'
  if (normalized === 'command') return 'command'
  if (normalized === 'domainevent') return 'domainevent'
  if (normalized === 'policy') return 'policy'
  if (normalized === 'readmodel') return 'readmodel'
  if (normalized === 'task') return 'task'
  if (normalized === 'specification') return 'specification'
  if (normalized === 'note') return 'note'
  return 'other'
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
  sourceKey: string
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

function formatPercent(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0.0%'
  return `${value.toFixed(1)}%`
}

function normalizeScorePercent(value: number | null | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, value * 100))
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

function graphPackSourceGroupLabel(sourceKey: string): string {
  if (sourceKey.includes('evidence')) return 'Evidence payload'
  if (sourceKey.includes('summary') || sourceKey.includes('context')) return 'Graph narrative'
  return 'Metadata envelope'
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
        sourceKey: slice.key,
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
  userId,
  projectId,
  projectName,
  projectChatIndexMode,
  projectChatAttachmentIngestionMode,
  overviewQuery,
  contextPackQuery,
  subgraphQuery,
  eventStormingOverviewQuery,
  eventStormingSubgraphQuery,
  knowledgeSearchQuery,
  setKnowledgeSearchQuery,
  knowledgeSearchResultsQuery,
  onCreateTaskFromSummary,
  onCreateNoteFromSummary,
  onLinkFocusTaskToSpecification,
}: {
  userId: string
  projectId: string
  projectName: string
  projectChatIndexMode?: string
  projectChatAttachmentIngestionMode?: string
  overviewQuery: QueryLike<GraphProjectOverview>
  contextPackQuery: QueryLike<GraphContextPack>
  subgraphQuery: QueryLike<GraphProjectSubgraph>
  eventStormingOverviewQuery: QueryLike<EventStormingOverview>
  eventStormingSubgraphQuery: QueryLike<EventStormingSubgraph>
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
  const [isEventStormingFullscreen, setIsEventStormingFullscreen] = React.useState(false)
  const [selectedEventStormingNodeId, setSelectedEventStormingNodeId] = React.useState<string | null>(null)
  const [showEventStormingArtifactsOnDiagram, setShowEventStormingArtifactsOnDiagram] = React.useState(false)
  const [showRejectedEventStormingLinks, setShowRejectedEventStormingLinks] = React.useState(false)
  const [eventStormingViewportTransform, setEventStormingViewportTransform] = React.useState({ x: 0, zoom: 1 })
  const [selectedEvidenceId, setSelectedEvidenceId] = React.useState<string | null>(null)
  const [activeTab, setActiveTab] = React.useState<KnowledgeGraphTab>('explore')
  const [overviewTab, setOverviewTab] = React.useState<'summary' | 'composition'>('summary')
  const [packTab, setPackTab] = React.useState<'composition' | 'markdown'>('composition')
  const [selectedOverviewSourceKey, setSelectedOverviewSourceKey] = React.useState<string | null>(null)
  const [selectedPackSourceKey, setSelectedPackSourceKey] = React.useState<string | null>(null)
  const [actionBusy, setActionBusy] = React.useState<string | null>(null)
  const [actionError, setActionError] = React.useState<string | null>(null)

  const graphRef = React.useRef<any>(null)
  const graphShellRef = React.useRef<HTMLDivElement | null>(null)
  const graphCanvasRef = React.useRef<HTMLDivElement | null>(null)
  const eventStormingShellRef = React.useRef<HTMLDivElement | null>(null)
  const eventStormingFlowRef = React.useRef<ReactFlowInstance<FlowNode<ReactFlowNodeData>, FlowEdge> | null>(null)
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
  const eventStormingOverview = eventStormingOverviewQuery.data
  const eventStormingSubgraph = eventStormingSubgraphQuery.data
  const eventStormingNodes = eventStormingSubgraph?.nodes ?? []
  const eventStormingEdges = eventStormingSubgraph?.edges ?? []
  const eventStormingProcessing = eventStormingOverview?.processing ?? {
    artifact_total: 0,
    processed: 0,
    queued: 0,
    running: 0,
    failed: 0,
    done: 0,
    progress_pct: 0,
  }
  const eventStormingProgressPct = Math.max(0, Math.min(100, Number(eventStormingProcessing.progress_pct || 0)))
  const eventStormingFrameModeRaw = String(eventStormingOverview?.context_frame?.mode || '').trim().toLowerCase()
  const eventStormingFrameMode = eventStormingFrameModeRaw === 'full' || eventStormingFrameModeRaw === 'delta'
    ? eventStormingFrameModeRaw.toUpperCase()
    : null
  const eventStormingFrameRevision = String(eventStormingOverview?.context_frame?.revision || '').trim()
  const eventStormingFrameRevisionShort = eventStormingFrameRevision ? eventStormingFrameRevision.slice(0, 8) : null
  const eventStormingFrameUpdatedAtRaw = String(eventStormingOverview?.context_frame?.updated_at || '').trim()
  const eventStormingFrameUpdatedAtLabel = eventStormingFrameUpdatedAtRaw
    ? new Date(eventStormingFrameUpdatedAtRaw).toLocaleString()
    : null
  const eventStormingProcessingActive = React.useMemo(() => {
    const enabled = Boolean(eventStormingOverview?.event_storming_enabled ?? true)
    if (!enabled) return false
    const queued = Number(eventStormingProcessing.queued || 0)
    const running = Number(eventStormingProcessing.running || 0)
    const processed = Number(eventStormingProcessing.processed || 0)
    const total = Number(eventStormingProcessing.artifact_total || 0)
    return queued > 0 || running > 0 || (total > 0 && processed < total)
  }, [
    eventStormingOverview?.event_storming_enabled,
    eventStormingProcessing.artifact_total,
    eventStormingProcessing.processed,
    eventStormingProcessing.queued,
    eventStormingProcessing.running,
  ])
  const eventStormingComponentStats = React.useMemo(() => {
    const normalizedCounts = new Map<EventStormingTypeKey, number>()
    for (const [rawKey, rawValue] of Object.entries(eventStormingOverview?.component_counts ?? {})) {
      const key = normalizeEventStormingTypeKey(rawKey)
      const current = normalizedCounts.get(key) ?? 0
      const nextValue = Number(rawValue || 0)
      normalizedCounts.set(key, current + (Number.isFinite(nextValue) ? nextValue : 0))
    }
    const orderedKeys: EventStormingTypeKey[] = [
      'boundedcontext',
      'aggregate',
      'command',
      'domainevent',
      'policy',
      'readmodel',
    ]
    return orderedKeys.map((key) => ({
      key,
      label: EVENT_STORMING_TYPE_META[key].label,
      color: EVENT_STORMING_TYPE_META[key].border,
      count: normalizedCounts.get(key) ?? 0,
    }))
  }, [eventStormingOverview?.component_counts])
  const queryClient = useQueryClient()
  const eventStormingComponentTypes = React.useMemo(
    () => new Set(['boundedcontext', 'aggregate', 'command', 'domainevent', 'policy', 'readmodel']),
    []
  )
  const eventStormingArtifactTypes = React.useMemo(() => new Set(['task', 'note', 'specification']), [])
  const selectedEventStormingNode = React.useMemo(
    () => eventStormingNodes.find((node) => String(node.entity_id || '') === String(selectedEventStormingNodeId || '')) ?? null,
    [eventStormingNodes, selectedEventStormingNodeId]
  )
  const selectedEventStormingNodeType = String(selectedEventStormingNode?.entity_type || '')
    .trim()
    .toLowerCase()
  const selectedEventStormingIsComponent = eventStormingComponentTypes.has(selectedEventStormingNodeType)
  const selectedEventStormingIsArtifact = eventStormingArtifactTypes.has(selectedEventStormingNodeType)
  const eventStormingEntityLinksQuery = useQuery<EventStormingEntityLinks>({
    queryKey: [
      'project-event-storming-entity-links',
      userId,
      projectId,
      selectedEventStormingNodeType,
      selectedEventStormingNodeId,
    ],
    queryFn: () =>
      getProjectEventStormingEntityLinks(userId, projectId, {
        entity_type: String(selectedEventStormingNode?.entity_type || ''),
        entity_id: String(selectedEventStormingNode?.entity_id || ''),
      }),
    enabled: Boolean(
      userId &&
      projectId &&
      selectedEventStormingNodeId &&
      selectedEventStormingNode &&
      selectedEventStormingIsArtifact
    ),
  })
  const eventStormingComponentLinksQuery = useQuery<EventStormingComponentLinks>({
    queryKey: ['project-event-storming-component-links', userId, projectId, selectedEventStormingNodeId],
    queryFn: () =>
      getProjectEventStormingComponentLinks(userId, projectId, {
        component_id: String(selectedEventStormingNode?.entity_id || ''),
      }),
    enabled: Boolean(
      userId &&
      projectId &&
      selectedEventStormingNodeId &&
      selectedEventStormingNode &&
      selectedEventStormingIsComponent
    ),
  })
  const reviewEventStormingLinkMutation = useMutation({
    mutationFn: (payload: {
      entity_type: string
      entity_id: string
      component_id: string
      review_status: 'candidate' | 'approved' | 'rejected'
      confidence?: number
    }) => patchProjectEventStormingLinkReview(userId, projectId, payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-overview', userId, projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-subgraph', userId, projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-entity-links', userId, projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-component-links', userId, projectId] }),
      ])
    },
  })

  const toggleEventStormingProjectMutation = useMutation({
    mutationFn: (enabled: boolean) => patchProject(userId, projectId, { event_storming_enabled: enabled }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['bootstrap', userId] }),
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-overview', userId, projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-event-storming-subgraph', userId, projectId] }),
      ])
    },
  })
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
    if (!eventStormingNodes.length) {
      setSelectedEventStormingNodeId(null)
      return
    }
    if (selectedEventStormingNodeId && eventStormingNodes.some((node) => node.entity_id === selectedEventStormingNodeId)) return
    setSelectedEventStormingNodeId(eventStormingNodes[0]?.entity_id ?? null)
  }, [eventStormingNodes, selectedEventStormingNodeId])

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
    if (key === 'boundedcontext') return '#14b8a6'
    if (key === 'aggregate') return '#f59e0b'
    if (key === 'command') return '#2563eb'
    if (key === 'domainevent') return '#ea580c'
    if (key === 'policy') return '#7c3aed'
    if (key === 'readmodel') return '#16a34a'
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

  const eventStormingNodeColor = React.useCallback((entityType: string) => {
    const key = normalizeEventStormingTypeKey(entityType)
    return EVENT_STORMING_TYPE_META[key].border
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

  const eventStormingFlowNodes = React.useMemo(() => {
    if (!eventStormingNodes.length) return [] as FlowNode<ReactFlowNodeData>[]
    const diagramEdges = eventStormingEdges.filter((edge) => {
      const relation = String(edge.relationship || '').trim().toUpperCase()
      const reviewStatus = String(edge.review_status || 'candidate').trim().toLowerCase()
      if (!showRejectedEventStormingLinks && relation === 'RELATES_TO_ES' && reviewStatus === 'rejected') return false
      return true
    })
    const supportedComponentIds = new Set<string>()
    for (const edge of diagramEdges) {
      const relation = String(edge.relationship || '').trim().toUpperCase()
      if (relation !== 'RELATES_TO_ES') continue
      const source = String(edge.source_entity_id || '').trim()
      const target = String(edge.target_entity_id || '').trim()
      const sourceNode = eventStormingNodes.find((node) => String(node.entity_id || '').trim() === source)
      const targetNode = eventStormingNodes.find((node) => String(node.entity_id || '').trim() === target)
      const sourceType = normalizeEventStormingTypeKey(String(sourceNode?.entity_type || ''))
      const targetType = normalizeEventStormingTypeKey(String(targetNode?.entity_type || ''))
      const sourceIsArtifact = sourceType === 'task' || sourceType === 'specification' || sourceType === 'note'
      const targetIsArtifact = targetType === 'task' || targetType === 'specification' || targetType === 'note'
      if (!sourceIsArtifact && !targetIsArtifact) continue
      if (!targetIsArtifact) supportedComponentIds.add(target)
      if (!sourceIsArtifact) supportedComponentIds.add(source)
    }
    const visibleNodeIds = new Set<string>()
    for (const edge of diagramEdges) {
      const source = String(edge.source_entity_id || '').trim()
      const target = String(edge.target_entity_id || '').trim()
      if (source) visibleNodeIds.add(source)
      if (target) visibleNodeIds.add(target)
    }
    const diagramNodes = eventStormingNodes.filter((node) => {
      const nodeId = String(node.entity_id || '').trim()
      const typeKey = normalizeEventStormingTypeKey(String(node.entity_type || ''))
      if (typeKey === 'boundedcontext') return true
      if (!showEventStormingArtifactsOnDiagram && (typeKey === 'task' || typeKey === 'specification' || typeKey === 'note')) {
        return false
      }
      if (
        typeKey !== 'task' &&
        typeKey !== 'specification' &&
        typeKey !== 'note' &&
        !supportedComponentIds.has(nodeId)
      ) {
        return false
      }
      return visibleNodeIds.has(nodeId)
    })
    const nodeById = new Map(diagramNodes.map((node) => [String(node.entity_id || ''), node]))
    const componentTypeSet = new Set(['boundedcontext', 'aggregate', 'command', 'domainevent', 'policy', 'readmodel'])
    const componentIds = new Set(
      diagramNodes
        .filter((node) => componentTypeSet.has(normalizeEventStormingTypeKey(String(node.entity_type || ''))))
        .map((node) => String(node.entity_id || ''))
    )
    const contextIds = eventStormingNodes
      .filter((node) => normalizeEventStormingTypeKey(String(node.entity_type || '')) === 'boundedcontext')
      .map((node) => String(node.entity_id || ''))
      .filter(Boolean)
    const adjacency = new Map<string, Set<string>>()
    for (const edge of diagramEdges) {
      const source = String(edge.source_entity_id || '')
      const target = String(edge.target_entity_id || '')
      if (!source || !target) continue
      if (!componentIds.has(source) || !componentIds.has(target)) continue
      const srcNeighbors = adjacency.get(source) ?? new Set<string>()
      srcNeighbors.add(target)
      adjacency.set(source, srcNeighbors)
      const dstNeighbors = adjacency.get(target) ?? new Set<string>()
      dstNeighbors.add(source)
      adjacency.set(target, dstNeighbors)
    }

    const contextDistanceByNode = new Map<string, number>()
    const contextByNodeId = new Map<string, string>()
    const queue: Array<{ nodeId: string; rootContextId: string; distance: number }> = []
    for (const contextId of contextIds) {
      contextByNodeId.set(contextId, contextId)
      contextDistanceByNode.set(contextId, 0)
      queue.push({ nodeId: contextId, rootContextId: contextId, distance: 0 })
    }
    while (queue.length > 0) {
      const current = queue.shift()
      if (!current) break
      const neighbors = adjacency.get(current.nodeId)
      if (!neighbors || neighbors.size === 0) continue
      for (const nextId of neighbors) {
        const nextDistance = current.distance + 1
        const bestDistance = contextDistanceByNode.get(nextId)
        if (bestDistance !== undefined && bestDistance <= nextDistance) continue
        contextDistanceByNode.set(nextId, nextDistance)
        contextByNodeId.set(nextId, current.rootContextId)
        queue.push({ nodeId: nextId, rootContextId: current.rootContextId, distance: nextDistance })
      }
    }

    const contextLabelById = new Map<string, string>()
    for (const contextId of contextIds) {
      const node = nodeById.get(contextId)
      contextLabelById.set(contextId, String(node?.title || contextId))
    }
    const sharedContextLabel = 'Shared Context'
    const rows = new Map<string, typeof eventStormingNodes>()
    const ensureRow = (contextLabel: string) => {
      const bucket = rows.get(contextLabel)
      if (bucket) return bucket
      const next: typeof eventStormingNodes = []
      rows.set(contextLabel, next)
      return next
    }
    const resolveContextLabel = (nodeId: string): string => {
      const contextId = contextByNodeId.get(nodeId)
      if (!contextId) return sharedContextLabel
      return String(contextLabelById.get(contextId) || sharedContextLabel)
    }

    for (const node of diagramNodes) {
      const nodeId = String(node.entity_id || '')
      if (!nodeId) continue
      const typeKey = normalizeEventStormingTypeKey(String(node.entity_type || ''))
      if (typeKey === 'other') continue
      const isArtifact = EVENT_STORMING_TYPE_META[typeKey].lane === 'artifact'
      if (isArtifact) {
        const linkedComponents = eventStormingEdges
          .filter((edge) => String(edge.source_entity_id || '') === nodeId || String(edge.target_entity_id || '') === nodeId)
          .map((edge) => {
            const source = String(edge.source_entity_id || '')
            const target = String(edge.target_entity_id || '')
            return source === nodeId ? target : source
          })
          .filter((candidateId) => componentIds.has(candidateId))
        const contextLabel = linkedComponents.length ? resolveContextLabel(linkedComponents[0] || '') : sharedContextLabel
        ensureRow(contextLabel).push(node)
        continue
      }
      ensureRow(resolveContextLabel(nodeId)).push(node)
    }

    const orderedContexts = Array.from(rows.keys()).sort((a, b) => {
      if (a === sharedContextLabel) return 1
      if (b === sharedContextLabel) return -1
      return a.localeCompare(b)
    })

    const stageByTypeKey: Record<EventStormingTypeKey, EventStormingTypeKey> = {
      boundedcontext: 'boundedcontext',
      aggregate: 'aggregate',
      command: 'command',
      domainevent: 'domainevent',
      policy: 'policy',
      readmodel: 'readmodel',
      task: 'task',
      specification: 'specification',
      note: 'note',
      other: 'task',
    }

    const laneStartX = EVENT_STORMING_LANE_START_X
    const lanePitch = EVENT_STORMING_LANE_WIDTH + EVENT_STORMING_LANE_GAP
    const stageX: Record<EventStormingTypeKey, number> = {
      // Keep bounded context anchored to the first lane so Command..Note align with headers.
      boundedcontext: laneStartX,
      command: laneStartX + lanePitch * 0,
      aggregate: laneStartX + lanePitch * 1,
      domainevent: laneStartX + lanePitch * 2,
      policy: laneStartX + lanePitch * 3,
      readmodel: laneStartX + lanePitch * 4,
      task: laneStartX + lanePitch * 5,
      specification: laneStartX + lanePitch * 6,
      note: laneStartX + lanePitch * 7,
      other: laneStartX + lanePitch * 5,
    }

    const out: FlowNode<ReactFlowNodeData>[] = []
    let rowTop = 12
    for (const contextLabel of orderedContexts) {
      const rowNodes = [...(rows.get(contextLabel) ?? [])]
      const byStage = new Map<EventStormingTypeKey, typeof rowNodes>()
      for (const item of rowNodes) {
        const typeKey = normalizeEventStormingTypeKey(String(item.entity_type || ''))
        const stageKey = stageByTypeKey[typeKey]
        const stageItems = byStage.get(stageKey) ?? []
        stageItems.push(item)
        byStage.set(stageKey, stageItems)
      }
      for (const stageItems of byStage.values()) {
        stageItems.sort((a, b) => {
          const degreeDiff = Number(b.degree || 0) - Number(a.degree || 0)
          if (degreeDiff !== 0) return degreeDiff
          const titleA = String(a.title || a.entity_id || '').toLowerCase()
          const titleB = String(b.title || b.entity_id || '').toLowerCase()
          if (titleA !== titleB) return titleA.localeCompare(titleB)
          return String(a.entity_id || '').localeCompare(String(b.entity_id || ''))
        })
      }

      const maxStageCount = Array.from(byStage.values()).reduce((max, items) => Math.max(max, items.length), 1)
      const rowHeight = Math.max(210, 84 + maxStageCount * 82)

      for (const stageKey of EVENT_STORMING_STAGE_ORDER) {
        const stageItems = byStage.get(stageKey) ?? []
        for (let idx = 0; idx < stageItems.length; idx += 1) {
          const item = stageItems[idx]
          if (!item) continue
          const itemId = String(item.entity_id || '')
          const itemType = normalizeEventStormingTypeKey(String(item.entity_type || ''))
          const meta = EVENT_STORMING_TYPE_META[itemType]
          const selected = itemId === String(selectedEventStormingNodeId || '')
          out.push({
            id: itemId,
            position: { x: stageX[stageKey], y: rowTop + 66 + idx * 82 },
            data: {
              label: String(item.title || itemId),
              entityType: String(item.entity_type || 'Entity'),
              contextLabel,
            },
            style: {
              border: selected ? '2px solid #22c55e' : `1px solid ${meta.border}`,
              borderRadius: 8,
              width: stageKey === 'task' ? 216 : 204,
              minHeight: 60,
              padding: '8px 10px',
              color: meta.text,
              background: meta.sticky,
              boxShadow: selected ? '0 0 0 2px rgba(34,197,94,0.14), 0 4px 10px rgba(15,23,42,0.12)' : '0 2px 8px rgba(15,23,42,0.10)',
              fontSize: 12,
              fontWeight: 700,
              lineHeight: 1.3,
            },
            sourcePosition: Position.Right,
            targetPosition: Position.Left,
            draggable: false,
          })
        }
      }

      const contextItems = byStage.get('boundedcontext') ?? []
      if (contextItems.length > 0) {
        const contextItem = contextItems[0]
        const contextId = String(contextItem?.entity_id || `ctx-${contextLabel}`)
        const selected = contextId === String(selectedEventStormingNodeId || '')
        const contextMeta = EVENT_STORMING_TYPE_META.boundedcontext
        out.push({
          id: contextId,
          position: { x: stageX.boundedcontext, y: rowTop + 62 },
          data: {
            label: String(contextItem?.title || contextLabel),
            entityType: String(contextItem?.entity_type || 'BoundedContext'),
            contextLabel,
          },
          style: {
            border: selected ? '2px solid #22c55e' : `1px solid ${contextMeta.border}`,
            borderRadius: 10,
            width: 212,
            minHeight: 64,
            padding: '8px 10px',
            color: contextMeta.text,
            background: contextMeta.sticky,
            boxShadow: selected ? '0 0 0 2px rgba(34,197,94,0.14), 0 4px 10px rgba(15,23,42,0.12)' : '0 2px 8px rgba(15,23,42,0.10)',
            fontSize: 12,
            fontWeight: 800,
            lineHeight: 1.3,
          },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          draggable: false,
        })
      }

      rowTop += rowHeight + 24
    }
    return out
  }, [
    eventStormingEdges,
    eventStormingNodes,
    selectedEventStormingNodeId,
    showRejectedEventStormingLinks,
    showEventStormingArtifactsOnDiagram,
  ])

  const eventStormingFlowEdges = React.useMemo(
    () => {
      const flowNodeIdSet = new Set(eventStormingFlowNodes.map((node) => String(node.id || '')))
      const edgeMeta: Record<
        string,
        { color: string; width: number; dash?: string; label: string }
      > = {
        CONTAINS_AGGREGATE: { color: '#0284c7', width: 1.6, label: 'contains' },
        HANDLES_COMMAND: { color: '#2563eb', width: 1.7, label: 'handles' },
        EMITS_EVENT: { color: '#ea580c', width: 1.9, label: 'emits' },
        TRIGGERS_POLICY: { color: '#7c3aed', width: 1.7, label: 'triggers' },
        ENFORCES_POLICY: { color: '#6d28d9', width: 1.7, label: 'enforces' },
        UPDATES_READ_MODEL: { color: '#16a34a', width: 1.8, label: 'updates' },
        RELATES_TO_ES: { color: '#64748b', width: 1.3, dash: '4 3', label: 'touches' },
      }

      return eventStormingEdges
        .map((edge, idx) => {
          const source = String(edge.source_entity_id || '')
          const target = String(edge.target_entity_id || '')
          if (!source || !target) return null
          if (!flowNodeIdSet.has(source) || !flowNodeIdSet.has(target)) return null
          const relation = String(edge.relationship || 'RELATED').trim().toUpperCase()
          const reviewStatus = String(edge.review_status || 'candidate').trim().toLowerCase()
          if (!showRejectedEventStormingLinks && relation === 'RELATES_TO_ES' && reviewStatus === 'rejected') {
            return null
          }
          let meta = edgeMeta[relation] ?? { color: '#475569', width: 1.25, label: relation.toLowerCase() }
          if (relation === 'RELATES_TO_ES') {
            if (reviewStatus === 'approved') {
              meta = { color: '#16a34a', width: 1.8, label: 'approved link' }
            } else if (reviewStatus === 'rejected') {
              meta = { color: '#dc2626', width: 1.5, dash: '5 4', label: 'rejected link' }
            } else {
              meta = { color: '#f59e0b', width: 1.5, dash: '4 3', label: 'candidate link' }
            }
          }
          return {
            id: `es-edge-${idx}-${source}-${target}`,
            source,
            target,
            type: 'smoothstep',
            label: meta.label,
            labelStyle: { fontSize: 10, fill: '#334155', fontWeight: 700 },
            labelBgStyle: { fill: 'rgba(248,250,252,0.9)', fillOpacity: 0.92 },
            markerEnd: { type: MarkerType.ArrowClosed, color: meta.color },
            style: { stroke: meta.color, strokeWidth: meta.width, strokeDasharray: meta.dash },
            animated: relation === 'EMITS_EVENT' || relation === 'TRIGGERS_POLICY',
          } as FlowEdge
        })
        .filter((edge): edge is FlowEdge => Boolean(edge))
    },
    [eventStormingEdges, eventStormingFlowNodes, showRejectedEventStormingLinks]
  )
  const eventStormingLaneLegend = React.useMemo(
    () => [
      { key: 'command', ...EVENT_STORMING_TYPE_META.command },
      { key: 'aggregate', ...EVENT_STORMING_TYPE_META.aggregate },
      { key: 'domainevent', ...EVENT_STORMING_TYPE_META.domainevent },
      { key: 'policy', ...EVENT_STORMING_TYPE_META.policy },
      { key: 'readmodel', ...EVENT_STORMING_TYPE_META.readmodel },
      { key: 'task', label: 'Artifacts', sticky: '#e2e8f0', text: '#0f172a', border: '#64748b', lane: 'artifact' as const },
    ],
    []
  )
  const eventStormingLaneHeaders = React.useMemo(
    () => [
      { key: 'command', label: 'Command' },
      { key: 'aggregate', label: 'Aggregate' },
      { key: 'event', label: 'Domain Event' },
      { key: 'policy', label: 'Policy' },
      { key: 'readmodel', label: 'Read Model' },
      { key: 'task', label: 'Task' },
      { key: 'specification', label: 'Specification' },
      { key: 'note', label: 'Note' },
    ],
    []
  )
  const eventStormingReviewLegend = React.useMemo(
    () => [
      { key: 'approved', label: 'Approved link', color: '#16a34a' },
      { key: 'candidate', label: 'Candidate link', color: '#f59e0b' },
      { key: 'rejected', label: 'Rejected link', color: '#dc2626' },
    ],
    []
  )

  const selectedNode = graphData.nodes.find((node) => node.id === selectedNodeId) ?? null
  const connectedSelectedEdges = selectedNode
    ? graphData.links.filter((edge) => String(edge.source) === selectedNode.id || String(edge.target) === selectedNode.id)
    : []
  const normalizedKnowledgeSearchQuery = String(knowledgeSearchQuery || '').trim()
  const knowledgeSearchActive = normalizedKnowledgeSearchQuery.length >= 2
  const knowledgeSearchItems = knowledgeSearchResultsQuery.data?.items ?? []
  const knowledgeSearchMode = knowledgeSearchResultsQuery.data?.mode ?? 'empty'
  const overviewEntityCount = counts.tasks + counts.notes + counts.specifications + counts.project_rules + counts.comments
  const overviewSources = React.useMemo(() => {
    const base = [
      { key: 'tasks', label: 'Tasks', color: '#0284c7', count: Number(counts.tasks || 0) },
      { key: 'notes', label: 'Notes', color: '#9333ea', count: Number(counts.notes || 0) },
      { key: 'specifications', label: 'Specifications', color: '#0d9488', count: Number(counts.specifications || 0) },
      { key: 'rules', label: 'Rules', color: '#ea580c', count: Number(counts.project_rules || 0) },
      { key: 'comments', label: 'Comments', color: '#16a34a', count: Number(counts.comments || 0) },
    ]
    const total = base.reduce((sum, item) => sum + item.count, 0)
    return base
      .filter((item) => item.count > 0)
      .map((item) => ({
        ...item,
        percent: total > 0 ? (item.count / total) * 100 : 0,
      }))
  }, [counts.comments, counts.notes, counts.project_rules, counts.specifications, counts.tasks])
  const overviewTiles = React.useMemo(
    () =>
      buildGraphCubeTiles(
        overviewSources.map((item) => ({
          key: item.key,
          label: item.label,
          color: item.color,
          value: item.count,
        })),
        300
      ),
    [overviewSources]
  )
  const packSourceGroups = React.useMemo(() => {
    const order = ['Graph narrative', 'Evidence payload', 'Metadata envelope']
    const bucket = new Map<string, GraphPackSourceUsage[]>()
    for (const source of graphPackSnapshot.sources) {
      const group = graphPackSourceGroupLabel(source.key)
      const current = bucket.get(group) ?? []
      current.push(source)
      bucket.set(group, current)
    }
    return order
      .map((group) => {
        const items = bucket.get(group) ?? []
        const percent = items.reduce((sum, item) => sum + item.percent, 0)
        const chars = items.reduce((sum, item) => sum + item.chars, 0)
        return { group, items, percent, chars }
      })
      .filter((item) => item.items.length > 0)
  }, [graphPackSnapshot.sources])

  React.useEffect(() => {
    if (!overviewSources.length) {
      setSelectedOverviewSourceKey(null)
      return
    }
    if (selectedOverviewSourceKey && overviewSources.some((item) => item.key === selectedOverviewSourceKey)) return
    setSelectedOverviewSourceKey(overviewSources[0]?.key ?? null)
  }, [overviewSources, selectedOverviewSourceKey])

  React.useEffect(() => {
    const sources = graphPackSnapshot.sources
    if (!sources.length) {
      setSelectedPackSourceKey(null)
      return
    }
    if (selectedPackSourceKey && sources.some((source) => source.key === selectedPackSourceKey)) return
    setSelectedPackSourceKey(sources[0]?.key ?? null)
  }, [graphPackSnapshot.sources, selectedPackSourceKey])

  React.useEffect(() => {
    if (knowledgeSearchActive) setActiveTab('explore')
  }, [knowledgeSearchActive])

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

  const setEventStormingLinkReview = React.useCallback(
    async (payload: {
      entity_type: string
      entity_id: string
      component_id: string
      review_status: 'candidate' | 'approved' | 'rejected'
      confidence?: number
    }) => {
      await runAction(`es-review-${payload.entity_id}-${payload.component_id}-${payload.review_status}`, async () => {
        await reviewEventStormingLinkMutation.mutateAsync(payload)
      })
    },
    [reviewEventStormingLinkMutation, runAction]
  )

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
      const eventStormingShell = eventStormingShellRef.current
      setIsGraphFullscreen(Boolean(shell && document.fullscreenElement === shell))
      setIsEventStormingFullscreen(Boolean(eventStormingShell && document.fullscreenElement === eventStormingShell))
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

  const toggleEventStormingFullscreen = React.useCallback(async () => {
    const shell = eventStormingShellRef.current
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

  const exitEventStormingFullscreen = React.useCallback(async () => {
    const shell = eventStormingShellRef.current
    if (!shell) return
    try {
      if (document.fullscreenElement === shell) {
        await document.exitFullscreen()
      }
    } catch {
      // no-op
    }
  }, [])

  const fitEventStormingViewport = React.useCallback(
    (duration = 420) => {
      if (!eventStormingFlowNodes.length) return
      const instance = eventStormingFlowRef.current
      if (!instance) return
      try {
        instance.fitView({
          padding: isEventStormingFullscreen ? 0.08 : 0.12,
          duration,
          maxZoom: 1.0,
        })
        const anyInstance = instance as unknown as {
          getViewport?: () => { x: number; y: number; zoom: number }
          setViewport?: (viewport: { x: number; y: number; zoom: number }, options?: { duration?: number }) => void
          getNodesBounds?: (nodes: Array<{ id: string }>) => { x: number; y: number; width: number; height: number }
        }
        const viewport = anyInstance.getViewport?.()
        const bounds = anyInstance.getNodesBounds?.(eventStormingFlowNodes.map((node) => ({ id: String(node.id || '') })))
        if (!viewport || !bounds) return
        const leftGutter = EVENT_STORMING_LANE_START_X
        const alignedX = leftGutter - bounds.x * viewport.zoom
        if (!Number.isFinite(alignedX)) return
        anyInstance.setViewport?.({ ...viewport, x: alignedX }, { duration: Math.max(0, Math.round(duration * 0.75)) })
      } catch {
        // no-op
      }
    },
    [eventStormingFlowNodes]
  )

  const syncEventStormingViewportTransform = React.useCallback(() => {
    const viewport = eventStormingFlowRef.current?.getViewport?.()
    if (!viewport) return
    setEventStormingViewportTransform((prev) => {
      const nextX = Number(viewport.x || 0)
      const nextZoom = Number(viewport.zoom || 1)
      if (Math.abs(prev.x - nextX) < 0.1 && Math.abs(prev.zoom - nextZoom) < 0.001) return prev
      return { x: nextX, zoom: nextZoom }
    })
  }, [])
  const eventStormingHeaderStyle = React.useMemo(() => {
    const zoom = Math.max(0.35, Number(eventStormingViewportTransform.zoom || 1))
    const laneWidth = EVENT_STORMING_LANE_WIDTH * zoom
    const laneGap = EVENT_STORMING_LANE_GAP * zoom
    const lanePad = EVENT_STORMING_LANE_START_X * zoom
    const laneFont = Math.max(9.5, Math.min(13, 11 * zoom))
    return {
      transform: `translateX(${eventStormingViewportTransform.x}px)`,
      transformOrigin: 'left center',
      ['--es-lane-width' as any]: `${laneWidth}px`,
      ['--es-lane-gap' as any]: `${laneGap}px`,
      ['--es-lane-pad' as any]: `${lanePad}px`,
      ['--es-lane-font' as any]: `${laneFont}px`,
    } as React.CSSProperties
  }, [eventStormingViewportTransform.x, eventStormingViewportTransform.zoom])

  React.useEffect(() => {
    if (!graphData.nodes.length) return
    const timer = window.setTimeout(() => {
      zoomReset()
    }, 60)
    return () => window.clearTimeout(timer)
  }, [graphData.nodes.length, graphData.links.length, canvasSize.width, canvasSize.height, zoomReset])

  React.useEffect(() => {
    if (!eventStormingFlowNodes.length) return
    const timer = window.setTimeout(() => {
      fitEventStormingViewport(420)
    }, 100)
    return () => window.clearTimeout(timer)
  }, [eventStormingFlowNodes.length, eventStormingFlowEdges.length, isEventStormingFullscreen, fitEventStormingViewport])

  React.useEffect(() => {
    if (!eventStormingProcessingActive) return
    const timer = window.setInterval(() => {
      eventStormingOverviewQuery.refetch?.()
      eventStormingSubgraphQuery.refetch?.()
    }, 2500)
    return () => window.clearInterval(timer)
  }, [eventStormingProcessingActive, eventStormingOverviewQuery, eventStormingSubgraphQuery])

  const eventStormingEntityLinkItems = eventStormingEntityLinksQuery.data?.items ?? []
  const eventStormingComponentLinkItems = eventStormingComponentLinksQuery.data?.items ?? []
  const visibleEventStormingEntityLinkItems = React.useMemo(
    () =>
      showRejectedEventStormingLinks
        ? eventStormingEntityLinkItems
        : eventStormingEntityLinkItems.filter((item) => String(item.review_status || '').toLowerCase() !== 'rejected'),
    [eventStormingEntityLinkItems, showRejectedEventStormingLinks]
  )
  const visibleEventStormingComponentLinkItems = React.useMemo(
    () =>
      showRejectedEventStormingLinks
        ? eventStormingComponentLinkItems
        : eventStormingComponentLinkItems.filter((item) => String(item.review_status || '').toLowerCase() !== 'rejected'),
    [eventStormingComponentLinkItems, showRejectedEventStormingLinks]
  )
  const eventStormingLinksLoading = Boolean(
    eventStormingEntityLinksQuery.isLoading || eventStormingComponentLinksQuery.isLoading
  )
  const eventStormingLinksError = eventStormingEntityLinksQuery.isError
    ? eventStormingEntityLinksQuery.error
    : eventStormingComponentLinksQuery.isError
      ? eventStormingComponentLinksQuery.error
      : null
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

          <div className="graph-insights-meta-row">
            <span className="badge">Retrieval: {contextPack?.mode ?? 'graph-only'}</span>
            <span className="badge">
              Chat policy: {chatIndexModeLabel(normalizedChatIndexMode)} / {chatAttachmentModeLabel(normalizedChatAttachmentMode)}
            </span>
            <span className="badge">Nodes: {graphData.nodes.length}</span>
            <span className="badge">Edges: {graphData.links.length}</span>
            <span className="badge">Evidence: {evidenceItems.length}</span>
          </div>

          <Tabs.Root className="kg-insights-tabs" value={activeTab} onValueChange={(value) => setActiveTab(value as KnowledgeGraphTab)}>
            <Tabs.List className="kg-insights-tabs-list" aria-label="Knowledge graph sections">
              <Tabs.Trigger className="kg-insights-tab-trigger" value="overview">
                <span>Overview</span>
                <span className="kg-insights-tab-count">{overviewEntityCount}</span>
              </Tabs.Trigger>
              <Tabs.Trigger className="kg-insights-tab-trigger" value="explore">
                <span>Explore</span>
                <span className="kg-insights-tab-count">{graphData.nodes.length}</span>
              </Tabs.Trigger>
              <Tabs.Trigger className="kg-insights-tab-trigger" value="pack">
                <span>Pack</span>
                <span className="kg-insights-tab-count">{graphPackSnapshot.sources.length}</span>
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content className="kg-insights-tab-content" value="overview">
              <Tabs.Root
                className="context-snapshot-tabs"
                value={overviewTab}
                onValueChange={(next) => {
                  if (next === 'summary' || next === 'composition') setOverviewTab(next)
                }}
              >
                <Tabs.List className="context-snapshot-tabs-list" aria-label="Knowledge graph overview views">
                  <Tabs.Trigger className="context-snapshot-tab-trigger" value="summary">Overview</Tabs.Trigger>
                  <Tabs.Trigger className="context-snapshot-tab-trigger" value="composition">Composition + Sources</Tabs.Trigger>
                </Tabs.List>

                <Tabs.Content value="summary" className="context-snapshot-tab-content">
                  <div className="graph-context-snapshot kg-snapshot-surface">
                    <div className="row wrap graph-context-snapshot-head">
                      <div>
                        <div className="meta">Project graph overview</div>
                        <div className="graph-context-snapshot-title">
                          Entity counts, connected structure, and dominant relationship signals for this project.
                        </div>
                      </div>
                      <div className="graph-context-snapshot-total">{overviewEntityCount.toLocaleString()} entities</div>
                    </div>
                    <div className="graph-context-metrics context-snapshot-metrics">
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Tasks</span>
                        <strong>{counts.tasks.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Notes</span>
                        <strong>{counts.notes.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Specifications</span>
                        <strong>{counts.specifications.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Rules</span>
                        <strong>{counts.project_rules.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Comments</span>
                        <strong>{counts.comments.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Focus neighbors</span>
                        <strong>{focusNeighbors.length.toLocaleString()}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="context-snapshot-band-card">
                    <div className="meta">Top tags</div>
                    {(overview?.top_tags ?? []).length === 0 ? (
                      <div className="meta">No tags yet.</div>
                    ) : (
                      <div className="context-snapshot-segment-grid">
                        {(overview?.top_tags ?? []).map((item, idx) => (
                          <div key={`kg-tag-${item.tag}`} className="context-snapshot-segment-chip">
                            <span
                              className="context-snapshot-segment-swatch"
                              style={{ backgroundColor: `hsl(${(idx * 37) % 360}deg 65% 48%)` }}
                            />
                            <span className="context-snapshot-segment-label">{item.tag || '(empty)'}</span>
                            <span className="meta">{item.usage.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="context-snapshot-band-card">
                    <div className="meta">Top relationships</div>
                    {(overview?.top_relationships ?? []).length === 0 ? (
                      <div className="meta">No relationships yet.</div>
                    ) : (
                      <div className="context-snapshot-segment-grid">
                        {(overview?.top_relationships ?? []).map((item, idx) => (
                          <div key={`kg-rel-${item.relationship}`} className="context-snapshot-segment-chip">
                            <span
                              className="context-snapshot-segment-swatch"
                              style={{ backgroundColor: `hsl(${(idx * 29 + 13) % 360}deg 62% 44%)` }}
                            />
                            <span className="context-snapshot-segment-label">{item.relationship || 'RELATED'}</span>
                            <span className="meta">{item.count.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <Accordion.Root className="context-snapshot-source-groups" type="multiple" defaultValue={['kg-focus-neighbors']}>
                    <Accordion.Item value="kg-focus-neighbors" className="context-snapshot-source-group">
                      <Accordion.Header>
                        <Accordion.Trigger className="context-snapshot-source-group-trigger">
                          <span className="context-snapshot-source-group-head">
                            <span className="context-snapshot-source-group-title">Focus neighbors</span>
                            <span className="meta">{focusNeighbors.length} connected entities</span>
                          </span>
                          <span className="context-snapshot-source-group-chevron" aria-hidden="true">
                            <Icon path="M6 9l6 6 6-6" />
                          </span>
                        </Accordion.Trigger>
                      </Accordion.Header>
                      <Accordion.Content className="context-snapshot-source-group-content">
                        {focusNeighbors.length === 0 ? (
                          <div className="meta">No focus neighbors for current selection.</div>
                        ) : (
                          <div className="context-snapshot-source-list">
                            {focusNeighbors.slice(0, 12).map((item) => (
                              <div key={`kg-focus-${item.entity_type}-${item.entity_id}`} className="context-snapshot-source-row">
                                <span className="graph-context-legend-swatch" style={{ backgroundColor: '#2563eb' }} />
                                <span className="context-snapshot-source-row-main">
                                  <span className="graph-context-legend-label">
                                    {item.entity_type}: {item.title || item.entity_id}
                                  </span>
                                  <span className="meta">{(item.path_types ?? []).join(' -> ') || 'RELATED'}</span>
                                </span>
                                <span className="meta context-snapshot-source-row-pct">
                                  {(item.path_types ?? []).length || 1} hops
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </Accordion.Content>
                    </Accordion.Item>

                    <Accordion.Item value="kg-dependency-paths" className="context-snapshot-source-group">
                      <Accordion.Header>
                        <Accordion.Trigger className="context-snapshot-source-group-trigger">
                          <span className="context-snapshot-source-group-head">
                            <span className="context-snapshot-source-group-title">Dependency paths</span>
                            <span className="meta">{dependencyPaths.length} discovered routes</span>
                          </span>
                          <span className="context-snapshot-source-group-chevron" aria-hidden="true">
                            <Icon path="M6 9l6 6 6-6" />
                          </span>
                        </Accordion.Trigger>
                      </Accordion.Header>
                      <Accordion.Content className="context-snapshot-source-group-content">
                        {dependencyPaths.length === 0 ? (
                          <div className="meta">No dependency paths available.</div>
                        ) : (
                          <div className="context-snapshot-source-list">
                            {dependencyPaths.slice(0, 12).map((item) => (
                              <div key={`kg-path-${item.to_entity_type}-${item.to_entity_id}`} className="context-snapshot-source-row">
                                <span className="graph-context-legend-swatch" style={{ backgroundColor: '#14b8a6' }} />
                                <span className="context-snapshot-source-row-main">
                                  <span className="graph-context-legend-label">
                                    {item.to_entity_type}: {item.to_entity_id}
                                  </span>
                                  <span className="meta">{(item.path ?? []).join(' -> ') || 'RELATED'}</span>
                                </span>
                                <span className="meta context-snapshot-source-row-pct">
                                  {item.hops || (item.path ?? []).length || 1} hops
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </Accordion.Content>
                    </Accordion.Item>
                  </Accordion.Root>
                </Tabs.Content>

                <Tabs.Content value="composition" className="context-snapshot-tab-content kg-overview-composition">
                  <div className="context-snapshot-band-card">
                    <div className="meta">Entity composition band</div>
                    {overviewSources.length === 0 ? (
                      <div className="meta" style={{ marginTop: 8 }}>No project entities are indexed yet.</div>
                    ) : (
                      <div className="context-snapshot-band" role="img" aria-label="Entity composition by type">
                        {overviewSources.map((source) => {
                          const isSelected = selectedOverviewSourceKey === source.key
                          return (
                            <button
                              key={`overview-band-${source.key}`}
                              type="button"
                              className={`context-snapshot-band-segment ${isSelected ? 'active' : ''}`.trim()}
                              style={{ flexGrow: Math.max(source.percent, 0.5), backgroundColor: source.color }}
                              aria-label={`${source.label}: ${formatPercent(source.percent)}`}
                              onClick={() => setSelectedOverviewSourceKey((current) => (current === source.key ? null : source.key))}
                            />
                          )
                        })}
                      </div>
                    )}
                    <div className="meta">Click a segment to focus matching cells and source rows below.</div>
                  </div>

                  <div className="graph-context-cube-block context-snapshot-cube-block">
                    <div className="meta">Entity occupancy map</div>
                    {overviewTiles.length === 0 ? (
                      <div className="meta" style={{ marginTop: 6 }}>No entity composition data available.</div>
                    ) : (
                      <div className="graph-context-cube-grid graph-context-cube-grid-dense" role="img" aria-label="Knowledge graph entity composition map">
                        {overviewTiles.map((tile, idx) => {
                          const isSelected = selectedOverviewSourceKey ? tile.sourceKey === selectedOverviewSourceKey : false
                          return (
                            <span
                              key={`overview-cube-${idx}-${tile.key}`}
                              className={`graph-context-cube context-snapshot-cube ${isSelected ? 'selected' : ''}`.trim()}
                              style={{ backgroundColor: tile.color }}
                              title={tile.label}
                            />
                          )
                        })}
                      </div>
                    )}
                    <div className="meta">
                      Resolution: {overviewTiles.length.toLocaleString()} cells · Total entities: {overviewEntityCount.toLocaleString()}
                    </div>
                  </div>

                  <div className="meta">Source breakdown</div>
                  {overviewSources.length === 0 ? (
                    <div className="meta">No source rows to display.</div>
                  ) : (
                    <div className="context-snapshot-source-list">
                      {overviewSources.map((source) => (
                        <button
                          key={`overview-source-${source.key}`}
                          type="button"
                          className={`context-snapshot-source-row ${selectedOverviewSourceKey === source.key ? 'active' : ''}`.trim()}
                          onClick={() => setSelectedOverviewSourceKey((current) => (current === source.key ? null : source.key))}
                        >
                          <span className="graph-context-legend-swatch" style={{ backgroundColor: source.color }} />
                          <span className="context-snapshot-source-row-main">
                            <span className="graph-context-legend-label">{source.label}</span>
                            <span className="meta">{source.count.toLocaleString()} entities</span>
                            <span className="context-snapshot-source-row-track">
                              <span
                                className="context-snapshot-source-row-fill"
                                style={{ width: `${Math.max(0, Math.min(100, source.percent))}%`, backgroundColor: source.color }}
                              />
                            </span>
                          </span>
                          <span className="meta context-snapshot-source-row-pct">{formatPercent(source.percent)}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </Tabs.Content>
              </Tabs.Root>
            </Tabs.Content>

            <Tabs.Content className="kg-insights-tab-content" value="explore">
              <div className="kg-explore-layout">
                <div className="kg-explore-main">
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
                                  <span className="graph-evidence-score graph-evidence-score-pill">Final {item.final_score.toFixed(3)}</span>
                                </div>
                                <div className="graph-evidence-entity">{item.entity_id}</div>
                                <div className="graph-evidence-snippet">{item.snippet}</div>
                                <div className="graph-evidence-score-grid">
                                  <div className="graph-evidence-score-row">
                                    <span className="meta">Final</span>
                                    <span className="graph-evidence-score-value">{item.final_score.toFixed(3)}</span>
                                    <span className="graph-evidence-score-track">
                                      <span
                                        className="graph-evidence-score-fill graph-evidence-score-fill-final"
                                        style={{ width: `${normalizeScorePercent(item.final_score)}%` }}
                                      />
                                    </span>
                                  </div>
                                  <div className="graph-evidence-score-row">
                                    <span className="meta">Graph</span>
                                    <span className="graph-evidence-score-value">{item.graph_score.toFixed(3)}</span>
                                    <span className="graph-evidence-score-track">
                                      <span
                                        className="graph-evidence-score-fill graph-evidence-score-fill-graph"
                                        style={{ width: `${normalizeScorePercent(item.graph_score)}%` }}
                                      />
                                    </span>
                                  </div>
                                  <div className="graph-evidence-score-row">
                                    <span className="meta">Vector</span>
                                    <span className="graph-evidence-score-value">
                                      {item.vector_similarity === null ? 'n/a' : item.vector_similarity.toFixed(3)}
                                    </span>
                                    <span className="graph-evidence-score-track">
                                      <span
                                        className="graph-evidence-score-fill graph-evidence-score-fill-vector"
                                        style={{ width: `${normalizeScorePercent(item.vector_similarity)}%` }}
                                      />
                                    </span>
                                  </div>
                                  {typeof item.template_alignment === 'number' ? (
                                    <div className="graph-evidence-score-row">
                                      <span className="meta">Template</span>
                                      <span className="graph-evidence-score-value">{item.template_alignment.toFixed(3)}</span>
                                      <span className="graph-evidence-score-track">
                                        <span
                                          className="graph-evidence-score-fill graph-evidence-score-fill-template"
                                          style={{ width: `${normalizeScorePercent(item.template_alignment)}%` }}
                                        />
                                      </span>
                                    </div>
                                  ) : null}
                                </div>
                                <div className="graph-evidence-meta">
                                  <span className="meta">Mode {knowledgeSearchMode}</span>
                                  <span className="meta">Updated {formatEvidenceUpdated(item.updated_at)}</span>
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
                                  <div className="graph-viz-selected-head">
                                    <span className="meta">Selected</span>
                                    <span className="status-chip">{selectedNode.entity_type}</span>
                                  </div>
                                  <div className="graph-viz-selected-title">{selectedNode.name}</div>
                                  <div className="graph-viz-selected-id" title={selectedNode.id}>
                                    {selectedNode.id}
                                  </div>
                                  <div className="graph-viz-selected-stats">
                                    <span className="graph-viz-selected-stat">
                                      <span className="meta">Degree</span>
                                      <strong>{selectedNode.degree}</strong>
                                    </span>
                                    <span className="graph-viz-selected-stat">
                                      <span className="meta">Connected edges</span>
                                      <strong>{connectedSelectedEdges.length}</strong>
                                    </span>
                                  </div>
                                </div>
                              ) : null}
                            </aside>
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  <div className="graph-viz-block graph-reactflow-block">
                    <div className="row wrap graph-viz-head">
                      <div className="meta">
                        Event Storming diagram ({eventStormingFlowNodes.length} nodes, {eventStormingFlowEdges.length} edges)
                      </div>
                    </div>
                    {eventStormingOverviewQuery.isError || eventStormingSubgraphQuery.isError ? (
                      <div className="notice notice-error">
                        Event storming projection is unavailable.
                        <div className="meta" style={{ color: 'inherit', marginTop: 4 }}>
                          {toErrorMessage(eventStormingOverviewQuery.error || eventStormingSubgraphQuery.error)}
                        </div>
                      </div>
                    ) : eventStormingOverviewQuery.isLoading || eventStormingSubgraphQuery.isLoading ? (
                      <div className="meta">Loading Event Storming diagram...</div>
                    ) : (
                      <>
                        <div className="event-storming-controls">
                          <div className="event-storming-controls-head">
                            <div className="event-storming-controls-title">Event Storming processing</div>
                            <label className="event-storming-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(eventStormingOverview?.event_storming_enabled ?? true)}
                                disabled={Boolean(toggleEventStormingProjectMutation.isPending)}
                                onChange={(e) => {
                                  void toggleEventStormingProjectMutation.mutateAsync(Boolean(e.target.checked))
                                }}
                              />
                              <span>Enable processing</span>
                            </label>
                          </div>
                          <div className="event-storming-controls-grid">
                            <div className="event-storming-controls-card">
                              <div className="event-storming-controls-card-title">Processing</div>
                              <div className="event-storming-progress-line">
                                <span>Artifacts</span>
                                <strong>
                                  {eventStormingProcessing.processed}/{eventStormingProcessing.artifact_total} ({eventStormingProgressPct.toFixed(1)}%)
                                </strong>
                              </div>
                              <div className="event-storming-progress-track" role="presentation" aria-hidden="true">
                                <span className="event-storming-progress-fill" style={{ width: `${eventStormingProgressPct}%` }} />
                              </div>
                              <div className="event-storming-mini-stats">
                                <span className="badge">Artifact links: {eventStormingOverview?.artifact_link_count ?? 0}</span>
                                {eventStormingFrameMode && (
                                  <span className="badge">
                                    Frame: {eventStormingFrameMode}{eventStormingFrameRevisionShort ? ` · ${eventStormingFrameRevisionShort}` : ''}
                                  </span>
                                )}
                                {eventStormingFrameUpdatedAtLabel && (
                                  <span className="badge">Frame updated: {eventStormingFrameUpdatedAtLabel}</span>
                                )}
                                <span className="badge">Queued: {eventStormingProcessing.queued}</span>
                                <span className="badge">Running: {eventStormingProcessing.running}</span>
                                <span className="badge">Failed: {eventStormingProcessing.failed}</span>
                              </div>
                            </div>
                            <div className="event-storming-controls-card">
                              <div className="event-storming-controls-card-title">Detected Components</div>
                              <div className="event-storming-component-grid">
                                {eventStormingComponentStats.map((item) => (
                                  <div
                                    key={`es-count-${item.key}`}
                                    className={`event-storming-component-chip ${item.count === 0 ? 'zero' : ''}`}
                                    style={{ borderColor: item.color }}
                                  >
                                    <span>{item.label}</span>
                                    <strong>{item.count}</strong>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        </div>
                        {eventStormingFlowNodes.length === 0 ? (
                          <div className="meta">No Event Storming components detected yet.</div>
                        ) : (
                          <div className="graph-reactflow-shell" ref={eventStormingShellRef}>
                            {!isEventStormingFullscreen ? (
                              <button
                                className="action-icon graph-viz-enter-button"
                                type="button"
                                title="Open full screen graph"
                                aria-label="Open full screen graph"
                                onClick={() => void toggleEventStormingFullscreen()}
                              >
                                <Icon path="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6" />
                              </button>
                            ) : null}
                            {isEventStormingFullscreen ? (
                              <button
                                className="action-icon graph-viz-exit-button"
                                type="button"
                                title="Exit full screen"
                                aria-label="Exit full screen"
                                onClick={() => void exitEventStormingFullscreen()}
                              >
                                <Icon path="M9 9H3V3h6v2H5v4h4v2zm12 0h-6V7h4V3h2v6zM9 21H3v-6h2v4h4v2zm12 0h-6v-2h4v-4h2v6z" />
                              </button>
                            ) : null}
                            <div className="graph-viz-composite graph-viz-composite-event-storming">
                              <div className="graph-viz-main-event-storming">
                                <div className="event-storming-lane-legend">
                                  {eventStormingLaneLegend.map((item) => (
                                    <span
                                      key={`es-legend-${item.key}`}
                                      className="event-storming-lane-chip"
                                      style={{ borderColor: item.border, backgroundColor: item.sticky, color: item.text }}
                                    >
                                      {item.label}
                                    </span>
                                  ))}
                                </div>
                                <div className="event-storming-review-legend">
                                  {eventStormingReviewLegend.map((item) => (
                                    <span key={`es-review-legend-${item.key}`} className="event-storming-review-chip">
                                      <span className="event-storming-review-dot" style={{ backgroundColor: item.color }} />
                                      {item.label}
                                    </span>
                                  ))}
                                </div>
                                <div className="event-storming-lane-header-shell" role="presentation" aria-hidden="true">
                                  <div
                                    className="event-storming-lane-header-grid"
                                    style={eventStormingHeaderStyle}
                                  >
                                    {eventStormingLaneHeaders.map((item) => (
                                      <span key={`es-lane-header-${item.key}`} className="event-storming-lane-header-item">
                                        {item.label}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                                <div className="graph-reactflow-canvas event-storming-canvas">
                                  <ReactFlow
                                    nodes={eventStormingFlowNodes}
                                    edges={eventStormingFlowEdges}
                                    fitView
                                    fitViewOptions={{ padding: 0.12, maxZoom: 1.0 }}
                                    nodesDraggable={false}
                                    nodesConnectable={false}
                                    elementsSelectable
                                    onNodeClick={(_, node) => {
                                      const nodeId = String(node.id || '').trim()
                                      if (!nodeId) return
                                      setSelectedEventStormingNodeId(nodeId)
                                    }}
                                    minZoom={0.2}
                                    maxZoom={1.4}
                                    proOptions={{ hideAttribution: true }}
                                    onInit={(instance) => {
                                      eventStormingFlowRef.current = instance
                                      fitEventStormingViewport(280)
                                      window.setTimeout(() => syncEventStormingViewportTransform(), 0)
                                    }}
                                    onMove={() => syncEventStormingViewportTransform()}
                                  >
                                    <MiniMap
                                      pannable
                                      zoomable
                                      nodeStrokeWidth={2}
                                      nodeColor={(node) => eventStormingNodeColor(String((node.data as ReactFlowNodeData | undefined)?.entityType || 'Entity'))}
                                    />
                                    <Controls showInteractive={false} />
                                    <Background gap={18} size={1} color="rgba(148,163,184,0.30)" />
                                  </ReactFlow>
                                </div>
                              </div>
                            <aside className="graph-viz-side graph-viz-side-event-storming">
                              <div className="meta">Selected Event Storming Node</div>
                              <label className="event-storming-toggle">
                                <input
                                  type="checkbox"
                                  checked={showEventStormingArtifactsOnDiagram}
                                  onChange={(e) => setShowEventStormingArtifactsOnDiagram(Boolean(e.target.checked))}
                                />
                                <span>Show artifacts on diagram</span>
                              </label>
                              <label className="event-storming-toggle">
                                <input
                                  type="checkbox"
                                  checked={showRejectedEventStormingLinks}
                                  onChange={(e) => setShowRejectedEventStormingLinks(Boolean(e.target.checked))}
                                />
                                <span>Show rejected links</span>
                              </label>
                              {selectedEventStormingNode ? (
                                <div className="graph-viz-selected" style={{ marginBottom: 10 }}>
                                  <div className="graph-viz-selected-head">
                                    <span className="meta">Type</span>
                                    <span className="status-chip">{selectedEventStormingNode.entity_type}</span>
                                  </div>
                                  <div className="graph-viz-selected-title">{selectedEventStormingNode.title || selectedEventStormingNode.entity_id}</div>
                                  <div className="graph-viz-selected-id" title={selectedEventStormingNode.entity_id}>
                                    {selectedEventStormingNode.entity_id}
                                  </div>
                                </div>
                              ) : (
                                <div className="meta">Select a node to inspect inferred links.</div>
                              )}
                              {eventStormingLinksError ? (
                                <div className="notice notice-error" style={{ marginBottom: 8 }}>
                                  {toErrorMessage(eventStormingLinksError)}
                                </div>
                              ) : null}
                              {eventStormingLinksLoading ? <div className="meta">Loading inferred links...</div> : null}
                              {selectedEventStormingNode && selectedEventStormingIsComponent && !eventStormingLinksLoading ? (
                                <>
                                  <div className="meta" style={{ marginBottom: 6 }}>
                                    Linked artifacts ({visibleEventStormingComponentLinkItems.length})
                                  </div>
                                  <div className="graph-evidence-list">
                                    {visibleEventStormingComponentLinkItems.map((item) => (
                                      <div key={`es-component-link-${item.entity_id}-${selectedEventStormingNode.entity_id}`} className="graph-evidence-item">
                                        <div className="graph-evidence-head">
                                          <div className="graph-evidence-badges">
                                            <span className="status-chip">{item.entity_type}</span>
                                            <span className="graph-evidence-id">{item.entity_id}</span>
                                          </div>
                                          <span className="graph-evidence-score graph-evidence-score-pill">{item.confidence.toFixed(2)}</span>
                                        </div>
                                        <div className="graph-evidence-snippet">{item.entity_title || item.entity_id}</div>
                                        <div className="es-link-review">
                                          <div className="es-link-review-buttons" role="group" aria-label="Set review status">
                                            {(['candidate', 'approved', 'rejected'] as const).map((status) => (
                                              <button
                                                key={`es-link-status-${item.entity_id}-${status}`}
                                                type="button"
                                                className={`es-link-review-btn ${item.review_status === status ? 'active' : ''}`.trim()}
                                                aria-pressed={item.review_status === status}
                                                disabled={Boolean(reviewEventStormingLinkMutation.isPending)}
                                                onClick={() =>
                                                  void setEventStormingLinkReview({
                                                    entity_type: String(item.entity_type || '').toLowerCase(),
                                                    entity_id: String(item.entity_id || ''),
                                                    component_id: String(selectedEventStormingNode.entity_id || ''),
                                                    review_status: status,
                                                  })
                                                }
                                              >
                                                {status}
                                              </button>
                                            ))}
                                          </div>
                                          <div className="es-link-review-meta">
                                            <span className="status-chip">Status: {item.review_status}</span>
                                            <span className="status-chip">Inference: {item.inference_method}</span>
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                    {visibleEventStormingComponentLinkItems.length === 0 ? (
                                      <div className="meta">No artifact links detected for this component.</div>
                                    ) : null}
                                  </div>
                                </>
                              ) : null}
                              {selectedEventStormingNode && selectedEventStormingIsArtifact && !eventStormingLinksLoading ? (
                                <>
                                  <div className="meta" style={{ marginBottom: 6 }}>
                                    Linked components ({visibleEventStormingEntityLinkItems.length})
                                  </div>
                                  <div className="graph-evidence-list">
                                    {visibleEventStormingEntityLinkItems.map((item) => (
                                      <div key={`es-entity-link-${selectedEventStormingNode.entity_id}-${item.component_id}`} className="graph-evidence-item">
                                        <div className="graph-evidence-head">
                                          <div className="graph-evidence-badges">
                                            <span className="status-chip">{item.component_type}</span>
                                            <span className="graph-evidence-id">{item.component_id}</span>
                                          </div>
                                          <span className="graph-evidence-score graph-evidence-score-pill">{item.confidence.toFixed(2)}</span>
                                        </div>
                                        <div className="graph-evidence-snippet">{item.component_title || item.component_id}</div>
                                        <div className="es-link-review">
                                          <div className="es-link-review-buttons" role="group" aria-label="Set review status">
                                            {(['candidate', 'approved', 'rejected'] as const).map((status) => (
                                              <button
                                                key={`es-link-status-${item.component_id}-${status}`}
                                                type="button"
                                                className={`es-link-review-btn ${item.review_status === status ? 'active' : ''}`.trim()}
                                                aria-pressed={item.review_status === status}
                                                disabled={Boolean(reviewEventStormingLinkMutation.isPending)}
                                                onClick={() =>
                                                  void setEventStormingLinkReview({
                                                    entity_type: String(selectedEventStormingNode.entity_type || '').toLowerCase(),
                                                    entity_id: String(selectedEventStormingNode.entity_id || ''),
                                                    component_id: String(item.component_id || ''),
                                                    review_status: status,
                                                  })
                                                }
                                              >
                                                {status}
                                              </button>
                                            ))}
                                          </div>
                                          <div className="es-link-review-meta">
                                            <span className="status-chip">Status: {item.review_status}</span>
                                            <span className="status-chip">Inference: {item.inference_method}</span>
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                    {visibleEventStormingEntityLinkItems.length === 0 ? (
                                      <div className="meta">No component links detected for this artifact.</div>
                                    ) : null}
                                  </div>
                                </>
                              ) : null}
                              {selectedEventStormingNode &&
                              !selectedEventStormingIsComponent &&
                              !selectedEventStormingIsArtifact &&
                              !eventStormingLinksLoading ? (
                                <div className="meta">No reviewable links for this node type.</div>
                              ) : null}
                            </aside>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>

                <div className="kg-explore-side">
                  <Accordion.Root
                    type="multiple"
                    className="kg-explore-accordion"
                    defaultValue={['kg-explore-evidence', 'kg-explore-summary']}
                  >
                    <Accordion.Item value="kg-explore-evidence" className="taskdrawer-section-item kg-explore-section">
                      <Accordion.Header className="taskdrawer-section-header">
                        <Accordion.Trigger className="taskdrawer-section-trigger">
                          <span className="taskdrawer-section-icon" aria-hidden="true">
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                          </span>
                          <span className="taskdrawer-section-head">
                            <span className="taskdrawer-section-title">Evidence</span>
                            <span className="taskdrawer-section-meta">{`${evidenceItems.length} scored entries`}</span>
                          </span>
                          <span className="taskdrawer-section-badge">{evidenceItems.length}</span>
                          <span className="taskdrawer-section-chevron" aria-hidden="true">
                            <Icon path="M6 9l6 6 6-6" />
                          </span>
                        </Accordion.Trigger>
                      </Accordion.Header>
                      <Accordion.Content className="taskdrawer-section-content">
                        <div className="kg-explore-content-stack">
                          <div className="meta">
                            Click an evidence item to focus and highlight its node in the visual graph.
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
                                      <span className="graph-evidence-score graph-evidence-score-pill">Final {item.final_score.toFixed(3)}</span>
                                    </div>
                                    <div className="graph-evidence-entity">{item.entity_id}</div>
                                    <div className="graph-evidence-snippet">{item.snippet}</div>
                                    <div className="graph-evidence-score-grid">
                                      <div className="graph-evidence-score-row">
                                        <span className="meta">Final</span>
                                        <span className="graph-evidence-score-value">{item.final_score.toFixed(3)}</span>
                                        <span className="graph-evidence-score-track">
                                          <span
                                            className="graph-evidence-score-fill graph-evidence-score-fill-final"
                                            style={{ width: `${normalizeScorePercent(item.final_score)}%` }}
                                          />
                                        </span>
                                      </div>
                                      <div className="graph-evidence-score-row">
                                        <span className="meta">Graph</span>
                                        <span className="graph-evidence-score-value">{item.graph_score.toFixed(3)}</span>
                                        <span className="graph-evidence-score-track">
                                          <span
                                            className="graph-evidence-score-fill graph-evidence-score-fill-graph"
                                            style={{ width: `${normalizeScorePercent(item.graph_score)}%` }}
                                          />
                                        </span>
                                      </div>
                                      <div className="graph-evidence-score-row">
                                        <span className="meta">Vector</span>
                                        <span className="graph-evidence-score-value">
                                          {item.vector_similarity === null ? 'n/a' : item.vector_similarity.toFixed(3)}
                                        </span>
                                        <span className="graph-evidence-score-track">
                                          <span
                                            className="graph-evidence-score-fill graph-evidence-score-fill-vector"
                                            style={{ width: `${normalizeScorePercent(item.vector_similarity)}%` }}
                                          />
                                        </span>
                                      </div>
                                      {typeof item.template_alignment === 'number' ? (
                                        <div className="graph-evidence-score-row">
                                          <span className="meta">Template</span>
                                          <span className="graph-evidence-score-value">{item.template_alignment.toFixed(3)}</span>
                                          <span className="graph-evidence-score-track">
                                            <span
                                              className="graph-evidence-score-fill graph-evidence-score-fill-template"
                                              style={{ width: `${normalizeScorePercent(item.template_alignment)}%` }}
                                            />
                                          </span>
                                        </div>
                                      ) : null}
                                    </div>
                                    <div className="graph-evidence-meta">
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
                      </Accordion.Content>
                    </Accordion.Item>

                    <Accordion.Item value="kg-explore-summary" className="taskdrawer-section-item kg-explore-section">
                      <Accordion.Header className="taskdrawer-section-header">
                        <Accordion.Trigger className="taskdrawer-section-trigger">
                          <span className="taskdrawer-section-icon" aria-hidden="true">
                            <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
                          </span>
                          <span className="taskdrawer-section-head">
                            <span className="taskdrawer-section-title">Summary with citations</span>
                            <span className="taskdrawer-section-meta">
                              {`${(summary?.key_points ?? []).length} key points · ${(summary?.gaps ?? []).length} gaps`}
                            </span>
                          </span>
                          <span className="taskdrawer-section-badge">{(summary?.key_points ?? []).length}</span>
                          <span className="taskdrawer-section-chevron" aria-hidden="true">
                            <Icon path="M6 9l6 6 6-6" />
                          </span>
                        </Accordion.Trigger>
                      </Accordion.Header>
                      <Accordion.Content className="taskdrawer-section-content">
                        <div className="kg-explore-content-stack">
                          <div className="row wrap" style={{ gap: 8 }}>
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
                                          <span className="graph-summary-point-count">
                                            {(point.evidence_ids ?? []).length} evidence
                                          </span>
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
                      </Accordion.Content>
                    </Accordion.Item>
                  </Accordion.Root>
                </div>
              </div>
            </Tabs.Content>

            <Tabs.Content className="kg-insights-tab-content" value="pack">
              <Tabs.Root
                className="context-snapshot-tabs"
                value={packTab}
                onValueChange={(next) => {
                  if (next === 'composition' || next === 'markdown') setPackTab(next)
                }}
              >
                <Tabs.List className="context-snapshot-tabs-list" aria-label="Knowledge graph pack views">
                  <Tabs.Trigger className="context-snapshot-tab-trigger" value="composition">Composition + Sources</Tabs.Trigger>
                  <Tabs.Trigger className="context-snapshot-tab-trigger" value="markdown">Pack markdown</Tabs.Trigger>
                </Tabs.List>

                <Tabs.Content value="composition" className="context-snapshot-tab-content kg-pack-composition">
                  <div className="graph-context-snapshot kg-snapshot-surface">
                    <div className="row wrap graph-context-snapshot-head">
                      <div>
                        <div className="meta">Knowledge graph pack</div>
                        <div className="graph-context-snapshot-title">
                          Token budget distribution across context markdown, evidence payload, summary, and metadata.
                        </div>
                      </div>
                      <div className="graph-context-snapshot-total">~{graphPackSnapshot.approxTokens.toLocaleString()} tokens</div>
                    </div>
                    <div className="context-snapshot-policy-row">
                      <span className="status-chip">{`Chat indexing: ${chatIndexModeLabel(normalizedChatIndexMode)}`}</span>
                      <span className="status-chip">{`Attachment ingestion: ${chatAttachmentModeLabel(normalizedChatAttachmentMode)}`}</span>
                    </div>
                    <div className="graph-context-metrics context-snapshot-metrics">
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Sources</span>
                        <strong>{graphPackSnapshot.sources.length.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Characters</span>
                        <strong>{graphPackSnapshot.totalChars.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Lines</span>
                        <strong>{graphPackSnapshot.totalLines.toLocaleString()}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Chat-derived evidence</span>
                        <strong>{`${graphPackSnapshot.chatEvidenceCount} (${graphPackSnapshot.chatEvidenceSharePct.toFixed(1)}%)`}</strong>
                      </div>
                      <div className="graph-context-metric context-snapshot-metric">
                        <span className="meta">Distinct chat entities</span>
                        <strong>{graphPackSnapshot.chatEvidenceEntityCount.toLocaleString()}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="context-snapshot-band-card">
                    <div className="meta">Context source occupancy band</div>
                    {graphPackSnapshot.sources.length === 0 ? (
                      <div className="meta" style={{ marginTop: 8 }}>No knowledge graph context has been produced yet.</div>
                    ) : (
                      <div className="context-snapshot-band" role="img" aria-label="Knowledge graph source occupancy by section">
                        {graphPackSnapshot.sources.map((source) => {
                          const isSelected = selectedPackSourceKey === source.key
                          return (
                            <button
                              key={`pack-band-${source.key}`}
                              type="button"
                              className={`context-snapshot-band-segment ${isSelected ? 'active' : ''}`.trim()}
                              style={{ flexGrow: Math.max(source.percent, 0.5), backgroundColor: source.color }}
                              aria-label={`${source.label}: ${formatPercent(source.percent)}`}
                              onClick={() => setSelectedPackSourceKey((current) => (current === source.key ? null : source.key))}
                            />
                          )
                        })}
                      </div>
                    )}
                    <div className="meta">
                      Resolution: {graphPackSnapshot.tileCount.toLocaleString()} cells · ~{Math.max(1, Math.round(graphPackSnapshot.charsPerTile || 0)).toLocaleString()} chars per cell
                    </div>
                  </div>

                  <div className="graph-context-cube-block context-snapshot-cube-block">
                    <div className="meta">Knowledge graph pack composition</div>
                    {graphPackSnapshot.tiles.length === 0 ? (
                      <div className="meta" style={{ marginTop: 6 }}>No knowledge graph context has been produced yet.</div>
                    ) : (
                      <div className="graph-context-cube-grid graph-context-cube-grid-dense graph-context-cube-grid-entities" role="img" aria-label="Knowledge graph context composition map">
                        {graphPackSnapshot.tiles.map((tile, idx) => {
                          const isSelected = selectedPackSourceKey ? tile.sourceKey === selectedPackSourceKey : false
                          return (
                            <span
                              key={`kg-pack-cube-${idx}-${tile.key}`}
                              className={`graph-context-cube context-snapshot-cube ${isSelected ? 'selected' : ''}`.trim()}
                              style={{ backgroundColor: tile.color }}
                              title={tile.label}
                            />
                          )
                        })}
                      </div>
                    )}
                    <div className="meta">
                      ~{graphPackSnapshot.approxTokens.toLocaleString()} tokens · {graphPackSnapshot.totalChars.toLocaleString()} chars · {graphPackSnapshot.totalLines.toLocaleString()} lines
                    </div>
                  </div>

                  <div className="meta">Source breakdown</div>
                  <Accordion.Root
                    className="context-snapshot-source-groups"
                    type="multiple"
                    defaultValue={packSourceGroups.map((group) => group.group)}
                  >
                    {packSourceGroups.map((group) => (
                      <Accordion.Item key={`pack-source-group-${group.group}`} value={group.group} className="context-snapshot-source-group">
                        <Accordion.Header>
                          <Accordion.Trigger className="context-snapshot-source-group-trigger">
                            <span className="context-snapshot-source-group-head">
                              <span className="context-snapshot-source-group-title">{group.group}</span>
                              <span className="meta">
                                {formatPercent(group.percent)} · {group.chars.toLocaleString()} chars
                              </span>
                            </span>
                            <span className="context-snapshot-source-group-chevron" aria-hidden="true">
                              <Icon path="M6 9l6 6 6-6" />
                            </span>
                          </Accordion.Trigger>
                        </Accordion.Header>
                        <Accordion.Content className="context-snapshot-source-group-content">
                          <div className="context-snapshot-source-list">
                            {group.items.map((source) => (
                              <button
                                key={`kg-pack-source-${source.key}`}
                                type="button"
                                className={`context-snapshot-source-row ${selectedPackSourceKey === source.key ? 'active' : ''}`.trim()}
                                onClick={() => setSelectedPackSourceKey((current) => (current === source.key ? null : source.key))}
                              >
                                <span className="graph-context-legend-swatch" style={{ backgroundColor: source.color }} />
                                <span className="context-snapshot-source-row-main">
                                  <span className="graph-context-legend-label">{source.label}</span>
                                  <span className="meta">
                                    {source.chars.toLocaleString()} chars
                                    {source.lines > 0 ? ` · ${source.lines.toLocaleString()} lines` : ''}
                                  </span>
                                  <span className="context-snapshot-source-row-track">
                                    <span
                                      className="context-snapshot-source-row-fill"
                                      style={{ width: `${Math.max(0, Math.min(100, source.percent))}%`, backgroundColor: source.color }}
                                    />
                                  </span>
                                </span>
                                <span className="meta context-snapshot-source-row-pct">{formatPercent(source.percent)}</span>
                              </button>
                            ))}
                          </div>
                        </Accordion.Content>
                      </Accordion.Item>
                    ))}
                  </Accordion.Root>
                </Tabs.Content>

                <Tabs.Content value="markdown" className="context-snapshot-tab-content">
                  <div className="graph-markdown-block">
                    <div className="meta">Context pack preview</div>
                    <div className="graph-markdown-preview">
                      <MarkdownView value={contextPack?.markdown || ''} />
                    </div>
                  </div>
                </Tabs.Content>
              </Tabs.Root>
            </Tabs.Content>
          </Tabs.Root>
        </>
      )}
    </section>
  )
}
