import React from 'react'
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
  return [
    'Help me create a new project through a strict interactive setup flow.',
    'Workflow requirements (mandatory):',
    '1. Ask one clarifying question at a time for missing inputs.',
    '2. Collect and confirm these discovery fields before any create call: project goal/domain, setup strategy (template or manual), project name, and key defaults/overrides.',
    '3. If template setup is chosen, list templates, show chosen template details, and run preview_project_from_template before create.',
    '4. Do not call create_project or create_project_from_template until I explicitly say: confirm create.',
    '5. After creation, ask whether seeded tasks/specifications/rules should be adjusted for this project, and apply updates if requested.',
    '6. Return a clickable project link in this format: ?tab=projects&project=<project_id>.',
  ].join('\n')
}

const CHAT_INPUT_MIN_HEIGHT_PX = 64
const CHAT_INPUT_MAX_HEIGHT_PX = 116

function normalizeMcpLookupKey(value: string): string {
  return String(value || '').trim().toLowerCase().replace(/_/g, '-')
}

const CORE_MCP_LOOKUP_KEYS = new Set(['task-management-tools'])

export function CodexChatDrawer({ state }: { state: any }) {
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [chatAttachmentRefs, setChatAttachmentRefs] = React.useState<AttachmentRef[]>([])
  const recognitionRef = React.useRef<any>(null)
  const speechBaseInstructionRef = React.useRef('')
  const speechHadResultRef = React.useRef(false)
  const speechStoppedManuallyRef = React.useRef(false)
  const [isListening, setIsListening] = React.useState(false)
  const [speechSupported, setSpeechSupported] = React.useState(false)
  const [showVoiceLangHint, setShowVoiceLangHint] = React.useState(false)

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
  sessions.sort((a: any, b: any) => (Number(b?.updatedAt) || 0) - (Number(a?.updatedAt) || 0))
  const activeSession = sessions.find((session: any) => session.id === state.codexChatActiveSessionId) ?? null
  const activeSessionUpdatedAt = activeSession?.updatedAt
    ? new Date(activeSession.updatedAt).toLocaleString(undefined, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
    : null
  const hasMessages = state.codexChatTurns.length > 0
  const availableMcpServers = (() => {
    if (!Array.isArray(state.bootstrap.data?.agent_chat_available_mcp_servers)) return []
    const seen = new Set<string>()
    const out: Array<{
      name: string
      display_name: string
      enabled: boolean
      disabled_reason: string | null
      auth_status: string | null
    }> = []
    for (const item of state.bootstrap.data.agent_chat_available_mcp_servers) {
      const name = String(item?.name || '').trim()
      if (!name) continue
      const key = normalizeMcpLookupKey(name)
      if (seen.has(key)) continue
      seen.add(key)
      const displayName = String(item?.display_name || '').trim() || name
      out.push({
        name,
        display_name: displayName,
        enabled: Boolean(item?.enabled),
        disabled_reason: String(item?.disabled_reason || '').trim() || null,
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
  const selectedMcpServers = (() => {
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
    if (!hasDiscoveredServers) return coreMcpServerName ? [coreMcpServerName] : []
    const defaultEnabled = availableMcpServers.filter((server) => server.enabled).map((server) => server.name)
    if (defaultEnabled.length > 0) {
      if (coreMcpServerName && !defaultEnabled.some((name) => normalizeMcpLookupKey(name) === normalizeMcpLookupKey(coreMcpServerName))) {
        defaultEnabled.unshift(coreMcpServerName)
      }
      return defaultEnabled
    }
    const allServers = availableMcpServers.map((server) => server.name)
    if (coreMcpServerName && !allServers.some((name) => normalizeMcpLookupKey(name) === normalizeMcpLookupKey(coreMcpServerName))) {
      allServers.unshift(coreMcpServerName)
    }
    return allServers
  })()
  const lastTurnId = state.codexChatTurns.length > 0
    ? state.codexChatTurns[state.codexChatTurns.length - 1]?.id ?? null
    : null
  const contextSummary = inputTokens !== null
    ? (contextLimitTokens && usagePercent !== null ? `Context ${usagePercent}%` : `Context ${inputTokens.toLocaleString()}`)
    : null
  const hasContext = contextSummary !== null
  const metaParts: string[] = []
  if (hasMessages) metaParts.push(`${state.codexChatTurns.length} ${state.codexChatTurns.length === 1 ? 'message' : 'messages'}`)
  if (activeSessionUpdatedAt && (hasMessages || hasContext)) metaParts.push(activeSessionUpdatedAt)
  if (contextSummary) metaParts.push(contextSummary)
  const canDeleteSession = Array.isArray(state.codexChatSessions) && state.codexChatSessions.length > 1 && !state.runAgentChatMutation.isPending
  const canUseProjectCreationStarter =
    !state.runAgentChatMutation.isPending &&
    !state.isCodexChatRunning &&
    Boolean(state.workspaceId)
  const canQuickConfirmCreate =
    canUseProjectCreationStarter && Boolean(state.workspaceId) && state.codexChatTurns.length > 0
  const activeSpeechLang = String(state.speechLang || '').trim() || 'en-US'
  const speechLangName = activeSpeechLang === 'bs-BA' ? 'Bosnian' : 'English'
  const speechLangLabel = `${speechLangName} (${activeSpeechLang})`

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
    if (state.runAgentChatMutation.isPending || isListening) return

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

  const statusText = state.isCodexChatRunning
    ? `Executing tools... ${state.codexChatElapsedSeconds}s`
    : isListening
      ? 'Listening...'
      : ''
  const canStopChat = Boolean(
    state.isCodexChatRunning &&
    state.runAgentChatMutation.isPending &&
    typeof state.cancelAgentChat === 'function'
  )
  const mcpControlsDisabled = state.runAgentChatMutation.isPending

  const toggleMcpServer = (serverName: string, nextEnabled: boolean) => {
    if (typeof state.setCodexChatMcpServers !== 'function') return
    const serverLookupKey = normalizeMcpLookupKey(serverName)
    if (CORE_MCP_LOOKUP_KEYS.has(serverLookupKey)) return
    const current = [...selectedMcpServers]
    const next = nextEnabled
      ? [...current, serverName]
      : current.filter((name) => normalizeMcpLookupKey(name) !== serverLookupKey)
    const deduped: string[] = []
    const seen = new Set<string>()
    for (const name of next) {
      const normalized = normalizeMcpLookupKey(name)
      if (!normalized || seen.has(normalized)) continue
      seen.add(normalized)
      deduped.push(name)
    }
    state.setCodexChatMcpServers(deduped)
  }

  const applyProjectCreationStarter = () => {
    if (!canUseProjectCreationStarter) return
    state.setUiError(null)
    sendChatInstruction(buildProjectCreationStarter())
  }

  const sendChatInstruction = (rawInstruction: string, opts?: { clearInput?: boolean }) => {
    if (isListening) stopVoiceInput()
    const instruction = String(rawInstruction || '').trim()
    if (!instruction || state.runAgentChatMutation.isPending || !state.workspaceId) return
    if (opts?.clearInput) state.setCodexChatInstruction('')
    const nextUserTurn = {
      id: globalThis.crypto?.randomUUID?.() ?? `u-${Date.now()}`,
      role: 'user',
      content: instruction,
      createdAt: Date.now()
    }
    const history = [...state.codexChatTurns, nextUserTurn]
      .slice(-80)
      .map((t: any) => ({ role: t.role, content: t.content }))
    state.setCodexChatTurns((prev: any) => [...prev, nextUserTurn])
    state.setIsCodexChatRunning(true)
    state.setCodexChatRunStartedAt(Date.now())
    state.setCodexChatElapsedSeconds(0)
    state.runAgentChatMutation.mutate({
      instruction,
      history,
      sessionId: state.codexChatSessionId,
      projectId: state.codexChatProjectId.trim() ? state.codexChatProjectId : null,
      mcpServers: selectedMcpServers,
      attachmentRefs: chatAttachmentRefs,
    })
  }

  return (
    <div className="drawer open" onClick={() => state.setShowCodexChat(false)}>
      <div className="drawer-body codex-chat-drawer-body" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
          <h3 style={{ margin: 0 }}>Chat</h3>
          <button className="action-icon" onClick={() => state.setShowCodexChat(false)} title="Close" aria-label="Close">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
        <div className="codex-chat-context-top-row">
          <div className="codex-chat-context">
            <label className="meta codex-chat-context-label" htmlFor="codex-chat-project-context">Project</label>
            <select
              className="codex-chat-context-select"
              id="codex-chat-project-context"
              value={state.codexChatProjectId}
              onChange={(e) => state.selectCodexChatProject(e.target.value)}
              disabled={state.runAgentChatMutation.isPending}
            >
              <option value="">No project</option>
              {(state.bootstrap.data?.projects ?? []).map((p: any) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="codex-chat-mcp-row">
            <span className="meta codex-chat-context-label">MCP</span>
            <div className="codex-chat-mcp-chips">
              {availableMcpServers.length === 0 && (
                <span className="meta">No MCP servers</span>
              )}
              {availableMcpServers.map((server) => {
                const serverLookupKey = normalizeMcpLookupKey(server.name)
                const isCoreServer = CORE_MCP_LOOKUP_KEYS.has(serverLookupKey)
                const selected = selectedMcpServers.some((name) => normalizeMcpLookupKey(name) === normalizeMcpLookupKey(server.name))
                const chipDisabled = mcpControlsDisabled || !server.enabled || isCoreServer
                const titleParts: string[] = []
                if (isCoreServer) {
                  titleParts.push('Core MCP server is always enabled in this chat session')
                } else {
                  titleParts.push(server.enabled ? `Use ${server.display_name} in this chat session` : `${server.display_name} is disabled`)
                }
                if (server.auth_status) titleParts.push(`Auth: ${server.auth_status}`)
                if (server.disabled_reason) titleParts.push(server.disabled_reason)
                return (
                  <button
                    key={server.name}
                    type="button"
                    className={`status-chip tag-filter-chip codex-chat-mcp-chip-btn ${selected ? 'active' : ''}`}
                    disabled={chipDisabled}
                    aria-pressed={selected}
                    title={titleParts.join(' · ')}
                    onClick={() => toggleMcpServer(server.name, !selected)}
                  >
                    {isCoreServer ? 'Core' : server.display_name}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
        <div className="codex-chat-session-row">
          <label className="meta codex-chat-session-label" htmlFor="codex-chat-session-select">Session</label>
          <select
            className="codex-chat-session-select"
            id="codex-chat-session-select"
            value={state.codexChatActiveSessionId}
            onChange={(e) => state.setCodexChatActiveSessionId(e.target.value)}
            disabled={state.runAgentChatMutation.isPending || sessions.length === 0}
          >
            {sessions.length === 0 && <option value="">No sessions</option>}
            {sessions.map((session: any) => (
              <option key={session.id} value={session.id}>{session.title}</option>
            ))}
          </select>
          <button
            className="action-icon"
            onClick={() => {
              const nextSessionId = state.createCodexChatSession({ projectId: state.codexChatProjectId || '' })
              if (nextSessionId) state.setCodexChatActiveSessionId(nextSessionId)
            }}
            disabled={state.runAgentChatMutation.isPending}
            title="New session"
            aria-label="New session"
          >
            <Icon path="M12 5v14M5 12h14" />
          </button>
          <button
            className="action-icon"
            onClick={() => {
              if (!canDeleteSession) return
              const confirmed = typeof window === 'undefined'
                ? true
                : window.confirm('Delete current chat session and all stored history for it?')
              if (!confirmed) return
              state.deleteCodexChatSession(state.codexChatActiveSessionId)
            }}
            disabled={!canDeleteSession}
            title="Delete session"
            aria-label="Delete session"
          >
            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
          </button>
        </div>
        {metaParts.length > 0 && (
          <div className="meta codex-chat-session-meta">
            {metaParts.map((part, idx) => <span key={`${idx}-${part}`}>{part}</span>)}
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
          {state.codexChatTurns.map((turn: any) => (
            <div key={turn.id} className={`codex-chat-bubble ${turn.role}`}>
              <div className="codex-chat-role">
                {turn.role === 'user' ? 'You' : 'Assistant'}
                {turn.createdAt ? ` · ${new Date(turn.createdAt).toLocaleTimeString()}` : ''}
              </div>
              {turn.role === 'assistant' ? (
                <MarkdownView
                  value={turn.content}
                  disableMermaid={Boolean(state.isCodexChatRunning && turn.id === lastTurnId)}
                />
              ) : (
                <div>{turn.content}</div>
              )}
            </div>
          ))}
        </div>
        <div className="codex-chat-composer">
          <textarea
            ref={inputRef}
            className="codex-chat-input"
            value={state.codexChatInstruction}
            onChange={(e) => state.setCodexChatInstruction(e.target.value)}
            rows={2}
            placeholder='Example: "Create 3 tasks for tomorrow in project Test2 with High priority"'
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
              <button
                className="status-chip"
                type="button"
                disabled={!canQuickConfirmCreate}
                onClick={() => sendChatInstruction('confirm create')}
              >
                Confirm create
              </button>
              <span className="meta">
                No project is selected, so chat can create a new one interactively.
              </span>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            style={{ display: 'none' }}
            onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (!file || !state.codexChatProjectId.trim()) return
              try {
                const ref = await state.uploadAttachmentRef(file, { project_id: state.codexChatProjectId })
                setChatAttachmentRefs((prev) => [...prev, ref])
                state.setUiError(null)
              } catch (err: any) {
                state.setUiError(err?.message || 'Chat attachment upload failed')
              }
            }}
          />
          <AttachmentRefList
            refs={chatAttachmentRefs}
            workspaceId={state.workspaceId}
            userId={state.userId}
            onRemovePath={(path) => setChatAttachmentRefs((prev) => prev.filter((ref) => ref.path !== path))}
          />
          <div className="codex-chat-toolbar">
            <button
              className={`action-icon ${isListening ? 'primary' : ''}`}
              onClick={() => {
                setShowVoiceLangHint(true)
                if (isListening) {
                  stopVoiceInput()
                  return
                }
                startVoiceInput()
              }}
              disabled={state.runAgentChatMutation.isPending || !speechSupported}
              title={
                speechSupported
                  ? `${isListening ? 'Stop voice input' : 'Start voice input'} (${speechLangLabel}). Change in Settings > Profile.`
                  : 'Voice input is not supported in this browser'
              }
              aria-label={isListening ? 'Stop voice input' : 'Start voice input'}
            >
              <Icon path="M12 15a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0m5 5v4m-4 0h8" />
            </button>
            {showVoiceLangHint ? (
              <button
                type="button"
                className="codex-chat-voice-chip"
                onClick={() => {
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
                }}
                title={`Voice language: ${speechLangLabel}. Open Settings > Profile to change.`}
                aria-label="Open voice language settings"
              >
                Voice: {speechLangName}
              </button>
            ) : null}
            <button
              className="action-icon"
              onClick={() => {
                if (!state.codexChatProjectId.trim()) {
                  state.setUiError('Select a project before attaching files to chat.')
                  return
                }
                fileInputRef.current?.click()
              }}
              disabled={state.runAgentChatMutation.isPending}
              title="Attach file"
              aria-label="Attach file"
            >
              <Icon path="M21.44 11.05l-8.49 8.49a5.5 5.5 0 0 1-7.78-7.78l9.19-9.2a3.5 3.5 0 1 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.48-8.49" />
            </button>
            <button
              className="action-icon"
              onClick={() => {
                stopVoiceInput()
                state.setCodexChatTurns([])
                state.setCodexChatUsage(null)
                setChatAttachmentRefs([])
              }}
              disabled={state.runAgentChatMutation.isPending || state.codexChatTurns.length === 0}
              title="Clear chat"
              aria-label="Clear chat"
            >
              <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
            </button>
            <span className={`codex-chat-status ${state.isCodexChatRunning || isListening ? 'codex-progress' : ''}`}>
              {statusText}
            </span>
            {canStopChat && (
              <button
                className="action-icon danger-ghost"
                onClick={() => {
                  state.cancelAgentChat()
                }}
                title="Stop generating"
                aria-label="Stop generating"
              >
                <Icon path="M8 8h8v8H8z" />
              </button>
            )}
            <button
              className="action-icon primary"
              onClick={() => {
                sendChatInstruction(state.codexChatInstruction, { clearInput: true })
              }}
              disabled={state.runAgentChatMutation.isPending || !state.codexChatInstruction.trim() || !state.workspaceId}
              title="Send"
              aria-label="Send"
            >
              <Icon path="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z" />
            </button>
          </div>
          {state.codexChatLastTaskEventAt && (
            <div className="row wrap" style={{ marginTop: 8 }}>
              <span className="meta">Last task event: {new Date(state.codexChatLastTaskEventAt).toLocaleTimeString()}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
