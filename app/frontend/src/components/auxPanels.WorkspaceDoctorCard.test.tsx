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
})
