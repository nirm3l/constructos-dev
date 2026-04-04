import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TasksPanel } from './TasksPanel'

function buildProps(overrides: Record<string, unknown> = {}): any {
  return {
    panelTitle: 'Tasks',
    allowBoardView: true,
    projectsMode: 'list',
    setProjectsMode: vi.fn(),
    taskGroups: [],
    taskGroupFilterId: '',
    setTaskGroupFilterId: vi.fn(),
    createTaskGroupMutation: { isPending: false, mutate: vi.fn() },
    patchTaskGroupMutation: { isPending: false, mutate: vi.fn() },
    deleteTaskGroupMutation: { isPending: false, mutate: vi.fn() },
    reorderTaskGroupsMutation: { isPending: false, mutate: vi.fn() },
    taskTagSuggestions: [],
    searchTags: [],
    toggleSearchTag: vi.fn(),
    clearSearchTags: vi.fn(),
    boardData: undefined,
    actorNames: {},
    taskTeamAgentLabelsByProjectId: {},
    onOpenTaskEditor: vi.fn(),
    onOpenSpecification: vi.fn(),
    specificationNames: {},
    onMoveTaskStatus: vi.fn(),
    tasks: [],
    canLoadMoreTasks: false,
    onLoadMoreTasks: vi.fn(),
    onRestoreTask: vi.fn(),
    onReopenTask: vi.fn(),
    onCompleteTask: vi.fn(),
    onNewTask: vi.fn(),
    doctorStatus: null,
    onOpenDoctorIncident: vi.fn(),
    ...overrides,
  }
}

describe('TasksPanel doctor incident summary strip', () => {
  it('renders incident summary and triggers open doctor incident callback', () => {
    const onOpenDoctorIncident = vi.fn()
    const props = buildProps({
      onOpenDoctorIncident,
      doctorStatus: {
        checks: {
          recent_executor_worktree_incident_count: 3,
          recent_executor_worktree_open_incident_count: 2,
        },
        runtime_health: {
          recommended_primary_action_id: 'executor-worktree-guard-diagnostics',
        },
      },
    })
    render(<TasksPanel {...props} />)

    expect(screen.getByText('Automation incidents')).toBeTruthy()
    expect(screen.getByText('Open 2 / Total 3')).toBeTruthy()
    expect(screen.getByText('Doctor primary: executor guard diagnostics')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Open Doctor incidents' }))
    expect(onOpenDoctorIncident).toHaveBeenCalledTimes(1)
  })

  it('hides incident summary strip when suppression flag is enabled', () => {
    const props = buildProps({
      suppressDoctorIncidentSummary: true,
      doctorStatus: {
        checks: {
          recent_executor_worktree_incident_count: 3,
          recent_executor_worktree_open_incident_count: 2,
        },
        runtime_health: {
          recommended_primary_action_id: 'executor-worktree-guard-diagnostics',
        },
      },
    })
    render(<TasksPanel {...props} />)

    expect(screen.queryByText('Automation incidents')).toBeNull()
  })
})
