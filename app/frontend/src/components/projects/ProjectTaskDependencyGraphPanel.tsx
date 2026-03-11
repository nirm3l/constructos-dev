import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { useQuery } from '@tanstack/react-query'
import {
  applyNodeChanges,
  Background,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeChange,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { getProjectTaskDependencyEventDetail } from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import type {
  ProjectTaskDependencyGraph,
  TaskDependencyGraphEdge,
  TaskDependencyGraphEventDetail,
  TaskDependencyGraphRuntimeEvent,
  TaskDependencyGraphNode,
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

type TaskFlowNodeData = {
  title: string
  role: string
  status: string
  automationState: string
  priority: string
  assignedAgentCode?: string | null
  phase?: string | null
  blockingGate?: string | null
  summary: string
}

type TaskFlowFilterMode = 'all' | 'runtime' | 'structural'

type GroupedRuntimeEvent = {
  key: string
  source: string
  reason: string | null
  triggerLink: string | null
  correlationId: string | null
  active: boolean
  firstAt: string | null
  latestAt: string | null
  records: TaskDependencyGraphRuntimeEvent[]
}

const TASK_FLOW_FIT_VIEW_OPTIONS = Object.freeze({ padding: 0.18, maxZoom: 1.1, duration: 240 })
const TASK_FLOW_PRO_OPTIONS = Object.freeze({ hideAttribution: true })
const TASK_FLOW_NODE_X_SPACING = 440
const TASK_FLOW_NODE_Y_SPACING = 252
const TASK_FLOW_LANE_GAP = 116

type StoredTaskFlowLayout = {
  positions: Array<{ task_id: string; x: number; y: number }>
  updated_at: string
}

function hashTaskFlowFingerprint(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function readStoredTaskFlowLayout(storageKey: string): Map<string, { x: number; y: number }> {
  if (typeof window === 'undefined') return new Map()
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw) as StoredTaskFlowLayout
    const rows = Array.isArray(parsed?.positions) ? parsed.positions : []
    const out = new Map<string, { x: number; y: number }>()
    for (const row of rows) {
      const taskId = String(row?.task_id || '').trim()
      const x = Number(row?.x)
      const y = Number(row?.y)
      if (!taskId || !Number.isFinite(x) || !Number.isFinite(y)) continue
      out.set(taskId, { x, y })
    }
    return out
  } catch {
    return new Map()
  }
}

function writeStoredTaskFlowLayout(storageKey: string, nodes: FlowNode<TaskFlowNodeData>[]): void {
  if (typeof window === 'undefined') return
  try {
    const previous = readStoredTaskFlowLayout(storageKey)
    for (const node of nodes) {
      previous.set(String(node.id || ''), {
        x: Number(node.position?.x || 0),
        y: Number(node.position?.y || 0),
      })
    }
    const payload: StoredTaskFlowLayout = {
      positions: Array.from(previous.entries()).map(([taskId, position]) => ({
        task_id: taskId,
        x: position.x,
        y: position.y,
      })),
      updated_at: new Date().toISOString(),
    }
    window.localStorage.setItem(storageKey, JSON.stringify(payload))
  } catch {
    // Ignore storage write failures and keep positions in memory.
  }
}

function flowNodesEqual(left: FlowNode<TaskFlowNodeData>[], right: FlowNode<TaskFlowNodeData>[]): boolean {
  if (left.length !== right.length) return false
  for (let index = 0; index < left.length; index += 1) {
    const a = left[index]
    const b = right[index]
    if (!a || !b) return false
    if (a.id !== b.id) return false
    if (a.position.x !== b.position.x || a.position.y !== b.position.y) return false
    if (a.selected !== b.selected) return false
  }
  return true
}

function mergeFlowNodes(
  current: FlowNode<TaskFlowNodeData>[],
  nextBase: FlowNode<TaskFlowNodeData>[]
): FlowNode<TaskFlowNodeData>[] {
  const currentById = new Map(current.map((node) => [String(node.id), node]))
  const merged = nextBase.map((node) => {
    const previous = currentById.get(String(node.id))
    if (!previous) return node
    return {
      ...node,
      position: previous.position,
      selected: previous.selected,
    }
  })
  return flowNodesEqual(current, merged) ? current : merged
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim()
  if (typeof error === 'string' && error.trim()) return error.trim()
  return 'Unable to load task flow graph.'
}

function normalizeRoleKey(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'task'
}

function normalizeStatusKey(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'open'
}

function normalizeAutomationKey(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'idle'
}

function roleLane(value: string): 'Developer' | 'Lead' | 'QA' | 'Other' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'developer') return 'Developer'
  if (normalized === 'lead') return 'Lead'
  if (normalized === 'qa') return 'QA'
  return 'Other'
}

function roleLaneOrder(value: string): number {
  const lane = roleLane(value)
  if (lane === 'Developer') return 0
  if (lane === 'Lead') return 1
  if (lane === 'QA') return 2
  return 3
}

function statusRank(value: string): number {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'blocked') return 0
  if (normalized === 'dev') return 1
  if (normalized === 'lead') return 2
  if (normalized === 'qa') return 3
  if (normalized === 'done') return 4
  return 5
}

function TaskFlowNodeCard(props: any) {
  const data = (props?.data || {}) as TaskFlowNodeData
  return (
    <div className="task-flow-node-card">
      <Handle id="l-in" type="target" position={Position.Left} className="task-flow-node-handle" />
      <Handle id="r-out" type="source" position={Position.Right} className="task-flow-node-handle" />
      <div className="task-flow-node-title" title={data.title}>{data.title}</div>
      <div className="task-flow-node-badges">
        <span className={`task-flow-role-pill role-${normalizeRoleKey(data.role)}`.trim()}>{data.role || 'Task'}</span>
        <span className={`task-flow-status-pill status-${normalizeStatusKey(data.status)}`.trim()}>{data.status || 'Open'}</span>
        <span className={`task-flow-automation-pill automation-${normalizeAutomationKey(data.automationState)}`.trim()}>
          {data.automationState || 'idle'}
        </span>
      </div>
      <div className="task-flow-node-summary">{data.summary}</div>
      <div className="task-flow-node-meta-row">
        {data.priority ? <span className="task-flow-meta-chip">Priority {data.priority}</span> : null}
        {data.assignedAgentCode ? <span className="task-flow-meta-chip">{data.assignedAgentCode}</span> : null}
        {data.phase ? <span className="task-flow-meta-chip">{data.phase}</span> : null}
      </div>
      {data.blockingGate ? <div className="task-flow-node-gate">{data.blockingGate}</div> : null}
    </div>
  )
}

