import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { MarkdownView } from '../../markdown/MarkdownView'
import { Icon } from '../shared/uiHelpers'

type AutomationTimelineEntry = {
  id: string
  action: 'requested' | 'started' | 'completed' | 'failed'
  title: string
  body: string
  createdAt: string | null
}

export function TaskDrawerInsights({ state }: { state: any }) {
  const [confirmDeleteCommentId, setConfirmDeleteCommentId] = React.useState<number | null>(null)
  const automationTimeline = React.useMemo<AutomationTimelineEntry[]>(() => {
    const events = Array.isArray(state.activity.data) ? state.activity.data : []
    const entries: AutomationTimelineEntry[] = []
    for (const event of events) {
      const action = String(event?.action || '')
      const details = (event?.details && typeof event.details === 'object' ? event.details : {}) as Record<string, unknown>
      if (action === 'TaskAutomationRequested') {
        entries.push({
          id: `${event.id}-requested`,
          action: 'requested',
          title: 'Run requested',
          body: String(details.instruction || '(no instruction)'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationStarted') {
        entries.push({
          id: `${event.id}-started`,
          action: 'started',
          title: 'Run started',
          body: String(details.started_at ? `Started at: ${String(details.started_at)}` : 'Execution started.'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationCompleted') {
        entries.push({
          id: `${event.id}-completed`,
          action: 'completed',
          title: 'Run completed',
          body: String(details.summary || 'Completed'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationFailed') {
        entries.push({
          id: `${event.id}-failed`,
          action: 'failed',
          title: 'Run failed',
          body: String(details.error || details.summary || 'Unknown error'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
      }
    }
    return entries
  }, [state.activity.data])

  return (
    <>
      <Tabs.Root className="taskdrawer-insights-tabs" defaultValue="comments">
        <Tabs.List className="taskdrawer-insights-tabs-list" aria-label="Task insights">
          <Tabs.Trigger className="taskdrawer-insights-tab-trigger" value="comments">
            Comments
            <span className="taskdrawer-insights-tab-meta">{state.comments.data?.length ?? 0}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="taskdrawer-insights-tab-trigger" value="automation">
            Automation
          </Tabs.Trigger>
          <Tabs.Trigger className="taskdrawer-insights-tab-trigger" value="activity">
            Activity
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className="taskdrawer-insights-content" value="comments">
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
                                onClick={() => setConfirmDeleteCommentId(commentId)}
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
        </Tabs.Content>

        <Tabs.Content className="taskdrawer-insights-content" value="automation">
          <h4 style={{ margin: 0 }}>Codex Automation</h4>
          <div className="automation-box">
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <span className={`badge ${state.automationStatus.data?.automation_state === 'completed' ? 'done' : ''}`}>
                State: {state.automationStatus.data?.automation_state ?? 'idle'}
              </span>
              {state.automationStatus.data?.last_agent_run_at && (
                <span className="meta">Last run: {new Date(state.automationStatus.data.last_agent_run_at).toLocaleString()}</span>
              )}
            </div>
            {automationTimeline.length > 0 ? (
              <div className="automation-history" aria-live="polite">
                {automationTimeline.map((entry) => (
                  <div key={entry.id} className={`automation-history-item ${entry.action}`}>
                    <div className="automation-history-head">
                      <strong>{entry.title}</strong>
                      {entry.createdAt && (
                        <span className="meta">{new Date(entry.createdAt).toLocaleString()}</span>
                      )}
                    </div>
                    <div className="automation-history-body">
                      <MarkdownView value={entry.body} />
                    </div>
                  </div>
                ))}
              </div>
            ) : state.automationStatus.data?.last_agent_comment ? (
              <div className="automation-history">
                <div className="automation-history-item completed">
                  <div className="automation-history-head">
                    <strong>Last response</strong>
                  </div>
                  <div className="automation-history-body">
                    <MarkdownView value={state.automationStatus.data.last_agent_comment} />
                  </div>
                </div>
              </div>
            ) : (
              <div className="meta">No automation responses yet.</div>
            )}
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
        </Tabs.Content>

        <Tabs.Content className="taskdrawer-insights-content" value="activity">
          <h4 style={{ margin: 0 }}>Activity</h4>
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
        </Tabs.Content>
      </Tabs.Root>
      <AlertDialog.Root
        open={confirmDeleteCommentId !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDeleteCommentId(null)
        }}
      >
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="codex-chat-alert-overlay" />
          <AlertDialog.Content className="codex-chat-alert-content">
            <AlertDialog.Title className="codex-chat-alert-title">
              Delete comment?
            </AlertDialog.Title>
            <AlertDialog.Description className="codex-chat-alert-description">
              This action cannot be undone.
            </AlertDialog.Description>
            <div className="codex-chat-alert-actions">
              <AlertDialog.Cancel asChild>
                <button className="status-chip" type="button">Cancel</button>
              </AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <button
                  className="status-chip"
                  type="button"
                  disabled={state.deleteCommentMutation.isPending}
                  onClick={() => {
                    const commentId = confirmDeleteCommentId
                    if (typeof commentId !== 'number') return
                    state.deleteCommentMutation.mutate(commentId)
                    setConfirmDeleteCommentId(null)
                  }}
                >
                  {state.deleteCommentMutation.isPending ? 'Deleting...' : 'Delete'}
                </button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </>
  )
}
