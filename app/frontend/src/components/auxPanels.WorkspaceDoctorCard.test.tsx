import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { WorkspaceDoctorCard } from './auxPanels'

function buildDoctorProps(overrides: Record<string, unknown> = {}) {
  const onExecuteDoctorQuickAction = vi.fn(async (actionId: string) => {
    if (actionId === 'descriptor-export-drift-check') {
      return {
        result: {
          descriptor_drift_detected: false,
        },
      }
    }
    return {}
  })

  return {
    doctorStatus: {
      workspace_id: 'ws-1',
      plugin_key: 'doctor',
      supported: true,
      enabled: true,
      fixture_version: '2',
      project: {
        id: 'proj-1',
        name: 'Doctor Project',
        status: 'active',
        link: '/projects/proj-1',
      },
      seeded: true,
      runner_enabled: true,
      checks: {
        team_mode_enabled: true,
        git_delivery_enabled: true,
        seeded_team_task_count: 4,
        task_count: 4,
      },
      last_seeded_at: null,
      last_run_at: null,
      last_run_status: 'passed',
      recent_runs: [],
      runtime_health: {
        generated_at: '2026-04-02T12:00:00Z',
        overall_status: 'warning',
        health_score: 78,
        recommended_primary_action_id: 'descriptor-export-drift-check',
        domains: {
          contracts: {
            status: 'warning',
            summary: 'drift',
            metrics: {
              runtime_contract_audit_stale: true,
              runtime_contract_audit_last_at: null,
              runtime_contract_audit_age_hours: null,
            },
            issues: ['architecture_export_audit_not_ok'],
          },
          bootstrap: { status: 'healthy', summary: 'ok', metrics: {}, issues: [] },
          plugins: { status: 'healthy', summary: 'ok', metrics: {}, issues: [] },
          agent_runtime: { status: 'healthy', summary: 'ok', metrics: {}, issues: [] },
          executor_guardrails: { status: 'healthy', summary: 'ok', metrics: {}, issues: [] },
        },
        recommended_actions: [
          {
            id: 'descriptor-export-drift-check',
            priority: 'high',
            title: 'Inspect descriptor/export drift',
            description: 'Recompute and reconcile descriptor surfaces.',
          },
        ],
      },
      recent_actions: [],
      quick_action_cooldowns: {},
    },
    architectureInventorySummary: {
      generated_at: '2026-04-02T12:00:00Z',
      counts: {
        execution_providers: 3,
        workflow_plugins: 4,
        plugin_descriptors: 3,
        constructos_mcp_tools: 84,
        prompt_templates: 16,
      },
      audit: { ok: true, error_count: 0, warning_count: 0, errors: [], warnings: [] },
      cache_status: { hit_count: 1, miss_count: 0 },
    },
    architectureExport: {
      generated_at: '2026-04-02T12:00:00Z',
      inventory_generated_at: '2026-04-02T12:00:00Z',
      counts: {
        execution_providers: 3,
        workflow_plugins: 4,
        plugin_descriptors: 2,
        constructos_mcp_tools: 84,
        prompt_templates: 16,
      },
      plugin_descriptors: [{ key: 'team_mode' }],
      audit: { ok: false, errors: ['missing descriptors'], warnings: [] },
    },
    architectureExportLoading: false,
    architectureExportError: null,
    pluginDescriptorsPayload: {
      count: 2,
      items: [{ key: 'team_mode' }, { key: 'git_delivery' }],
    },
    pluginDescriptorsLoading: false,
    pluginDescriptorsError: null,
    forceIncidentModeRequestId: 0,
    doctorLoading: false,
    doctorError: null,
    canManage: true,
    onSeedDoctor: vi.fn(async () => ({})),
    seedDoctorPending: false,
    onRunDoctor: vi.fn(async () => ({})),
    runDoctorPending: false,
    onExecuteDoctorQuickAction,
    executeDoctorQuickActionPending: false,
    executeDoctorQuickActionId: null,
    onResetDoctor: vi.fn(async () => ({})),
    resetDoctorPending: false,
    ...overrides,
  }
}

