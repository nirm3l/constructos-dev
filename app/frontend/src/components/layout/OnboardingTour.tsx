import React from 'react'
import { driver, type DriveStep, type Driver } from 'driver.js'
import type { Tab } from '../../utils/ui'

type OnboardingTourProps = {
  userId: string
  workspaceId: string
  tourPreferencesLoaded: boolean
  quickTourCompleted: boolean
  advancedTourCompleted: boolean
  setTab: (tab: Tab) => void
  setShowQuickAdd: React.Dispatch<React.SetStateAction<boolean>>
  setShowCodexChat: React.Dispatch<React.SetStateAction<boolean>>
  saveTourProgress: (payload: {
    onboarding_quick_tour_completed?: boolean
    onboarding_advanced_tour_completed?: boolean
  }) => Promise<unknown>
  registerControls: (
    controls: {
      startQuick: () => void
      startAdvanced: () => void
    } | null
  ) => void
}

function skipStepIfTargetMissing(instance: Driver, selector: string): void {
  window.setTimeout(() => {
    const active = instance.getActiveStep()
    const target = document.querySelector(selector)
    if (!active || !instance.isActive() || target) return
    if (instance.hasNextStep()) {
      instance.moveNext()
      return
    }
    instance.destroy()
  }, 220)
}

function clickTargetWhenAvailable(selector: string): void {
  window.setTimeout(() => {
    const element = document.querySelector<HTMLElement>(selector)
    element?.click()
  }, 80)
}

function quickTourSteps(
  setTab: (tab: Tab) => void,
  setShowQuickAdd: React.Dispatch<React.SetStateAction<boolean>>,
  setShowCodexChat: React.Dispatch<React.SetStateAction<boolean>>
): DriveStep[] {
  return [
    {
      element: '[data-tour-id="header-project-select"]',
      popover: {
        title: 'Project Scope',
        description: 'Pick the active project first. Tasks, notes, specifications, graph views, and search all follow this selection.',
        side: 'bottom',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-project-select"]')
      },
    },
    {
      element: '[data-tour-id="tasks-panel"]',
      popover: {
        title: 'Task Workspace',
        description: 'Start here for daily work. Switch between board and list views, filter by tags, and open tasks for full execution details.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="tasks-panel"]')
      },
    },
    {
      element: '[data-tour-id="tasks-new-task"]',
      popover: {
        title: 'New Task',
        description: 'Create either a manual task or a scheduled task from the task workspace.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="tasks-new-task"]')
      },
    },
    {
      element: '[data-tour-id="quickadd-create-task"]',
      popover: {
        title: 'Quick Add Drawer',
        description: 'Create the task inline with project, priority, due date, assignee, tags, or a scheduled run.',
        side: 'top',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(true)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="quickadd-create-task"]')
      },
    },
    {
      element: '[data-tour-id="fab-chat"]',
      popover: {
        title: 'Codex Chat',
        description: 'Open chat for guided setup, planning, and execution help directly from your current context.',
        side: 'left',
        align: 'center',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="fab-chat"]')
      },
    },
    {
      element: '[data-tour-id="codex-chat-composer"]',
      popover: {
        title: 'Chat Composer',
        description: 'Use chat for planning, implementation help, debugging, or guided setup in the current workspace context.',
        side: 'top',
        align: 'center',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowCodexChat(true)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="codex-chat-composer"]')
      },
    },
    {
      element: '[data-tour-id="header-search"]',
      popover: {
        title: 'Global Search',
        description: 'Jump straight to tasks, notes, and specifications from one query. It opens the dedicated Search workspace when you start typing.',
        side: 'bottom',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-search"]')
      },
    },
    {
      element: '[data-tour-id="header-knowledge-graph"]',
      popover: {
        title: 'Knowledge Graph',
        description: 'Open graph and context views when you need linked project memory, dependencies, and grounded search support.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-knowledge-graph"]')
      },
    },
    {
      element: '[data-tour-id="header-notifications"]',
      popover: {
        title: 'Notifications',
        description: 'Track assignments, automation outcomes, and status changes here.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-notifications"]')
      },
    },
    {
      element: '[data-tour-id="header-settings-menu"]',
      popover: {
        title: 'Settings And Tours',
        description: 'Open workspace settings, jump to projects, graph, or search, and relaunch these tours any time.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-settings-menu"]')
      },
    },
  ]
}

