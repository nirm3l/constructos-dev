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
        description: 'Pick the active project first. Most lists and actions are scoped to this selection.',
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
      element: '[data-tour-id="fab-new-task"]',
      popover: {
        title: 'Quick Task',
        description: 'Use this floating action button to create a task from anywhere in the app.',
        side: 'left',
        align: 'center',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="fab-new-task"]')
      },
    },
    {
      element: '[data-tour-id="quickadd-create-task"]',
      popover: {
        title: 'Quick Add Drawer',
        description: 'Set the title, project, due date, and create the task in one step.',
        side: 'top',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(true)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="quickadd-create-task"]')
      },
    },
    {
      element: '[data-tour-id="tasks-panel"]',
      popover: {
        title: 'Tasks Workspace',
        description: 'Manage tasks in board or list view, filter by tags, and open any task for full details.',
        side: 'top',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setTab('tasks')
        setShowQuickAdd(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="tasks-panel"]')
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
        description: 'Describe what you need. If no project is selected, chat can guide you through project creation.',
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
        description: 'Search tasks, notes, and specifications from one input.',
        side: 'bottom',
        align: 'start',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-search"]')
      },
    },
    {
      element: '[data-tour-id="header-notifications"]',
      popover: {
        title: 'Notifications',
        description: 'Track assignment and execution updates here.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-notifications"]')
      },
    },
    {
      element: '[data-tour-id="header-knowledge-graph"]',
      popover: {
        title: 'Knowledge Graph',
        description: 'Explore project context, linked entities, and graph-assisted insights.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-knowledge-graph"]')
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
        description: 'Projects define your working scope, statuses, rules, and team setup.',
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
        description: 'Use this action to create a new project manually or from a template.',
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
        description: 'Capture implementation scope and link tasks and notes to a concrete spec.',
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
        description: 'Start with a draft spec, then attach tasks and notes for execution traceability.',
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
        description: 'Store decisions, research, and operational context as long-lived project memory.',
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
        description: 'Move here when you need dependency-aware context and graph exploration tools.',
        side: 'bottom',
        align: 'end',
      },
      onHighlightStarted: (_element, _step, opts) => {
        setShowQuickAdd(false)
        setShowCodexChat(false)
        skipStepIfTargetMissing(opts.driver, '[data-tour-id="header-knowledge-graph"]')
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
