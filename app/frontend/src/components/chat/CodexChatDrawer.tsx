import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import * as Tooltip from '@radix-ui/react-tooltip'
import { archiveChatSession, updateChatSessionContext } from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { AttachmentRef } from '../../types'
import { AttachmentRefList, Icon } from '../shared/uiHelpers'

function getSpeechRecognitionCtor(): any | null {
  if (typeof window === 'undefined') return null
  const win = window as any
  const ctor = win.SpeechRecognition || win.webkitSpeechRecognition
  return typeof ctor === 'function' ? ctor : null
}

function appendTranscript(base: string, transcript: string): string {
  const cleanTranscript = String(transcript || '').trim()
  if (!cleanTranscript) return base
  if (!base.trim()) return cleanTranscript
  const separator = /\s$/.test(base) ? '' : ' '
  return `${base}${separator}${cleanTranscript}`
}

function buildProjectCreationStarter(): string {
  return 'Help me set up a new project in chat. Use setup_project_orchestration and, if inputs are missing, ask only the next missing question from the tool response.'
}

const CHAT_INPUT_MIN_HEIGHT_PX = 64
const CHAT_INPUT_MAX_HEIGHT_PX = 116
const VOICE_LANG_HINT_SEEN_STORAGE_KEY = 'ui_codex_chat_voice_lang_hint_seen'

function normalizeMcpLookupKey(value: string): string {
  return String(value || '').trim().toLowerCase().replace(/_/g, '-')
}

const CORE_MCP_LOOKUP_KEYS = new Set(['task-management-tools'])

function dedupeAttachmentRefs(refs: AttachmentRef[]): AttachmentRef[] {
  const seen = new Set<string>()
  const out: AttachmentRef[] = []
  for (const ref of refs) {
    const path = String(ref.path || '').trim()
    if (!path) continue
    const key = path.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(ref)
  }
  return out
}

function resolveSessionLastMessageAtMs(session: any): number {
  const turns = Array.isArray(session?.turns) ? session.turns : []
  let lastTurnAt = 0
  for (const turn of turns) {
    const createdAt = Number(turn?.createdAt)
    if (Number.isFinite(createdAt) && createdAt > lastTurnAt) lastTurnAt = createdAt
  }
  return lastTurnAt
}

function resolveSessionSortAtMs(session: any): number {
  const lastMessageAtMs = resolveSessionLastMessageAtMs(session)
  if (lastMessageAtMs > 0) return lastMessageAtMs
  const updatedAt = Number(session?.updatedAt)
  if (Number.isFinite(updatedAt) && updatedAt > 0) return Math.floor(updatedAt)
  return 0
}

function formatSessionTimestamp(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return 'No messages yet'
  return new Date(value).toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatTaskEventTimestamp(value: number | string | null | undefined): string {
  const ms = Number(value)
  if (!Number.isFinite(ms) || ms <= 0) return '—'
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function normalizeBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    return normalized === 'true' || normalized === '1' || normalized === 'yes' || normalized === 'on'
  }
  return false
}

function normalizeReasoningEffort(value: unknown): 'low' | 'medium' | 'high' | 'xhigh' {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'low' || normalized === 'high' || normalized === 'xhigh') return normalized
  return 'medium'
}

function buildClassifierMarkdown(value: Record<string, unknown> | null | undefined): string {
  if (!value || Object.keys(value).length === 0) return '_No classifier data recorded_'
  return `\`\`\`json\n${JSON.stringify(value, null, 2)}\n\`\`\``
}

function reasoningEffortLabel(value: 'low' | 'medium' | 'high' | 'xhigh'): string {
  if (value === 'xhigh') return 'Very high'
  return value.charAt(0).toUpperCase() + value.slice(1)
}

async function copyTextToClipboard(text: string): Promise<void> {
  const canUseClipboardApi = typeof navigator !== 'undefined' && Boolean(navigator.clipboard?.writeText)
  if (canUseClipboardApi) {
    await navigator.clipboard.writeText(text)
  } else if (typeof document !== 'undefined') {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', 'true')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    ta.style.pointerEvents = 'none'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (!ok) throw new Error('Clipboard copy is not supported in this browser context')
  } else {
    throw new Error('Clipboard copy is not available')
  }
}

function extractCodexThreadIdFromTurns(turns: any[]): string | null {
  if (!Array.isArray(turns) || turns.length === 0) return null
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    const content = String(turn?.content || '')
    if (!content) continue
    const fromResumeCommand = content.match(/\bcos\s+resume\s+([0-9a-fA-F-]{20,})\b/)
    if (fromResumeCommand?.[1]) return fromResumeCommand[1]
    const fromThreadLabel = content.match(/\bcodex\s+thread\s+id\s*:\s*([0-9a-fA-F-]{20,})\b/i)
    if (fromThreadLabel?.[1]) return fromThreadLabel[1]
  }
  return null
}

