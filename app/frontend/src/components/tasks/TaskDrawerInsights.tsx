import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import { runTaskAutomationLiveStream } from '../../api'
import { MarkdownView } from '../../markdown/MarkdownView'
import { Icon } from '../shared/uiHelpers'

type AutomationTimelineEntry = {
  id: string
  action: 'requested' | 'started' | 'completed' | 'failed'
  title: string
  body: string
  createdAt: string | null
}

type ExecutionGate = {
  id: string
  label: string
  status: 'pass' | 'fail' | 'waiting' | 'not_applicable' | string
  blocking: boolean
  message?: string | null
}

function MetricsTooltip({
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

function normalizeAutomationStreamStatus(message: string): string {
  const text = String(message || '').trim()
  if (!text) return ''
  if (text === 'Codex started processing the request.') return ''
  if (text === 'Reasoning step completed.') return ''
  if (text === 'Automation run completed.') return ''
  return text
}

function normalizeDoctorHealthLabel(value: unknown): string {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'healthy') return 'Healthy'
  if (normalized === 'failing' || normalized === 'failed') return 'Failing'
  if (normalized === 'warning') return 'Warning'
  return 'Unknown'
}

export function TaskDrawerInsights({ state }: { state: any }) {
  const [confirmDeleteCommentId, setConfirmDeleteCommentId] = React.useState<number | null>(null)
  const [doctorFixFeedback, setDoctorFixFeedback] = React.useState<string | null>(null)
  const [doctorFixPending, setDoctorFixPending] = React.useState(false)
  const liveOutputRef = React.useRef<HTMLDivElement | null>(null)
  const automationHistoryRef = React.useRef<HTMLDivElement | null>(null)
  const selectedTaskId = String(state.selectedTaskId || '').trim()
  const lastAutomationSource = String(state.automationStatus.data?.last_requested_source || '').trim().toLowerCase()
  const automationTimeline = React.useMemo<AutomationTimelineEntry[]>(() => {
    const events = Array.isArray(state.activity.data) ? state.activity.data : []
    const entries: AutomationTimelineEntry[] = []
    const seen = new Set<string>()
    const pushUnique = (entry: AutomationTimelineEntry) => {
      const dedupeKey = `${entry.action}|${entry.title}|${entry.createdAt ?? ''}|${entry.body}`
      if (seen.has(dedupeKey)) return
      seen.add(dedupeKey)
      entries.push(entry)
    }
    for (const event of events) {
      const action = String(event?.action || '')
      const details = (event?.details && typeof event.details === 'object' ? event.details : {}) as Record<string, unknown>
      if (action === 'TaskAutomationRequested') {
        pushUnique({
          id: `${event.id}-requested`,
          action: 'requested',
          title: 'Run requested',
          body: String(details.instruction || '(no instruction)'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationStarted') {
        if (lastAutomationSource === 'manual_stream') {
          continue
        }
        const startedAt = String(details.started_at || '').trim()
        const startedLabel = startedAt
          ? `Started at ${new Date(startedAt).toLocaleString()}.`
          : 'Execution started.'
        pushUnique({
          id: `${event.id}-started`,
          action: 'started',
          title: 'Run started',
          body: startedLabel,
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationCompleted') {
        const completedBody = String(
          details.comment ||
          details.final_text ||
          details.last_agent_comment ||
          details.summary ||
          'Completed'
        )
        pushUnique({
          id: `${event.id}-completed`,
          action: 'completed',
          title: 'Run completed',
          body: completedBody,
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
        continue
      }
      if (action === 'TaskAutomationFailed') {
        pushUnique({
          id: `${event.id}-failed`,
          action: 'failed',
          title: 'Run failed',
          body: String(details.error || details.summary || 'Unknown error'),
          createdAt: typeof event.created_at === 'string' ? event.created_at : null,
        })
      }
    }
    return entries
  }, [state.activity.data, lastAutomationSource])
  const isLocalLiveRun = Boolean(
    state.automationLiveActive &&
    selectedTaskId &&
    String(state.automationLiveTaskId || '').trim() === selectedTaskId
  )
  const liveAutomationProgress = String(
    isLocalLiveRun
      ? state.automationLiveBuffer
      : (state.automationStatus.data?.last_agent_progress || '')
  )
  const liveAutomationStatusText = normalizeAutomationStreamStatus(String(
    isLocalLiveRun
      ? state.automationLiveStatusText
      : (state.automationStatus.data?.last_agent_stream_status || '')
  ))
  const rawLiveAutomationStatusText = String(
    isLocalLiveRun
      ? state.automationLiveStatusText
      : (state.automationStatus.data?.last_agent_stream_status || '')
  ).trim()
  const automationModeLabel = (() => {
    if (lastAutomationSource === 'manual_stream') return 'stream'
    if (lastAutomationSource) return 'dispatch'
    return 'unknown'
  })()
  const automationErrorCode = String(state.automationStatus.data?.last_agent_error_code || '').trim()
  const automationErrorTitle = String(state.automationStatus.data?.last_agent_error_title || '').trim()
  const automationErrorRecommendedAction = String(
    state.automationStatus.data?.last_agent_error_recommended_doctor_action_id || ''
  ).trim()
  const doctorRuntimeHealth = state.workspaceDoctorStatus?.runtime_health
  const doctorQuickActionCooldowns = (state.workspaceDoctorStatus?.quick_action_cooldowns
    && typeof state.workspaceDoctorStatus.quick_action_cooldowns === 'object')
    ? state.workspaceDoctorStatus.quick_action_cooldowns
    : {}
  const doctorActionMutation = state.executeDoctorQuickActionMutation
  const doctorFixCooldownState = (() => {
    const cooldown = doctorQuickActionCooldowns[automationErrorRecommendedAction]
    if (!cooldown || typeof cooldown !== 'object') {
      return { active: false, retryAfterSeconds: 0 }
    }
    const active = Boolean((cooldown as Record<string, unknown>).active)
    const retryAfter = Number((cooldown as Record<string, unknown>).retry_after_seconds)
    return {
      active,
      retryAfterSeconds: Number.isFinite(retryAfter) ? Math.max(0, Math.round(retryAfter)) : 0,
    }
  })()
  const doctorFixCooldownLabel = doctorFixCooldownState.active && doctorFixCooldownState.retryAfterSeconds > 0
    ? `Retry in ${doctorFixCooldownState.retryAfterSeconds}s`
    : null
  const canRunDoctorFix = Boolean(
    automationErrorRecommendedAction
    && doctorActionMutation
    && typeof doctorActionMutation.mutateAsync === 'function'
  )
  const doctorFixMutationPending = Boolean(
    doctorActionMutation?.isPending
    && String(doctorActionMutation?.variables || '').trim() === automationErrorRecommendedAction
  )
  const runDoctorFix = React.useCallback(async () => {
    if (!canRunDoctorFix || doctorFixPending || doctorFixMutationPending) return
    if (doctorFixCooldownLabel) {
      setDoctorFixFeedback(`Doctor quick action is on cooldown. ${doctorFixCooldownLabel}.`)
      return
    }
    try {
      setDoctorFixPending(true)
      setDoctorFixFeedback(null)
      const response = await doctorActionMutation.mutateAsync(automationErrorRecommendedAction)
      const message = String(response?.message || '').trim() || 'Doctor quick action completed.'
      const runtimeHealth = response?.status?.runtime_health
      const overall = normalizeDoctorHealthLabel(runtimeHealth?.overall_status)
      const primaryAction = String(runtimeHealth?.recommended_primary_action_id || '').trim()
      const runtimeSuffix = primaryAction
        ? ` Runtime health: ${overall}. Primary action: ${primaryAction}.`
        : ` Runtime health: ${overall}.`
      setDoctorFixFeedback(`${message}${runtimeSuffix}`)
      if (typeof state.openWorkspaceDoctorIncident === 'function') {
        state.openWorkspaceDoctorIncident()
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Doctor quick action failed.'
      setDoctorFixFeedback(message)
    } finally {
      setDoctorFixPending(false)
    }
  }, [
    automationErrorRecommendedAction,
    canRunDoctorFix,
    doctorActionMutation,
    doctorFixCooldownLabel,
    doctorFixMutationPending,
    doctorFixPending,
    state,
  ])
  const automationUsageRaw = state.automationStatus.data?.last_agent_usage
  const automationUsage = automationUsageRaw && typeof automationUsageRaw === 'object'
    ? (automationUsageRaw as Record<string, unknown>)
    : null
  const automationPromptModeRaw = String(
    state.automationStatus.data?.last_agent_prompt_mode
    || automationUsage?.prompt_mode
    || ''
  ).trim().toLowerCase()
  const automationPromptMode = automationPromptModeRaw === 'full' || automationPromptModeRaw === 'resume'
    ? automationPromptModeRaw
    : ''
  const automationPromptSegmentCharsRaw = (
    state.automationStatus.data?.last_agent_prompt_segment_chars
    || automationUsage?.prompt_segment_chars
  )
  const automationPromptSegmentChars = React.useMemo(() => {
    if (!automationPromptSegmentCharsRaw || typeof automationPromptSegmentCharsRaw !== 'object') return {}
    const out: Record<string, number> = {}
    for (const [key, value] of Object.entries(automationPromptSegmentCharsRaw as Record<string, unknown>)) {
      const normalizedKey = String(key || '').trim()
      if (!normalizedKey) continue
      const parsed = Number(value)
      if (!Number.isFinite(parsed) || parsed < 0) continue
      out[normalizedKey] = Math.round(parsed)
    }
    return out
  }, [automationPromptSegmentCharsRaw])
  const automationInputTokens = Number(automationUsage?.input_tokens)
  const automationCachedInputTokens = Number(automationUsage?.cached_input_tokens)
  const automationOutputTokens = Number(automationUsage?.output_tokens)
  const automationContextLimitTokens = Number(automationUsage?.context_limit_tokens)
  const automationGraphFrameMode = String(automationUsage?.graph_context_frame_mode || '').trim()
  const automationGraphFrameRevision = String(automationUsage?.graph_context_frame_revision || '').trim()
  const automationCodexSessionId = String(state.automationStatus.data?.last_agent_codex_session_id || '').trim()
  const automationResumeAttempted = state.automationStatus.data?.last_agent_codex_resume_attempted
  const automationResumeSucceeded = state.automationStatus.data?.last_agent_codex_resume_succeeded
  const automationResumeFallbackUsed = state.automationStatus.data?.last_agent_codex_resume_fallback_used
  const automationPromptTooltip = React.useMemo(() => {
    if (!automationPromptMode) return ''
    const lines: string[] = [`Prompt mode: ${automationPromptMode.toUpperCase()}`]
    if (Number.isFinite(automationInputTokens) && automationInputTokens >= 0) {
      lines.push(`Input tokens: ${Math.round(automationInputTokens)}`)
    }
    if (Number.isFinite(automationCachedInputTokens) && automationCachedInputTokens >= 0) {
      lines.push(`Cached input tokens: ${Math.round(automationCachedInputTokens)}`)
    }
    if (Number.isFinite(automationOutputTokens) && automationOutputTokens >= 0) {
      lines.push(`Output tokens: ${Math.round(automationOutputTokens)}`)
    }
    if (Number.isFinite(automationContextLimitTokens) && automationContextLimitTokens > 0) {
      lines.push(`Context limit tokens: ${Math.round(automationContextLimitTokens)}`)
    }
    if (automationGraphFrameMode) {
      lines.push(`Graph frame mode: ${automationGraphFrameMode}`)
    }
    if (automationGraphFrameRevision) {
      lines.push(`Graph frame revision: ${automationGraphFrameRevision}`)
    }
    if (automationCodexSessionId) {
      lines.push(`Codex session: ${automationCodexSessionId}`)
    }
    if (typeof automationResumeAttempted === 'boolean') {
      lines.push(`Resume attempted: ${automationResumeAttempted ? 'yes' : 'no'}`)
    }
    if (typeof automationResumeSucceeded === 'boolean') {
      lines.push(`Resume succeeded: ${automationResumeSucceeded ? 'yes' : 'no'}`)
    }
    if (typeof automationResumeFallbackUsed === 'boolean') {
      lines.push(`Resume fallback used: ${automationResumeFallbackUsed ? 'yes' : 'no'}`)
    }
    const segmentEntries = Object.entries(automationPromptSegmentChars)
      .filter(([, value]) => Number.isFinite(value) && value > 0)
      .sort((a, b) => b[1] - a[1])
    if (segmentEntries.length > 0) {
      lines.push('Segments:')
      for (const [key, value] of segmentEntries) {
        lines.push(`${key}: ${value} chars`)
      }
    }
    return lines.join('\n')
  }, [
    automationCachedInputTokens,
    automationCodexSessionId,
    automationContextLimitTokens,
    automationGraphFrameMode,
    automationGraphFrameRevision,
    automationInputTokens,
    automationOutputTokens,
    automationPromptMode,
    automationPromptSegmentChars,
    automationResumeAttempted,
    automationResumeFallbackUsed,
    automationResumeSucceeded,
  ])
  const isAutomationRunning = String(state.automationStatus.data?.automation_state || '').toLowerCase() === 'running'
  const isAutomationQueued = String(state.automationStatus.data?.automation_state || '').toLowerCase() === 'queued'
  const executionGates = React.useMemo<ExecutionGate[]>(() => {
    const raw = state.automationStatus.data?.execution_gates
    if (!Array.isArray(raw)) return []
    return raw
      .filter((item: unknown) => item && typeof item === 'object')
      .map((item: unknown) => {
        const gate = item as Record<string, unknown>
        return {
          id: String(gate.id || '').trim(),
          label: String(gate.label || gate.id || '').trim(),
          status: String(gate.status || '').trim().toLowerCase() || 'waiting',
          blocking: Boolean(gate.blocking),
          message: String(gate.message || '').trim() || null,
        }
      })
      .filter((gate) => Boolean(gate.id) && Boolean(gate.label))
  }, [state.automationStatus.data?.execution_gates])
  const executionGateSummary = React.useMemo(() => {
    let pass = 0
    let fail = 0
    let waiting = 0
    let na = 0
    let blocking = 0
    for (const gate of executionGates) {
      if (gate.blocking) blocking += 1
      if (gate.status === 'pass') pass += 1
      else if (gate.status === 'fail') fail += 1
      else if (gate.status === 'not_applicable') na += 1
      else waiting += 1
    }
    return { pass, fail, waiting, na, blocking, total: executionGates.length }
  }, [executionGates])
  const deliveryMode = String(state.selectedTask?.delivery_mode || '').trim().toLowerCase()
  const deliveryModeLabel =
    deliveryMode === 'merged_increment'
      ? 'Merged Increment'
      : deliveryMode === 'deployable_slice'
        ? 'Deployable Slice'
        : ''
  const deliveryModeCopy =
    deliveryMode === 'merged_increment'
      ? 'This task completes after committed merge evidence. It does not require its own dedicated deploy and QA runtime cycle.'
      : deliveryMode === 'deployable_slice'
        ? 'This task must pass the full Team Mode lifecycle: Developer merge, Lead deploy, and QA validation before completion.'
        : ''
  const isRecoverableLive = !isLocalLiveRun && (isAutomationRunning || isAutomationQueued)
  const [recoveredLiveText, setRecoveredLiveText] = React.useState('')
  const [recoveredLiveSnapshot, setRecoveredLiveSnapshot] = React.useState('')
  const [resumeStreamSeq, setResumeStreamSeq] = React.useState(0)
  const [resumeStreamRunId, setResumeStreamRunId] = React.useState<string | null>(null)
  const [resumeStreamConnected, setResumeStreamConnected] = React.useState(false)
  const selectedRunId = String(state.automationStatus.data?.last_agent_run_id || '').trim()
  React.useEffect(() => {
    if (!selectedRunId) {
      setResumeStreamRunId(null)
      setResumeStreamSeq(0)
      return
    }
    if (selectedRunId !== resumeStreamRunId) {
      setResumeStreamRunId(selectedRunId)
      setResumeStreamSeq(0)
      setRecoveredLiveText('')
      setRecoveredLiveSnapshot('')
    }
  }, [resumeStreamRunId, selectedRunId])
  React.useEffect(() => {
    if (!isRecoverableLive) {
      setResumeStreamConnected(false)
      return
    }
    if (!selectedTaskId || !selectedRunId) {
      setResumeStreamConnected(false)
      return
    }
    const controller = new AbortController()
    let cancelled = false
    setResumeStreamConnected(true)
    const startSeq = resumeStreamSeq
    void runTaskAutomationLiveStream(state.userId, selectedTaskId, selectedRunId, startSeq, {
      signal: controller.signal,
      onSeq: (seq) => {
        if (cancelled) return
        setResumeStreamSeq((prev) => (seq > prev ? seq : prev))
      },
      onAssistantDelta: (delta) => {
        if (cancelled || !delta) return
        setRecoveredLiveText((prev) => `${prev}${delta}`)
      },
      onStatus: (message) => {
        if (cancelled || !message) return
        setRecoveredLiveSnapshot((prev) => {
          const base = String(prev || '').trim()
          return `${base ? `${base}\n\n` : ''}${message}`
        })
      },
    }).catch(() => {
      // Silent fallback to status polling snapshot.
    }).finally(() => {
      if (!cancelled) setResumeStreamConnected(false)
    })
    return () => {
      cancelled = true
      controller.abort()
      setResumeStreamConnected(false)
    }
  }, [
    isRecoverableLive,
    selectedRunId,
    selectedTaskId,
    state.userId,
  ])
  React.useEffect(() => {
    if (resumeStreamConnected) return
    if (!isRecoverableLive) {
      setRecoveredLiveText('')
      setRecoveredLiveSnapshot('')
      return
    }
    const next = String(state.automationStatus.data?.last_agent_progress || '')
    if (!next) return
    setRecoveredLiveSnapshot((prev) => {
      const previous = String(prev || '')
      if (!previous) {
        setRecoveredLiveText(next)
        return next
      }
      if (next.startsWith(previous)) {
        const delta = next.slice(previous.length)
        if (delta) setRecoveredLiveText((current) => `${current}${delta}`)
      } else {
        setRecoveredLiveText(next)
      }
      return next
    })
  }, [isRecoverableLive, resumeStreamConnected, state.automationStatus.data?.last_agent_progress])
  const showLiveOutput = true
  const isAutomationMutationPending = Boolean(state.runAutomationMutation?.isPending)
  const displayedLiveAutomationProgress = isRecoverableLive
    ? (recoveredLiveText || liveAutomationProgress)
    : liveAutomationProgress
  const shouldHideCompletedStatusDuringLiveRun =
    isAutomationMutationPending && /completed/i.test(liveAutomationStatusText)
  const visibleLiveStatusText = shouldHideCompletedStatusDuringLiveRun ? '' : liveAutomationStatusText
  const liveOutputStickToBottomRef = React.useRef(true)
  const handleLiveOutputScroll = React.useCallback(() => {
    const el = liveOutputRef.current
    if (!el) return
    const thresholdPx = 32
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    liveOutputStickToBottomRef.current = distanceFromBottom <= thresholdPx
  }, [])
  React.useEffect(() => {
    const el = liveOutputRef.current
    if (!el) return
    if (!isAutomationRunning && !isAutomationQueued) return
    if (!liveOutputStickToBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [displayedLiveAutomationProgress, liveAutomationStatusText, isAutomationRunning, isAutomationQueued])

  React.useEffect(() => {
    const el = automationHistoryRef.current
    if (!el) return
    if (!automationTimeline.length) return
    // Keep newest automation entry in view when a new history item arrives.
    el.scrollTop = 0
  }, [automationTimeline[0]?.id, automationTimeline.length])

  return (
    <Tooltip.Provider delayDuration={180}>
      <Tabs.Root className="taskdrawer-insights-tabs" defaultValue="automation">
        <Tabs.List className="taskdrawer-insights-tabs-list" aria-label="Task insights">
          <Tabs.Trigger className="taskdrawer-insights-tab-trigger" value="automation">
            Execution
          </Tabs.Trigger>
          <Tabs.Trigger className="taskdrawer-insights-tab-trigger" value="comments">
            Comments
            <span className="taskdrawer-insights-tab-meta">{state.comments.data?.length ?? 0}</span>
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
          <h4 style={{ margin: 0 }}>Execution</h4>
          <div className="automation-box">
            <div className="row wrap" style={{ marginBottom: 8 }}>
              <span className={`badge ${state.automationStatus.data?.automation_state === 'completed' ? 'done' : ''}`}>
                State: {state.automationStatus.data?.automation_state ?? 'idle'}
              </span>
              <span className="badge">Mode: {automationModeLabel}</span>
              {automationPromptMode && (
                <MetricsTooltip content={automationPromptTooltip || 'Prompt metrics unavailable.'}>
                  <span className="badge">
                    Prompt: {automationPromptMode.toUpperCase()}
                  </span>
                </MetricsTooltip>
              )}
              {state.automationStatus.data?.last_agent_run_at && (
                <span className="meta">Last run: {new Date(state.automationStatus.data.last_agent_run_at).toLocaleString()}</span>
              )}
              {(isLocalLiveRun ? state.automationLiveUpdatedAt : state.automationStatus.data?.last_agent_stream_updated_at) && (
                <span className="meta">
                  Stream updated: {new Date(
                    isLocalLiveRun
                      ? state.automationLiveUpdatedAt
                      : state.automationStatus.data.last_agent_stream_updated_at
                  ).toLocaleString()}
                </span>
              )}
            </div>
            {showLiveOutput && (
              <div
                className="automation-history"
                aria-live="polite"
                ref={liveOutputRef}
                onScroll={handleLiveOutputScroll}
                style={{ marginBottom: 8 }}
              >
                <div className={`automation-history-item ${isAutomationRunning ? 'started' : (isAutomationQueued ? 'requested' : 'completed')}`}>
                  <div className="automation-history-head">
                    <strong>Live output</strong>
                    {visibleLiveStatusText && <span className="meta">{visibleLiveStatusText}</span>}
                  </div>
                  <div className="automation-history-body">
                    {displayedLiveAutomationProgress ? (
                      (isAutomationRunning || isAutomationQueued) ? (
                        <div className="codex-chat-streaming-text" aria-live="polite">
                          {displayedLiveAutomationProgress}
                          {isAutomationRunning && <span className="codex-chat-stream-caret" aria-hidden="true" />}
                        </div>
                      ) : (
                        <MarkdownView value={liveAutomationProgress} />
                      )
                    ) : (
                      <div className="meta">
                        {rawLiveAutomationStatusText || (
                          isAutomationQueued
                            ? 'Queued...'
                            : isAutomationRunning
                              ? 'Running...'
                              : 'No live output yet.'
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            {automationTimeline.length > 0 ? (
              <div className="automation-history" aria-live="polite" ref={automationHistoryRef}>
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
              <div className="meta">No execution responses yet.</div>
            )}
            {state.automationStatus.data?.last_agent_error && (
              <div className="notice notice-error">
                <div>Runner error: {state.automationStatus.data.last_agent_error}</div>
                {(automationErrorCode || automationErrorTitle || automationErrorRecommendedAction) ? (
                  <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
                    {automationErrorCode ? <span className="badge">Code: {automationErrorCode}</span> : null}
                    {automationErrorTitle ? <span className="badge">Type: {automationErrorTitle}</span> : null}
                    {automationErrorRecommendedAction ? (
                      <span className="badge">Doctor action: {automationErrorRecommendedAction}</span>
                    ) : null}
                    {doctorRuntimeHealth ? (
                      <span className="badge">
                        Doctor runtime: {normalizeDoctorHealthLabel(doctorRuntimeHealth.overall_status)}
                      </span>
                    ) : null}
                    {canRunDoctorFix ? (
                      <button
                        type="button"
                        className="status-chip"
                        disabled={doctorFixPending || doctorFixMutationPending || Boolean(doctorFixCooldownLabel)}
                        onClick={() => { void runDoctorFix() }}
                      >
                        {(doctorFixPending || doctorFixMutationPending)
                          ? 'Running Doctor fix...'
                          : (doctorFixCooldownLabel || 'Run Doctor fix')}
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {doctorFixFeedback ? (
                  <div className="meta" style={{ marginTop: 6 }}>{doctorFixFeedback}</div>
                ) : null}
              </div>
            )}
            {(state.automationStatus.data?.last_requested_source || state.automationStatus.data?.last_requested_reason) ? (
              <div className="automation-gates" style={{ marginTop: 8 }}>
                <div className="automation-gates-head">
                  <strong>Workflow communication</strong>
                </div>
                <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
                  {state.automationStatus.data?.last_requested_source ? (
                    <span className="badge">Source: {String(state.automationStatus.data.last_requested_source)}</span>
                  ) : null}
                  {state.automationStatus.data?.last_requested_reason ? (
                    <span className="badge">Reason: {String(state.automationStatus.data.last_requested_reason)}</span>
                  ) : null}
                  {state.automationStatus.data?.last_requested_source_task_id ? (
                    <span className="badge">From task: {String(state.automationStatus.data.last_requested_source_task_id)}</span>
                  ) : null}
                </div>
                <div className="meta">
                  {state.automationStatus.data?.last_dispatch_decision && typeof state.automationStatus.data.last_dispatch_decision === 'object' ? (
                    <>
                      Dispatch: <code>{JSON.stringify(state.automationStatus.data.last_dispatch_decision)}</code><br />
                    </>
                  ) : null}
                  {state.automationStatus.data?.last_requested_trigger_link ? (
                    <>Trigger link: <code>{String(state.automationStatus.data.last_requested_trigger_link)}</code><br /></>
                  ) : null}
                  {state.automationStatus.data?.last_requested_correlation_id ? (
                    <>Correlation: <code>{String(state.automationStatus.data.last_requested_correlation_id)}</code></>
                  ) : null}
                </div>
              </div>
            ) : null}
            {(state.automationStatus.data?.last_ignored_request_source || state.automationStatus.data?.last_ignored_request_reason) ? (
              <div className="automation-gates" style={{ marginTop: 8 }}>
                <div className="automation-gates-head">
                  <strong>Ignored workflow trigger</strong>
                </div>
                <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
                  {state.automationStatus.data?.last_ignored_request_source ? (
                    <span className="badge">Source: {String(state.automationStatus.data.last_ignored_request_source)}</span>
                  ) : null}
                  {state.automationStatus.data?.last_ignored_request_reason ? (
                    <span className="badge">Reason: {String(state.automationStatus.data.last_ignored_request_reason)}</span>
                  ) : null}
                  {state.automationStatus.data?.last_ignored_request_source_task_id ? (
                    <span className="badge">From task: {String(state.automationStatus.data.last_ignored_request_source_task_id)}</span>
                  ) : null}
                </div>
                <div className="meta">
                  {state.automationStatus.data?.last_ignored_request_trigger_link ? (
                    <>Trigger link: <code>{String(state.automationStatus.data.last_ignored_request_trigger_link)}</code><br /></>
                  ) : null}
                  {state.automationStatus.data?.last_ignored_request_correlation_id ? (
                    <>Correlation: <code>{String(state.automationStatus.data.last_ignored_request_correlation_id)}</code></>
                  ) : null}
                </div>
              </div>
            ) : null}
            <div className="automation-gates">
              <div className="automation-gates-head">
                <strong>Execution gates</strong>
                <div className="row wrap" style={{ gap: 6 }}>
                  {state.automationStatus.data?.team_mode_phase ? (
                    <span className="badge">Phase: {String(state.automationStatus.data.team_mode_phase)}</span>
                  ) : null}
                  {deliveryModeLabel ? (
                    <span className="badge">Delivery: {deliveryModeLabel}</span>
                  ) : null}
                  {state.automationStatus.data?.last_lead_handoff_token ? (
                    <span className="badge status-done">Lead handoff recorded</span>
                  ) : null}
                  <span className="badge">Total: {executionGateSummary.total}</span>
                  <span className="badge">Blocking: {executionGateSummary.blocking}</span>
                  {executionGateSummary.fail > 0 ? <span className="badge status-blocked">Fail: {executionGateSummary.fail}</span> : null}
                  {executionGateSummary.waiting > 0 ? <span className="badge">Waiting: {executionGateSummary.waiting}</span> : null}
                  {executionGateSummary.pass > 0 ? <span className="badge status-done">Pass: {executionGateSummary.pass}</span> : null}
                  {executionGateSummary.na > 0 ? <span className="badge">N/A: {executionGateSummary.na}</span> : null}
                </div>
              </div>
              <div className="meta" style={{ marginBottom: 8 }}>
                Deterministic runner gates for this task execution role and status.
              </div>
              {deliveryModeCopy ? (
                <div className="meta" style={{ marginBottom: 8 }}>
                  {deliveryModeCopy}
                </div>
              ) : null}
              {executionGates.length > 0 ? (
                <div className="automation-gates-list">
                  {executionGates.map((gate) => {
                    const toneClass =
                      gate.status === 'pass'
                        ? 'status-done'
                        : gate.status === 'fail'
                          ? 'status-blocked'
                          : ''
                    const statusLabel =
                      gate.status === 'not_applicable'
                        ? 'N/A'
                        : gate.status.toUpperCase()
                    return (
                      <div key={gate.id} className="automation-gate-row">
                        <div className="automation-gate-copy">
                          <code>{gate.id}</code>
                          <strong>{gate.label}</strong>
                          {gate.message ? <span className="meta">{gate.message}</span> : null}
                        </div>
                        <div className="row wrap" style={{ gap: 6, alignItems: 'center', justifyContent: 'flex-end' }}>
                          {gate.blocking ? <span className="badge">Blocking</span> : <span className="badge">Info</span>}
                          <span className={`badge ${toneClass}`.trim()}>{statusLabel}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="meta">
                  No execution gates apply to this task right now. Gates appear for Team Mode/Git Delivery tasks when their current role and semantic status activate deterministic checks.
                </div>
              )}
            </div>
            <div className="row wrap" style={{ marginTop: 8 }}>
              <textarea
                value={state.automationInstruction}
                onChange={(e) => state.setAutomationInstruction(e.target.value)}
                placeholder='Instruction (default streams now; prefix with "#dispatch" to queue workflow execution)'
                rows={4}
                style={{ width: '100%' }}
              />
              <button
                className="primary"
                onClick={() => state.runAutomationMutation.mutate()}
                disabled={state.runAutomationMutation.isPending || !state.selectedTaskId}
              >
                Run now
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
    </Tooltip.Provider>
  )
}
