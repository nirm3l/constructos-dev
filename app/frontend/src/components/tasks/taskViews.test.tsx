import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TaskListItem } from './taskViews'

describe('TaskListItem workflow and automation labels', () => {
  it('renders explicit workflow and automation chips for non-scheduled tasks', () => {
    render(
      <TaskListItem
        task={{
          id: 'task-1',
          workspace_id: 'ws-1',
          project_id: 'proj-1',
          specification_id: null,
          task_group_id: null,
          title: 'Test task',
          description: 'Task description',
          status: 'In Progress',
          priority: 'High',
          due_date: null,
          labels: [],
          archived: false,
          created_at: null,
          updated_at: null,
          assignee_id: null,
          assigned_agent_code: null,
          external_refs: [],
          attachment_refs: [],
          linked_note_count: 0,
          instruction: null,
          execution_triggers: [],
          task_relationships: [],
          task_type: 'manual',
          scheduled_instruction: null,
          scheduled_at_utc: null,
          schedule_timezone: null,
          schedule_state: 'idle',
          last_schedule_error: null,
          last_schedule_run_at: null,
          recurring_rule: null,
          automation_state: 'failed',
          automation_requested_at: null,
          automation_started_at: null,
          automation_completed_at: null,
          automation_failed_at: null,
          last_automation_error: null,
          last_agent_comment: null,
          review_status: null,
          review_started_at: null,
          review_completed_at: null,
        } as any}
        onOpen={vi.fn()}
        onRestore={vi.fn()}
        onReopen={vi.fn()}
        onComplete={vi.fn()}
      />
    )

    expect(screen.getByText(/Workflow: In Progress/)).toBeTruthy()
    expect(screen.getByText('Automation Failed')).toBeTruthy()
    expect(screen.getByText('Execution incident')).toBeTruthy()
  })

  it('shows workflow/automation mismatch hint when automation completed but workflow is still open', () => {
    render(
      <TaskListItem
        task={{
          id: 'task-2',
          workspace_id: 'ws-1',
          project_id: 'proj-1',
          specification_id: null,
          task_group_id: null,
          title: 'Mismatch task',
          description: '',
          status: 'In Progress',
          priority: 'Med',
          due_date: null,
          labels: [],
          archived: false,
          created_at: null,
          updated_at: null,
          assignee_id: null,
          assigned_agent_code: null,
          external_refs: [],
          attachment_refs: [],
          linked_note_count: 0,
          instruction: null,
          execution_triggers: [],
          task_relationships: [],
          task_type: 'manual',
          scheduled_instruction: null,
          scheduled_at_utc: null,
          schedule_timezone: null,
          schedule_state: 'idle',
          last_schedule_error: null,
          last_schedule_run_at: null,
          recurring_rule: null,
          automation_state: 'completed',
          automation_requested_at: null,
          automation_started_at: null,
          automation_completed_at: null,
          automation_failed_at: null,
          last_automation_error: null,
          last_agent_comment: null,
          review_status: null,
          review_started_at: null,
          review_completed_at: null,
        } as any}
        onOpen={vi.fn()}
        onRestore={vi.fn()}
        onReopen={vi.fn()}
        onComplete={vi.fn()}
      />
    )

    expect(screen.getByText('Automation Completed')).toBeTruthy()
    expect(screen.getByText('Workflow not closed')).toBeTruthy()
  })
})