function ChatTooltip({
  content,
  children,
}: {
  content: string
  children: React.ReactElement
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="codex-chat-tooltip-content" sideOffset={6}>
          {content}
          <Tooltip.Arrow className="codex-chat-tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

type TurnCopyState =
  | { status: 'copied' | 'error'; turnId: string }
  | { status: 'idle'; turnId: null }

export function CodexChatDrawer({ state }: { state: any }) {
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [chatAttachmentRefs, setChatAttachmentRefs] = React.useState<AttachmentRef[]>([])
  const [isUploadingAttachments, setIsUploadingAttachments] = React.useState(false)
  const [isUpdatingSessionAttachments, setIsUpdatingSessionAttachments] = React.useState(false)
  const [isDeletingSession, setIsDeletingSession] = React.useState(false)
  const recognitionRef = React.useRef<any>(null)
  const speechBaseInstructionRef = React.useRef('')
  const speechHadResultRef = React.useRef(false)
  const speechStoppedManuallyRef = React.useRef(false)
  const [isListening, setIsListening] = React.useState(false)
  const [speechSupported, setSpeechSupported] = React.useState(false)
  const [showVoiceLangHint, setShowVoiceLangHint] = React.useState(false)
  const [hasSeenVoiceLangHint, setHasSeenVoiceLangHint] = React.useState<boolean>(() => {
    if (typeof window === 'undefined') return true
    try {
      return window.localStorage.getItem(VOICE_LANG_HINT_SEEN_STORAGE_KEY) === '1'
    } catch {
      return true
    }
  })
  const [deleteSessionDialogOpen, setDeleteSessionDialogOpen] = React.useState(false)
  const [clearChatDialogOpen, setClearChatDialogOpen] = React.useState(false)
  const [deleteSessionId, setDeleteSessionId] = React.useState<string | null>(null)
  const [projectSetupStarterUsed, setProjectSetupStarterUsed] = React.useState(false)
  const [resumeCommandCopyState, setResumeCommandCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const [turnCopyState, setTurnCopyState] = React.useState<TurnCopyState>({ status: 'idle', turnId: null })
  const [expandedDebugTurns, setExpandedDebugTurns] = React.useState<Record<string, boolean>>({})
  const codexThreadId = String(state.codexChatCodexSessionId || '').trim()
    || extractCodexThreadIdFromTurns(state.codexChatTurns)
    || ''
  const codexResumeCommand = codexThreadId ? `cos resume ${codexThreadId}` : null
  const markVoiceLangHintSeen = React.useCallback(() => {
    setHasSeenVoiceLangHint(true)
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(VOICE_LANG_HINT_SEEN_STORAGE_KEY, '1')
    } catch {
      // Ignore storage failures for one-time hint tracking.
    }
  }, [])

  React.useEffect(() => {
    setChatAttachmentRefs([])
  }, [state.codexChatSessionId, state.codexChatProjectId])

  React.useEffect(() => {
    setSpeechSupported(Boolean(getSpeechRecognitionCtor()))
  }, [])

  React.useEffect(() => {
    if (!showVoiceLangHint || isListening) return
    const timer = window.setTimeout(() => {
      setShowVoiceLangHint(false)
    }, 5500)
    return () => window.clearTimeout(timer)
  }, [showVoiceLangHint, isListening])

  React.useEffect(() => {
    return () => {
      const recognition = recognitionRef.current
      recognitionRef.current = null
      if (!recognition) return
      try {
        recognition.abort?.()
      } catch {
        // Ignore stop/abort cleanup errors on unmount.
      }
    }
  }, [])

  React.useEffect(() => {
    const input = inputRef.current
    if (!input) return
    input.style.height = 'auto'
    const nextHeight = Math.max(
      CHAT_INPUT_MIN_HEIGHT_PX,
      Math.min(input.scrollHeight, CHAT_INPUT_MAX_HEIGHT_PX)
    )
    input.style.height = `${nextHeight}px`
    input.style.overflowY = input.scrollHeight > CHAT_INPUT_MAX_HEIGHT_PX ? 'auto' : 'hidden'
  }, [state.codexChatInstruction, state.showCodexChat, state.codexChatSessionId])

  React.useEffect(() => {
    setResumeCommandCopyState('idle')
  }, [codexResumeCommand])

  React.useEffect(() => {
    setTurnCopyState({ status: 'idle', turnId: null })
  }, [state.codexChatSessionId])

  React.useEffect(() => {
    setExpandedDebugTurns({})
  }, [state.codexChatSessionId])

  React.useEffect(() => {
    setProjectSetupStarterUsed(false)
  }, [state.codexChatSessionId])

  React.useEffect(() => {
    if (resumeCommandCopyState === 'idle') return
    const timeoutMs = resumeCommandCopyState === 'copied' ? 1400 : 1800
    const timer = window.setTimeout(() => {
      setResumeCommandCopyState('idle')
    }, timeoutMs)
    return () => window.clearTimeout(timer)
  }, [resumeCommandCopyState])

  React.useEffect(() => {
    if (turnCopyState.status === 'idle' || !turnCopyState.turnId) return
    const timeoutMs = turnCopyState.status === 'copied' ? 1400 : 1800
    const timer = window.setTimeout(() => {
      setTurnCopyState({ status: 'idle', turnId: null })
    }, timeoutMs)
    return () => window.clearTimeout(timer)
  }, [turnCopyState])

  const copyResumeCommandToClipboard = React.useCallback(async () => {
    if (!codexResumeCommand) return
    try {
      await copyTextToClipboard(codexResumeCommand)
      setResumeCommandCopyState('copied')
    } catch {
      setResumeCommandCopyState('error')
      if (typeof window !== 'undefined' && typeof window.prompt === 'function') {
        window.prompt('Copy this command to continue in COS CLI:', codexResumeCommand)
      }
    }
  }, [codexResumeCommand])

  const copyTurnToClipboard = React.useCallback(async (turn: any) => {
    const turnId = String(turn?.id || '').trim()
    const content = String(turn?.content || '')
    if (!turnId || !content.trim()) return
    try {
      await copyTextToClipboard(content)
      setTurnCopyState({ status: 'copied', turnId })
    } catch {
      setTurnCopyState({ status: 'error', turnId })
      if (typeof window !== 'undefined' && typeof window.prompt === 'function') {
        window.prompt('Copy this message manually:', content)
      }
    }
  }, [])

  if (!state.showCodexChat) return null
  const usage = state.codexChatUsage
  const inputTokens = typeof usage?.input_tokens === 'number' ? Math.max(0, usage.input_tokens) : null
  const contextLimitTokens = typeof usage?.context_limit_tokens === 'number' && usage.context_limit_tokens > 0
    ? usage.context_limit_tokens
    : null
  const usagePercent = inputTokens !== null && contextLimitTokens
    ? Math.max(0, Math.min(100, Math.round((inputTokens / contextLimitTokens) * 100)))
    : null
  const sessions = Array.isArray(state.codexChatProjectSessions)
    ? [...state.codexChatProjectSessions]
    : Array.isArray(state.codexChatSessions)
      ? [...state.codexChatSessions].filter((session: any) => String(session?.projectId || '') === String(state.codexChatProjectId || ''))
      : []
  sessions.sort((a: any, b: any) => resolveSessionSortAtMs(b) - resolveSessionSortAtMs(a))
  const activeSession = sessions.find((session: any) => session.id === state.codexChatActiveSessionId) ?? null
  const activeSessionUpdatedAtRaw = activeSession ? resolveSessionLastMessageAtMs(activeSession) : 0
  const activeSessionUpdatedAt = activeSessionUpdatedAtRaw > 0 ? formatSessionTimestamp(activeSessionUpdatedAtRaw) : null
  const lastTaskEventTimeLabel = formatTaskEventTimestamp(state.codexChatLastTaskEventAt)
  const hasLastTaskEvent = lastTaskEventTimeLabel !== '—'
  const sessionOptions = sessions.map((session: any) => {
    const lastMessageAtMs = resolveSessionLastMessageAtMs(session)
    const lastMessageLabel = formatSessionTimestamp(lastMessageAtMs)
    return {
      id: String(session?.id || ''),
      title: String(session?.title || 'Session'),
      lastMessageLabel,
    }
  })
  const projectOptions: Array<{ id: string; name: string }> = Array.isArray(state.bootstrap.data?.projects)
    ? state.bootstrap.data.projects.map((project: any) => ({
      id: String(project?.id || ''),
      name: String(project?.name || '').trim() || 'Untitled project',
    }))
    : []
  const projectSelectValue = (() => {
    const current = String(state.codexChatProjectId || '').trim()
    if (!current) return '__none__'
    return projectOptions.some((project: { id: string; name: string }) => project.id === current) ? current : '__none__'
  })()
  const hasMessages = state.codexChatTurns.length > 0
  const availableMcpServers = (() => {
    if (!Array.isArray(state.bootstrap.data?.agent_chat_available_mcp_servers)) return []
    const seen = new Set<string>()
    const out: Array<{
      name: string
      display_name: string
      auth_status: string | null
    }> = []
    for (const item of state.bootstrap.data.agent_chat_available_mcp_servers) {
      const name = String(item?.name || '').trim()
      if (!name) continue
      if (!Boolean(item?.enabled)) continue
      const key = normalizeMcpLookupKey(name)
      if (seen.has(key)) continue
      seen.add(key)
      const displayName = String(item?.display_name || '').trim() || name
      out.push({
        name,
        display_name: displayName,
        auth_status: String(item?.auth_status || '').trim() || null,
      })
    }
    return out
  })()
  const mcpAliasToName = new Map<string, string>()
  for (const server of availableMcpServers) {
    mcpAliasToName.set(normalizeMcpLookupKey(server.name), server.name)
  }
  const coreMcpServerName = availableMcpServers.find((server) => CORE_MCP_LOOKUP_KEYS.has(normalizeMcpLookupKey(server.name)))?.name || null
  const hasOptionalMcpServers = availableMcpServers.some((server) => !CORE_MCP_LOOKUP_KEYS.has(normalizeMcpLookupKey(server.name)))
  const showMcpSection = hasOptionalMcpServers
  const selectedMcpServers: string[] = (() => {
    const hasDiscoveredServers = availableMcpServers.length > 0
    const rawSelection = Array.isArray(state.codexChatMcpServers) ? state.codexChatMcpServers : []
    const normalizedSelection: string[] = []
    const seen = new Set<string>()
    for (const raw of rawSelection) {
      const clean = String(raw || '').trim()
      if (!clean) continue
      const lookupKey = normalizeMcpLookupKey(clean)
      const canonical = hasDiscoveredServers ? (mcpAliasToName.get(lookupKey) || '') : clean
      if (!canonical) continue
      const dedupeKey = normalizeMcpLookupKey(canonical)
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)
      normalizedSelection.push(canonical)
    }
    const withCore = [...normalizedSelection]
    if (coreMcpServerName && !withCore.some((name) => normalizeMcpLookupKey(name) === normalizeMcpLookupKey(coreMcpServerName))) {
      withCore.unshift(coreMcpServerName)
    }
    if (withCore.length > 0) return withCore
    if (coreMcpServerName) return [coreMcpServerName]
    if (!hasDiscoveredServers) return []
    const firstAvailable = availableMcpServers[0]?.name
    return firstAvailable ? [firstAvailable] : []
  })()
  const optionalMcpServers = availableMcpServers.filter(
    (server) => !CORE_MCP_LOOKUP_KEYS.has(normalizeMcpLookupKey(server.name))
  )
  const selectedOptionalMcpServers = selectedMcpServers.filter(
    (name) => !CORE_MCP_LOOKUP_KEYS.has(normalizeMcpLookupKey(name))
  )
  const isChatBusy = Boolean(state.runAgentChatMutation.isPending || state.isCodexChatRunning || state.codexChatLiveRunActive)
  const lastTurnId = state.codexChatTurns.length > 0
    ? state.codexChatTurns[state.codexChatTurns.length - 1]?.id ?? null
    : null
  const contextSummary = inputTokens !== null
    ? (contextLimitTokens && usagePercent !== null ? `Context ${usagePercent}%` : `Context ${inputTokens.toLocaleString()}`)
    : null
  const contextFrameModeRaw = String(usage?.graph_context_frame_mode || '').trim().toLowerCase()
  const contextFrameMode = contextFrameModeRaw === 'full' || contextFrameModeRaw === 'delta'
    ? contextFrameModeRaw.toUpperCase()
    : null
  const contextFrameRevision = String(usage?.graph_context_frame_revision || '').trim()
  const contextFrameRevisionShort = contextFrameRevision ? contextFrameRevision.slice(0, 8) : null
  const contextFrameSummary = contextFrameMode
    ? `Frame ${contextFrameMode}${contextFrameRevisionShort ? ` · ${contextFrameRevisionShort}` : ''}`
    : null
  const promptModeRaw = String(usage?.prompt_mode || '').trim().toLowerCase()
  const promptMode = promptModeRaw === 'resume' || promptModeRaw === 'full' ? promptModeRaw.toUpperCase() : null
  const promptSegmentChars = usage?.prompt_segment_chars && typeof usage.prompt_segment_chars === 'object'
    ? usage.prompt_segment_chars
    : null
  const promptSegmentEntries = promptSegmentChars
    ? Object.entries(promptSegmentChars)
      .filter(([key, value]) => String(key || '').trim() && Number.isFinite(Number(value)) && Number(value) >= 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]))
    : []
  const promptSegmentsTotal = promptSegmentEntries.length > 0
    ? promptSegmentEntries.reduce((sum, [, value]) => sum + Number(value), 0)
    : null
  const promptSegmentsSummary = promptSegmentsTotal !== null
    ? `Prompt ${promptMode || 'N/A'} · ${(promptSegmentsTotal / 1000).toFixed(1)}k chars`
    : null
  const promptSegmentsTooltip = promptSegmentEntries.length > 0
    ? promptSegmentEntries
      .slice(0, 6)
      .map(([key, value]) => `${key}: ${Number(value).toLocaleString()} chars`)
      .join('\n')
    : null
  const contextFrameLabel = contextFrameSummary || null
  const hasContextMetrics = Boolean(contextSummary || contextFrameLabel || promptSegmentsSummary || promptSegmentsTooltip)
  const contextMetaText = contextSummary || 'Context'
  const contextMetricsTooltip = (() => {
    const lines: string[] = []
    if (contextSummary) lines.push(contextSummary)
    if (contextFrameLabel) lines.push(contextFrameLabel)
    if (promptSegmentsSummary) lines.push(promptSegmentsSummary)
    if (promptSegmentsTooltip) {
      lines.push('Segments:')
      lines.push(promptSegmentsTooltip)
    }
    return lines.length > 0 ? lines.join('\n') : null
  })()
  const codexResumeFallbackUsed = Boolean(
    normalizeBool(state.codexChatResumeState?.fallbackUsed)
    || normalizeBool(usage?.codex_resume_fallback_used)
  )
  const continueSessionMenuLabel = resumeCommandCopyState === 'copied'
    ? 'Continue session in CLI (copied)'
    : resumeCommandCopyState === 'error'
      ? 'Continue session in CLI (copy failed)'
      : codexResumeCommand
        ? 'Continue session in CLI'
        : 'Continue session in CLI (missing Codex thread ID)'
  const hasContext = contextSummary !== null
  const metaParts: string[] = []
  if (hasMessages) metaParts.push(`${state.codexChatTurns.length} ${state.codexChatTurns.length === 1 ? 'message' : 'messages'}`)
  if (activeSessionUpdatedAt && (hasMessages || hasContext)) metaParts.push(activeSessionUpdatedAt)
  const hasSessionMeta = metaParts.length > 0 || Boolean(contextSummary) || Boolean(contextFrameSummary) || codexResumeFallbackUsed
  const canDeleteSession = (
    Array.isArray(state.codexChatSessions)
    && state.codexChatSessions.length > 1
    && !state.runAgentChatMutation.isPending
    && !isDeletingSession
  )
  const canCreateSession = !isChatBusy
  const canUseProjectCreationStarter =
    !isChatBusy &&
    Boolean(state.workspaceId) &&
    !projectSetupStarterUsed
  const canClearChat = !isChatBusy && state.codexChatTurns.length > 0
  const activeSpeechLang = String(state.speechLang || '').trim() || 'en-US'
  const speechLangName = activeSpeechLang === 'bs-BA' ? 'Bosnian' : 'English'
  const speechLangLabel = `${speechLangName} (${activeSpeechLang})`
  const sessionAttachmentRefs = dedupeAttachmentRefs(
    Array.isArray(state.codexChatSessionAttachmentRefs)
      ? state.codexChatSessionAttachmentRefs
      : []
  )
  const chatModelOverride = String(state.agentChatModel || '').trim()
  const defaultChatModel = String(state.agentChatDefaultModel || '').trim()
  const effectiveChatModel = chatModelOverride || defaultChatModel || 'system default'
  const compactChatModelLabel = chatModelOverride || defaultChatModel || 'System'
  const effectiveReasoningEffort = normalizeReasoningEffort(
    state.agentChatReasoningEffort || state.agentChatDefaultReasoningEffort
  )
  const effectiveReasoningLabel = reasoningEffortLabel(effectiveReasoningEffort)
  const codexAuthStatus = state.codexAuthStatus?.data ?? null
  const codexAuthMissing = !Boolean(state.codexAuthStatus?.isLoading || state.codexAuthStatus?.isFetching)
    && String(codexAuthStatus?.effective_source || '').trim().toLowerCase() === 'none'
  const canManageCodexAuth = Boolean(state.canManageUsers)
  const codexAuthMissingGuidance = canManageCodexAuth
    ? 'Codex authentication is not configured. Open Profile > Security and connect Codex before using chat or task automation.'
    : 'Codex authentication is not configured. Ask a workspace admin to open Profile > Security and connect Codex before using chat or task automation.'
  const codexAuthMissingBannerText = canManageCodexAuth
    ? 'Codex authentication is not configured. Open settings and connect Codex before sending messages.'
    : 'Codex authentication is not configured. Ask a workspace admin to connect Codex in settings before sending messages.'
  const codexAuthMissingPlaceholder = canManageCodexAuth
    ? 'Connect Codex in Profile > Security before starting a chat session.'
    : 'Ask a workspace admin to connect Codex in Profile > Security before starting a chat session.'

  const stopVoiceInput = () => {
    const recognition = recognitionRef.current
    if (!recognition) return
    speechStoppedManuallyRef.current = true
    try {
      recognition.stop?.()
    } catch {
      setIsListening(false)
      recognitionRef.current = null
    }
  }

  const startVoiceInput = () => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) {
      state.setUiError('Voice input is not supported in this browser.')
      return
    }
    if (isChatBusy || isListening) return

    const recognition = new Ctor()
    speechBaseInstructionRef.current = state.codexChatInstruction
    speechHadResultRef.current = false
    speechStoppedManuallyRef.current = false

    recognition.lang = activeSpeechLang
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onresult = (event: any) => {
      let finalText = ''
      let interimText = ''
      const results = event?.results || []
      for (let i = 0; i < results.length; i += 1) {
        const transcript = String(results[i]?.[0]?.transcript || '').trim()
        if (!transcript) continue
        if (results[i]?.isFinal) {
          finalText = finalText ? `${finalText} ${transcript}` : transcript
        } else {
          interimText = interimText ? `${interimText} ${transcript}` : transcript
        }
      }
      const combined = `${finalText}${finalText && interimText ? ' ' : ''}${interimText}`.trim()
      if (!combined) return
      speechHadResultRef.current = true
      state.setCodexChatInstruction(appendTranscript(speechBaseInstructionRef.current, combined))
    }

    recognition.onerror = (event: any) => {
      const code = String(event?.error || '').trim().toLowerCase()
      if (code === 'aborted') return
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        state.setUiError('Microphone permission denied.')
        return
      }
      if (code === 'audio-capture') {
        state.setUiError('No microphone was found.')
        return
      }
      if (code === 'no-speech') {
        state.setUiError('No speech detected. Try again.')
        return
      }
      state.setUiError(code ? `Voice input failed: ${code}` : 'Voice input failed.')
    }

    recognition.onend = () => {
      setIsListening(false)
      recognitionRef.current = null
      const stoppedManually = speechStoppedManuallyRef.current
      speechStoppedManuallyRef.current = false
      if (!speechHadResultRef.current && !stoppedManually) {
        state.setUiError((prev: string | null) => prev || 'No speech captured.')
      }
    }

    try {
      recognitionRef.current = recognition
      recognition.start()
      setIsListening(true)
      state.setUiError(null)
    } catch {
      recognitionRef.current = null
      setIsListening(false)
      state.setUiError('Unable to start voice input.')
    }
  }

  const statusText = isUploadingAttachments
    ? 'Uploading files...'
    : isUpdatingSessionAttachments
      ? 'Updating session context...'
    : state.isCodexChatRunning
      ? `Executing tools... ${state.codexChatElapsedSeconds}s`
      : isListening
        ? 'Listening...'
        : ''
  const canStopChat = Boolean(
    (state.isCodexChatRunning || state.codexChatLiveRunActive) &&
    typeof state.cancelAgentChat === 'function'
  )
  const mcpControlsDisabled = isChatBusy
  const handleOptionalMcpServersChange = (values: string[]) => {
    if (typeof state.setCodexChatMcpServers !== 'function') return
    const deduped: string[] = []
    const seen = new Set<string>()
    for (const raw of values) {
      const canonical = mcpAliasToName.get(normalizeMcpLookupKey(raw)) || raw
      const normalized = normalizeMcpLookupKey(canonical)
      if (!normalized || seen.has(normalized)) continue
      if (CORE_MCP_LOOKUP_KEYS.has(normalized)) continue
      seen.add(normalized)
      deduped.push(canonical)
    }
    state.setCodexChatMcpServers(deduped)
    if (!state.workspaceId || !state.codexChatSessionId || !state.userId) return
    const nextSelected = [...deduped]
    if (coreMcpServerName) {
      const coreLookup = normalizeMcpLookupKey(coreMcpServerName)
      if (!nextSelected.some((name) => normalizeMcpLookupKey(name) === coreLookup)) {
        nextSelected.unshift(coreMcpServerName)
      }
    }
    void updateChatSessionContext(state.userId, state.codexChatSessionId, {
      workspace_id: state.workspaceId,
      mcp_servers: nextSelected,
    })
      .then(() => {
        state.setUiError(null)
      })
      .catch((err: any) => {
        const message = String(err?.message || '').trim()
        if (message.toLowerCase().includes('chat session not found')) return
        state.setUiError(message || 'Failed to update MCP tool selection')
      })
  }

  const confirmDeleteSession = async () => {
    if (!canDeleteSession) return
    const sessionId = String(deleteSessionId || state.codexChatActiveSessionId || '').trim()
    if (!sessionId) return
    setIsDeletingSession(true)
    try {
      if (state.workspaceId && state.userId) {
        await archiveChatSession(state.userId, sessionId, state.workspaceId)
      }
      state.deleteCodexChatSession(sessionId)
      setDeleteSessionId(null)
      setDeleteSessionDialogOpen(false)
      state.setUiError(null)
    } catch (err: any) {
      const message = String(err?.message || '').trim()
      if (message.toLowerCase().includes('chat session not found')) {
        state.deleteCodexChatSession(sessionId)
        setDeleteSessionId(null)
        setDeleteSessionDialogOpen(false)
        state.setUiError(null)
      } else {
        state.setUiError(message || 'Failed to delete chat session')
      }
    } finally {
      setIsDeletingSession(false)
    }
  }

  const confirmClearChat = () => {
    stopVoiceInput()
    state.setCodexChatTurns([])
    state.setCodexChatUsage(null)
    setChatAttachmentRefs([])
    setClearChatDialogOpen(false)
  }

  const applyProjectCreationStarter = () => {
    if (!canUseProjectCreationStarter) return
    state.setUiError(null)
    setProjectSetupStarterUsed(true)
    sendChatInstruction(buildProjectCreationStarter())
  }

  const openVoiceLanguageSettings = () => {
    stopVoiceInput()
    setShowVoiceLangHint(false)
    try {
      window.sessionStorage.setItem('ui_profile_scroll_target', 'voice_language')
      window.dispatchEvent(new Event('ui:focus-voice-language'))
    } catch {
      // Ignore storage failures and still navigate.
    }
    state.setTab?.('profile')
    state.setShowCodexChat?.(false)
  }

  const openChatExecutionSettings = () => {
    stopVoiceInput()
    try {
      window.sessionStorage.setItem('ui_profile_scroll_target', 'chat_execution')
      window.dispatchEvent(new Event('ui:focus-chat-execution'))
    } catch {
      // Ignore storage failures and still navigate.
    }
    state.setTab?.('profile')
    state.setShowCodexChat?.(false)
  }

  const openCodexAuthSettings = () => {
    stopVoiceInput()
    try {
      window.sessionStorage.setItem('ui_profile_scroll_target', 'codex_auth')
      window.dispatchEvent(new Event('ui:focus-codex-auth'))
    } catch {
      // Ignore storage failures and still navigate.
    }
    state.setTab?.('profile')
    state.setShowCodexChat?.(false)
  }

  const appendLocalCodexAuthGuidance = () => {
    const content = codexAuthMissingGuidance
    state.setCodexChatTurns((prev: any[]) => {
      const lastTurn = Array.isArray(prev) && prev.length > 0 ? prev[prev.length - 1] : null
      if (lastTurn?.role === 'assistant' && String(lastTurn?.content || '').trim() === content) {
        return prev
      }
      return [
        ...(Array.isArray(prev) ? prev : []),
        {
          id: globalThis.crypto?.randomUUID?.() ?? `a-local-${Date.now()}`,
          role: 'assistant',
          content,
          createdAt: Date.now(),
        },
      ]
    })
  }

  const persistSessionAttachmentRefs = async (nextRefs: AttachmentRef[]) => {
    if (!state.workspaceId || !state.codexChatSessionId || !state.userId) return
    if (typeof state.setCodexChatSessionAttachmentRefs !== 'function') return
    setIsUpdatingSessionAttachments(true)
    const normalized = dedupeAttachmentRefs(nextRefs)
    try {
      const updated = await updateChatSessionContext(state.userId, state.codexChatSessionId, {
        workspace_id: state.workspaceId,
        session_attachment_refs: normalized,
      })
      const persisted = dedupeAttachmentRefs(
        Array.isArray(updated?.session_attachment_refs)
          ? updated.session_attachment_refs
          : normalized
      )
      state.setCodexChatSessionAttachmentRefs(persisted)
      state.setUiError(null)
    } catch (err: any) {
      state.setUiError(err?.message || 'Failed to update session attachments')
    } finally {
      setIsUpdatingSessionAttachments(false)
    }
  }

  const pinDraftAttachmentsToSession = async () => {
    if (chatAttachmentRefs.length === 0) return
    await persistSessionAttachmentRefs([...sessionAttachmentRefs, ...chatAttachmentRefs])
  }

  const sendChatInstruction = (rawInstruction: string, opts?: { clearInput?: boolean }) => {
    if (isListening) stopVoiceInput()
    const instruction = String(rawInstruction || '').trim()
    if (
      !instruction
      || state.runAgentChatMutation.isPending
      || !state.workspaceId
      || isUploadingAttachments
      || isUpdatingSessionAttachments
    ) return
    if (codexAuthMissing) {
      appendLocalCodexAuthGuidance()
      return
    }
    if (opts?.clearInput) state.setCodexChatInstruction('')
    const attachedRefs = [...chatAttachmentRefs]
    const nextUserTurn = {
      id: globalThis.crypto?.randomUUID?.() ?? `u-${Date.now()}`,
      role: 'user',
      content: instruction,
      createdAt: Date.now(),
      attachmentRefs: attachedRefs,
    }
    const commandId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
    const history = [...state.codexChatTurns, nextUserTurn]
      .slice(-80)
      .map((t: any) => ({ role: t.role, content: t.content }))
    state.setCodexChatTurns((prev: any) => [...prev, nextUserTurn])
    setChatAttachmentRefs([])
    if (typeof state.setCodexChatLiveRunForSession === 'function' && state.codexChatSessionId) {
      state.setCodexChatLiveRunForSession(state.codexChatSessionId, {
        liveRunId: commandId,
        liveRunStartedAt: Date.now(),
        liveRunActive: true,
      })
    }
    state.setIsCodexChatRunning(true)
    state.setCodexChatRunStartedAt(Date.now())
    state.setCodexChatElapsedSeconds(0)
    state.runAgentChatMutation.mutate({
      instruction,
      history,
      sessionId: state.codexChatSessionId,
      projectId: state.codexChatProjectId.trim() ? state.codexChatProjectId : null,
      mcpServers: selectedMcpServers,
      model: chatModelOverride || null,
      reasoningEffort: effectiveReasoningEffort,
      attachmentRefs: attachedRefs,
      sessionAttachmentRefs,
      commandId,
    })
  }

  return (
    <Tooltip.Provider delayDuration={180}>
      <div className="drawer open" onClick={() => state.setShowCodexChat(false)}>
        <div className="drawer-body codex-chat-drawer-body" onClick={(e) => e.stopPropagation()}>
          <div className="row codex-chat-header-row">
            <div className="codex-chat-header-main">
              <h3 className="codex-chat-header-title">Chat</h3>
              <ChatTooltip content="Open Profile settings to change chat model and reasoning level">
                <button
                  className="status-chip tag-filter-chip codex-chat-execution-chip codex-chat-header-inline-chip"
                  type="button"
                  onClick={openChatExecutionSettings}
                >
                  <span className="codex-chat-execution-chip-main">
                    {compactChatModelLabel}
                  </span>
                  <span className="codex-chat-execution-chip-sep">·</span>
                  <span className="codex-chat-execution-chip-meta">{effectiveReasoningLabel}</span>
                </button>
              </ChatTooltip>
            </div>
            <div className="codex-chat-header-actions">
              <ChatTooltip content="Close chat">
                <button className="action-icon" onClick={() => state.setShowCodexChat(false)} aria-label="Close">
                  <Icon path="M6 6l12 12M18 6 6 18" />
                </button>
              </ChatTooltip>
            </div>
          </div>
        <div className="codex-chat-context-top-row">
          <div className="codex-chat-context">
            <label className="meta codex-chat-context-label" htmlFor="codex-chat-project-context">Project</label>
            <Select.Root
              value={projectSelectValue}
              onValueChange={(value) => state.selectCodexChatProject(value === '__none__' ? '' : value)}
              disabled={isChatBusy}
            >
              <Select.Trigger
                id="codex-chat-project-context"
                className="codex-chat-session-trigger codex-chat-project-trigger"
                aria-label="Project context"
              >
                <Select.Value placeholder="No project" />
                <Select.Icon asChild>
                  <span className="codex-chat-session-trigger-icon codex-chat-project-trigger-icon" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Content className="codex-chat-session-content codex-chat-project-content" position="popper" sideOffset={6}>
                  <Select.Viewport className="codex-chat-session-viewport codex-chat-project-viewport">
                    <Select.Item value="__none__" className="codex-chat-session-item codex-chat-project-item">
                      <Select.ItemText>
                        <span className="codex-chat-session-item-title">No project</span>
                      </Select.ItemText>
                      <span className="codex-chat-session-item-meta">Chat can guide project creation</span>
                      <Select.ItemIndicator className="codex-chat-session-item-indicator codex-chat-project-item-indicator">
                        <Icon path="M5 13l4 4L19 7" />
                      </Select.ItemIndicator>
                    </Select.Item>
                    {projectOptions.map((project: { id: string; name: string }) => (
                      <Select.Item key={project.id} value={project.id} className="codex-chat-session-item codex-chat-project-item">
                        <Select.ItemText>
                          <span className="codex-chat-session-item-title">{project.name}</span>
                        </Select.ItemText>
                        <Select.ItemIndicator className="codex-chat-session-item-indicator codex-chat-project-item-indicator">
                          <Icon path="M5 13l4 4L19 7" />
                        </Select.ItemIndicator>
                      </Select.Item>
                    ))}
                  </Select.Viewport>
                </Select.Content>
              </Select.Portal>
            </Select.Root>
          </div>
          {showMcpSection && (
            <div className="codex-chat-mcp-row">
              <span className="meta codex-chat-context-label">MCP</span>
              <div className="codex-chat-mcp-chips">
                {coreMcpServerName ? (
                  <ChatTooltip content="Core MCP server is always enabled in this chat session">
                    <span className="status-chip tag-filter-chip codex-chat-mcp-core-chip">Core</span>
                  </ChatTooltip>
                ) : null}
                <ToggleGroup.Root
                  type="multiple"
                  className="codex-chat-mcp-toggle-group"
                  value={selectedOptionalMcpServers}
                  onValueChange={handleOptionalMcpServersChange}
                  aria-label="Optional MCP servers"
                  disabled={mcpControlsDisabled}
                >
                  {optionalMcpServers.map((server) => {
                    const selected = selectedOptionalMcpServers.some(
                      (name) => normalizeMcpLookupKey(name) === normalizeMcpLookupKey(server.name)
                    )
                    const chipDisabled = mcpControlsDisabled
                    const tooltipParts: string[] = [`Use ${server.display_name} in this chat session`]
                    if (server.auth_status) tooltipParts.push(`Auth: ${server.auth_status}`)
                    return (
                      <ChatTooltip key={server.name} content={tooltipParts.join(' · ')}>
                        <span className="codex-chat-mcp-tooltip-trigger">
                          <ToggleGroup.Item
                            value={server.name}
                            className={`status-chip tag-filter-chip codex-chat-mcp-toggle-item ${selected ? 'active' : ''}`}
                            disabled={chipDisabled}
                            aria-label={server.display_name}
                          >
                            {server.display_name}
                          </ToggleGroup.Item>
                        </span>
                      </ChatTooltip>
                    )
                  })}
                </ToggleGroup.Root>
              </div>
            </div>
          )}
        </div>
        <div className="codex-chat-session-row">
          <label className="meta codex-chat-session-label" htmlFor="codex-chat-session-select">Session</label>
          <Select.Root
            value={state.codexChatActiveSessionId}
            onValueChange={(value) => state.setCodexChatActiveSessionId(value)}
            disabled={isChatBusy || sessions.length === 0}
          >
            <Select.Trigger
              id="codex-chat-session-select"
              className="codex-chat-session-trigger"
              aria-label="Session"
            >
              <Select.Value placeholder="No sessions" />
              <Select.Icon asChild>
                <span className="codex-chat-session-trigger-icon" aria-hidden="true">
                  <Icon path="M6 9l6 6 6-6" />
                </span>
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className="codex-chat-session-content" position="popper" sideOffset={6}>
                <Select.Viewport className="codex-chat-session-viewport">
                  {sessionOptions.length === 0 ? (
                    <div className="codex-chat-session-empty">No sessions</div>
                  ) : (
                    sessionOptions.map((session) => (
                      <Select.Item key={session.id} value={session.id} className="codex-chat-session-item">
                        <Select.ItemText>
                          <span className="codex-chat-session-item-title">{session.title}</span>
                        </Select.ItemText>
                        <span className="codex-chat-session-item-meta">{session.lastMessageLabel}</span>
                        <Select.ItemIndicator className="codex-chat-session-item-indicator">
                          <Icon path="M5 13l4 4L19 7" />
                        </Select.ItemIndicator>
                      </Select.Item>
                    ))
                  )}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                className="action-icon codex-chat-session-actions-trigger"
                disabled={!canCreateSession && !canDeleteSession}
                title="Session actions"
                aria-label="Session actions"
              >
                <Icon path="M5 12h14M5 6h14M5 18h14" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                className="codex-chat-menu-content"
                align="end"
                side="bottom"
                sideOffset={6}
              >
                <DropdownMenu.Item
                  className="codex-chat-menu-item"
                  disabled={!canCreateSession}
                  onSelect={() => {
                    const nextSessionId = state.createCodexChatSession({ projectId: state.codexChatProjectId || '' })
                    if (nextSessionId) state.setCodexChatActiveSessionId(nextSessionId)
                  }}
                >
                  New session
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  className="codex-chat-menu-item"
                  disabled={!codexResumeCommand}
                  onSelect={() => {
                    void copyResumeCommandToClipboard()
                  }}
                >
                  {continueSessionMenuLabel}
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="codex-chat-menu-separator" />
                <DropdownMenu.Item
                  className="codex-chat-menu-item codex-chat-menu-item-danger"
                  disabled={!canDeleteSession}
                  onSelect={() => {
                    if (!canDeleteSession) return
                    setDeleteSessionId(String(state.codexChatActiveSessionId || '').trim() || null)
                    setDeleteSessionDialogOpen(true)
                  }}
                >
                  Delete current session
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
        {hasSessionMeta && (
          <div className="meta codex-chat-session-meta">
            {(metaParts.length > 0 || codexResumeFallbackUsed) && (
              <div className="codex-chat-session-meta-left">
                {metaParts.map((part, idx) => <span key={`${idx}-${part}`}>{part}</span>)}
                {codexResumeFallbackUsed && (
                  <ChatTooltip content="Last turn used fallback start because resume was unavailable for the saved thread.">
                    <span className="codex-chat-session-meta-resume-fallback" aria-label="Codex resume fallback used">
                      Resume fallback
                    </span>
                  </ChatTooltip>
                )}
              </div>
            )}
            {hasContextMetrics && (
              <ChatTooltip content={contextMetricsTooltip || 'Context metrics unavailable.'}>
                <span className="codex-chat-session-meta-context">{contextMetaText}</span>
              </ChatTooltip>
            )}
          </div>
        )}
        <div className="codex-chat-usage">
          {usagePercent !== null && (
            <div
              className="codex-chat-usage-bar"
              role="progressbar"
              aria-label="Context usage"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={usagePercent}
            >
              <span style={{ width: `${usagePercent}%` }} />
            </div>
          )}
        </div>
        <div className="codex-chat-history" ref={state.codexChatHistoryRef}>
          {state.codexChatTurns.length === 0 && (
            <div className="meta">Chat is empty. Send your first instruction.</div>
          )}
          {state.codexChatTurns.map((turn: any) => {
            const isStreamingAssistantTurn = Boolean(
              turn.role === 'assistant' && state.isCodexChatRunning && turn.id === lastTurnId
            )
            const turnContent = String(turn?.content || '')
            const lastStreamChunk = isStreamingAssistantTurn ? String(turn?.lastStreamChunk || '') : ''
            const streamShimmerChunk = isStreamingAssistantTurn ? String(turn?.streamShimmerChunk || '') : ''
            const fallbackChunkLength = Math.min(32, Math.max(12, Math.floor(turnContent.length * 0.35)))
            const shimmerChunk = streamShimmerChunk || lastStreamChunk || turnContent.slice(-fallbackChunkLength)
            const hasShimmerChunk = Boolean(shimmerChunk)
            const streamLeadContent = hasShimmerChunk
              ? turnContent.slice(0, Math.max(0, turnContent.length - shimmerChunk.length))
              : turnContent
            return (
            <div
              key={turn.id}
              className={`codex-chat-bubble ${turn.role} ${isStreamingAssistantTurn ? 'is-streaming' : ''}`.trim()}
            >
              <div className="codex-chat-role">
                <span className="codex-chat-role-meta">
                  {turn.role === 'user' ? 'You' : 'Assistant'}
                  {turn.createdAt ? ` · ${new Date(turn.createdAt).toLocaleTimeString()}` : ''}
                </span>
                <ChatTooltip
                  content={
                    turnCopyState.turnId === turn.id
                      ? turnCopyState.status === 'copied'
                        ? 'Copied'
                        : turnCopyState.status === 'error'
                          ? 'Copy failed'
                          : 'Copy message'
                      : 'Copy message'
                  }
                >
                  <button
                    className={`action-icon codex-chat-turn-copy ${turnCopyState.turnId === turn.id && turnCopyState.status !== 'idle' ? `is-${turnCopyState.status}` : ''}`}
                    type="button"
                    onClick={() => {
                      void copyTurnToClipboard(turn)
                    }}
                    aria-label={turn.role === 'user' ? 'Copy your message' : 'Copy assistant message'}
                    disabled={!String(turn?.content || '').trim()}
                  >
                    <Icon path="M16 4H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zM4 8H3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-1v-1" />
                  </button>
                </ChatTooltip>
              </div>
              {turn.role === 'assistant' ? (
                isStreamingAssistantTurn ? (
                  <div className="codex-chat-streaming-text" aria-live="polite">
                    {streamLeadContent}
                    {hasShimmerChunk && (
                      <span className="codex-chat-stream-last-chunk">
                        {shimmerChunk}
                      </span>
                    )}
                    <span className="codex-chat-stream-caret" aria-hidden="true" />
                  </div>
                ) : (
                  <MarkdownView
                    value={turn.content}
                    disableMermaid={Boolean(state.isCodexChatRunning && turn.id === lastTurnId)}
                  />
                )
              ) : (
                <>
                  <div>{turn.content}</div>
                  {turn.usage && typeof turn.usage === 'object' && 'intent_flags' in turn.usage && (
                    <div className="codex-chat-debug">
                      <button
                        type="button"
                        className="codex-chat-debug-toggle"
                        onClick={() => {
                          setExpandedDebugTurns((prev: Record<string, boolean>) => ({
                            ...prev,
                            [turn.id]: !Boolean(prev[turn.id]),
                          }))
                        }}
                        aria-expanded={Boolean(expandedDebugTurns[turn.id])}
                      >
                        <span>Debug</span>
                        <Icon path={expandedDebugTurns[turn.id] ? 'M18 15 12 9 6 15' : 'm6 9 6 6 6-6'} />
                      </button>
                      {expandedDebugTurns[turn.id] && (
                        <div className="codex-chat-debug-panel">
                          <div className="meta">Classifier output</div>
                          <MarkdownView value={buildClassifierMarkdown((turn.usage.intent_flags as Record<string, unknown> | null | undefined) ?? null)} />
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
              {Array.isArray(turn.attachmentRefs) && turn.attachmentRefs.length > 0 && (
                <div className="codex-chat-attachments">
                  <div className="codex-chat-attachments-label">
                    {turn.attachmentRefs.length === 1 ? 'Attachment' : 'Attachments'}
                  </div>
                  <AttachmentRefList
                    refs={turn.attachmentRefs}
                    workspaceId={state.workspaceId}
                    userId={state.userId}
                  />
                </div>
              )}
            </div>
          )})}
          {hasMessages && codexResumeCommand && (
            <div className="codex-chat-history-resume-row">
              <ChatTooltip content="Continue this conversation in COS CLI. Click to copy the resume command.">
                <button
                  className={`codex-chat-history-resume-link ${
                    resumeCommandCopyState === 'copied'
                      ? 'is-copied'
                      : resumeCommandCopyState === 'error'
                        ? 'is-error'
                        : ''
                  }`}
                  type="button"
                  onClick={() => {
                    void copyResumeCommandToClipboard()
                  }}
                  aria-label="Copy COS resume command"
                >
                  <span className="codex-chat-history-resume-text">{codexResumeCommand}</span>
                  <Icon path="M16 4H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zM4 8H3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-1v-1" />
                </button>
              </ChatTooltip>
            </div>
          )}
        </div>
        <div className="codex-chat-composer" data-tour-id="codex-chat-composer">
          {codexAuthMissing && (
            <div className="notice notice-error codex-chat-auth-banner" role="alert">
              <div className="codex-chat-auth-banner-copy">
                {codexAuthMissingBannerText}
              </div>
              <button
                type="button"
                className="button-secondary codex-chat-auth-banner-action"
                onClick={openCodexAuthSettings}
              >
                Open settings
              </button>
            </div>
          )}
          <textarea
            ref={inputRef}
            className="codex-chat-input"
            value={state.codexChatInstruction}
            onChange={(e) => state.setCodexChatInstruction(e.target.value)}
            rows={2}
            placeholder={
              codexAuthMissing
                ? codexAuthMissingPlaceholder
                : 'Try: Create 3 high-priority tasks for tomorrow in the Website Redesign project and assign them to me.'
            }
          />
          {!state.codexChatProjectId.trim() && (
            <div className="row wrap" style={{ marginTop: 8, alignItems: 'center', gap: 8 }}>
              <button
                className="status-chip"
                type="button"
                disabled={!canUseProjectCreationStarter}
                onClick={() => applyProjectCreationStarter()}
              >
                Start project setup
              </button>
              <span className="meta">
                No project is selected, so chat can create a new one interactively.
              </span>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={async (e) => {
              const files = Array.from(e.target.files ?? [])
              e.target.value = ''
              if (files.length === 0 || !state.codexChatProjectId.trim()) return
              try {
                setIsUploadingAttachments(true)
                const uploads = await Promise.allSettled(
                  files.map((file) => state.uploadAttachmentRef(file, { project_id: state.codexChatProjectId }))
                )
                const successful = uploads
                  .filter((result): result is PromiseFulfilledResult<AttachmentRef> => result.status === 'fulfilled')
                  .map((result) => result.value)
                const failed = uploads.filter((result): result is PromiseRejectedResult => result.status === 'rejected')

                if (successful.length > 0) {
                  setChatAttachmentRefs((prev) => dedupeAttachmentRefs([...prev, ...successful]))
                }

                if (failed.length === 0) {
                  state.setUiError(null)
                } else {
                  const firstError = failed
                    .map((result) => (result.reason instanceof Error ? result.reason.message : String(result.reason || '').trim()))
                    .find((message) => Boolean(message)) || 'Chat attachment upload failed'
                  if (successful.length > 0) {
                    state.setUiError(`Uploaded ${successful.length}/${files.length} files. ${firstError}`)
                  } else {
                    state.setUiError(firstError)
                  }
                }
              } catch (err: any) {
                state.setUiError(err?.message || 'Chat attachment upload failed')
              } finally {
                setIsUploadingAttachments(false)
              }
            }}
          />
          <AttachmentRefList
            refs={chatAttachmentRefs}
            workspaceId={state.workspaceId}
            userId={state.userId}
            onRemovePath={(path) => setChatAttachmentRefs((prev) => prev.filter((ref) => ref.path !== path))}
          />
          {chatAttachmentRefs.length > 0 && (
            <div className="row wrap" style={{ marginTop: 6, gap: 8, alignItems: 'center' }}>
              <button
                className="status-chip"
                type="button"
                disabled={isUpdatingSessionAttachments || isUploadingAttachments}
                onClick={() => {
                  void pinDraftAttachmentsToSession()
                }}
              >
                Pin selected to session
              </button>
              <span className="meta">Pinned files are included in every next chat request for this session.</span>
            </div>
          )}
          {sessionAttachmentRefs.length > 0 && (
            <div className="codex-chat-attachments" style={{ marginTop: 8 }}>
              <div className="codex-chat-attachments-label">Pinned to session</div>
              <AttachmentRefList
                refs={sessionAttachmentRefs}
                workspaceId={state.workspaceId}
                userId={state.userId}
                onRemovePath={(path) => {
                  const next = sessionAttachmentRefs.filter((ref) => ref.path !== path)
                  void persistSessionAttachmentRefs(next)
                }}
              />
            </div>
          )}
          <div className="codex-chat-toolbar">
            <Popover.Root
              open={showVoiceLangHint}
              onOpenChange={(nextOpen) => {
                if (!nextOpen) setShowVoiceLangHint(false)
              }}
            >
              <ChatTooltip
                content={
                  speechSupported
                    ? `${isListening ? 'Stop voice input' : 'Start voice input'} (${speechLangLabel})`
                    : 'Voice input is not supported in this browser'
                }
              >
                <Popover.Anchor asChild>
                  <button
                    className={`action-icon codex-chat-toolbar-item codex-chat-toolbar-item-voice ${isListening ? 'primary' : ''}`}
                    onClick={() => {
                      if (!hasSeenVoiceLangHint) {
                        setShowVoiceLangHint(true)
                        markVoiceLangHintSeen()
                      }
                      if (isListening) {
                        stopVoiceInput()
                        return
                      }
                      startVoiceInput()
                    }}
                    disabled={isChatBusy || !speechSupported}
                    aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
                  >
                    <Icon path="M12 15a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0m5 5v4m-4 0h8" />
                  </button>
                </Popover.Anchor>
              </ChatTooltip>
              <Popover.Portal>
                <Popover.Content
                  className="codex-chat-voice-popover"
                  side="top"
                  align="start"
                  sideOffset={8}
                >
                  <div className="codex-chat-voice-popover-title">Voice input language</div>
                  <div className="codex-chat-voice-popover-value">{speechLangLabel}</div>
                  <button
                    type="button"
                    className="codex-chat-voice-popover-action"
                    onClick={openVoiceLanguageSettings}
                    aria-label="Open voice language settings"
                  >
                    Open Settings
                  </button>
                  <Popover.Arrow className="codex-chat-voice-popover-arrow" />
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
            <ChatTooltip content="Attach one or more files">
              <span className="codex-chat-tooltip-trigger-inline codex-chat-toolbar-item codex-chat-toolbar-item-attach">
                <button
                  className="action-icon"
                  onClick={() => {
                    if (!state.codexChatProjectId.trim()) {
                      state.setUiError('Select a project before attaching files to chat.')
                      return
                    }
                    fileInputRef.current?.click()
                  }}
                  disabled={isChatBusy || isUploadingAttachments || isUpdatingSessionAttachments}
                  aria-label="Attach files"
                >
                  <Icon path="M21.44 11.05l-8.49 8.49a5.5 5.5 0 0 1-7.78-7.78l9.19-9.2a3.5 3.5 0 1 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.48-8.49" />
                </button>
              </span>
            </ChatTooltip>
            <ChatTooltip content={canClearChat ? 'Clear current chat history' : 'No messages to clear'}>
              <span className="codex-chat-tooltip-trigger-inline codex-chat-toolbar-item codex-chat-toolbar-item-clear">
                <button
                  className="action-icon"
                  onClick={() => {
                    if (!canClearChat) return
                    setClearChatDialogOpen(true)
                  }}
                  disabled={!canClearChat}
                  aria-label="Clear chat"
                >
                  <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                </button>
              </span>
            </ChatTooltip>
            <span className={`codex-chat-status codex-chat-toolbar-item codex-chat-toolbar-item-status ${state.isCodexChatRunning || isListening || isUploadingAttachments || isUpdatingSessionAttachments ? 'codex-progress' : ''}`}>
              {statusText}
            </span>
            {canStopChat && (
              <ChatTooltip content="Stop generating">
                <button
                  className="action-icon danger-ghost codex-chat-toolbar-item codex-chat-toolbar-item-stop"
                  onClick={() => {
                    state.cancelAgentChat()
                  }}
                  aria-label="Stop generating"
                >
                  <Icon path="M8 8h8v8H8z" />
                </button>
              </ChatTooltip>
            )}
            <ChatTooltip content="Send message">
              <span className="codex-chat-tooltip-trigger-inline codex-chat-toolbar-item codex-chat-toolbar-item-send">
                <button
                  className="action-icon primary"
                  onClick={() => {
                    sendChatInstruction(state.codexChatInstruction, { clearInput: true })
                  }}
                  disabled={
                    isChatBusy
                    || isUploadingAttachments
                    || isUpdatingSessionAttachments
                    || !state.codexChatInstruction.trim()
                    || !state.workspaceId
                  }
                  aria-label="Send"
                >
                  <Icon path="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z" />
                </button>
              </span>
            </ChatTooltip>
          </div>
          <div className="codex-chat-task-event-row" aria-live="polite" aria-atomic="true">
            <span className={`meta codex-chat-task-event ${hasLastTaskEvent ? '' : 'is-empty'}`.trim()}>
              Last task event: <span className="codex-chat-task-event-time">{lastTaskEventTimeLabel}</span>
            </span>
          </div>
          <AlertDialog.Root
            open={deleteSessionDialogOpen}
            onOpenChange={(open) => {
              setDeleteSessionDialogOpen(open)
              if (!open) setDeleteSessionId(null)
            }}
          >
            <AlertDialog.Portal>
              <AlertDialog.Overlay className="codex-chat-alert-overlay" />
              <AlertDialog.Content className="codex-chat-alert-content">
                <AlertDialog.Title className="codex-chat-alert-title">
                  Delete current session?
                </AlertDialog.Title>
                <AlertDialog.Description className="codex-chat-alert-description">
                  This removes all stored chat messages for this session. This action cannot be undone.
                </AlertDialog.Description>
                <div className="codex-chat-alert-actions">
                  <AlertDialog.Cancel asChild>
                    <button type="button" className="status-chip">
                      Cancel
                    </button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button
                      type="button"
                      className="status-chip danger-ghost"
                      disabled={isDeletingSession}
                      onClick={confirmDeleteSession}
                    >
                      {isDeletingSession ? 'Deleting...' : 'Delete session'}
                    </button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Portal>
          </AlertDialog.Root>
          <AlertDialog.Root
            open={clearChatDialogOpen}
            onOpenChange={setClearChatDialogOpen}
          >
            <AlertDialog.Portal>
              <AlertDialog.Overlay className="codex-chat-alert-overlay" />
              <AlertDialog.Content className="codex-chat-alert-content">
                <AlertDialog.Title className="codex-chat-alert-title">
                  Clear current chat?
                </AlertDialog.Title>
                <AlertDialog.Description className="codex-chat-alert-description">
                  This clears messages from the current window only. Stored history remains available in this session.
                </AlertDialog.Description>
                <div className="codex-chat-alert-actions">
                  <AlertDialog.Cancel asChild>
                    <button type="button" className="status-chip">
                      Keep messages
                    </button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button
                      type="button"
                      className="status-chip danger-ghost"
                      onClick={confirmClearChat}
                    >
                      Clear
                    </button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Portal>
          </AlertDialog.Root>
        </div>
        </div>
      </div>
    </Tooltip.Provider>
  )
}
