import React from 'react'

export type TeamModeAutomationTranscriptEventItem = {
  event_type: string
  index: number
  at: string | null
  phase: string | null
  reason: string | null
  queued_task_ids: string[]
  blocked_reasons: string[]
  verify_fix_attempt_count: number
  verify_fix_fix_attempt_count: number
  verify_fix_runner_error_count: number
  summary_text: string | null
}

export function buildTeamModeAutomationTranscriptMeta(event: TeamModeAutomationTranscriptEventItem): string {
  const parts: string[] = [`idx=${event.index}`]
  if (event.at) parts.push(`at=${event.at}`)
  if (event.phase) parts.push(`phase=${event.phase}`)
  if (event.reason) parts.push(`reason=${event.reason}`)
  if (event.queued_task_ids.length > 0) parts.push(`queued=${event.queued_task_ids.length}`)
  if (event.blocked_reasons.length > 0) parts.push(`blocked=${event.blocked_reasons[0]}`)
  if (event.verify_fix_attempt_count > 0) parts.push(`attempts=${event.verify_fix_attempt_count}`)
  if (event.verify_fix_fix_attempt_count > 0) parts.push(`fixes=${event.verify_fix_fix_attempt_count}`)
  if (event.verify_fix_runner_error_count > 0) parts.push(`runnerErrors=${event.verify_fix_runner_error_count}`)
  if (event.summary_text) parts.push(event.summary_text)
  return parts.join(' · ')
}

export function TeamModeAutomationTranscriptList({
  transcript,
  limit = 12,
}: {
  transcript: TeamModeAutomationTranscriptEventItem[]
  limit?: number
}) {
  if (!Array.isArray(transcript) || transcript.length <= 0) {
    return (
      <div className="meta" style={{ marginTop: 8 }}>
        No transcript events are currently available for this session.
      </div>
    )
  }
  const [eventFilter, setEventFilter] = React.useState<string>('all')
  const [sortOrder, setSortOrder] = React.useState<'newest' | 'oldest'>('newest')
  const normalizedLimit = Math.max(1, Number(limit || 12))
  const eventTypeOptions = React.useMemo(() => {
    const uniqueTypes = Array.from(new Set(transcript.map((item) => String(item.event_type || '').trim()).filter(Boolean)))
    uniqueTypes.sort((a, b) => a.localeCompare(b))
    return uniqueTypes
  }, [transcript])
  const filteredTranscript = React.useMemo(() => {
    const source = eventFilter === 'all'
      ? transcript
      : transcript.filter((item) => String(item.event_type || '').trim() === eventFilter)
    const sorted = [...source].sort((left, right) => {
      if (sortOrder === 'oldest') return Number(left.index) - Number(right.index)
      return Number(right.index) - Number(left.index)
    })
    return sorted
  }, [eventFilter, sortOrder, transcript])
  const visibleTranscript = filteredTranscript.slice(0, normalizedLimit)
  const totalAttempts = transcript.reduce((sum, item) => sum + Number(item.verify_fix_attempt_count || 0), 0)
  const totalFixes = transcript.reduce((sum, item) => sum + Number(item.verify_fix_fix_attempt_count || 0), 0)
  const totalRunnerErrors = transcript.reduce((sum, item) => sum + Number(item.verify_fix_runner_error_count || 0), 0)

  return (
    <div style={{ marginTop: 8 }}>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <span className="status-chip">Events {transcript.length}</span>
        <span className="status-chip">Attempts {totalAttempts}</span>
        <span className="status-chip">Fixes {totalFixes}</span>
        <span className="status-chip">Runner errors {totalRunnerErrors}</span>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <label className="meta">
          Event type{' '}
          <select
            aria-label="Filter transcript event type"
            value={eventFilter}
            onChange={(event) => setEventFilter(event.target.value)}
          >
            <option value="all">All events</option>
            {eventTypeOptions.map((eventType) => (
              <option key={eventType} value={eventType}>
                {eventType}
              </option>
            ))}
          </select>
        </label>
        <label className="meta">
          Sort{' '}
          <select
            aria-label="Sort transcript events"
            value={sortOrder}
            onChange={(event) => {
              const value = event.target.value === 'oldest' ? 'oldest' : 'newest'
              setSortOrder(value)
            }}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
        <span className="meta">
          Showing {visibleTranscript.length} of {filteredTranscript.length}
        </span>
      </div>
      <div className="gates-check-list">
        {visibleTranscript.map((event) => (
          <div className="gates-check-row" key={`tm-log-event:${event.index}:${event.event_type}`}>
            <div className="gates-check-copy">
              <strong>{event.event_type}</strong>
              <span className="meta">{buildTeamModeAutomationTranscriptMeta(event)}</span>
            </div>
          </div>
        ))}
      </div>
      {filteredTranscript.length <= 0 ? (
        <div className="meta" style={{ marginTop: 8 }}>
          No transcript events match the current filter.
        </div>
      ) : null}
    </div>
  )
}
