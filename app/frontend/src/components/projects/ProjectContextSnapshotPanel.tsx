import React from 'react'
import type { GraphContextPack, GraphProjectOverview, ProjectRule, ProjectSkill } from '../../types'

type SnapshotSourceKey =
  | 'soul'
  | 'rules'
  | 'skills'
  | 'knowledge_graph_context'
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
  lines: number
  percent: number
  windowPercent: number
}

type SnapshotCubeTile = {
  key: string
  label: string
  color: string
}

type ChatTurnLike = {
  role?: unknown
  content?: unknown
}

const CHAT_HISTORY_WINDOW_SIZE = 12
const CONTEXT_OCCUPANCY_TILE_COUNT = 480

const PROMPT_SCAFFOLD_TEMPLATE = [
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
  'Project Name: {project_name}',
  'Instruction: {instruction}',
  '',
  'Context Pack:',
  'File: Soul.md (source: project.description)',
  'File: ProjectRules.md (source: project_rules)',
  'File: ProjectSkills.md (source: project_skills)',
  'File: GraphContext.md (source: knowledge_graph)',
  'File: GraphEvidence.json (source: knowledge_graph.evidence)',
  'File: GraphSummary.md (source: knowledge_graph.summary)',
  '',
  'Guidance:',
  '- This is a general chat request (not bound to a single task). Use workspace/project context and MCP tools as needed.',
  '- Mutating tools are allowed for this request.',
  '- Apply requested changes via MCP tools directly when possible.',
  '- Respond directly to the user with clear, actionable text.',
].join('\n')