function edgeChannelLabel(edge: TaskDependencyGraphEdge): string {
  const parts: string[] = []
  const relationshipKinds = Array.isArray(edge.relationship_kinds) ? edge.relationship_kinds : []
  if (relationshipKinds.length > 0) {
    parts.push(relationshipKinds.map((item) => String(item || '').replace(/_/g, ' ')).join(' + '))
  }
  if (edge.trigger_dependency) parts.push('status trigger')
  if (edge.runtime_dependency) {
    if (Number(edge.lead_handoffs_total || 0) > 0) parts.push(`handoff x${edge.lead_handoffs_total}`)
    const runtimeTotal = Number(edge.runtime_requests_total || 0)
    if (runtimeTotal > Number(edge.lead_handoffs_total || 0)) parts.push(`runtime x${runtimeTotal}`)
  }
  return parts.join(' · ') || 'task dependency'
}

function formatChannelLabel(value: string): string {
  return String(value || '')
    .replace(/[_:]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim() || 'channel'
}

function edgeColor(edge: TaskDependencyGraphEdge): string {
  if (edge.active_runtime) return '#059669'
  if (edge.runtime_dependency) return '#2563eb'
  if (edge.trigger_dependency) return '#d97706'
  return '#64748b'
}

function formatEventTimestamp(value: string | null | undefined): string {
  const raw = String(value || '').trim()
  if (!raw) return 'No timestamp'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return raw
  return parsed.toLocaleString()
}

function buildEventResponseMarkdown(detail: TaskDependencyGraphEventDetail): string {
  return String(
    detail.response_markdown
    || detail.response_comment_body
    || detail.response_error
    || detail.response_summary
    || '_No stored response summary_',
  )
}

function runtimeEventsForEdge(edge: TaskDependencyGraphEdge): TaskDependencyGraphRuntimeEvent[] {
  const rows = Array.isArray(edge.runtime_events) ? edge.runtime_events : []
  return [...rows].sort((left, right) => String(right?.at || '').localeCompare(String(left?.at || '')))
}

function eventHistoryKey(edge: TaskDependencyGraphEdge, event: TaskDependencyGraphRuntimeEvent): string {
  return [
    String(edge.source_entity_id || '').trim(),
    String(edge.target_entity_id || '').trim(),
    String(event.source || '').trim(),
    String(event.at || '').trim(),
    String(event.correlation_id || '').trim(),
  ].join('::')
}

function groupedRuntimeEventsForEdge(edge: TaskDependencyGraphEdge): GroupedRuntimeEvent[] {
  const rows = runtimeEventsForEdge(edge)
  const grouped = new Map<string, GroupedRuntimeEvent>()
  for (const event of rows) {
    const source = String(event.source || '').trim()
    const reason = String(event.reason || '').trim() || null
    const triggerLink = String(event.trigger_link || '').trim() || null
    const correlationId = String(event.correlation_id || '').trim() || null
    const key = correlationId || [source, reason || '', triggerLink || ''].join('::')
    const existing = grouped.get(key)
    if (!existing) {
      grouped.set(key, {
        key,
        source,
        reason,
        triggerLink,
        correlationId,
        active: Boolean(event.active),
        firstAt: String(event.at || '').trim() || null,
        latestAt: String(event.at || '').trim() || null,
        records: [event],
      })
      continue
    }
    existing.records.push(event)
    existing.active = existing.active || Boolean(event.active)
    const eventAt = String(event.at || '').trim() || null
    if (eventAt && (!existing.latestAt || eventAt > existing.latestAt)) existing.latestAt = eventAt
    if (eventAt && (!existing.firstAt || eventAt < existing.firstAt)) existing.firstAt = eventAt
  }
  return Array.from(grouped.values()).sort((left, right) => String(right.latestAt || '').localeCompare(String(left.latestAt || '')))
}

function edgeWidth(edge: TaskDependencyGraphEdge): number {
  if (edge.active_runtime) return 4
  if (edge.runtime_dependency) return 3.25
  if (edge.trigger_dependency) return 2.6
  return 2
}

function buildTaskHref(projectId: string, taskId: string): string {
  const url = new URL(typeof window !== 'undefined' ? window.location.href : 'http://localhost/')
  url.searchParams.set('tab', 'tasks')
  url.searchParams.set('project', projectId)
  url.searchParams.set('task', taskId)
  return `${url.pathname}${url.search}`
}

function navigateToTask(projectId: string, taskId: string): void {
  if (typeof window === 'undefined') return
  const href = buildTaskHref(projectId, taskId)
  if (`${window.location.pathname}${window.location.search}` === href) return
  window.history.pushState(null, '', href)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function computeVisibleNodeIds(args: {
  graph: ProjectTaskDependencyGraph
  filterMode: TaskFlowFilterMode
  searchQuery: string
  selectedRole: string
  showOnlyConnected: boolean
}): Set<string> {
  const { graph, filterMode, searchQuery, selectedRole, showOnlyConnected } = args
  const nodeLookup = new Map(graph.nodes.map((node) => [String(node.entity_id || '').trim(), node]))
  const search = String(searchQuery || '').trim().toLowerCase()
  const roleFilter = String(selectedRole || 'all').trim().toLowerCase()

  const matchingEdges = graph.edges.filter((edge) => {
    if (filterMode === 'runtime') return Boolean(edge.runtime_dependency)
    if (filterMode === 'structural') return Boolean(edge.structural || edge.trigger_dependency)
    return true
  })
  const connectedNodeIds = new Set<string>()
  for (const edge of matchingEdges) {
    connectedNodeIds.add(String(edge.source_entity_id || '').trim())
    connectedNodeIds.add(String(edge.target_entity_id || '').trim())
  }

  const visible = new Set<string>()
  for (const node of graph.nodes) {
    const nodeId = String(node.entity_id || '').trim()
    if (!nodeId) continue
    if (roleFilter !== 'all' && String(node.role || '').trim().toLowerCase() !== roleFilter) continue
    if (showOnlyConnected && !connectedNodeIds.has(nodeId)) continue
    if (search) {
      const corpus = [
        node.title,
        node.status,
        node.priority,
        node.role,
        node.automation_state,
        node.assigned_agent_code,
      ].join(' ').toLowerCase()
      if (!corpus.includes(search)) continue
    }
    visible.add(nodeId)
  }

  if (!search) return visible

  const expanded = new Set(visible)
  for (const edge of matchingEdges) {
    const source = String(edge.source_entity_id || '').trim()
    const target = String(edge.target_entity_id || '').trim()
    if (!source || !target) continue
    if (visible.has(source) && nodeLookup.has(target)) expanded.add(target)
    if (visible.has(target) && nodeLookup.has(source)) expanded.add(source)
  }
  return expanded
}

function computeDepths(nodes: TaskDependencyGraphNode[], edges: TaskDependencyGraphEdge[]): Map<string, number> {
  const nodeIds = nodes.map((node) => String(node.entity_id || '').trim()).filter(Boolean)
  const indegree = new Map<string, number>()
  const adjacency = new Map<string, Set<string>>()
  for (const nodeId of nodeIds) {
    indegree.set(nodeId, 0)
    adjacency.set(nodeId, new Set())
  }

  for (const edge of edges) {
    const source = String(edge.source_entity_id || '').trim()
    const target = String(edge.target_entity_id || '').trim()
    if (!source || !target || source === target) continue
    if (!indegree.has(source) || !indegree.has(target)) continue
    const neighbors = adjacency.get(source) ?? new Set<string>()
    if (neighbors.has(target)) continue
    neighbors.add(target)
    adjacency.set(source, neighbors)
    indegree.set(target, Number(indegree.get(target) || 0) + 1)
  }

  const queue = nodeIds
    .filter((nodeId) => Number(indegree.get(nodeId) || 0) === 0)
    .sort((left, right) => left.localeCompare(right))
  const depths = new Map<string, number>()
  for (const nodeId of queue) depths.set(nodeId, 0)
  const remaining = [...queue]

  while (remaining.length > 0) {
    const current = remaining.shift()
    if (!current) break
    const currentDepth = Number(depths.get(current) || 0)
    for (const next of adjacency.get(current) ?? new Set<string>()) {
      const nextDepth = Math.max(Number(depths.get(next) || 0), currentDepth + 1)
      depths.set(next, nextDepth)
      indegree.set(next, Number(indegree.get(next) || 0) - 1)
      if (Number(indegree.get(next) || 0) === 0) remaining.push(next)
    }
  }

  let fallbackDepth = Math.max(0, ...Array.from(depths.values()))
  for (const nodeId of nodeIds) {
    if (depths.has(nodeId)) continue
    fallbackDepth += 1
    depths.set(nodeId, fallbackDepth)
  }

  return depths
}

function buildDefaultLayout(args: {
  nodes: TaskDependencyGraphNode[]
  edges: TaskDependencyGraphEdge[]
  storedPositions?: Map<string, { x: number; y: number }>
}): FlowNode<TaskFlowNodeData>[] {
  const { nodes, edges, storedPositions } = args
  const depths = computeDepths(nodes, edges)
  const laneGroups = new Map<string, TaskDependencyGraphNode[]>()

  for (const node of nodes) {
    const lane = roleLane(node.role)
    const group = laneGroups.get(lane) ?? []
    group.push(node)
    laneGroups.set(lane, group)
  }

  const laneOrder = ['Developer', 'Lead', 'QA', 'Other']
  const laneBaseY = new Map<string, number>()
  let nextY = 32
  for (const lane of laneOrder) {
    const group = laneGroups.get(lane) ?? []
    laneBaseY.set(lane, nextY)
    nextY += Math.max(1, group.length) * TASK_FLOW_NODE_Y_SPACING + TASK_FLOW_LANE_GAP
  }

  const perLaneDepthCount = new Map<string, number>()

  return [...nodes]
    .sort((left, right) => {
      const laneDiff = roleLaneOrder(left.role) - roleLaneOrder(right.role)
      if (laneDiff !== 0) return laneDiff
      const depthDiff =
        Number(depths.get(String(left.entity_id || '')) || 0) -
        Number(depths.get(String(right.entity_id || '')) || 0)
      if (depthDiff !== 0) return depthDiff
      const statusDiff = statusRank(left.status) - statusRank(right.status)
      if (statusDiff !== 0) return statusDiff
      return String(left.title || '').localeCompare(String(right.title || ''))
    })
    .map((node) => {
      const lane = roleLane(node.role)
      const nodeId = String(node.entity_id || '').trim()
      const depth = Number(depths.get(nodeId) || 0)
      const laneKey = `${lane}:${depth}`
      const laneIndex = Number(perLaneDepthCount.get(laneKey) || 0)
      perLaneDepthCount.set(laneKey, laneIndex + 1)
      const summary = `${node.inbound_count} in · ${node.outbound_count} out · runtime ${node.runtime_inbound_count}/${node.runtime_outbound_count}`

      const storedPosition = storedPositions?.get(nodeId)
      return {
        id: nodeId,
        type: 'taskFlowNode',
        position: storedPosition ?? {
          x: 36 + depth * TASK_FLOW_NODE_X_SPACING,
          y: Number(laneBaseY.get(lane) || 32) + laneIndex * TASK_FLOW_NODE_Y_SPACING,
        },
        data: {
          title: node.title,
          role: node.role,
          status: node.status,
          automationState: node.automation_state,
          priority: node.priority,
          assignedAgentCode: node.assigned_agent_code,
          phase: node.team_mode_phase,
          blockingGate: node.team_mode_blocking_gate,
          summary,
        },
        draggable: true,
        selectable: true,
        connectable: false,
        focusable: true,
      } satisfies FlowNode<TaskFlowNodeData>
    })
}

function buildFlowEdges(edges: TaskDependencyGraphEdge[]): FlowEdge[] {
  return edges.map((edge) => {
    const source = String(edge.source_entity_id || '').trim()
    const target = String(edge.target_entity_id || '').trim()
    const color = edgeColor(edge)
    const width = edgeWidth(edge)

    return {
      id: `${source}->${target}`,
      source,
      target,
      type: 'smoothstep',
      animated: Boolean(edge.active_runtime),
      label: edgeChannelLabel(edge),
      selectable: false,
      focusable: false,
      style: {
        stroke: color,
        strokeWidth: width,
        strokeDasharray: edge.runtime_dependency ? undefined : edge.trigger_dependency ? '7 6' : undefined,
        opacity: 1,
      },
      labelStyle: {
        fill: '#0f172a',
        fontSize: 11,
        fontWeight: 700,
      },
      labelBgStyle: {
        fill: '#ffffff',
        fillOpacity: 0.92,
      },
      labelBgPadding: [6, 3],
      labelBgBorderRadius: 10,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color,
        width: 18,
        height: 18,
      },
    } satisfies FlowEdge
  })
}

function edgeListNodeTitle(
  nodes: TaskDependencyGraphNode[],
  entityId: string,
  fallback: string
): string {
  return nodes.find((node) => String(node.entity_id || '') === entityId)?.title || fallback
}

function EdgeRuntimeTimeline({
  edge,
  onSelectEvent,
}: {
  edge: TaskDependencyGraphEdge
  onSelectEvent: (edge: TaskDependencyGraphEdge, event: TaskDependencyGraphRuntimeEvent) => void
}) {
  const groups = groupedRuntimeEventsForEdge(edge)
  const [expandedKeys, setExpandedKeys] = React.useState<Set<string>>(() => new Set())
  React.useEffect(() => {
    setExpandedKeys(new Set())
  }, [edge.source_entity_id, edge.target_entity_id])
  if (groups.length === 0) return null
  return (
    <div className="task-flow-runtime-timeline">
      {groups.map((group) => {
        const isExpanded = expandedKeys.has(group.key)
        const latestEvent = group.records[0] || null
        return (
          <div key={`runtime-group-${group.key}`} className="task-flow-runtime-group">
            <button
              type="button"
              className="task-flow-runtime-event"
              onClick={(triggerEvent) => {
                triggerEvent.preventDefault()
                triggerEvent.stopPropagation()
                if (latestEvent) onSelectEvent(edge, latestEvent)
              }}
            >
              <div className="task-flow-runtime-event-head">
                <span className={`task-flow-channel-chip runtime ${group.active ? 'active' : ''}`.trim()}>
                  {formatChannelLabel(group.source)}
                </span>
                {group.records.length > 1 ? (
                  <span className="task-flow-runtime-count">{group.records.length} records</span>
                ) : null}
                <span className="task-flow-runtime-event-time">{formatEventTimestamp(group.latestAt)}</span>
              </div>
              {group.reason ? <div className="task-flow-runtime-event-detail">Reason: {group.reason}</div> : null}
              {group.triggerLink ? <div className="task-flow-runtime-event-detail">Trigger: {group.triggerLink}</div> : null}
              {group.correlationId ? <div className="task-flow-runtime-event-detail">Correlation: {group.correlationId}</div> : null}
              {group.records.length > 1 ? (
                <div className="task-flow-runtime-event-detail">
                  First seen: {formatEventTimestamp(group.firstAt)} · Latest: {formatEventTimestamp(group.latestAt)}
                </div>
              ) : null}
            </button>
            {group.records.length > 1 ? (
              <button
                type="button"
                className="task-flow-runtime-toggle"
                onClick={(triggerEvent) => {
                  triggerEvent.preventDefault()
                  triggerEvent.stopPropagation()
                  setExpandedKeys((current) => {
                    const next = new Set(current)
                    if (next.has(group.key)) next.delete(group.key)
                    else next.add(group.key)
                    return next
                  })
                }}
              >
                {isExpanded ? 'Hide raw event log' : 'Show raw event log'}
              </button>
            ) : null}
            {isExpanded ? (
              <div className="task-flow-runtime-raw-list">
                {group.records.map((event, index) => (
                  <button
                    key={`runtime-event-${eventHistoryKey(edge, event)}-${index}`}
                    type="button"
                    className="task-flow-runtime-raw-item"
                    onClick={(triggerEvent) => {
                      triggerEvent.preventDefault()
                      triggerEvent.stopPropagation()
                      onSelectEvent(edge, event)
                    }}
                  >
                    <span className="task-flow-runtime-event-time">{formatEventTimestamp(event.at)}</span>
                    <span className={`task-flow-channel-chip runtime ${event.active ? 'active' : ''}`.trim()}>
                      {event.active ? 'Current' : 'Recorded'}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export function ProjectTaskDependencyGraphPanel({
  projectId,
  userId,
  projectName,
  graphQuery,
  showHeader = true,
  fitSignal,
}: {
  projectId: string
  userId: string
  projectName: string
  graphQuery: QueryLike<ProjectTaskDependencyGraph>
  showHeader?: boolean
  fitSignal?: number
}) {
  const [filterMode, setFilterMode] = React.useState<TaskFlowFilterMode>('all')
  const [searchQuery, setSearchQuery] = React.useState('')
  const [selectedRole, setSelectedRole] = React.useState('all')
  const [showOnlyConnected, setShowOnlyConnected] = React.useState(false)
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(null)
  const [selectedRuntimeEvent, setSelectedRuntimeEvent] = React.useState<{
    edge: TaskDependencyGraphEdge
    event: TaskDependencyGraphRuntimeEvent
  } | null>(null)
  const [canvasNodes, setCanvasNodes] = React.useState<FlowNode<TaskFlowNodeData>[]>([])
  const flowRef = React.useRef<ReactFlowInstance<FlowNode<TaskFlowNodeData>, FlowEdge> | null>(null)

  const nodeTypes = React.useMemo(() => ({ taskFlowNode: TaskFlowNodeCard }), [])
  const miniMapStyle = React.useMemo(() => ({ background: '#f8fafc' }), [])

  const graph = graphQuery.data
  const isLoading = Boolean(graphQuery.isLoading)
  const isError = Boolean(graphQuery.isError)
  const isRefreshing = Boolean(!graphQuery.isLoading && graphQuery.isFetching)
  const errorMessage = isError ? toErrorMessage(graphQuery.error) : null

  const visibleNodeIds = React.useMemo(
    () =>
      graph
        ? computeVisibleNodeIds({
            graph,
            filterMode,
            searchQuery,
            selectedRole,
            showOnlyConnected,
          })
        : new Set<string>(),
    [filterMode, graph, searchQuery, selectedRole, showOnlyConnected]
  )

  const visibleNodes = React.useMemo(
    () => (graph?.nodes ?? []).filter((node) => visibleNodeIds.has(String(node.entity_id || '').trim())),
    [graph?.nodes, visibleNodeIds]
  )

  const layoutStorageKey = React.useMemo(() => {
    const nodeFingerprint = (graph?.nodes ?? [])
      .map((node) => `${String(node.entity_id || '').trim()}:${String(node.status || '').trim()}:${String(node.role || '').trim()}`)
      .sort()
      .join('|')
    const edgeFingerprint = (graph?.edges ?? [])
      .map((edge) => `${String(edge.source_entity_id || '').trim()}->${String(edge.target_entity_id || '').trim()}:${Number(edge.runtime_requests_total || 0)}:${Number(edge.lead_handoffs_total || 0)}`)
      .sort()
      .join('|')
    const fingerprint = hashTaskFlowFingerprint(`${nodeFingerprint}::${edgeFingerprint}`)
    return `task-flow-layout:${projectId}:${fingerprint}`
  }, [graph?.edges, graph?.nodes, projectId])

  const storedPositions = React.useMemo(
    () => readStoredTaskFlowLayout(layoutStorageKey),
    [layoutStorageKey]
  )

  const visibleEdges = React.useMemo(
    () =>
      (graph?.edges ?? []).filter((edge) => {
        const source = String(edge.source_entity_id || '').trim()
        const target = String(edge.target_entity_id || '').trim()
        if (!visibleNodeIds.has(source) || !visibleNodeIds.has(target)) return false
        if (filterMode === 'runtime') return Boolean(edge.runtime_dependency)
        if (filterMode === 'structural') return Boolean(edge.structural || edge.trigger_dependency)
        return true
      }),
    [filterMode, graph?.edges, visibleNodeIds]
  )

  React.useEffect(() => {
    if (!visibleNodes.length) {
      setSelectedTaskId(null)
      return
    }
    if (selectedTaskId && visibleNodes.some((node) => String(node.entity_id || '') === selectedTaskId)) return
    const activeRuntimeTarget = visibleEdges.find((edge) => edge.active_runtime)?.target_entity_id
    setSelectedTaskId(String(activeRuntimeTarget || visibleNodes[0]?.entity_id || ''))
  }, [selectedTaskId, visibleEdges, visibleNodes])

  const flowNodes = React.useMemo(
    () => buildDefaultLayout({ nodes: visibleNodes, edges: visibleEdges, storedPositions }),
    [storedPositions, visibleEdges, visibleNodes]
  )

  React.useEffect(() => {
    setCanvasNodes((current) => mergeFlowNodes(current, flowNodes))
  }, [flowNodes])

  const flowEdges = React.useMemo(
    () => buildFlowEdges(visibleEdges),
    [visibleEdges]
  )

  const handleFlowInit = React.useCallback((instance: ReactFlowInstance<FlowNode<TaskFlowNodeData>, FlowEdge>) => {
    flowRef.current = instance
    window.requestAnimationFrame(() => {
      instance.fitView(TASK_FLOW_FIT_VIEW_OPTIONS)
    })
  }, [])

  React.useEffect(() => {
    if (!flowRef.current || flowNodes.length === 0) return
    window.requestAnimationFrame(() => {
      flowRef.current?.fitView(TASK_FLOW_FIT_VIEW_OPTIONS)
    })
  }, [fitSignal, flowNodes.length])

  const handleNodeClick = React.useCallback((_event: React.MouseEvent, node: FlowNode<TaskFlowNodeData>) => {
    setSelectedTaskId(String(node.id || ''))
  }, [])

  const handleNodesChange = React.useCallback((changes: NodeChange<FlowNode<TaskFlowNodeData>>[]) => {
    setCanvasNodes((current) => {
      const next = applyNodeChanges(changes, current)
      writeStoredTaskFlowLayout(layoutStorageKey, next)
      return flowNodesEqual(current, next) ? current : next
    })
  }, [layoutStorageKey])

  const selectedNode = React.useMemo(
    () => visibleNodes.find((node) => String(node.entity_id || '') === String(selectedTaskId || '')) ?? null,
    [selectedTaskId, visibleNodes]
  )

  const selectedIncomingEdges = React.useMemo(
    () => visibleEdges.filter((edge) => String(edge.target_entity_id || '') === String(selectedTaskId || '')),
    [selectedTaskId, visibleEdges]
  )

  const selectedOutgoingEdges = React.useMemo(
    () => visibleEdges.filter((edge) => String(edge.source_entity_id || '') === String(selectedTaskId || '')),
    [selectedTaskId, visibleEdges]
  )

  const roleOptions = React.useMemo(() => {
    const labels = new Set<string>()
    for (const node of graph?.nodes ?? []) {
      const role = String(node.role || '').trim()
      if (role) labels.add(role)
    }
    return ['all', ...Array.from(labels).sort((left, right) => roleLaneOrder(left) - roleLaneOrder(right) || left.localeCompare(right))]
  }, [graph?.nodes])

  const filteredCounts = React.useMemo(() => {
    const runtimeEdges = visibleEdges.filter((edge) => edge.runtime_dependency).length
    const structuralEdges = visibleEdges.filter((edge) => edge.structural).length
    const triggerEdges = visibleEdges.filter((edge) => edge.trigger_dependency).length
    const activeRuntimeEdges = visibleEdges.filter((edge) => edge.active_runtime).length
    return {
      tasks: visibleNodes.length,
      runtimeEdges,
      structuralEdges,
      triggerEdges,
      activeRuntimeEdges,
      runningTasks: visibleNodes.filter((node) => String(node.automation_state || '').trim().toLowerCase() === 'running').length,
    }
  }, [visibleEdges, visibleNodes])

  const runtimeSourceRows = React.useMemo(
    () =>
      Object.entries(graph?.runtime_source_counts ?? {})
        .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0) || left[0].localeCompare(right[0]))
        .slice(0, 6),
    [graph?.runtime_source_counts]
  )

  const relationshipRows = React.useMemo(
    () =>
      Object.entries(graph?.relationship_counts ?? {})
        .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0) || left[0].localeCompare(right[0]))
        .slice(0, 6),
    [graph?.relationship_counts]
  )

  const eventDetailQuery = useQuery({
    queryKey: [
      'project-task-dependency-event-detail',
      userId,
      projectId,
      selectedRuntimeEvent?.edge?.source_entity_id,
      selectedRuntimeEvent?.edge?.target_entity_id,
      selectedRuntimeEvent?.event?.source,
      selectedRuntimeEvent?.event?.at,
      selectedRuntimeEvent?.event?.correlation_id,
    ],
    queryFn: () =>
      getProjectTaskDependencyEventDetail(userId, projectId, {
        source_task_id: String(selectedRuntimeEvent?.edge?.source_entity_id || ''),
        target_task_id: String(selectedRuntimeEvent?.edge?.target_entity_id || ''),
        source: String(selectedRuntimeEvent?.event?.source || ''),
        at: String(selectedRuntimeEvent?.event?.at || '') || undefined,
        correlation_id: String(selectedRuntimeEvent?.event?.correlation_id || '') || undefined,
      }),
    enabled: Boolean(
      userId &&
      projectId &&
      selectedRuntimeEvent?.edge?.source_entity_id &&
      selectedRuntimeEvent?.edge?.target_entity_id &&
      selectedRuntimeEvent?.event?.source
    ),
  })

  const selectedEventDetail: TaskDependencyGraphEventDetail | undefined = eventDetailQuery.data

  if (isLoading) {
    return <div className="meta">Loading task flow graph...</div>
  }

  if (isError) {
    return (
      <div className="notice error">
        <div>{errorMessage}</div>
        <button type="button" className="btn secondary" onClick={() => graphQuery.refetch?.()}>
          Retry
        </button>
      </div>
    )
  }

  if (!graph || graph.node_count === 0) {
    return <div className="meta">No task dependencies are available for this project yet.</div>
  }

  return (
    <div className="task-flow-shell">
      {showHeader ? (
        <div className="task-flow-head">
          <div>
            <div className="meta">Task flow graph</div>
            <div className="task-flow-title">
              Task-only execution view for {graph.project_name || projectName || 'this project'}
            </div>
            <div className="task-flow-subtitle">
              Structural task relationships, status-change triggers, and historical TaskAutomationRequested handoffs are combined into one execution graph.
            </div>
          </div>
          <div className="task-flow-head-actions">
            {isRefreshing ? <span className="status-chip">Refreshing...</span> : null}
          </div>
        </div>
      ) : null}

      <div className="task-flow-metrics">
        <div className="task-flow-metric-card">
          <span className="meta">Visible tasks</span>
          <strong>{filteredCounts.tasks}</strong>
        </div>
        <div className="task-flow-metric-card">
          <span className="meta">Runtime edges</span>
          <strong>{filteredCounts.runtimeEdges}</strong>
        </div>
        <div className="task-flow-metric-card">
          <span className="meta">Structural edges</span>
          <strong>{filteredCounts.structuralEdges}</strong>
        </div>
        <div className="task-flow-metric-card">
          <span className="meta">Trigger edges</span>
          <strong>{filteredCounts.triggerEdges}</strong>
        </div>
        <div className="task-flow-metric-card">
          <span className="meta">Active runtime</span>
          <strong>{filteredCounts.activeRuntimeEdges}</strong>
        </div>
        <div className="task-flow-metric-card">
          <span className="meta">Running tasks</span>
          <strong>{filteredCounts.runningTasks}</strong>
        </div>
      </div>

      <div className="task-flow-toolbar">
        <div className="task-flow-filter-group">
          <span className="meta">Mode</span>
          <button
            type="button"
            className={`task-flow-filter-btn ${filterMode === 'all' ? 'active' : ''}`.trim()}
            onClick={() => setFilterMode('all')}
          >
            All
          </button>
          <button
            type="button"
            className={`task-flow-filter-btn ${filterMode === 'runtime' ? 'active' : ''}`.trim()}
            onClick={() => setFilterMode('runtime')}
          >
            Runtime
          </button>
          <button
            type="button"
            className={`task-flow-filter-btn ${filterMode === 'structural' ? 'active' : ''}`.trim()}
            onClick={() => setFilterMode('structural')}
          >
            Structural
          </button>
        </div>

        <div className="task-flow-filter-group">
          <span className="meta">Role</span>
          <select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>
            {roleOptions.map((role) => (
              <option key={`task-flow-role-${role}`} value={role}>
                {role === 'all' ? 'All roles' : role}
              </option>
            ))}
          </select>
        </div>

        <label className="task-flow-toggle">
          <input
            type="checkbox"
            checked={showOnlyConnected}
            onChange={(event) => setShowOnlyConnected(event.target.checked)}
          />
          <span>Only connected tasks</span>
        </label>

        <label className="task-flow-search">
          <Icon path="M10.5 3a7.5 7.5 0 015.93 12.09l4.24 4.24-1.41 1.41-4.24-4.24A7.5 7.5 0 1110.5 3zm0 2a5.5 5.5 0 100 11 5.5 5.5 0 000-11z" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search tasks, roles, statuses, agents"
          />
        </label>
      </div>

      <div className="task-flow-legend">
        <span className="task-flow-legend-item"><span className="task-flow-legend-line runtime" /> runtime request</span>
        <span className="task-flow-legend-item"><span className="task-flow-legend-line active" /> active runtime chain</span>
        <span className="task-flow-legend-item"><span className="task-flow-legend-line trigger" /> status trigger</span>
        <span className="task-flow-legend-item"><span className="task-flow-legend-line structural" /> structural dependency</span>
      </div>

      {(runtimeSourceRows.length > 0 || relationshipRows.length > 0) ? (
        <div className="task-flow-channel-band">
          {runtimeSourceRows.length > 0 ? (
            <div className="task-flow-channel-group">
              <span className="meta">Runtime sources</span>
              <div className="task-flow-channel-chips">
                {runtimeSourceRows.map(([key, count]) => (
                  <span key={`runtime-source-${key}`} className="task-flow-channel-chip runtime">
                    {formatChannelLabel(key)} · {Number(count || 0)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {relationshipRows.length > 0 ? (
            <div className="task-flow-channel-group">
              <span className="meta">Structural links</span>
              <div className="task-flow-channel-chips">
                {relationshipRows.map(([key, count]) => (
                  <span key={`relationship-kind-${key}`} className="task-flow-channel-chip structural">
                    {formatChannelLabel(key)} · {Number(count || 0)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="task-flow-layout">
        <div className="task-flow-canvas">
          {flowNodes.length === 0 ? (
            <div className="meta">No visible tasks for the current filter set.</div>
          ) : (
            <ReactFlow
              id={`task-flow-${projectId}`}
              nodes={canvasNodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              proOptions={TASK_FLOW_PRO_OPTIONS}
              onNodeClick={handleNodeClick}
              onNodesChange={handleNodesChange}
              onInit={handleFlowInit}
            >
              <MiniMap pannable zoomable style={miniMapStyle} />
              <Background gap={18} size={1} color="#dbe4f0" />
            </ReactFlow>
          )}
        </div>

        <aside className="task-flow-inspector">
          {!selectedNode ? (
            <div className="meta">Select a task node to inspect its dependency context.</div>
          ) : (
            <>
              <div className="task-flow-inspector-summary">
                <div className="task-flow-inspector-head">
                  <div className="task-flow-inspector-head-copy">
                    <div className="meta">Selected task</div>
                    <div className="task-flow-inspector-title">{selectedNode.title}</div>
                  </div>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => navigateToTask(projectId, selectedNode.entity_id)}
                  >
                    Open task
                  </button>
                </div>

                <div className="task-flow-selected-badges">
                  <span className={`task-flow-role-pill role-${normalizeRoleKey(selectedNode.role)}`.trim()}>{selectedNode.role}</span>
                  <span className={`task-flow-status-pill status-${normalizeStatusKey(selectedNode.status)}`.trim()}>{selectedNode.status}</span>
                  <span className={`task-flow-automation-pill automation-${normalizeAutomationKey(selectedNode.automation_state)}`.trim()}>
                    {selectedNode.automation_state}
                  </span>
                  {selectedNode.priority ? <span className="task-flow-meta-chip">Priority {selectedNode.priority}</span> : null}
                  {selectedNode.assigned_agent_code ? <span className="task-flow-meta-chip">{selectedNode.assigned_agent_code}</span> : null}
                </div>

                <div className="task-flow-inspector-grid">
                  <div className="task-flow-inspector-card">
                    <span className="meta">Incoming</span>
                    <strong>{selectedNode.inbound_count}</strong>
                    <span className="meta">runtime {selectedNode.runtime_inbound_count} · structural {selectedNode.structural_inbound_count}</span>
                  </div>
                  <div className="task-flow-inspector-card">
                    <span className="meta">Outgoing</span>
                    <strong>{selectedNode.outbound_count}</strong>
                    <span className="meta">runtime {selectedNode.runtime_outbound_count} · structural {selectedNode.structural_outbound_count}</span>
                  </div>
                </div>
              </div>

              {selectedNode.team_mode_blocking_gate ? (
                <div className="task-flow-inspector-section">
                  <div className="meta">Blocking gate</div>
                  <div className="task-flow-blocking-gate">{selectedNode.team_mode_blocking_gate}</div>
                </div>
              ) : null}

              <div className="task-flow-inspector-section">
                <div className="meta">Incoming dependencies</div>
                {selectedIncomingEdges.length === 0 ? (
                  <div className="meta">No upstream dependencies in the current view.</div>
                ) : (
                  <div className="task-flow-edge-list">
                    {selectedIncomingEdges.map((edge) => {
                      const sourceId = String(edge.source_entity_id || '')
                      return (
                        <div
                          key={`incoming-${sourceId}-${edge.target_entity_id}`}
                          className="task-flow-edge-item"
                          onClick={() => setSelectedTaskId(sourceId)}
                          onKeyDown={(keyboardEvent) => {
                            if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                              keyboardEvent.preventDefault()
                              setSelectedTaskId(sourceId)
                            }
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          <div className="task-flow-edge-item-head">
                            <span className="task-flow-edge-pill incoming">From</span>
                            <span className="task-flow-edge-title">
                              {edgeListNodeTitle(graph.nodes, sourceId, sourceId)}
                            </span>
                          </div>
                          <div className="task-flow-edge-desc">{edgeChannelLabel(edge)}</div>
                          <div className="task-flow-edge-meta">
                            {edge.latest_runtime_at ? <span>Latest {new Date(edge.latest_runtime_at).toLocaleString()}</span> : <span>No runtime timestamp</span>}
                          </div>
                          <EdgeRuntimeTimeline edge={edge} onSelectEvent={(selectedEdge, event) => setSelectedRuntimeEvent({ edge: selectedEdge, event })} />
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="task-flow-inspector-section">
                <div className="meta">Outgoing dependencies</div>
                {selectedOutgoingEdges.length === 0 ? (
                  <div className="meta">No downstream tasks in the current view.</div>
                ) : (
                  <div className="task-flow-edge-list">
                    {selectedOutgoingEdges.map((edge) => {
                      const targetId = String(edge.target_entity_id || '')
                      return (
                        <div
                          key={`outgoing-${edge.source_entity_id}-${targetId}`}
                          className="task-flow-edge-item"
                          onClick={() => setSelectedTaskId(targetId)}
                          onKeyDown={(keyboardEvent) => {
                            if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                              keyboardEvent.preventDefault()
                              setSelectedTaskId(targetId)
                            }
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          <div className="task-flow-edge-item-head">
                            <span className="task-flow-edge-pill outgoing">To</span>
                            <span className="task-flow-edge-title">
                              {edgeListNodeTitle(graph.nodes, targetId, targetId)}
                            </span>
                          </div>
                          <div className="task-flow-edge-desc">{edgeChannelLabel(edge)}</div>
                          <div className="task-flow-edge-meta">
                            {edge.active_runtime ? <span>Active runtime chain</span> : <span>{Number(edge.runtime_requests_total || 0)} runtime requests</span>}
                          </div>
                          <EdgeRuntimeTimeline edge={edge} onSelectEvent={(selectedEdge, event) => setSelectedRuntimeEvent({ edge: selectedEdge, event })} />
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </>
          )}
        </aside>
      </div>

      <AlertDialog.Root open={Boolean(selectedRuntimeEvent)} onOpenChange={(open) => { if (!open) setSelectedRuntimeEvent(null) }}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content task-flow-event-dialog">
            <div className="task-flow-event-dialog-head">
              <div className="task-flow-event-dialog-heading">
                <AlertDialog.Title className="codex-chat-alert-title">Runtime Event Detail</AlertDialog.Title>
                <AlertDialog.Description className="codex-chat-alert-description">
                  {selectedEventDetail?.source_task_title && selectedEventDetail?.target_task_title
                    ? `${selectedEventDetail.source_task_title} -> ${selectedEventDetail.target_task_title}`
                    : 'Task-to-task communication detail'}
                </AlertDialog.Description>
              </div>
              <AlertDialog.Cancel asChild>
                <button className="task-flow-event-dismiss" type="button" aria-label="Close runtime event detail">
                  <Icon path="M18.3 5.71a1 1 0 0 0-1.41 0L12 10.59 7.11 5.7A1 1 0 0 0 5.7 7.11L10.59 12 5.7 16.89a1 1 0 1 0 1.41 1.41L12 13.41l4.89 4.89a1 1 0 0 0 1.41-1.41L13.41 12l4.89-4.89a1 1 0 0 0 0-1.4Z" />
                </button>
              </AlertDialog.Cancel>
            </div>
            <div className="task-flow-event-meta-row">
              {selectedRuntimeEvent?.event?.source ? <span className="task-flow-channel-chip runtime">{formatChannelLabel(selectedRuntimeEvent.event.source)}</span> : null}
              <span className="task-flow-event-meta-pill">{formatEventTimestamp(selectedRuntimeEvent?.event?.at)}</span>
              {selectedRuntimeEvent?.event?.correlation_id ? <span className="task-flow-event-meta-pill">Correlation: {selectedRuntimeEvent.event.correlation_id}</span> : null}
            </div>
            {eventDetailQuery.isLoading ? (
              <div className="meta">Loading runtime event detail...</div>
            ) : eventDetailQuery.isError ? (
              <div className="notice error">Unable to load runtime event detail.</div>
            ) : !selectedEventDetail ? (
              <div className="notice">No stored detail was found for this runtime event.</div>
            ) : (
              <div className="task-flow-event-detail-layout">
                <div className="task-flow-event-detail-main">
                  <div className="task-flow-event-detail-card">
                    <div className="task-flow-event-card-head">
                      <div className="meta">Prompt request</div>
                      {selectedEventDetail.requested_at ? <span className="meta">{formatEventTimestamp(selectedEventDetail.requested_at)}</span> : null}
                    </div>
                    <div className="task-flow-event-markdown md-editor-surface">
                      <div className="task-flow-event-scroll-viewport">
                        <div className="md-editor-content">
                          <MarkdownView value={String(selectedEventDetail.request_markdown || '_No stored instruction_')} />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="task-flow-event-detail-card">
                    <div className="task-flow-event-card-head">
                      <div className="meta">Response</div>
                      {selectedEventDetail.response_status ? (
                        <span className={`task-flow-status-pill ${selectedEventDetail.response_status === 'failed' ? 'is-failed' : 'is-completed'}`}>
                          {selectedEventDetail.response_status}
                        </span>
                      ) : null}
                    </div>
                    <div className="task-flow-event-markdown md-editor-surface">
                      <div className="task-flow-event-scroll-viewport">
                        <div className="md-editor-content">
                          <MarkdownView value={buildEventResponseMarkdown(selectedEventDetail)} />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="task-flow-event-separator" />
                <div className="task-flow-event-facts">
                  {selectedEventDetail.response_at ? (
                    <div className="task-flow-event-fact">
                      <span className="meta">Response time</span>
                      <strong>{formatEventTimestamp(selectedEventDetail.response_at)}</strong>
                    </div>
                  ) : null}
                  {selectedEventDetail.reason ? (
                    <div className="task-flow-event-fact">
                      <span className="meta">Reason</span>
                      <strong>{selectedEventDetail.reason}</strong>
                    </div>
                  ) : null}
                  {selectedEventDetail.trigger_link ? (
                    <div className="task-flow-event-fact">
                      <span className="meta">Trigger link</span>
                      <strong>{selectedEventDetail.trigger_link}</strong>
                    </div>
                  ) : null}
                  {selectedEventDetail.correlation_id ? (
                    <div className="task-flow-event-fact">
                      <span className="meta">Correlation</span>
                      <strong>{selectedEventDetail.correlation_id}</strong>
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </div>
  )
}
