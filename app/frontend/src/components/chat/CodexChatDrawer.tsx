import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import { Icon } from '../shared/uiHelpers'

export function CodexChatDrawer({ state }: { state: any }) {
  if (!state.showCodexChat) return null

  return (
    <div className="drawer open" onClick={() => state.setShowCodexChat(false)}>
      <div className="drawer-body" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
          <h3 style={{ margin: 0 }}>Codex Chat</h3>
          <button className="action-icon" onClick={() => state.setShowCodexChat(false)} title="Close" aria-label="Close">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
        <p className="meta">
          General instruction mode. Session: <code>{state.codexChatSessionId}</code>
        </p>
        <div className="codex-chat-context">
          <label className="meta codex-chat-context-label" htmlFor="codex-chat-project-context">Project</label>
          <select
            className="codex-chat-context-select"
            id="codex-chat-project-context"
            value={state.codexChatProjectId}
            onChange={(e) => state.setCodexChatProjectId(e.target.value)}
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
        <div className="codex-chat-history" ref={state.codexChatHistoryRef}>
          {state.codexChatTurns.length === 0 && (
            <div className="meta">Chat is empty. Send your first instruction.</div>
          )}
          {state.codexChatTurns.map((turn: any) => (
            <div key={turn.id} className={`codex-chat-bubble ${turn.role}`}>
              <div className="codex-chat-role">{turn.role === 'user' ? 'You' : 'Codex'}</div>
              {turn.role === 'assistant' ? <MarkdownView value={turn.content} /> : <div>{turn.content}</div>}
            </div>
          ))}
        </div>
        <textarea
          value={state.codexChatInstruction}
          onChange={(e) => state.setCodexChatInstruction(e.target.value)}
          rows={5}
          style={{ width: '100%', marginTop: 8 }}
          placeholder='Example: "Create 3 tasks for tomorrow in project Test2 with High priority"'
        />
        <div className="codex-chat-toolbar">
          <button
            className="action-icon"
            onClick={() => state.setCodexChatTurns([])}
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
                .slice(-16)
                .map((t: any) => ({ role: t.role, content: t.content }))
              state.setCodexChatTurns((prev: any) => [...prev, nextUserTurn])
              state.setIsCodexChatRunning(true)
              state.setCodexChatRunStartedAt(Date.now())
              state.setCodexChatElapsedSeconds(0)
              state.runAgentChatMutation.mutate({
                instruction,
                history,
                projectId: state.codexChatProjectId.trim() ? state.codexChatProjectId : null,
              })
            }}
            disabled={state.runAgentChatMutation.isPending || !state.codexChatInstruction.trim() || !state.workspaceId}
            title="Send to Codex"
            aria-label="Send to Codex"
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