function advancedTourSteps(
  setTab: (tab: Tab) => void,
  setShowQuickAdd: React.Dispatch<React.SetStateAction<boolean>>,
  setShowCodexChat: React.Dispatch<React.SetStateAction<boolean>>
): DriveStep[] {
  return [
    {
      element: '[data-tour-id="projects-panel"]',
      popover: {
        title: 'Projects',
        description: 'Projects define statuses, rules, plugins, members, and the scope used across the rest of the app.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('projects')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="projects-panel"]')
      },
    },
    {
      element: '[data-tour-id="project-new-project"]',
      popover: {
        title: 'Create Project',
        description: 'Create a project manually, then configure its statuses, rules, skills, and supported plugins from the inline editor.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('projects')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="project-new-project"]')
      },
    },
    {
      element: '[data-tour-id="specifications-panel"]',
      popover: {
        title: 'Specifications',
        description: 'Capture implementation scope and link tasks and notes back to a concrete specification for traceability.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('specifications')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="specifications-panel"]')
      },
    },
    {
      element: '[data-tour-id="spec-new"]',
      popover: {
        title: 'New Specification',
        description: 'Create a draft spec, then connect tasks and notes to keep planning and execution tied together.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('specifications')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="spec-new"]')
      },
    },
    {
      element: '[data-tour-id="notes-panel"]',
      popover: {
        title: 'Notes',
        description: 'Store research, decisions, and operational context, then link notes to tasks or specifications when they matter.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('notes')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="notes-panel"]')
      },
    },
    {
      element: '[data-tour-id="header-knowledge-graph"]',
      popover: {
        title: 'Knowledge Graph',
        description: 'Use graph views for dependency-aware context, linked entities, grounded summaries, and project knowledge exploration.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-knowledge-graph"]')
      },
    },
    {
      element: '[data-tour-id="search-panel"]',
      popover: {
        title: 'Search Workspace',
        description: 'Use the dedicated Search workspace for combined lexical and semantic results across tasks, notes, and specifications.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('search')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="search-panel"]')
      },
    },
    {
      element: '[data-tour-id="header-settings-menu"]',
      popover: {
        title: 'Workspace Settings',
        description: 'Use Settings for shared connections, runtime configuration, user administration, skills, and Doctor.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-settings-menu"]')
      },
    },
    {
      element: '[data-tour-id="workspace-tab-doctor"]',
      popover: {
        title: 'Doctor Tab',
        description: 'Open the Doctor tab in Workspace Settings to seed, run, reset, and inspect the validation fixture for the workspace.',
        side: 'bottom',
        align: 'center',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('settings')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        clickTargetWhenAvailable('[data-tour-id="workspace-tab-doctor"]')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="workspace-tab-doctor"]')
      },
    },
    {
      element: '[data-tour-id="workspace-doctor-card"]',
      popover: {
        title: 'ConstructOS Doctor',
        description: 'Doctor seeds a dedicated validation project, runs checks, and shows recent runs so you can verify core workspace functionality.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('settings')
        setShowQuickAdd(false)
        setShowCodexChat(false)
        clickTargetWhenAvailable('[data-tour-id="workspace-tab-doctor"]')
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="workspace-doctor-card"]')
      },
    },
  ]
}

