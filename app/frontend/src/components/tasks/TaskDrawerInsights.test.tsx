import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TaskDrawerInsights } from './TaskDrawerInsights'

function buildState(overrides: Record<string, unknown> = {}): any {
  return {
    selectedTask: {
      id: 'task-1',
      title: 'Task',
      project_id: 'proj-1',
      workspace_id: 'ws-1',
      status: 'Blocked',
      priority: 'High',
      labels: [],
      external_refs: [],
      created_at: '2026-04-04T10:00:00Z',
    },
    selectedTaskId: 'task-1',
    userId: 'user-1',
    comments: { data: [] },
    commentsListRef: { current: null },
    expandedCommentIds: new Set<string>(),
    setExpandedCommentIds: vi.fn(),
    actorNames: {},
    deleteCommentMutation: { mutateAsync: vi.fn(async () => ({})), isPending: false },
    commentInputRef: { current: null },
    commentBody: '',
    setCommentBody: vi.fn(),
    addCommentMutation: { mutate: vi.fn(), isPending: false },
    automationStatus: {
      data: {
        automation_state: 'failed',
        last_agent_error: '[EXECUTOR_WORKTREE_ROOT_MUTATION] Executor modified the repository root outside the task worktree.',
        last_agent_error_code: 'EXECUTOR_WORKTREE_ROOT_MUTATION',
        last_agent_error_title: 'Task worktree isolation violation',
        last_agent_error_recommended_doctor_action_id: 'executor-worktree-guard-diagnostics',
        execution_gates: [],
      },
    },
    executeDoctorQuickActionMutation: {
      isPending: false,
      variables: null,
      mutateAsync: vi.fn(async (_actionId: string) => ({
        message: 'Collected executor worktree guard diagnostics.',
        status: {
          runtime_health: {
            overall_status: 'warning',
            recommended_primary_action_id: 'executor-worktree-guard-diagnostics',
          },
        },
      })),
    },
    openWorkspaceDoctorIncident: vi.fn(),
    workspaceDoctorStatus: {
      runtime_health: {
        overall_status: 'warning',
      },
    },
    automationLiveTaskId: null,
    automationLiveActive: false,
    automationLiveBuffer: '',
    automationLiveStatusText: '',
    automationLiveUpdatedAt: null,
    automationInstruction: '',
    setAutomationInstruction: vi.fn(),
    runAutomationMutation: { mutate: vi.fn(), isPending: false },
    activityShowRawDetails: false,
    setActivityShowRawDetails: vi.fn(),
    activity: { data: [] },
    formatActivitySummary: vi.fn(() => 'summary'),
    activityTone: vi.fn(() => 'neutral'),
    activityExpandedIds: new Set<string>(),
    setActivityExpandedIds: vi.fn(),
    toReadableDate: vi.fn((value: unknown) => String(value || '')),
    ...overrides,
  }
}

describe('TaskDrawerInsights doctor fix action', () => {
  it('runs recommended Doctor quick action from automation error block', async () => {
    const state = buildState()
    render(<TaskDrawerInsights state={state} />)

    fireEvent.click(screen.getByRole('button', { name: 'Run Doctor fix' }))

    await waitFor(() => {
      expect(state.executeDoctorQuickActionMutation.mutateAsync).toHaveBeenCalledWith('executor-worktree-guard-diagnostics')
      expect(state.openWorkspaceDoctorIncident).toHaveBeenCalledTimes(1)
      expect(screen.getByText(/Collected executor worktree guard diagnostics\./)).toBeTruthy()
      expect(screen.getByText(/Runtime health: Warning\./)).toBeTruthy()
      expect(screen.getByText(/Primary action: executor-worktree-guard-diagnostics\./)).toBeTruthy()
    })
  })

  it('shows cooldown skip message when Doctor fix is deduplicated', async () => {
    const state = buildState({
      executeDoctorQuickActionMutation: {
        isPending: false,
        variables: null,
        mutateAsync: vi.fn(async (_actionId: string) => ({
          skipped: true,
          message: "Skipped duplicate quick action 'executor-worktree-guard-diagnostics' due to cooldown. Retry in 12s.",
          status: {
            runtime_health: {
              overall_status: 'warning',
              recommended_primary_action_id: 'executor-worktree-guard-diagnostics',
            },
          },
        })),
      },
    })
    render(<TaskDrawerInsights state={state} />)

    fireEvent.click(screen.getByRole('button', { name: 'Run Doctor fix' }))

    await waitFor(() => {
      expect(state.executeDoctorQuickActionMutation.mutateAsync).toHaveBeenCalledWith('executor-worktree-guard-diagnostics')
      expect(screen.getByText(/Skipped duplicate quick action/)).toBeTruthy()
    })
  })

  it('disables Doctor fix button when cooldown is active in Doctor status', () => {
    const state = buildState({
      workspaceDoctorStatus: {
        runtime_health: {
          overall_status: 'warning',
        },
        quick_action_cooldowns: {
          'executor-worktree-guard-diagnostics': {
            active: true,
            retry_after_seconds: 9,
            cooldown_seconds: 20,
            last_event_at: '2026-04-04T12:00:00Z',
            last_event_message: 'cooldown active',
          },
        },
      },
    })
    render(<TaskDrawerInsights state={state} />)

    const button = screen.getByRole('button', { name: 'Retry in 9s' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })
})