const PROMPT_GUIDANCE_TEMPLATE = [
  '- Treat Soul.md, ProjectRules.md, ProjectSkills.md, GraphContext.md, GraphEvidence.json, and GraphSummary.md as durable project-level context.',
  '- ProjectRules.md defines how you should behave within this project.',
  '- ProjectSkills.md captures reusable skills configured for this project.',
  '- Apply ProjectSkills with mode=enforced before advisory skills.',
  '- If no enforced skill applies, use advisory skills as guidance alongside project rules.',
  '- GraphContext.md captures resource relations and should guide dependency-aware decisions.',
  '- GraphEvidence.json is the canonical evidence source for grounded claims.',
  '- GraphSummary.md can be used as a concise overview, but validate against GraphEvidence.json before acting.',
  '- Treat claims without an evidence_id as low confidence.',
  '- If project context conflicts with the latest explicit user instruction, follow the latest explicit user instruction.',
  '- You may call task-management MCP tools relevant to the request.',
  '- For profile preference changes (theme/timezone/notifications), use MCP tools directly.',
  '- For chat theme changes, use set_user_theme(theme=\'light\'|\'dark\').',
  '- set_user_theme targets the current app user profile.',
  '- Use toggle_my_theme only if the user explicitly asks to toggle (not set) theme.',
  '- Report the final theme based on set_user_theme tool output.',
  '- Use graph_* MCP tools when you need relation-aware lookup across project resources.',
  '- Prefer bulk tools when operating on many tasks (avoid per-task loops when possible).',
  '- Prefer archive_all_notes/archive_all_tasks for \'archive everything\' requests.',
  '- For mutating MCP tool calls, always provide command_id.',
  '- If retrying the same mutation, reuse the exact same command_id.',
  '- If the user asks for a plan/spec/design doc, prefer creating a Note (Markdown) via MCP tools so it is visible in the UI.',
  '- When creating a plan note: use a clear title starting with \'Plan:\' and include actionable steps.',
  '- If you are in task context, link the note to the task by setting task_id when creating the note.',
  '- For every request to create a new project, always use a strict interactive setup protocol.',
  '- Strict protocol is mandatory even if the user asks for immediate creation.',
  '- Ask one clarifying question at a time and track missing fields until they are resolved.',
  '- Discovery fields before creation: project goal/domain, setup strategy (template or manual), project name, and defaults/overrides (statuses, members, embeddings, context top K, template parameters when applicable).',
  '- Template strategy sequence: list_project_templates -> get_project_template -> collect template parameters -> preview_project_from_template -> explicit user confirmation -> create_project_from_template.',
  '- Manual strategy sequence: collect required fields -> explicit user confirmation -> create_project.',
  '- Never call create_project or create_project_from_template until the user explicitly confirms creation in the current conversation (for example: \'confirm create\').',
  '- After successful creation, ask whether seeded tasks/specifications/rules should be adjusted for this specific project; if yes, apply the requested updates via MCP tools.',
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

function estimateTokenCount(charCount: number): number {
  if (!Number.isFinite(charCount) || charCount <= 0) return 0
  return Math.max(1, Math.round(charCount / 4))
}

function countLines(value: string): number {
  if (!value.trim()) return 0
  return value.split(/\r?\n/).length
}

function normalizeEntityTypeLabel(entityType: string | null | undefined): string {
  const normalized = String(entityType || '').trim()
  if (!normalized) return 'Entity'
  return normalized
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

function sourceGroupLabel(group: SnapshotSourceGroup): string {
  if (group === 'project') return 'Project-managed'
  if (group === 'knowledge_graph') return 'Knowledge graph'
  if (group === 'hardcoded') return 'Prompt code'
  return 'Runtime session'
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
    const body = String(item.body || '').trim()
    if (!title && !body) continue
    const label = title || 'Untitled rule'
    if (body) lines.push(`- ${label}: ${body}`)
    else lines.push(`- ${label}`)
  }
  if (lines.length === 0) return '_(no project rules)_'
  return lines.join('\n')
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
  const evidenceItems = contextPack?.evidence ?? []
  const normalizedChatIndexMode = normalizeChatIndexMode(projectChatIndexMode)
  const normalizedChatAttachmentMode = normalizeChatAttachmentIngestionMode(projectChatAttachmentIngestionMode)
  const rulesMarkdown = React.useMemo(() => renderRulesMarkdown(projectRules), [projectRules])
  const skillsMarkdown = React.useMemo(() => renderSkillsMarkdown(projectSkills), [projectSkills])
  const graphSummaryMarkdown = React.useMemo(() => renderGraphSummaryMarkdown(contextPack?.summary), [contextPack?.summary])
  const graphContextMarkdown = String(contextPack?.markdown || '')
  const chatEvidenceItems = React.useMemo(() => evidenceItems.filter((item) => isChatEntityType(item.entity_type)), [evidenceItems])
  const nonChatEvidenceItems = React.useMemo(
    () => evidenceItems.filter((item) => !isChatEntityType(item.entity_type)),
    [evidenceItems]
  )
  const graphEvidenceJsonChat = chatEvidenceItems.length > 0 ? JSON.stringify(chatEvidenceItems) : ''
  const graphEvidenceJsonNonChat = nonChatEvidenceItems.length > 0 ? JSON.stringify(nonChatEvidenceItems) : ''
  const chatHistoryText = React.useMemo(
    () =>
      buildConversationHistoryText({
        projectId,
        activeChatProjectId,
        activeChatTurns: Array.isArray(activeChatTurns) ? activeChatTurns : [],
      }),
    [activeChatProjectId, activeChatTurns, projectId]
  )

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
        chars: projectDescription.length,
        lines: countLines(projectDescription),
      },
      {
        key: 'rules',
        group: 'project',
        label: 'Project rules (ProjectRules.md)',
        color: '#ea580c',
        chars: rulesMarkdown.length,
        lines: countLines(rulesMarkdown),
      },
      {
        key: 'skills',
        group: 'project',
        label: 'Project skills (ProjectSkills.md)',
        color: '#7c3aed',
        chars: skillsMarkdown.length,
        lines: countLines(skillsMarkdown),
      },
      {
        key: 'knowledge_graph_context',
        group: 'knowledge_graph',
        label: 'Knowledge graph context + summary',
        color: '#2563eb',
        chars: graphContextMarkdown.length + graphSummaryMarkdown.length,
        lines: countLines(graphContextMarkdown) + countLines(graphSummaryMarkdown),
      },
      {
        key: 'knowledge_graph_evidence_non_chat',
        group: 'knowledge_graph',
        label: 'Indexed project corpus (non-chat evidence)',
        color: '#0ea5e9',
        chars: graphEvidenceJsonNonChat.length,
        lines: countLines(graphEvidenceJsonNonChat),
      },
      {
        key: 'knowledge_graph_evidence_chat',
        group: 'knowledge_graph',
        label: 'Indexed project chat corpus',
        color: '#22c55e',
        chars: graphEvidenceJsonChat.length,
        lines: countLines(graphEvidenceJsonChat),
      },
      {
        key: 'system_scaffold',
        group: 'hardcoded',
        label: 'System prompt scaffold',
        color: '#334155',
        chars: PROMPT_SCAFFOLD_TEMPLATE.length,
        lines: countLines(PROMPT_SCAFFOLD_TEMPLATE),
      },
      {
        key: 'system_guidance',
        group: 'hardcoded',
        label: 'Guidance and policy block',
        color: '#0f172a',
        chars: PROMPT_GUIDANCE_TEMPLATE.length,
        lines: countLines(PROMPT_GUIDANCE_TEMPLATE),
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
    const normalizedContextLimitTokens = Math.max(0, Math.floor(Number(contextLimitTokens || 0)))
    const contextWindowTokens = Math.max(totalTokens, normalizedContextLimitTokens)
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

    const scopeTotal =
      Number(counts.tasks || 0) +
      Number(counts.notes || 0) +
      Number(counts.specifications || 0) +
      Number(counts.project_rules || 0) +
      Number(counts.comments || 0)
    const distinctEvidenceEntities = new Set(
      evidenceItems.map((item) => `${normalizeEntityTypeLabel(item.entity_type)}:${String(item.entity_id || '').trim()}`)
    ).size
    const contextCoveragePct = scopeTotal > 0 ? Math.min(100, Math.round((distinctEvidenceEntities / scopeTotal) * 100)) : 0
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

    return {
      totalChars,
      totalLines: sources.reduce((sum, section) => sum + section.lines, 0),
      approxTokens: estimateTokenCount(totalChars),
      hardcodedTokens: estimateTokenCount(hardcodedChars),
      chatHistoryTokens: estimateTokenCount(chatHistoryText.length),
      indexedChatTokens: estimateTokenCount(graphEvidenceJsonChat.length),
      contextWindowTokens,
      tileCount: CONTEXT_OCCUPANCY_TILE_COUNT,
      tokensPerTile,
      emptyTokens,
      emptyWindowPercent,
      sources: visibleSources,
      sourceTiles: sourceTilesWithEmpty,
      evidenceCount: evidenceItems.length,
      distinctEvidenceEntities,
      contextCoveragePct,
      averageEvidenceScore,
      chatEvidenceCount,
      chatEvidenceEntityCount,
      chatEvidenceSharePct,
    }
  }, [
    chatHistoryText,
    contextLimitTokens,
    contextPack?.focus?.entity_id,
    contextPack?.focus?.entity_type,
    contextPack?.mode,
    counts.comments,
    counts.notes,
    counts.project_rules,
    counts.specifications,
    counts.tasks,
    evidenceItems,
    graphContextMarkdown,
    graphEvidenceJsonChat,
    graphEvidenceJsonNonChat,
    graphSummaryMarkdown,
    projectDescription,
    normalizedChatAttachmentMode,
    normalizedChatIndexMode,
    projectName,
    rulesMarkdown,
    skillsMarkdown,
  ])

  return (
    <div className="graph-context-snapshot" style={{ marginTop: 10, marginBottom: 12 }}>
      <div className="row wrap graph-context-snapshot-head">
        <div>
          <div className="meta">Project context snapshot</div>
          <div className="graph-context-snapshot-title">Full context footprint across project data, hardcoded prompt logic, and runtime inputs</div>
        </div>
        <div className="graph-context-snapshot-total">
          Used ~{snapshot.approxTokens.toLocaleString()} / {snapshot.contextWindowTokens.toLocaleString()} tokens
        </div>
      </div>

      <div className="meta" style={{ marginTop: 6 }}>
        Includes hardcoded system prompt and guidance from automation code, plus live active-session chat history when present.
      </div>
      <div className="meta" style={{ marginTop: 4 }}>
        Indexed project chat corpus is shown separately from active session history so you can track persisted-chat contribution.
      </div>
      <div className="meta" style={{ marginTop: 4 }}>
        Chat indexing policy: {chatIndexModeLabel(normalizedChatIndexMode)} · Attachment ingestion: {chatAttachmentModeLabel(normalizedChatAttachmentMode)}
      </div>
      {normalizedChatIndexMode !== 'OFF' ? (
        <div className="meta" style={{ marginTop: 4 }}>
          Even with an empty active session, project chat corpus remains retrievable via indexing policy and appears under Chat-derived evidence.
        </div>
      ) : null}

      <div className="graph-context-metrics">
        <div className="graph-context-metric">
          <span className="meta">Rules</span>
          <strong>{projectRules.length}</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Skills</span>
          <strong>{projectSkills.length}</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Evidence items</span>
          <strong>{snapshot.evidenceCount}</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Hardcoded baseline</span>
          <strong>~{snapshot.hardcodedTokens.toLocaleString()} tokens</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Live chat history</span>
          <strong>~{snapshot.chatHistoryTokens.toLocaleString()} tokens</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Indexed chat corpus</span>
          <strong>~{snapshot.indexedChatTokens.toLocaleString()} tokens</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Chat-derived evidence</span>
          <strong>{snapshot.chatEvidenceCount} ({snapshot.chatEvidenceSharePct.toFixed(1)}%)</strong>
        </div>
        <div className="graph-context-metric">
          <span className="meta">Scope coverage</span>
          <strong>{snapshot.contextCoveragePct}%</strong>
        </div>
      </div>

      <div className="graph-context-cube-block">
        <div className="meta">Context source occupancy map</div>
        {snapshot.sourceTiles.length === 0 ? (
          <div className="meta" style={{ marginTop: 6 }}>Context is empty for this project.</div>
        ) : (
          <div className="graph-context-cube-grid graph-context-cube-grid-dense" role="img" aria-label="Project context source occupancy map">
            {snapshot.sourceTiles.map((tile, idx) => (
              <span
                key={`source-cube-${idx}-${tile.key}`}
                className="graph-context-cube"
                style={{ backgroundColor: tile.color }}
                title={tile.label}
              />
            ))}
          </div>
        )}
        <div className="meta">
          Used window: {(100 - snapshot.emptyWindowPercent).toFixed(1)}% (~{snapshot.approxTokens.toLocaleString()} tokens)
        </div>
        <div className="meta">
          Resolution: {snapshot.tileCount.toLocaleString()} cells · ~{Math.max(1, Math.round(snapshot.tokensPerTile || 0)).toLocaleString()} tokens per cell
        </div>
        <div className="graph-context-legend">
          {snapshot.sources.map((source) => (
            <div key={`source-legend-${source.key}`} className="graph-context-legend-row">
              <span className="graph-context-legend-swatch" style={{ backgroundColor: source.color }} />
              <span className="graph-context-legend-label">{source.label}</span>
              <span className="meta">
                {sourceGroupLabel(source.group)} · {source.windowPercent.toFixed(1)}% window · {source.percent.toFixed(1)}% used · {source.chars.toLocaleString()} chars
                {source.lines > 0 ? ` · ${source.lines} lines` : ''}
              </span>
            </div>
          ))}
          {snapshot.emptyTokens > 0 ? (
            <div className="graph-context-legend-row">
              <span className="graph-context-legend-swatch graph-context-legend-swatch-empty" />
              <span className="graph-context-legend-label">Empty context window</span>
              <span className="meta">{snapshot.emptyWindowPercent.toFixed(1)}% window · {snapshot.emptyTokens.toLocaleString()} tokens</span>
            </div>
          ) : null}
        </div>
      </div>

      <div className="meta" style={{ marginTop: 8 }}>
        Attachment excerpts are runtime-dependent and can contribute up to ~9,000 tokens when files are included in chat.
      </div>
      <div className="meta" style={{ marginTop: 4 }}>
        Average evidence score: {snapshot.averageEvidenceScore.toFixed(3)} · Distinct evidence entities: {snapshot.distinctEvidenceEntities} · Chat evidence entities: {snapshot.chatEvidenceEntityCount}
      </div>
    </div>
  )
}