export function OnboardingTour({
  userId,
  workspaceId,
  tourPreferencesLoaded,
  quickTourCompleted,
  advancedTourCompleted,
  setTab,
  setShowQuickAdd,
  setShowCodexChat,
  saveTourProgress,
  registerControls,
}: OnboardingTourProps) {
  const driverRef = React.useRef<Driver | null>(null)
  const prevScrollbarGutterRef = React.useRef<string | null>(null)
  const autoStartAttemptedRef = React.useRef(false)

  const applyTourViewportFix = React.useCallback(() => {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    if (prevScrollbarGutterRef.current === null) {
      prevScrollbarGutterRef.current = root.style.scrollbarGutter || ''
    }
    root.style.scrollbarGutter = 'auto'
    root.setAttribute('data-tour-active', '1')
  }, [])

  const clearTourViewportFix = React.useCallback(() => {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    root.removeAttribute('data-tour-active')
    root.style.scrollbarGutter = prevScrollbarGutterRef.current ?? ''
    prevScrollbarGutterRef.current = null
  }, [])

  const runTour = React.useCallback((steps: DriveStep[], force = false, kind: 'quick' | 'advanced' = 'quick') => {
    if (typeof window === 'undefined') return
    if (!force && kind === 'quick' && quickTourCompleted) return
    if (!force && kind === 'advanced' && advancedTourCompleted) return

    setTab('tasks')
    setShowQuickAdd(false)
    setShowCodexChat(false)
    applyTourViewportFix()
    const isDarkTheme = document.documentElement.getAttribute('data-theme') === 'dark'

    const instance = driver({
      steps,
      showProgress: true,
      animate: true,
      allowClose: true,
      smoothScroll: true,
      overlayColor: isDarkTheme ? '#020906' : '#10251a',
      overlayOpacity: isDarkTheme ? 0.76 : 0.58,
      stageRadius: 12,
      stagePadding: 6,
      popoverClass: 'app-tour-popover',
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Finish',
      onDestroyed: () => {
        if (kind === 'quick') {
          void saveTourProgress({ onboarding_quick_tour_completed: true })
        } else {
          void saveTourProgress({ onboarding_advanced_tour_completed: true })
        }
        setShowQuickAdd(false)
        clearTourViewportFix()
      },
    })

    driverRef.current = instance
    instance.drive(0)
  }, [advancedTourCompleted, applyTourViewportFix, clearTourViewportFix, quickTourCompleted, saveTourProgress, setShowCodexChat, setShowQuickAdd, setTab, userId, workspaceId])

  const startQuickTour = React.useCallback((force = false) => {
    runTour(quickTourSteps(setTab, setShowQuickAdd, setShowCodexChat), force, 'quick')
  }, [runTour, setShowCodexChat, setShowQuickAdd, setTab])

  const startAdvancedTour = React.useCallback((force = false) => {
    runTour(advancedTourSteps(setTab, setShowQuickAdd, setShowCodexChat), force, 'advanced')
  }, [runTour, setShowCodexChat, setShowQuickAdd, setTab])

  React.useEffect(() => {
    registerControls({
      startQuick: () => startQuickTour(true),
      startAdvanced: () => startAdvancedTour(true),
    })
    return () => registerControls(null)
  }, [registerControls, startAdvancedTour, startQuickTour])

  React.useEffect(() => {
    if (!workspaceId) return
    if (!tourPreferencesLoaded) return
    if (autoStartAttemptedRef.current) return
    autoStartAttemptedRef.current = true
    if (quickTourCompleted) return
    const timer = window.setTimeout(() => {
      startQuickTour(false)
    }, 450)
    return () => window.clearTimeout(timer)
  }, [quickTourCompleted, startQuickTour, tourPreferencesLoaded, workspaceId])

  React.useEffect(() => {
    return () => {
      if (driverRef.current?.isActive()) {
        driverRef.current.destroy()
      }
      driverRef.current = null
      clearTourViewportFix()
    }
  }, [clearTourViewportFix])

  return null
}
