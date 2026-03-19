import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { AgentChatUsage, GraphContextPack, GraphProjectOverview, ProjectRule, ProjectSkill } from '../../types'
import { Icon } from '../shared/uiHelpers'

type SnapshotSourceKey =
  | 'soul'
  | 'rules'
  | 'skills'
  | 'plugin_policy'
  | 'plugin_required_checks'
  | 'knowledge_graph_context'
  | 'knowledge_graph_summary'
  | 'knowledge_graph_fresh_snapshot'
  | 'knowledge_graph_evidence_non_chat'
  | 'knowledge_graph_evidence_chat'
  | 'system_scaffold'
  | 'system_guidance'
  | 'chat_history'
  | 'runtime_metadata'

type SnapshotSourceGroup = 'project' | 'knowledge_graph' | 'hardcoded' | 'runtime'

type SnapshotSourceUsage = {
  key: SnapshotSourceKey
  label: string
  group: SnapshotSourceGroup
  color: string
  chars: number
  tokens: number
  lines: number
  percent: number
  windowPercent: number
}

type SnapshotCubeTile = {
  key: string
  label: string
  color: string
}

type SnapshotCompositionSegment = {
  key: string
  label: string
  color: string
  tokens: number
  windowPercent: number
  usedPercent: number
  groupLabel: string
}

type OverviewEntityCountItem = {
  key: string
  label: string
  color: string
  count: number
}

type ChatTurnLike = {
  role?: unknown
  content?: unknown
}

type CodexResumeStateLike = {
  attempted?: boolean
  succeeded?: boolean
  fallbackUsed?: boolean
} | null

type PromptMode = 'full' | 'full_fallback' | 'resume'

const CHAT_HISTORY_WINDOW_SIZE = 12
const CONTEXT_OCCUPANCY_TILE_COUNT = 480

const FULL_PROMPT_SCAFFOLD_TEMPLATE = [
  'You are an automation agent for task management.',
  'Use available MCP tools to satisfy the instruction.',
  'Return plain Markdown text for the end user.',
  'Do not output JSON wrappers.',
  '',
  'Task ID: {task_id}',
  'Title: {title}',
  'Status: {status}',
  'Description: {description}',
  'Workspace ID: {workspace_id}',
  'Project ID: {project_id}',
  'Current User ID: {actor_user_id}',
  'Current User Project Role: {actor_project_role}',
  'Project Name: {project_name}',
  'Instruction: {instruction}',
  'Task Branch: {task_branch}',
  'Task Workdir: {task_workdir}',
  'Repository Root: {repo_root}',
  'Status Change Trigger Context:',
  '{status_change_trigger_context}',
  '',
  'Context Pack:',
  'File: Soul.md (source: project.description)',
  'File: ProjectRules.md (source: project_rules)',
  'File: ProjectSkills.md (source: project_skills)',
  'File: PluginPolicy.json (source: project_plugin_configs[*].compiled_policy_json)',
  'File: PluginRequiredChecks.md (source: plugin_policy.required_checks)',
  'File: GraphContext.md (source: knowledge_graph)',
  'File: GraphEvidence.json (source: knowledge_graph.evidence)',
  'File: GraphSummary.md (source: knowledge_graph.summary)',
  '',
  'Guidance:',
  '- This is a general chat request (not bound to a single task). Use workspace/project context and MCP tools as needed.',
  '- Enabled MCP servers for this run: {enabled_mcp_servers}.',
  '- Mutating tools are allowed for this request.',
  '- Apply requested changes via MCP tools directly when possible.',
  '- Respond directly to the user with clear, actionable text.',
].join('\n')

const FULL_PROMPT_GUIDANCE_TEMPLATE = [
  '- Treat Soul.md, ProjectRules.md, ProjectSkills.md, GraphContext.md, GraphEvidence.json, and GraphSummary.md as durable project-level context.',
  '- ProjectRules.md defines how you should behave within this project.',
  '- ProjectSkills.md captures reusable skills configured for this project.',
  '- Apply ProjectSkills with mode=enforced before advisory skills.',
  '- If no enforced skill applies, use advisory skills as guidance alongside project rules.',
  '- Treat PluginPolicy.json + PluginRequiredChecks.md as explicit execution constraints for this project.',
  '- GraphContext.md captures resource relations and should guide dependency-aware decisions.',
  '- GraphEvidence.json is the canonical evidence source for grounded claims.',
  '- GraphSummary.md can be used as a concise overview, but validate against GraphEvidence.json before acting.',
  '- Treat claims without an evidence_id as low confidence.',
  '- If project context conflicts with the latest explicit user instruction, follow the latest explicit user instruction.',
  '- You may call task-management MCP tools relevant to the request.',
  '- If the user asks to implement/work on a specific project by ID or name (for example \'Implement project <id|name>\'), call get_project_chat_context(project_ref=..., workspace_id=...) first.',
  '- If get_project_chat_context returns ambiguous name matches, ask for a concrete project ID or workspace_id and then call it again.',
  '- Read each MCP tool description and follow its payload contract and operational guidance.',
  '- For mutating MCP tool calls, always provide command_id.',
  '- If retrying the same mutation, reuse the exact same command_id.',
  '- When mentioning created/updated entities in summary/comment, include clickable Markdown links (not raw IDs).',
  '- Never return generic phrases like \'open task\' or \'open note\' without a concrete link target.',
  '- For each created entity, include at least one explicit link that can be clicked in chat.',
  '- Link format in this app:',
  '- Note: ?tab=notes&project=<project_id>&note=<note_id>',
  '- Task: ?tab=tasks&project=<project_id>&task=<task_id>',
  '- Specification: ?tab=specifications&project=<project_id>&specification=<specification_id>',
  '- Project: ?tab=projects&project=<project_id>',
  '- For recurring schedules, set task.recurring_rule explicitly using canonical format: every:<number><m|h|d> (example: every:1m).',
  '- After scheduling changes, verify by reading the task and confirming scheduled_at_utc + recurring_rule values.',
].join('\n')

const RESUME_PROMPT_SCAFFOLD_TEMPLATE = [
  'You are an automation agent for task management.',
  'This is a resumed Codex thread. Reuse prior thread context instead of re-deriving project bootstrap context.',
  'Return plain Markdown text for the end user.',
  'Do not output JSON wrappers.',
  '',
  'Current Turn Context:',
  'Task ID: {task_id}',
  'Title: {title}',
  'Status: {status}',
  'Description: {description}',
  'Workspace ID: {workspace_id}',
  'Project ID: {project_id}',
  'Current User ID: {actor_user_id}',
  'Project Name: {project_name}',
  'Instruction: {instruction}',
  'Status Change Trigger Context:',
  '{status_change_trigger_context}',
  '',
  'Fresh Cross-Session Memory Snapshot (generated for this turn):',
  '{fresh_memory_snapshot}',
  '',
  'Guidance:',
  '- This is a general chat request; use workspace/project context as needed.',
  '- Enabled MCP servers for this run: {enabled_mcp_servers}.',
].join('\n')