describe('WorkspaceDoctorCard drift actions smoke', () => {
  it('runs descriptor drift check from diagnostics panel and shows success feedback', async () => {
    const props = buildDoctorProps()
    render(<WorkspaceDoctorCard {...(props as any)} />)

    expect(screen.getByText('Drift detected')).toBeTruthy()
    expect(screen.getByText(/Contract audit:\s*stale/i)).toBeTruthy()
    expect(screen.getByText(/Last contract audit:\s*never/i)).toBeTruthy()
    const runCheck = screen.getByRole('button', { name: 'Run descriptor drift check' })
    fireEvent.click(runCheck)

    await waitFor(() => {
      expect(props.onExecuteDoctorQuickAction).toHaveBeenCalledWith('descriptor-export-drift-check')
      expect(screen.getByText('Descriptor/export surfaces are aligned.')).toBeTruthy()
    })
  })

  it('invokes recommended action Fix now for descriptor drift', async () => {
    const props = buildDoctorProps()
    render(<WorkspaceDoctorCard {...(props as any)} />)

    const fixNow = screen.getByRole('button', { name: 'Fix now' })
    fireEvent.click(fixNow)

    await waitFor(() => {
      expect(props.onExecuteDoctorQuickAction).toHaveBeenCalledWith('descriptor-export-drift-check')
    })
  })

  it('renders primary recommended action banner when provided by runtime health', () => {
    const props = buildDoctorProps()
    render(<WorkspaceDoctorCard {...(props as any)} />)

    expect(screen.getByText(/Primary action: Inspect descriptor\/export drift/)).toBeTruthy()
  })

  it('invokes executor guard diagnostics action from recommendations', async () => {
    const onExecuteDoctorQuickAction = vi.fn(async (_actionId: string) => ({
      result: {
        issues: [],
        guidance: ['Executor task worktree guardrails are healthy.'],
      },
    }))
    const props = buildDoctorProps({
      onExecuteDoctorQuickAction,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        runtime_health: {
          ...((buildDoctorProps().doctorStatus as any).runtime_health || {}),
          recommended_actions: [
            {
              id: 'executor-worktree-guard-diagnostics',
              priority: 'high',
              title: 'Inspect executor worktree guardrails',
              description: 'Validate isolation guardrails.',
            },
          ],
        },
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    fireEvent.click(screen.getByRole('button', { name: 'Fix now' }))

    await waitFor(() => {
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('executor-worktree-guard-diagnostics')
      expect(screen.getByText('Executor task worktree guardrails are healthy.')).toBeTruthy()
    })
  })

  it('runs high-priority actions in sequence from bulk control', async () => {
    const onExecuteDoctorQuickAction = vi.fn(async (_actionId: string) => ({}))
    const props = buildDoctorProps({
      onExecuteDoctorQuickAction,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        runtime_health: {
          ...((buildDoctorProps().doctorStatus as any).runtime_health || {}),
          recommended_actions: [
            {
              id: 'runtime-contract-audit',
              priority: 'high',
              title: 'Refresh runtime contract audit',
              description: 'Run contract audit now.',
            },
            {
              id: 'descriptor-export-drift-check',
              priority: 'high',
              title: 'Inspect descriptor/export drift',
              description: 'Recompute and reconcile descriptor surfaces.',
            },
          ],
        },
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    fireEvent.click(screen.getByRole('button', { name: 'Run high-priority actions' }))

    await waitFor(() => {
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('runtime-contract-audit')
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('descriptor-export-drift-check')
      expect(screen.getByText(/High-priority run completed: 2 passed, 0 failed, 0 skipped\./)).toBeTruthy()
    })
  })

  it('uses backend runbook suggestion for failed run checks', async () => {
    const onExecuteDoctorQuickAction = vi.fn(async (_actionId: string) => ({}))
    const props = buildDoctorProps({
      onExecuteDoctorQuickAction,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-1',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    missing_slots: ['dev-a'],
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Doctor fixture team slots must match canonical role allocation.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    expect(screen.getAllByText(/Doctor fixture team slots must match canonical role allocation\./).length).toBeGreaterThan(0)
    const runSuggestedFix = screen.getByRole('button', { name: 'Run suggested fix' })
    fireEvent.click(runSuggestedFix)

    await waitFor(() => {
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('doctor-plugin-wiring')
    })
  })

  it('renders failed checks section expanded by default and warning/passed sections collapsed', () => {
    const props = buildDoctorProps({
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-2',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Fix slot wiring.',
                    },
                  },
                },
                {
                  id: 'contracts_drift',
                  label: 'Contracts drift',
                  status: 'warning',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'runtime-contract-audit',
                      severity: 'medium',
                      rationale: 'Run contracts audit.',
                    },
                  },
                },
                {
                  id: 'project_present',
                  label: 'Doctor project exists',
                  status: 'passed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: null,
                      severity: 'low',
                      rationale: 'No action required.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    const { container } = render(<WorkspaceDoctorCard {...(props as any)} />)

    const detailsNodes = Array.from(container.querySelectorAll('details'))
    const failedDetails = detailsNodes.find((node) => String(node.textContent || '').includes('Failed checks: 1'))
    const warningDetails = detailsNodes.find((node) => String(node.textContent || '').includes('Warning checks: 1'))
    const passedDetails = detailsNodes.find((node) => String(node.textContent || '').includes('Passed checks: 1'))

    expect(failedDetails).toBeTruthy()
    expect(warningDetails).toBeTruthy()
    expect(passedDetails).toBeTruthy()
    expect(failedDetails?.hasAttribute('open')).toBe(true)
    expect(warningDetails?.hasAttribute('open')).toBe(false)
    expect(passedDetails?.hasAttribute('open')).toBe(false)
  })

  it('disables run suggested fix when manage permission is missing', () => {
    const props = buildDoctorProps({
      canManage: false,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-3',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Fix slot wiring.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    const actionButton = screen.getByRole('button', { name: 'Run suggested fix' }) as HTMLButtonElement
    expect(actionButton.disabled).toBe(true)
  })

  it('shows suggested fix button pending state when matching quick action is in progress', () => {
    const props = buildDoctorProps({
      executeDoctorQuickActionPending: true,
      executeDoctorQuickActionId: 'doctor-plugin-wiring',
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-4',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Fix slot wiring.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    const runningButton = screen.getByRole('button', { name: 'Running...' }) as HTMLButtonElement
    expect(runningButton.disabled).toBe(true)
  })

  it('shows feedback when suggested fix execution fails', async () => {
    const onExecuteDoctorQuickAction = vi.fn(async (_actionId: string) => {
      throw new Error('forced quick action failure')
    })
    const props = buildDoctorProps({
      onExecuteDoctorQuickAction,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-5',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Fix slot wiring.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    fireEvent.click(screen.getByRole('button', { name: 'Run suggested fix' }))

    await waitFor(() => {
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('doctor-plugin-wiring')
      expect(screen.getByText('Quick action failed. Run it manually from the recommendation details.')).toBeTruthy()
    })
  })

  it('shows suggested fix running state before success feedback', async () => {
    let resolveAction: ((value?: void | PromiseLike<void>) => void) | undefined
    const onExecuteDoctorQuickAction = vi.fn((_actionId: string) => (
      new Promise<void>((resolve) => {
        resolveAction = resolve
      })
    ))
    const props = buildDoctorProps({
      onExecuteDoctorQuickAction,
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-6',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'seeded_team_slot_integrity',
                  label: 'Seeded team slot integrity',
                  status: 'failed',
                  details: {
                    runbook: {
                      suggested_quick_action_id: 'doctor-plugin-wiring',
                      severity: 'high',
                      rationale: 'Fix slot wiring.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    fireEvent.click(screen.getByRole('button', { name: 'Run suggested fix' }))

    await waitFor(() => {
      expect(onExecuteDoctorQuickAction).toHaveBeenCalledWith('doctor-plugin-wiring')
      const runningButton = screen.getByRole('button', { name: 'Running...' }) as HTMLButtonElement
      expect(runningButton.disabled).toBe(true)
    })

    if (resolveAction) resolveAction()
    await waitFor(() => {
      expect(screen.getByText('Doctor fixture re-seeded.')).toBeTruthy()
    })
  })

  it('renders enriched incident details for recent executor worktree incidents check', () => {
    const props = buildDoctorProps({
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-incidents',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'recent_executor_worktree_incidents',
                  label: 'Recent executor worktree incidents',
                  status: 'failed',
                  details: {
                    incident_count: 2,
                    open_incident_count: 1,
                    resolved_incident_count: 1,
                    latest_incident_at: '2026-04-04T12:00:00Z',
                    code_counts: [
                      { code: 'EXECUTOR_WORKTREE_ROOT_MUTATION', count: 2 },
                    ],
                    source_counts: [
                      { source: 'manual', count: 2 },
                    ],
                    items: [
                      {
                        task_id: 'task-123',
                        error_code: 'EXECUTOR_WORKTREE_ROOT_MUTATION',
                        incident_state: 'open',
                        source: 'manual',
                        task_link: '?tab=tasks&project=proj-1&task=task-123',
                      },
                    ],
                    runbook: {
                      suggested_quick_action_id: 'executor-worktree-guard-diagnostics',
                      severity: 'high',
                      rationale: 'Recent task automation incidents indicate possible executor worktree isolation regressions.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    expect(screen.getByText(/Worktree incidents: 2 \(open 1, resolved 1\)/)).toBeTruthy()
    expect(screen.getByText(/Incident codes: EXECUTOR_WORKTREE_ROOT_MUTATION:2/)).toBeTruthy()
    expect(screen.getByText(/Showing 1 of 1 incidents\./)).toBeTruthy()
    expect(screen.getByText(/Latest incident: 2026-04-04T12:00:00Z/)).toBeTruthy()
    expect(screen.getByText(/Top incident: task task-123, EXECUTOR_WORKTREE_ROOT_MUTATION, source manual/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'task-123' })).toBeTruthy()
  })

  it('disables recommended action button and shows retry label when cooldown is active', () => {
    const props = buildDoctorProps({
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        quick_action_cooldowns: {
          'descriptor-export-drift-check': {
            active: true,
            retry_after_seconds: 11,
            cooldown_seconds: 20,
            last_event_at: '2026-04-04T12:00:00Z',
            last_event_message: 'cooldown active',
          },
        },
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    const buttons = screen.getAllByRole('button', { name: 'Retry in 11s' }) as HTMLButtonElement[]
    expect(buttons.length).toBeGreaterThanOrEqual(1)
    expect(buttons.every((item) => item.disabled)).toBe(true)
  })

  it('filters incident list by open-only and selected source', () => {
    const props = buildDoctorProps({
      doctorStatus: {
        ...buildDoctorProps().doctorStatus,
        recent_runs: [
          {
            id: 'run-incidents-filters',
            workspace_id: 'ws-1',
            project_id: 'proj-1',
            fixture_version: '2',
            status: 'failed',
            started_at: '2026-04-03T10:00:00Z',
            finished_at: '2026-04-03T10:02:00Z',
            summary: {
              checks: [
                {
                  id: 'recent_executor_worktree_incidents',
                  label: 'Recent executor worktree incidents',
                  status: 'failed',
                  details: {
                    incident_count: 2,
                    open_incident_count: 1,
                    resolved_incident_count: 1,
                    code_counts: [
                      { code: 'EXECUTOR_WORKTREE_ROOT_MUTATION', count: 1 },
                      { code: 'EXECUTOR_WORKTREE_SCOPE_REQUIRED', count: 1 },
                    ],
                    source_counts: [
                      { source: 'manual', count: 1 },
                      { source: 'lead_handoff', count: 1 },
                    ],
                    items: [
                      {
                        task_id: 'task-open',
                        error_code: 'EXECUTOR_WORKTREE_ROOT_MUTATION',
                        incident_state: 'open',
                        source: 'manual',
                        task_link: '?tab=tasks&project=proj-1&task=task-open',
                      },
                      {
                        task_id: 'task-resolved',
                        error_code: 'EXECUTOR_WORKTREE_SCOPE_REQUIRED',
                        incident_state: 'resolved',
                        source: 'lead_handoff',
                        task_link: '?tab=tasks&project=proj-1&task=task-resolved',
                      },
                    ],
                    runbook: {
                      suggested_quick_action_id: 'executor-worktree-guard-diagnostics',
                      severity: 'high',
                      rationale: 'Recent task automation incidents indicate possible executor worktree isolation regressions.',
                    },
                  },
                },
              ],
            },
          },
        ],
      },
    })
    render(<WorkspaceDoctorCard {...(props as any)} />)

    expect(screen.getByText(/Showing 1 of 2 incidents\./)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'task-open' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'task-resolved' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Open only ON' }))
    expect(screen.getByText(/Showing 2 of 2 incidents\./)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'task-resolved' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'lead_handoff (1)' }))
    expect(screen.getByText(/Showing 1 of 2 incidents\./)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'task-resolved' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'task-open' })).toBeNull()
  })
})
