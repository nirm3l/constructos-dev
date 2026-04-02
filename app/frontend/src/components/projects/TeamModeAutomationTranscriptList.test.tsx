import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  buildTeamModeAutomationTranscriptMeta,
  TeamModeAutomationTranscriptList,
  type TeamModeAutomationTranscriptEventItem,
} from './TeamModeAutomationTranscriptList'

describe('TeamModeAutomationTranscriptList', () => {
  it('renders verify/fix timeline metadata with visible counters', () => {
    const events: TeamModeAutomationTranscriptEventItem[] = [
      {
        event_type: 'verify_fix',
        index: 3,
        at: '2026-04-02T14:00:00Z',
        phase: 'verify',
        reason: 'followup',
        queued_task_ids: ['task-1', 'task-2'],
        blocked_reasons: ['missing-evidence'],
        verify_fix_attempt_count: 2,
        verify_fix_fix_attempt_count: 1,
        verify_fix_runner_error_count: 1,
        summary_text: 'Retry succeeded.',
      },
      {
        event_type: 'summary',
        index: 4,
        at: '2026-04-02T14:01:00Z',
        phase: null,
        reason: null,
        queued_task_ids: [],
        blocked_reasons: [],
        verify_fix_attempt_count: 0,
        verify_fix_fix_attempt_count: 0,
        verify_fix_runner_error_count: 0,
        summary_text: 'Session complete.',
      },
    ]
    render(<TeamModeAutomationTranscriptList transcript={events} />)

    expect(screen.getByText('Events 2')).toBeTruthy()
    expect(screen.getByText('Attempts 2')).toBeTruthy()
    expect(screen.getByText('Fixes 1')).toBeTruthy()
    expect(screen.getByText('Runner errors 1')).toBeTruthy()
    expect(screen.getByText('Showing 2 of 2')).toBeTruthy()
    expect(screen.getByText('verify_fix', { selector: 'strong' })).toBeTruthy()
    expect(screen.getByText(/idx=3/)).toBeTruthy()
    expect(screen.getByText(/attempts=2/)).toBeTruthy()
    expect(screen.getByText(/fixes=1/)).toBeTruthy()
    expect(screen.getByText(/runnerErrors=1/)).toBeTruthy()
    expect(screen.getByText(/Retry succeeded\./)).toBeTruthy()
  })

  it('renders fallback message for empty transcripts', () => {
    render(<TeamModeAutomationTranscriptList transcript={[]} />)
    expect(screen.getByText('No transcript events are currently available for this session.')).toBeTruthy()
  })

  it('builds compact transcript metadata string deterministically', () => {
    const text = buildTeamModeAutomationTranscriptMeta({
      event_type: 'summary',
      index: 0,
      at: null,
      phase: null,
      reason: null,
      queued_task_ids: [],
      blocked_reasons: [],
      verify_fix_attempt_count: 0,
      verify_fix_fix_attempt_count: 0,
      verify_fix_runner_error_count: 0,
      summary_text: 'Done.',
    })
    expect(text).toBe('idx=0 · Done.')
  })

  it('filters and sorts transcript events from controls', () => {
    const events: TeamModeAutomationTranscriptEventItem[] = [
      {
        event_type: 'phase_start',
        index: 1,
        at: '2026-04-02T14:00:00Z',
        phase: 'queue',
        reason: null,
        queued_task_ids: [],
        blocked_reasons: [],
        verify_fix_attempt_count: 0,
        verify_fix_fix_attempt_count: 0,
        verify_fix_runner_error_count: 0,
        summary_text: null,
      },
      {
        event_type: 'verify_fix',
        index: 3,
        at: '2026-04-02T14:02:00Z',
        phase: 'verify',
        reason: null,
        queued_task_ids: [],
        blocked_reasons: [],
        verify_fix_attempt_count: 1,
        verify_fix_fix_attempt_count: 0,
        verify_fix_runner_error_count: 0,
        summary_text: null,
      },
      {
        event_type: 'summary',
        index: 4,
        at: '2026-04-02T14:03:00Z',
        phase: null,
        reason: null,
        queued_task_ids: [],
        blocked_reasons: [],
        verify_fix_attempt_count: 0,
        verify_fix_fix_attempt_count: 0,
        verify_fix_runner_error_count: 0,
        summary_text: 'Done.',
      },
    ]
    render(<TeamModeAutomationTranscriptList transcript={events} />)

    const eventFilter = screen.getByLabelText('Filter transcript event type') as HTMLSelectElement
    fireEvent.change(eventFilter, { target: { value: 'verify_fix' } })
    expect(screen.getByText('Showing 1 of 1')).toBeTruthy()
    expect(screen.getByText('verify_fix', { selector: 'strong' })).toBeTruthy()
    expect(screen.queryByText('phase_start', { selector: 'strong' })).toBeNull()

    fireEvent.change(eventFilter, { target: { value: 'all' } })
    const sortSelect = screen.getByLabelText('Sort transcript events') as HTMLSelectElement
    fireEvent.change(sortSelect, { target: { value: 'oldest' } })
    const labels = screen.getAllByText(/phase_start|verify_fix|summary/, { selector: 'strong' })
    expect(labels[0]?.textContent).toBe('phase_start')
    expect(labels[2]?.textContent).toBe('summary')
  })
})