const RESUME_PROMPT_GUIDANCE_TEMPLATE = [
  '- For factual questions that may depend on other sessions, prefer Fresh Cross-Session Memory Snapshot over stale thread memory.',
  '- If prior thread context appears stale or missing, refresh by calling get_project_chat_context(project_ref=..., workspace_id=...).',
  '- Read each MCP tool description and follow its payload contract and operational guidance.',
  '- For mutating MCP tool calls, always provide command_id.',
  '- If retrying the same mutation, reuse the exact same command_id.',
  '- Mutating tools are allowed for this request.',
  '- Respond directly to the user with clear, actionable text.',
].join('\n')

function estimateTokenCount(charCount: number): number {
  if (!Number.isFinite(charCount) || charCount <= 0) return 0
  return Math.max(1, Math.round(charCount / 4))
}

function countLines(value: string): number {
  if (!value.trim()) return 0
  return value.split(/\r?\n/).length
}

function normalizeGraphEntityTypeKey(entityType: unknown): string {
  return String(entityType || '')
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, '')
}

function normalizeEntityTypeLabel(entityType: string | null | undefined): string {
  const normalized = String(entityType || '').trim()
  if (!normalized) return 'Entity'
  return normalized
}

function graphEntityTypeDisplayLabel(entityType: unknown): string {
  const key = normalizeGraphEntityTypeKey(entityType)
  if (key === 'task') return 'Tasks'
  if (key === 'note') return 'Notes'
  if (key === 'specification') return 'Specifications'
  if (key === 'projectrule') return 'Rules'
  if (key === 'chatmessage') return 'Chat messages'
  if (key === 'chatattachment') return 'Chat attachments'
  if (key === 'chatsession') return 'Chat sessions'
  if (key === 'boundedcontext') return 'Bounded contexts'
  if (key === 'aggregate') return 'Aggregates'
  if (key === 'command') return 'Commands'
  if (key === 'domainevent') return 'Domain events'
  if (key === 'policy') return 'Policies'
  if (key === 'readmodel') return 'Read models'
  if (key === 'comment') return 'Comments'
  if (key === 'tag') return 'Tags'
  if (key === 'user') return 'Users'
  if (key === 'workspace') return 'Workspaces'
  if (!key) return 'Entities'
  return String(entityType || 'Entity')
}

function graphEntityTypeColor(entityType: unknown): string {
  const key = normalizeGraphEntityTypeKey(entityType)
  if (key === 'task') return '#0284c7'
  if (key === 'note') return '#9333ea'
  if (key === 'specification') return '#0d9488'
  if (key === 'projectrule') return '#ea580c'
  if (key === 'chatmessage') return '#16a34a'
  if (key === 'chatattachment') return '#65a30d'
  if (key === 'chatsession') return '#22c55e'
  if (key === 'boundedcontext') return '#14b8a6'
  if (key === 'aggregate') return '#f59e0b'
  if (key === 'command') return '#2563eb'
  if (key === 'domainevent') return '#ea580c'
  if (key === 'policy') return '#7c3aed'
  if (key === 'readmodel') return '#16a34a'
  if (key === 'comment') return '#16a34a'
  if (key === 'tag') return '#ca8a04'
  if (key === 'user') return '#4f46e5'
  if (key === 'workspace') return '#6b7280'
  return '#64748b'
}

function buildOverviewEntityCountItems(overview?: GraphProjectOverview): OverviewEntityCountItem[] {
  const entityTypeCounts = Array.isArray(overview?.entity_type_counts) ? overview?.entity_type_counts : []
  if (entityTypeCounts.length > 0) {
    return entityTypeCounts
      .map((item) => ({
        key: normalizeGraphEntityTypeKey(item?.entity_type),
        label: graphEntityTypeDisplayLabel(item?.entity_type),
        color: graphEntityTypeColor(item?.entity_type),
        count: Math.max(0, Number(item?.count || 0)),
      }))
      .filter((item) => item.key && item.count > 0)
  }
  const counts = overview?.counts
  return [
    { key: 'task', label: 'Tasks', color: graphEntityTypeColor('task'), count: Math.max(0, Number(counts?.tasks || 0)) },
    { key: 'note', label: 'Notes', color: graphEntityTypeColor('note'), count: Math.max(0, Number(counts?.notes || 0)) },
    { key: 'specification', label: 'Specifications', color: graphEntityTypeColor('specification'), count: Math.max(0, Number(counts?.specifications || 0)) },
    { key: 'projectrule', label: 'Rules', color: graphEntityTypeColor('projectrule'), count: Math.max(0, Number(counts?.project_rules || 0)) },
  ].filter((item) => item.count > 0)
}

function normalizeChatIndexMode(mode: unknown): 'OFF' | 'VECTOR_ONLY' | 'KG_AND_VECTOR' {
  const normalized = String(mode || '').trim().toUpperCase()
  if (normalized === 'VECTOR_ONLY' || normalized === 'KG_AND_VECTOR') return normalized
  return 'OFF'
}

