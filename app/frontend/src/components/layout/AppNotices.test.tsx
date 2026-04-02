import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppNotices } from './AppNotices'

function buildState(overrides: Record<string, unknown> = {}): any {
  const executeDoctorQuickActionMutation = {
    isPending: false,
    variables: null,
    mutateAsync: vi.fn().mockResolvedValue({
      ok: true,
      status: {
        runtime_health: {
          overall_status: 'healthy',
          health_score: 86,
        },
      },
    }),
  }
  return {
    workspaceId: 'workspace-1',
    licenseStatus: {
      data: {
        license: {
          status: 'active',
        },
      },
    },
    workspaceDoctorQuery: {
      data: {
        runtime_health: {
          overall_status: 'failing',
          health_score: 42,
        },
        recent_runs: [],
        recent_actions: [],
      },
    },
    executeDoctorQuickActionMutation,
    openWorkspaceDoctorIncident: vi.fn(),
    activateLicenseMutation: null,
    uiError: null,
    uiInfo: null,
    setUiError: vi.fn(),
    setUiInfo: vi.fn(),
    ...overrides,
  }
}

describe('AppNotices Doctor Incident Smoke', () => {
  it('renders failing runtime notice and opens incident view CTA', () => {
    const state = buildState()
    render(<AppNotices state={state} />)

    expect(
      screen.getByText('ConstructOS runtime health is failing. Immediate intervention is recommended.')
    ).toBeTruthy()

    const cta = screen.getByText('Open Doctor Incident Mode')
    fireEvent.click(cta)
    expect(state.openWorkspaceDoctorIncident).toHaveBeenCalledTimes(1)
  })

  it('replays recovery from timeline action', async () => {
    const state = buildState()
    render(<AppNotices state={state} />)

    const replay = screen.getByRole('button', { name: 'Replay recovery' })
    fireEvent.click(replay)

    await waitFor(() => {
      expect(state.executeDoctorQuickActionMutation.mutateAsync).toHaveBeenCalledWith('recovery-sequence')
    })
  })
})
