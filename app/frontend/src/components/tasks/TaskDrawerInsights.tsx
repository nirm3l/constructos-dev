import React from 'react'
import { MarkdownView } from '../../markdown/MarkdownView'
import { Icon } from '../shared/uiHelpers'

export function TaskDrawerInsights({ state }: { state: any }) {
  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginTop: 10 }}>
        <h4 style={{ margin: 0 }}>Comments</h4>
        <span className="meta">{state.comments.data?.length ?? 0}</span>
      </div>
      <div ref={state.commentsListRef} className="note-list comment-list">
        {state.comments.isLoading && <div className="meta">Loading comments...</div>}
        {state.comments.data?.map((c: any) => (
          <div
            className="note comment-item"
            key={`${c.id}-${c.created_at}`}
            data-comment-key={`${c.id ?? 'null'}-${c.created_at ?? ''}-${c.user_id}`}
          >
            {(() => {
              const body = c.body || ''
              const commentId = c.id
              const commentKey = `${c.id ?? 'null'}-${c.created_at ?? ''}-${c.user_id}`
              const expanded = state.expandedCommentIds.has(commentKey)
              const isLong = body.length > 520 || body.split('\n').length > 14
              const author = state.actorNames[c.user_id] || 'Someone'
              const avatar = (author || 'S').trim().slice(0, 1).toUpperCase()
              return (
                <>
                  <div className="comment-gutter" aria-hidden="true">
                    <div className="comment-avatar">{avatar}</div>
                  </div>
                  <div className="comment-main">
                    <div className="comment-head">
                      <strong className="comment-author">{author}</strong>
                      <div className="row" style={{ gap: 6 }}>
                        <span className="meta">{c.created_at ? new Date(c.created_at).toLocaleString() : ''}</span>
                        {typeof commentId === 'number' && (
                          <button
                            className="action-icon danger-ghost comment-delete-btn"
                            title="Delete comment"
                            aria-label="Delete comment"
                            disabled={state.deleteCommentMutation.isPending}
                            onClick={() => {
                              if (!window.confirm('Delete this comment?')) return
                              state.deleteCommentMutation.mutate(commentId)
                            }}
                          >
                            <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                          </button>
                        )}
                      </div>
                    </div>
                    <div className={`comment-body ${isLong && !expanded ? 'collapsed' : ''}`}>
                      <MarkdownView value={body} />
                    </div>
                    {isLong && (
                      <div className="comment-actions">
                        <button
                          className="status-chip"
                          onClick={() =>
                            state.setExpandedCommentIds((prev: Set<string>) => {
                              const next = new Set(prev)
                              if (next.has(commentKey)) next.delete(commentKey)
                              else next.add(commentKey)
                              return next
                            })
                          }
                        >
                          {expanded ? 'Show less' : 'Show more'}
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )
            })()}
          </div>
        ))}
        {!state.comments.isLoading && (state.comments.data ?? []).length === 0 && <div className="meta">No comments yet.</div>}
      </div>
      <div className="comment-composer">
        <div className="comment-help meta">
          Markdown supported. Use <code>@username</code> to mention. Press <code>Enter</code> to send, <code>Shift</code> + <code>Enter</code> for a new line.
        </div>
        <textarea
          ref={state.commentInputRef}
          value={state.commentBody}
          onChange={(e) => state.setCommentBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              const body = state.commentBody.trim()
              if (!body || state.addCommentMutation.isPending) return
              state.addCommentMutation.mutate()
            }
          }}
          rows={3}
          placeholder="Write a comment..."
          disabled={state.addCommentMutation.isPending}
        />
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="meta">{state.commentBody.trim().length ? `${state.commentBody.trim().length} chars` : ''}</span>
          <button
            className="primary"
            onClick={() => state.addCommentMutation.mutate()}
            disabled={!state.commentBody.trim() || state.addCommentMutation.isPending}
          >
            {state.addCommentMutation.isPending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </div>
      <h4>Codex Automation</h4>
      <div className="automation-box">
        <div className="row wrap" style={{ marginBottom: 8 }}>
          <span className={`badge ${state.automationStatus.data?.automation_state === 'completed' ? 'done' : ''}`}>
            State: {state.automationStatus.data?.automation_state ?? 'idle'}
          </span>
          {state.automationStatus.data?.last_agent_run_at && (
            <span className="meta">Last run: {new Date(state.automationStatus.data.last_agent_run_at).toLocaleString()}</span>
          )}
        </div>
        {state.automationStatus.data?.last_agent_comment && <div className="note">{state.automationStatus.data.last_agent_comment}</div>}
        {state.automationStatus.data?.last_agent_error && <div className="notice notice-error">Runner error: {state.automationStatus.data.last_agent_error}</div>}
        <div className="row wrap" style={{ marginTop: 8 }}>
          <textarea
            value={state.automationInstruction}
            onChange={(e) => state.setAutomationInstruction(e.target.value)}
            placeholder='Instruction (e.g. "#complete", "update due date", "create related task")'
            rows={4}
            style={{ width: '100%' }}
          />
          <button
            className="primary"
            onClick={() => state.runAutomationMutation.mutate()}
            disabled={state.runAutomationMutation.isPending || !state.selectedTaskId}
          >
            Run with Codex
          </button>
        </div>
      </div>
      <h4>Activity</h4>
      <div className="row wrap" style={{ marginBottom: 8 }}>
        <label className="row archived-toggle">
          <input
            type="checkbox"
            checked={state.activityShowRawDetails}
            onChange={(e) => state.setActivityShowRawDetails(e.target.checked)}
          />
          Show raw details JSON
        </label>
      </div>
      <div className="note-list">
        {state.activity.data?.slice(0, 20).map((a: any) => {
          const summary = state.formatActivitySummary(a.action, a.details, state.actorNames[a.actor_id] || 'Someone')
          const fullDetail = summary.detail || ''
          const isLong = fullDetail.length > 180
          const expanded = state.activityExpandedIds.has(a.id)
          const visibleDetail = isLong && !expanded ? `${fullDetail.slice(0, 180)}...` : fullDetail
          const tone = state.activityTone(a.action)
          return (
            <div key={a.id} className={`note activity-note ${tone}`}>
              <div>
                <strong>{summary.title}</strong>
                <div className="meta">{visibleDetail}</div>
                {isLong && (
                  <button
                    className="status-chip"
                    onClick={() =>
                      state.setActivityExpandedIds((prev: Set<number>) => {
                        const next = new Set(prev)
                        if (next.has(a.id)) next.delete(a.id)
                        else next.add(a.id)
                        return next
                      })
                    }
                  >
                    {expanded ? 'Show less' : 'Show more'}
                  </button>
                )}
                {state.activityShowRawDetails && (
                  <pre className="activity-raw-json">{JSON.stringify(a.details, null, 2)}</pre>
                )}
                <div className="meta">{state.toReadableDate(a.created_at)}</div>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
