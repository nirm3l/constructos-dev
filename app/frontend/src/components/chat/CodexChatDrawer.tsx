import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import type { AttachmentRef } from '../../types'
import { AttachmentRefList, Icon } from '../shared/uiHelpers'

export function CodexChatDrawer({ state }: { state: any }) {
  const fileInputRef = React.useRef<HTMLInputElement | null>(null)
  const [chatAttachmentRefs, setChatAttachmentRefs] = React.useState<AttachmentRef[]>([])

  React.useEffect(() => {
    setChatAttachmentRefs([])
  }, [state.codexChatSessionId, state.codexChatProjectId])

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
  const contextSummary = inputTokens !== null
    ? (contextLimitTokens && usagePercent !== null ? `Context ${usagePercent}%` : `Context ${inputTokens.toLocaleString()}`)
    : null
  const hasContext = contextSummary !== null
  const metaParts: string[] = []
  if (hasMessages) metaParts.push(`${state.codexChatTurns.length} ${state.codexChatTurns.length === 1 ? 'message' : 'messages'}`)
  if (activeSessionUpdatedAt && (hasMessages || hasContext)) metaParts.push(activeSessionUpdatedAt)
  if (contextSummary) metaParts.push(contextSummary)
  const canDeleteSession = Array.isArray(state.codexChatSessions) && state.codexChatSessions.length > 1 && !state.runAgentChatMutation.isPending

  return (
    <div className="drawer open" onClick={() => state.setShowCodexChat(false)}>
      <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
          <h3 style={{ margin: 0 }}>Chat</h3>
          <button className="action-icon" onClick={() => state.setShowCodexChat(false)} title="Close" aria-label="Close">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
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
              {turn.role === 'assistant' ? <MarkdownView value={turn.content} /> : <div>{turn.content}</div>}
            </div>
          ))}
        </div>
        <textarea
          className="codex-chat-input"
          value={state.codexChatInstruction}
          onChange={(e) => state.setCodexChatInstruction(e.target.value)}
          rows={5}
          placeholder='Example: "Create 3 tasks for tomorrow in project Test2 with High priority"'
        />
        <div className="row wrap" style={{ marginTop: 8, alignItems: 'center', gap: 8 }}>
          <button
            className="status-chip"
            type="button"
            disabled={state.runAgentChatMutation.isPending || !state.codexChatProjectId.trim()}
            onClick={() => {
              if (!state.codexChatProjectId.trim()) {
                state.setUiError('Select a project before attaching files to chat.')
                return
              }
              fileInputRef.current?.click()
            }}
          >
            Attach file
          </button>
          <span className="meta">Attached text files are sent with your chat instruction.</span>
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
        </div>
        <AttachmentRefList
          refs={chatAttachmentRefs}
          workspaceId={state.workspaceId}
          userId={state.userId}
          onRemovePath={(path) => setChatAttachmentRefs((prev) => prev.filter((ref) => ref.path !== path))}
        />
        <div className="codex-chat-toolbar">
          <button
            className="action-icon"
            onClick={() => {
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
          <span className={`codex-chat-status ${state.isCodexChatRunning ? 'codex-progress' : ''}`}>
            {state.isCodexChatRunning ? `Executing tools... ${state.codexChatElapsedSeconds}s` : ''}
          </span>
          <button
            className="action-icon primary"
            onClick={() => {
              const instruction = state.codexChatInstruction.trim()
              if (!instruction) return
              state.setCodexChatInstruction('')
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
                attachmentRefs: chatAttachmentRefs,
              })
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
  )
}