function normalizeChatAttachmentIngestionMode(mode: unknown): 'OFF' | 'METADATA_ONLY' | 'FULL_TEXT' {
  const normalized = String(mode || '').trim().toUpperCase()
  if (normalized === 'OFF' || normalized === 'FULL_TEXT') return normalized
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

function sourceGroupLabel(group: SnapshotSourceGroup): string {
  if (group === 'project') return 'Project-managed'
  if (group === 'knowledge_graph') return 'Knowledge graph'
  if (group === 'hardcoded') return 'Prompt code'
  return 'Runtime session'
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0.0%'
  return `${value.toFixed(1)}%`
}

function promptModeLabel(mode: PromptMode): string {
  if (mode === 'resume') return 'Resume'
  if (mode === 'full_fallback') return 'Full (resume fallback)'
  return 'Full'
}

function buildConversationHistoryText({
  projectId,
  activeChatProjectId,
  activeChatTurns,
}: {
  projectId: string
  activeChatProjectId?: string
  activeChatTurns: ChatTurnLike[]
}): string {
  if (!projectId || !activeChatProjectId || projectId !== activeChatProjectId) return ''
  const normalized = activeChatTurns
    .map((item) => {
      const role = String(item?.role || '').trim().toLowerCase()
      const content = String(item?.content || '').trim()
      if ((role !== 'user' && role !== 'assistant') || !content) return ''
      return `${role.toUpperCase()}: ${content}`
    })
    .filter(Boolean)
    .slice(-CHAT_HISTORY_WINDOW_SIZE)
  if (normalized.length === 0) return ''
  return `Conversation history:\n${normalized.join('\n')}\n\nLatest user instruction:\n`
}

function buildSnapshotCubeTiles(
  slices: Array<{ key: string; label: string; color: string; value: number }>,
  tileCount: number
): SnapshotCubeTile[] {
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

  const output: SnapshotCubeTile[] = []
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

function renderRulesMarkdown(projectRules: ProjectRule[]): string {
  const lines: string[] = []
  for (const item of projectRules) {
    const title = String(item.title || '').trim()
    if (title.toLowerCase() === 'plugin policy') continue
    const body = String(item.body || '').trim()
    if (!title && !body) continue
    const label = title || 'Untitled rule'
    if (body) lines.push(`- ${label}: ${body}`)
    else lines.push(`- ${label}`)
  }
  if (lines.length === 0) return '_(no project rules)_'
  return lines.join('\n')
}

function renderPluginPolicyMarkdown(projectRules: ProjectRule[]): { pluginPolicy: string; pluginRequiredChecks: string } {
  const pluginRule = projectRules.find((item) => String(item?.title || '').trim().toLowerCase() === 'plugin policy')
  if (!pluginRule) {
    return {
      pluginPolicy: '_(Plugin Policy unavailable)_',
      pluginRequiredChecks: '_(none)_',
    }
  }
  const rawBody = String(pluginRule.body || '').trim()
  if (!rawBody) {
    return {
      pluginPolicy: '_(Plugin Policy body is empty)_',
      pluginRequiredChecks: '_(none)_',
    }
  }
  let body = rawBody
  const fencedMatch = rawBody.match(/```(?:json)?\s*(\{[\s\S]*\})\s*```/i)
  if (fencedMatch?.[1]) body = String(fencedMatch[1]).trim()
  try {
    const parsed = JSON.parse(body) as unknown
    if (!parsed || typeof parsed !== 'object') {
      return {
        pluginPolicy: rawBody,
        pluginRequiredChecks: '_(required_checks unavailable)_',
      }
    }
    const pluginPolicy = JSON.stringify(parsed, null, 2)
    const requiredChecksRaw = (parsed as { required_checks?: unknown }).required_checks
    if (!requiredChecksRaw || typeof requiredChecksRaw !== 'object' || Array.isArray(requiredChecksRaw)) {
      return {
        pluginPolicy,
        pluginRequiredChecks: '_(required_checks unavailable)_',
      }
    }
    const requiredChecks = requiredChecksRaw as Record<string, unknown>
    const lines: string[] = []
    for (const [scope, checks] of Object.entries(requiredChecks)) {
      const scopeName = String(scope || '').trim() || 'unknown'
      const checkNames = Array.isArray(checks)
        ? checks.map((item) => String(item || '').trim()).filter(Boolean)
        : []
      lines.push(checkNames.length > 0 ? `- ${scopeName}: ${checkNames.join(', ')}` : `- ${scopeName}: _(none)_`)
    }
    return {
      pluginPolicy,
      pluginRequiredChecks: lines.join('\n').trim() || '_(none)_',
    }
  } catch {
    return {
      pluginPolicy: rawBody,
      pluginRequiredChecks: '_(required_checks unavailable)_',
    }
  }
}

function renderSkillsMarkdown(projectSkills: ProjectSkill[]): string {
  const lines: string[] = []
  for (const item of projectSkills) {
    const name = String(item.name || '').trim()
    const skillKey = String(item.skill_key || '').trim()
    const summary = String(item.summary || '').trim()
    const mode = String(item.mode || '').trim().toLowerCase() || 'advisory'
    const trust = String(item.trust_level || '').trim().toLowerCase() || 'reviewed'
    const source = String(item.source_locator || '').trim()
    if (!name && !skillKey) continue
    const label = name || skillKey
    const keyText = skillKey ? ` (${skillKey})` : ''
    const sourceText = source ? ` source=${source}` : ''
    const suffixParts = [`mode=${mode}`, `trust=${trust}`]
    if (summary) suffixParts.push(summary)
    lines.push(`- ${label}${keyText}: ${suffixParts.join('; ')}${sourceText}`)
  }
  if (lines.length === 0) return '_(no project skills)_'
  return lines.join('\n')
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

function normalizeSnapshotText(value: unknown, maxChars: number): string {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  if (normalized.length <= maxChars) return normalized
  return `${normalized.slice(0, Math.max(0, maxChars - 3))}...`
}

function buildResumeFreshMemorySnapshot({
  summaryMarkdown,
  evidenceItems,
  maxSummaryChars = 1100,
  maxEvidenceItems = 6,
  maxEvidenceSnippetChars = 180,
  maxBlockChars = 2400,
}: {
  summaryMarkdown: string
  evidenceItems: Array<{
    evidence_id?: string | null
    entity_type?: string | null
    source_type?: string | null
    snippet?: string | null
    final_score?: number | null
  }>
  maxSummaryChars?: number
  maxEvidenceItems?: number
  maxEvidenceSnippetChars?: number
  maxBlockChars?: number
}): string {
  const blocks: string[] = []

  const summaryText = normalizeSnapshotText(summaryMarkdown, maxSummaryChars)
  if (summaryText) {
    blocks.push(`Fresh Summary:\n${summaryText}`)
  }

  const evidenceLines: string[] = []
  for (const item of evidenceItems) {
    const snippet = normalizeSnapshotText(item?.snippet || '', maxEvidenceSnippetChars)
    if (!snippet) continue
    const evidenceId = String(item?.evidence_id || '').trim()
    const entityType = String(item?.entity_type || '').trim() || 'Entity'
    const sourceType = String(item?.source_type || '').trim() || 'source'
    const scoreValue = Number(item?.final_score)
    const scoreText = Number.isFinite(scoreValue) ? scoreValue.toFixed(3) : ''
    const evidencePrefix = evidenceId ? `[${evidenceId}] ` : ''
    const scoreSuffix = scoreText ? ` score=${scoreText}` : ''
    evidenceLines.push(`- ${evidencePrefix}${entityType} (${sourceType})${scoreSuffix}: ${snippet}`)
    if (evidenceLines.length >= Math.max(1, Math.floor(maxEvidenceItems))) break
  }
  if (evidenceLines.length > 0) {
    blocks.push(`Fresh Evidence:\n${evidenceLines.join('\n')}`)
  }

  const snapshot = blocks.join('\n\n').trim()
  if (!snapshot) return '_(fresh project snapshot unavailable)_'
  if (snapshot.length <= maxBlockChars) return snapshot
  return normalizeSnapshotText(snapshot, maxBlockChars)
}

export function ProjectContextSnapshotPanel({
  projectId,
  projectName,
  projectDescription,
  projectRules,
  projectSkills,
  overview,
  contextPack,
  contextLimitTokens,
  activeChatProjectId,
  activeChatTurns,
  codexChatUsage,
  codexChatResumeState,
  projectChatIndexMode,
  projectChatAttachmentIngestionMode,
}: {
  projectId: string
  projectName: string
  projectDescription: string
  projectRules: ProjectRule[]
  projectSkills: ProjectSkill[]
  overview?: GraphProjectOverview
  contextPack?: GraphContextPack
  contextLimitTokens?: number
  activeChatProjectId?: string
  activeChatTurns?: ChatTurnLike[]
  codexChatUsage?: AgentChatUsage | null
  codexChatResumeState?: CodexResumeStateLike
  projectChatIndexMode?: string
  projectChatAttachmentIngestionMode?: string
}) {
  const counts = overview?.counts ?? {
    tasks: 0,
    notes: 0,
    specifications: 0,
    project_rules: 0,
    comments: 0,
  }
  const overviewEntityCounts = React.useMemo(() => buildOverviewEntityCountItems(overview), [overview])
  const indexedEntityCount = React.useMemo(() => {
    const total = Number(overview?.total_entities || 0)
    if (Number.isFinite(total) && total > 0) return Math.floor(total)
    return overviewEntityCounts.reduce((sum, item) => sum + item.count, 0)
  }, [overview?.total_entities, overviewEntityCounts])
  const evidenceItems = contextPack?.evidence ?? []
  const normalizedChatIndexMode = normalizeChatIndexMode(projectChatIndexMode)
  const normalizedChatAttachmentMode = normalizeChatAttachmentIngestionMode(projectChatAttachmentIngestionMode)
  const rulesMarkdown = React.useMemo(() => renderRulesMarkdown(projectRules), [projectRules])
  const skillsMarkdown = React.useMemo(() => renderSkillsMarkdown(projectSkills), [projectSkills])
  const pluginPolicyContext = React.useMemo(() => renderPluginPolicyMarkdown(projectRules), [projectRules])
  const graphSummaryMarkdown = React.useMemo(() => renderGraphSummaryMarkdown(contextPack?.summary), [contextPack?.summary])
  const graphContextMarkdown = String(contextPack?.markdown || '')
  const resumeFreshMemorySnapshot = React.useMemo(
    () =>
      buildResumeFreshMemorySnapshot({
        summaryMarkdown: graphSummaryMarkdown,
        evidenceItems: evidenceItems.map((item) => ({
          evidence_id: item.evidence_id,
          entity_type: item.entity_type,
          source_type: item.source_type,
          snippet: item.snippet,
          final_score: item.final_score,
        })),
      }),
    [evidenceItems, graphSummaryMarkdown]
  )
  const chatEvidenceItems = React.useMemo(() => evidenceItems.filter((item) => isChatEntityType(item.entity_type)), [evidenceItems])
  const nonChatEvidenceItems = React.useMemo(
    () => evidenceItems.filter((item) => !isChatEntityType(item.entity_type)),
    [evidenceItems]
  )
  const usagePromptMode = String(codexChatUsage?.prompt_mode || '').trim().toLowerCase()
  const activePromptMode = React.useMemo<PromptMode>(() => {
    if (usagePromptMode === 'resume') return 'resume'
    const resumeFallbackUsed = Boolean(
      codexChatResumeState?.attempted
      && !codexChatResumeState?.succeeded
    )
    return resumeFallbackUsed ? 'full_fallback' : 'full'
  }, [codexChatResumeState?.attempted, codexChatResumeState?.succeeded, usagePromptMode])
  const activePromptLabel = promptModeLabel(activePromptMode)
  const activePromptScaffoldTemplate = activePromptMode === 'resume'
    ? RESUME_PROMPT_SCAFFOLD_TEMPLATE
    : FULL_PROMPT_SCAFFOLD_TEMPLATE
  const activePromptGuidanceTemplate = activePromptMode === 'resume'
    ? RESUME_PROMPT_GUIDANCE_TEMPLATE
    : FULL_PROMPT_GUIDANCE_TEMPLATE
  const observedInputTokens = typeof codexChatUsage?.input_tokens === 'number' && codexChatUsage.input_tokens >= 0
    ? Math.floor(codexChatUsage.input_tokens)
    : null
  const observedOutputTokens = typeof codexChatUsage?.output_tokens === 'number' && codexChatUsage.output_tokens >= 0
    ? Math.floor(codexChatUsage.output_tokens)
    : null
  const observedCachedInputTokens = typeof codexChatUsage?.cached_input_tokens === 'number' && codexChatUsage.cached_input_tokens >= 0
    ? Math.floor(codexChatUsage.cached_input_tokens)
    : null
  const observedContextLimitTokens = typeof codexChatUsage?.context_limit_tokens === 'number' && codexChatUsage.context_limit_tokens > 0
    ? Math.floor(codexChatUsage.context_limit_tokens)
    : null
  const promptSegmentChars = codexChatUsage?.prompt_segment_chars && typeof codexChatUsage.prompt_segment_chars === 'object'
    ? codexChatUsage.prompt_segment_chars
    : null
  const promptSegmentMap = React.useMemo(() => {
    const out = new Map<string, number>()
    if (!promptSegmentChars) return out
    for (const [rawKey, rawValue] of Object.entries(promptSegmentChars)) {
      const key = String(rawKey || '').trim().toLowerCase()
      const value = Number(rawValue)
      if (!key || !Number.isFinite(value) || value < 0) continue
      out.set(key, Math.floor(value))
    }
    return out
  }, [promptSegmentChars])
  const observedSegmentChars = React.useCallback(
    (key: string): number | null => {
      const normalizedKey = String(key || '').trim().toLowerCase()
      if (!normalizedKey) return null
      const value = promptSegmentMap.get(normalizedKey)
      return Number.isFinite(value) ? Number(value) : null
    },
    [promptSegmentMap]
  )
  const graphEvidenceJsonChat = chatEvidenceItems.length > 0 ? JSON.stringify(chatEvidenceItems) : ''
  const graphEvidenceJsonNonChat = nonChatEvidenceItems.length > 0 ? JSON.stringify(nonChatEvidenceItems) : ''
  const chatHistoryText = React.useMemo(() => {
    if (activePromptMode === 'resume') return ''
    return buildConversationHistoryText({
      projectId,
      activeChatProjectId,
      activeChatTurns: Array.isArray(activeChatTurns) ? activeChatTurns : [],
    })
  }, [activeChatProjectId, activeChatTurns, activePromptMode, projectId])

  const snapshot = React.useMemo(() => {
    const runtimeMetadataText = [
      `Project Name: ${String(projectName || '').trim()}`,
      `Retrieval mode: ${String(contextPack?.mode || '').trim()}`,
      `Focus entity type: ${String(contextPack?.focus?.entity_type || '').trim()}`,
      `Focus entity id: ${String(contextPack?.focus?.entity_id || '').trim()}`,
      `Chat indexing mode: ${normalizedChatIndexMode}`,
      `Chat attachment ingestion mode: ${normalizedChatAttachmentMode}`,
    ].join('\n')

    const sourceBase: Array<{
      key: SnapshotSourceKey
      group: SnapshotSourceGroup
      label: string
      color: string
      chars: number
      lines: number
    }> = [
      {
        key: 'soul',
        group: 'project',
        label: 'Project description (Soul.md)',
        color: '#0f766e',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('soul') ?? projectDescription.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(projectDescription),
      },
      {
        key: 'rules',
        group: 'project',
        label: 'Project rules (ProjectRules.md)',
        color: '#ea580c',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('project_rules') ?? rulesMarkdown.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(rulesMarkdown),
      },
      {
        key: 'skills',
        group: 'project',
        label: 'Project skills (ProjectSkills.md)',
        color: '#7c3aed',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('project_skills') ?? skillsMarkdown.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(skillsMarkdown),
      },
      {
        key: 'plugin_policy',
        group: 'project',
        label: 'Plugin policy (PluginPolicy.json)',
        color: '#8b5e34',
        chars: observedSegmentChars('plugin_policy') ?? pluginPolicyContext.pluginPolicy.length,
        lines: countLines(pluginPolicyContext.pluginPolicy),
      },
      {
        key: 'plugin_required_checks',
        group: 'project',
        label: 'Plugin required checks (PluginRequiredChecks.md)',
        color: '#a16207',
        chars:
          observedSegmentChars('plugin_required_checks') ??
          pluginPolicyContext.pluginRequiredChecks.length,
        lines: countLines(pluginPolicyContext.pluginRequiredChecks),
      },
      {
        key: 'knowledge_graph_context',
        group: 'knowledge_graph',
        label: 'Knowledge graph context (GraphContext.md)',
        color: '#2563eb',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('graph_context') ?? graphContextMarkdown.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(graphContextMarkdown),
      },
      {
        key: 'knowledge_graph_summary',
        group: 'knowledge_graph',
        label: 'Knowledge graph summary (GraphSummary.md)',
        color: '#14b8a6',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('graph_summary') ?? graphSummaryMarkdown.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(graphSummaryMarkdown),
      },
      {
        key: 'knowledge_graph_fresh_snapshot',
        group: 'knowledge_graph',
        label: 'Fresh cross-session memory snapshot',
        color: '#2563eb',
        chars: activePromptMode === 'resume' ? (observedSegmentChars('fresh_memory_snapshot') ?? resumeFreshMemorySnapshot.length) : 0,
        lines: activePromptMode === 'resume' ? countLines(resumeFreshMemorySnapshot) : 0,
      },
      {
        key: 'knowledge_graph_evidence_non_chat',
        group: 'knowledge_graph',
        label: 'Indexed project corpus (non-chat evidence)',
        color: '#0ea5e9',
        chars: activePromptMode === 'resume' ? 0 : (observedSegmentChars('graph_evidence') ?? graphEvidenceJsonNonChat.length),
        lines: activePromptMode === 'resume' ? 0 : countLines(graphEvidenceJsonNonChat),
      },
      {
        key: 'knowledge_graph_evidence_chat',
        group: 'knowledge_graph',
        label: 'Indexed project chat corpus',
        color: '#22c55e',
        chars: activePromptMode === 'resume' ? 0 : graphEvidenceJsonChat.length,
        lines: activePromptMode === 'resume' ? 0 : countLines(graphEvidenceJsonChat),
      },
      {
        key: 'system_scaffold',
        group: 'hardcoded',
        label: `System prompt scaffold (${activePromptLabel.toLowerCase()})`,
        color: '#334155',
        chars: activePromptScaffoldTemplate.length,
        lines: countLines(activePromptScaffoldTemplate),
      },
      {
        key: 'system_guidance',
        group: 'hardcoded',
        label: `Guidance and policy block (${activePromptLabel.toLowerCase()})`,
        color: '#0f172a',
        chars: activePromptGuidanceTemplate.length,
        lines: countLines(activePromptGuidanceTemplate),
      },
      {
        key: 'chat_history',
        group: 'runtime',
        label: 'Conversation history (active session, optional)',
        color: '#16a34a',
        chars: chatHistoryText.length,
        lines: countLines(chatHistoryText),
      },
      {
        key: 'runtime_metadata',
        group: 'runtime',
        label: 'Runtime metadata envelope',
        color: '#64748b',
        chars: runtimeMetadataText.length,
        lines: countLines(runtimeMetadataText),
      },
    ]

    const totalChars = sourceBase.reduce((sum, section) => sum + section.chars, 0)
    const totalTokens = estimateTokenCount(totalChars)
    const normalizedContextLimitTokens = Math.max(0, Math.floor(Number(observedContextLimitTokens ?? contextLimitTokens ?? 0)))
    const contextWindowTokens = Math.max(totalTokens, normalizedContextLimitTokens, observedInputTokens ?? 0)
    const usedTileCount =
      contextWindowTokens > 0 && totalTokens > 0
        ? Math.max(1, Math.min(CONTEXT_OCCUPANCY_TILE_COUNT, Math.round((totalTokens / contextWindowTokens) * CONTEXT_OCCUPANCY_TILE_COUNT)))
        : 0
    const emptyTileCount = Math.max(0, CONTEXT_OCCUPANCY_TILE_COUNT - usedTileCount)
    const emptyWindowPercent = contextWindowTokens > 0 ? (emptyTileCount / CONTEXT_OCCUPANCY_TILE_COUNT) * 100 : 0
    const emptyTokens = Math.max(0, contextWindowTokens - totalTokens)
    const tokensPerTile = contextWindowTokens > 0 ? contextWindowTokens / CONTEXT_OCCUPANCY_TILE_COUNT : 0

    const sources: SnapshotSourceUsage[] = sourceBase.map((section) => {
      const sectionTokens = estimateTokenCount(section.chars)
      return {
        ...section,
        tokens: sectionTokens,
        percent: totalChars > 0 ? (section.chars / totalChars) * 100 : 0,
        windowPercent: contextWindowTokens > 0 ? (sectionTokens / contextWindowTokens) * 100 : 0,
      }
    })
    const visibleSources = sources.filter((section) => {
      if (section.chars > 0) return true
      if (section.key === 'chat_history' && normalizedChatIndexMode !== 'OFF') return true
      if (section.key === 'knowledge_graph_evidence_chat' && normalizedChatIndexMode !== 'OFF') return true
      return false
    })
    const sourceTiles = buildSnapshotCubeTiles(
      visibleSources.map((section) => ({
        key: section.key,
        label: section.label,
        color: section.color,
        value: section.chars,
      })),
      usedTileCount
    )
    const sourceTilesWithEmpty: SnapshotCubeTile[] = [
      ...sourceTiles,
      ...Array.from({ length: emptyTileCount }, (_, idx) => ({
        key: `empty-${idx}`,
        label: 'Empty context window',
        color: 'var(--surface-alt)',
      })),
    ]

    const distinctEvidenceEntities = new Set(
      evidenceItems.map((item) => `${normalizeEntityTypeLabel(item.entity_type)}:${String(item.entity_id || '').trim()}`)
    ).size
    const contextCoveragePct = indexedEntityCount > 0 ? Math.min(100, Math.round((distinctEvidenceEntities / indexedEntityCount) * 100)) : 0
    const averageEvidenceScore =
      evidenceItems.length > 0
        ? evidenceItems.reduce((sum, item) => sum + Number(item.final_score || 0), 0) / evidenceItems.length
        : 0
    const chatEvidenceCount = chatEvidenceItems.length
    const chatEvidenceEntityCount = new Set(
      chatEvidenceItems.map((item) => `${normalizeEntityTypeLabel(item.entity_type)}:${String(item.entity_id || '').trim()}`)
    ).size
    const chatEvidenceSharePct = evidenceItems.length > 0 ? (chatEvidenceCount / evidenceItems.length) * 100 : 0

    const hardcodedChars =
      sourceBase
        .filter((section) => section.group === 'hardcoded')
        .reduce((sum, section) => sum + section.chars, 0)
    const fullHardcodedChars = FULL_PROMPT_SCAFFOLD_TEMPLATE.length + FULL_PROMPT_GUIDANCE_TEMPLATE.length
    const coldStartChars = Math.max(0, totalChars - hardcodedChars + fullHardcodedChars)
    const coldStartTokens = estimateTokenCount(coldStartChars)
    const coldStartWindowUsedPercent = contextWindowTokens > 0 ? (coldStartTokens / contextWindowTokens) * 100 : 0
    const observedWindowUsedPercent = contextWindowTokens > 0 && observedInputTokens !== null
      ? (observedInputTokens / contextWindowTokens) * 100
      : null

    return {
      totalChars,
      totalLines: sources.reduce((sum, section) => sum + section.lines, 0),
      approxTokens: estimateTokenCount(totalChars),
      coldStartApproxTokens: coldStartTokens,
      promptModeLabel: activePromptLabel,
      hardcodedTokens: estimateTokenCount(hardcodedChars),
      chatHistoryTokens: estimateTokenCount(chatHistoryText.length),
      indexedChatTokens: estimateTokenCount(graphEvidenceJsonChat.length),
      contextWindowTokens,
      windowUsedPercent: contextWindowTokens > 0 ? (totalTokens / contextWindowTokens) * 100 : 0,
      coldStartWindowUsedPercent,
      observedWindowUsedPercent,
      tileCount: CONTEXT_OCCUPANCY_TILE_COUNT,
      tokensPerTile,
      emptyTokens,
      emptyWindowPercent,
      observedInputTokens,
      observedCachedInputTokens,
      observedOutputTokens,
      sources: visibleSources,
      sourceTiles: sourceTilesWithEmpty,
      indexedEntityCount,
      commentActivityCount: Number(counts.comments || 0),
      evidenceCount: evidenceItems.length,
      distinctEvidenceEntities,
      contextCoveragePct,
      averageEvidenceScore,
      chatEvidenceCount,
      chatEvidenceEntityCount,
      chatEvidenceSharePct,
    }
  }, [
    activePromptGuidanceTemplate,
    activePromptLabel,
    activePromptMode,
    activePromptScaffoldTemplate,
    chatHistoryText,
    contextLimitTokens,
    contextPack?.focus?.entity_id,
    contextPack?.focus?.entity_type,
    contextPack?.mode,
    counts.comments,
    evidenceItems,
    pluginPolicyContext.pluginPolicy,
    pluginPolicyContext.pluginRequiredChecks,
    graphContextMarkdown,
    graphEvidenceJsonChat,
    graphEvidenceJsonNonChat,
    graphSummaryMarkdown,
    observedSegmentChars,
    projectDescription,
    normalizedChatAttachmentMode,
    normalizedChatIndexMode,
    observedCachedInputTokens,
    observedContextLimitTokens,
    observedInputTokens,
    observedOutputTokens,
    indexedEntityCount,
    projectName,
    resumeFreshMemorySnapshot,
    rulesMarkdown,
    skillsMarkdown,
  ])

  const [snapshotTab, setSnapshotTab] = React.useState<'overview' | 'composition'>('overview')
  const [selectedSourceKey, setSelectedSourceKey] = React.useState<string | null>(null)

  const sourceGroups = React.useMemo(() => {
    const groups: SnapshotSourceGroup[] = ['project', 'knowledge_graph', 'hardcoded', 'runtime']
    return groups
      .map((group) => {
        const items = snapshot.sources.filter((source) => source.group === group)
        const chars = items.reduce((sum, item) => sum + item.chars, 0)
        const tokens = items.reduce((sum, item) => sum + item.tokens, 0)
        const windowPercent = items.reduce((sum, item) => sum + item.windowPercent, 0)
        const usedPercent = items.reduce((sum, item) => sum + item.percent, 0)
        return {
          group,
          label: sourceGroupLabel(group),
          items,
          chars,
          tokens,
          windowPercent,
          usedPercent,
        }
      })
      .filter((group) => group.items.length > 0)
  }, [snapshot.sources])

  const compositionSegments = React.useMemo<SnapshotCompositionSegment[]>(() => {
    const activeSegments: SnapshotCompositionSegment[] = snapshot.sources.map((source) => ({
      key: source.key,
      label: source.label,
      color: source.color,
      tokens: source.tokens,
      windowPercent: source.windowPercent,
      usedPercent: source.percent,
      groupLabel: sourceGroupLabel(source.group),
    }))
    if (snapshot.emptyTokens > 0) {
      activeSegments.push({
        key: 'empty-window',
        label: 'Empty context window',
        color: 'var(--surface-alt)',
        tokens: snapshot.emptyTokens,
        windowPercent: snapshot.emptyWindowPercent,
        usedPercent: 0,
        groupLabel: 'Unused capacity',
      })
    }
    return activeSegments.filter((segment) => segment.windowPercent > 0)
  }, [snapshot.emptyTokens, snapshot.emptyWindowPercent, snapshot.sources])

  React.useEffect(() => {
    if (!selectedSourceKey) return
    const exists = compositionSegments.some((segment) => segment.key === selectedSourceKey)
    if (!exists) setSelectedSourceKey(null)
  }, [compositionSegments, selectedSourceKey])

  return (
    <Tooltip.Provider delayDuration={120}>
      <div className="graph-context-snapshot context-snapshot-surface" style={{ marginTop: 10, marginBottom: 12 }}>
        <div className="row wrap graph-context-snapshot-head">
          <div>
            <div className="meta">Project context snapshot</div>
            <div className="graph-context-snapshot-title">
              Context budget across project resources, indexed graph evidence, hardcoded guidance, and runtime session input.
            </div>
          </div>
          <div className="graph-context-snapshot-total">
            ~{snapshot.approxTokens.toLocaleString()} / {snapshot.contextWindowTokens.toLocaleString()} tokens
            {snapshot.observedInputTokens !== null ? (
              <div className="meta">{`Observed input: ${snapshot.observedInputTokens.toLocaleString()} tokens`}</div>
            ) : null}
          </div>
        </div>

        <div className="context-snapshot-policy-row">
          <span className="status-chip">{`Prompt mode: ${snapshot.promptModeLabel}`}</span>
          <span className="status-chip">{`Chat indexing: ${chatIndexModeLabel(normalizedChatIndexMode)}`}</span>
          <span className="status-chip">{`Attachment ingestion: ${chatAttachmentModeLabel(normalizedChatAttachmentMode)}`}</span>
          <span className="status-chip">{`Indexed coverage: ${snapshot.contextCoveragePct}%`}</span>
        </div>

        <div className="context-snapshot-capacity-track" role="img" aria-label="Context capacity usage">
          <div
            className="context-snapshot-capacity-fill"
            style={{ width: `${Math.max(0, Math.min(100, snapshot.windowUsedPercent))}%` }}
          />
        </div>
        <div className="meta">
          Used window: {formatPercent(snapshot.windowUsedPercent)} · Cold-start equivalent: {formatPercent(snapshot.coldStartWindowUsedPercent)} · Empty capacity: {formatPercent(snapshot.emptyWindowPercent)}
          {snapshot.observedWindowUsedPercent !== null ? ` · Observed this turn: ${formatPercent(snapshot.observedWindowUsedPercent)}` : ''}
        </div>

        <Tabs.Root
          className="context-snapshot-tabs"
          value={snapshotTab}
          onValueChange={(next) => {
            if (next === 'overview' || next === 'composition') {
              setSnapshotTab(next)
            }
          }}
        >
          <Tabs.List className="context-snapshot-tabs-list" aria-label="Context snapshot views">
            <Tabs.Trigger className="context-snapshot-tab-trigger" value="overview">Overview</Tabs.Trigger>
            <Tabs.Trigger className="context-snapshot-tab-trigger" value="composition">Composition + Sources</Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content value="overview" className="context-snapshot-tab-content">
            <div className="graph-context-metrics context-snapshot-metrics">
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M4 4h16v16H4zM8 8h8v8H8z" />
                  <span className="meta">Indexed entities</span>
                </div>
                <strong>{snapshot.indexedEntityCount.toLocaleString()}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M4 6h16v10H7l-3 3V6z" />
                  <span className="meta">Comment activity</span>
                </div>
                <strong>{snapshot.commentActivityCount.toLocaleString()}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M6 2h9l3 3v17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm8 1v3h3" />
                  <span className="meta">Rules</span>
                </div>
                <strong>{projectRules.length}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M4 6h16M4 12h16M4 18h16" />
                  <span className="meta">Skills</span>
                </div>
                <strong>{projectSkills.length}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                  <span className="meta">Evidence items</span>
                </div>
                <strong>{snapshot.evidenceCount}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M5 12h14M12 5v14" />
                  <span className="meta">Effective estimate</span>
                </div>
                <strong>{`~${snapshot.approxTokens.toLocaleString()}`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M3 12h18M12 3v18" />
                  <span className="meta">Cold-start estimate</span>
                </div>
                <strong>{`~${snapshot.coldStartApproxTokens.toLocaleString()}`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M3 5h18v14H3zM7 9h10M7 13h6" />
                  <span className="meta">Observed input</span>
                </div>
                <strong>
                  {snapshot.observedInputTokens !== null ? snapshot.observedInputTokens.toLocaleString() : 'n/a'}
                </strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M4 12h16M12 4v16" />
                  <span className="meta">Hardcoded block</span>
                </div>
                <strong>{`~${snapshot.hardcodedTokens.toLocaleString()}`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M4 6h16v10H7l-3 3V6z" />
                  <span className="meta">Live chat history</span>
                </div>
                <strong>{`~${snapshot.chatHistoryTokens.toLocaleString()}`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M12 2v20M2 12h20" />
                  <span className="meta">Indexed chat corpus</span>
                </div>
                <strong>{`~${snapshot.indexedChatTokens.toLocaleString()}`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M7 7h10v10H7zM4 4h16v16H4z" />
                  <span className="meta">Chat-derived evidence</span>
                </div>
                <strong>{`${snapshot.chatEvidenceCount} (${snapshot.chatEvidenceSharePct.toFixed(1)}%)`}</strong>
              </div>
              <div className="graph-context-metric context-snapshot-metric">
                <div className="context-snapshot-metric-head">
                  <Icon path="M3 17l6-6 4 4 8-8" />
                  <span className="meta">Avg evidence score</span>
                </div>
                <strong>{snapshot.averageEvidenceScore.toFixed(3)}</strong>
              </div>
            </div>
            <div className="context-snapshot-footnotes">
              <div className="meta">
                Uses the active prompt profile for this session ({snapshot.promptModeLabel}). Conversation history is only included for full-profile turns.
              </div>
              <div className="meta">
                Cold-start estimate keeps the same project/runtime payload but replaces hardcoded prompt blocks with the full profile.
              </div>
              <div className="meta">
                Indexed chat corpus remains available when active session is empty, as long as project chat indexing policy is enabled.
              </div>
              <div className="meta">
                Indexed entities: {snapshot.indexedEntityCount} · Distinct evidence entities: {snapshot.distinctEvidenceEntities} · Chat evidence entities: {snapshot.chatEvidenceEntityCount} · Map resolution: {snapshot.tileCount.toLocaleString()} cells (~{Math.max(1, Math.round(snapshot.tokensPerTile || 0)).toLocaleString()} tokens/cell)
              </div>
            </div>
          </Tabs.Content>

          <Tabs.Content value="composition" className="context-snapshot-tab-content">
            <div className="context-snapshot-band-card">
              <div className="meta">Context source occupancy band</div>
              {compositionSegments.length === 0 ? (
                <div className="meta" style={{ marginTop: 8 }}>No context payload available yet.</div>
              ) : (
                <div className="context-snapshot-band" role="img" aria-label="Context occupancy by source">
                  {compositionSegments.map((segment) => {
                    const isSelected = selectedSourceKey === segment.key
                    return (
                      <Tooltip.Root key={`segment-${segment.key}`}>
                        <Tooltip.Trigger asChild>
                          <button
                            type="button"
                            className={`context-snapshot-band-segment ${isSelected ? 'active' : ''}`.trim()}
                            style={{
                              flexGrow: Math.max(segment.windowPercent, 0.45),
                              backgroundColor: segment.color,
                            }}
                            aria-label={`${segment.label}: ${formatPercent(segment.windowPercent)} of context window`}
                            onClick={() => {
                              setSelectedSourceKey((current) => (current === segment.key ? null : segment.key))
                            }}
                          />
                        </Tooltip.Trigger>
                        <Tooltip.Portal>
                          <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
                            <strong>{segment.label}</strong>
                            <div className="meta">{segment.groupLabel}</div>
                            <div className="meta">
                              {formatPercent(segment.windowPercent)} window · {segment.tokens.toLocaleString()} tokens
                            </div>
                            {segment.key !== 'empty-window' ? (
                              <div className="meta">{formatPercent(segment.usedPercent)} of used payload</div>
                            ) : null}
                            <Tooltip.Arrow className="header-tooltip-arrow" />
                          </Tooltip.Content>
                        </Tooltip.Portal>
                      </Tooltip.Root>
                    )
                  })}
                </div>
              )}
              <div className="meta">
                Click a segment to focus matching cells and source rows below.
              </div>
            </div>

            <div className="graph-context-cube-block context-snapshot-cube-block">
              <div className="meta">Context source occupancy map</div>
              {snapshot.sourceTiles.length === 0 ? (
                <div className="meta" style={{ marginTop: 6 }}>Context is empty for this project.</div>
              ) : (
                <div className="graph-context-cube-grid graph-context-cube-grid-dense" role="img" aria-label="Project context source occupancy map">
                  {snapshot.sourceTiles.map((tile, idx) => {
                    const tileSourceKey = tile.key.startsWith('empty-')
                      ? 'empty-window'
                      : snapshot.sources.find((source) => tile.key.startsWith(`${source.key}-`))?.key ?? null
                    const isSelected = selectedSourceKey ? selectedSourceKey === tileSourceKey : false
                    return (
                      <span
                        key={`source-cube-${idx}-${tile.key}`}
                        className={`graph-context-cube context-snapshot-cube ${isSelected ? 'selected' : ''}`.trim()}
                        style={{ backgroundColor: tile.color }}
                        title={tile.label}
                      />
                    )
                  })}
                </div>
              )}
              <div className="meta">
                Used window: {formatPercent(snapshot.windowUsedPercent)} (~{snapshot.approxTokens.toLocaleString()} tokens) · Cold-start equivalent: {formatPercent(snapshot.coldStartWindowUsedPercent)} (~{snapshot.coldStartApproxTokens.toLocaleString()} tokens)
              </div>
            </div>

            <div className="context-snapshot-segment-grid">
              {compositionSegments.map((segment) => (
                <Tooltip.Root key={`segment-chip-${segment.key}`}>
                  <Tooltip.Trigger asChild>
                    <button
                      type="button"
                      className={`context-snapshot-segment-chip ${selectedSourceKey === segment.key ? 'active' : ''}`.trim()}
                      onClick={() => setSelectedSourceKey((current) => (current === segment.key ? null : segment.key))}
                    >
                      <span className="context-snapshot-segment-swatch" style={{ backgroundColor: segment.color }} />
                      <span className="context-snapshot-segment-label">{segment.label}</span>
                      <span className="meta">{formatPercent(segment.windowPercent)}</span>
                    </button>
                  </Tooltip.Trigger>
                  <Tooltip.Portal>
                    <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
                      <strong>{segment.label}</strong>
                      <div className="meta">{segment.groupLabel}</div>
                      <div className="meta">
                        {formatPercent(segment.windowPercent)} window · {segment.tokens.toLocaleString()} tokens
                      </div>
                      {segment.key !== 'empty-window' ? (
                        <div className="meta">{formatPercent(segment.usedPercent)} of used payload</div>
                      ) : null}
                      <Tooltip.Arrow className="header-tooltip-arrow" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                </Tooltip.Root>
              ))}
            </div>
            <div className="meta">Source breakdown</div>
            <Accordion.Root
              className="context-snapshot-source-groups"
              type="multiple"
              defaultValue={sourceGroups.map((group) => group.group)}
            >
              {sourceGroups.map((group) => (
                <Accordion.Item
                  key={`source-group-${group.group}`}
                  value={group.group}
                  className="context-snapshot-source-group"
                >
                  <Accordion.Header>
                    <Accordion.Trigger className="context-snapshot-source-group-trigger">
                      <span className="context-snapshot-source-group-head">
                        <span className="context-snapshot-source-group-title">{group.label}</span>
                        <span className="meta">
                          {formatPercent(group.windowPercent)} window · {formatPercent(group.usedPercent)} used · {group.tokens.toLocaleString()} tokens
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
                        <Tooltip.Root key={`source-row-${source.key}`}>
                          <Tooltip.Trigger asChild>
                            <button
                              type="button"
                              className={`context-snapshot-source-row ${selectedSourceKey === source.key ? 'active' : ''}`.trim()}
                              onClick={() => setSelectedSourceKey((current) => (current === source.key ? null : source.key))}
                            >
                              <span className="graph-context-legend-swatch" style={{ backgroundColor: source.color }} />
                              <span className="context-snapshot-source-row-main">
                                <span className="graph-context-legend-label">{source.label}</span>
                                <span className="meta">
                                  {source.tokens.toLocaleString()} tokens · {source.chars.toLocaleString()} chars
                                  {source.lines > 0 ? ` · ${source.lines} lines` : ''}
                                </span>
                                <span className="context-snapshot-source-row-track">
                                  <span
                                    className="context-snapshot-source-row-fill"
                                    style={{ width: `${Math.max(0, Math.min(100, source.windowPercent))}%`, backgroundColor: source.color }}
                                  />
                                </span>
                              </span>
                              <span className="meta context-snapshot-source-row-pct">
                                {formatPercent(source.windowPercent)}
                              </span>
                            </button>
                          </Tooltip.Trigger>
                          <Tooltip.Portal>
                            <Tooltip.Content className="header-tooltip-content" side="top" sideOffset={6}>
                              <strong>{source.label}</strong>
                              <div className="meta">{sourceGroupLabel(source.group)}</div>
                              <div className="meta">
                                {formatPercent(source.windowPercent)} window · {formatPercent(source.percent)} used
                              </div>
                              <div className="meta">
                                {source.tokens.toLocaleString()} tokens · {source.chars.toLocaleString()} chars
                                {source.lines > 0 ? ` · ${source.lines} lines` : ''}
                              </div>
                              <Tooltip.Arrow className="header-tooltip-arrow" />
                            </Tooltip.Content>
                          </Tooltip.Portal>
                        </Tooltip.Root>
                      ))}
                    </div>
                  </Accordion.Content>
                </Accordion.Item>
              ))}
            </Accordion.Root>
            {snapshot.emptyTokens > 0 ? (
              <div className="meta" style={{ marginTop: 8 }}>
                Empty context window: {formatPercent(snapshot.emptyWindowPercent)} · {snapshot.emptyTokens.toLocaleString()} tokens
              </div>
            ) : null}
          </Tabs.Content>
        </Tabs.Root>
      </div>
    </Tooltip.Provider>
  )
}
