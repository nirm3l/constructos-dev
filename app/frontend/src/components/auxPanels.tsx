import React from 'react'
import * as Accordion from '@radix-ui/react-accordion'
import * as Checkbox from '@radix-ui/react-checkbox'
import * as Collapsible from '@radix-ui/react-collapsible'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Select from '@radix-ui/react-select'
import * as Switch from '@radix-ui/react-switch'
import * as Tabs from '@radix-ui/react-tabs'
import * as Tooltip from '@radix-ui/react-tooltip'
import type {
  AdminWorkspaceUser,
  LicenseStatus,
  Note,
  Specification,
  Task,
  WorkspaceSkill,
  WorkspaceSkillsPage,
} from '../types'
import { tagHue } from '../utils/ui'
import { MarkdownView } from '../markdown/MarkdownView'
import { PopularTagFilters } from './shared/PopularTagFilters'
import { Icon, MarkdownModeToggle, MarkdownSplitPane } from './shared/uiHelpers'
import { TaskListItem } from './tasks/taskViews'

const VOICE_LANG_OPTIONS = [
  { value: 'bs-BA', label: 'Bosnian (bs-BA)' },
  { value: 'en-US', label: 'English (en-US)' },
]

const PROFILE_FEEDBACK_TYPE_OPTIONS: Array<{
  value: 'general' | 'feature_request' | 'question' | 'other'
  label: string
}> = [
  { value: 'general', label: 'General' },
  { value: 'feature_request', label: 'Feature request' },
  { value: 'question', label: 'Question' },
  { value: 'other', label: 'Other' },
]

const GITHUB_ISSUES_URL = 'https://github.com/nirm3l/constructos/issues'
const SEARCH_ANY_VALUE = '__any__'

const SEARCH_TASK_STATUS_OPTIONS = [
  { value: 'To do', label: 'To do' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Done', label: 'Done' },
]

const SEARCH_SPEC_STATUS_OPTIONS = [
  { value: 'Draft', label: 'Draft' },
  { value: 'Ready', label: 'Ready' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Implemented', label: 'Implemented' },
  { value: 'Archived', label: 'Archived' },
]

const SEARCH_PRIORITY_OPTIONS = [
  { value: 'Low', label: 'Low' },
  { value: 'Med', label: 'Med' },
  { value: 'High', label: 'High' },
]

const ADMIN_ROLE_OPTIONS = [
  { value: 'Owner', label: 'Owner' },
  { value: 'Admin', label: 'Admin' },
  { value: 'Member', label: 'Member' },
  { value: 'Guest', label: 'Guest' },
]

const SKILL_MODE_OPTIONS = [
  { value: 'advisory', label: 'advisory' },
  { value: 'enforced', label: 'enforced' },
]

const SKILL_TRUST_OPTIONS = [
  { value: 'reviewed', label: 'reviewed' },
  { value: 'verified', label: 'verified' },
  { value: 'untrusted', label: 'untrusted' },
]

function normalizeOptionValue(
  value: string,
  options: Array<{ value: string; label: string }>,
  fallback: string
): string {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) return fallback
  const match = options.find((option) => option.value.toLowerCase() === normalized)
  return match?.value || fallback
}

function SearchFilterSelect({
  value,
  onValueChange,
  anyLabel,
  options,
  ariaLabel,
}: {
  value: string
  onValueChange: (value: string) => void
  anyLabel: string
  options: Array<{ value: string; label: string }>
  ariaLabel: string
}) {
  const normalizedValue = String(value || '').trim() || SEARCH_ANY_VALUE
  return (
    <Select.Root
      value={normalizedValue}
      onValueChange={(nextValue) => onValueChange(nextValue === SEARCH_ANY_VALUE ? '' : nextValue)}
    >
      <Select.Trigger className="quickadd-project-trigger search-panel-select-trigger" aria-label={ariaLabel}>
        <Select.Value />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content search-panel-select-content" position="popper" sideOffset={6}>
          <Select.Viewport className="quickadd-project-viewport">
            <Select.Item value={SEARCH_ANY_VALUE} className="quickadd-project-item">
              <Select.ItemText>{anyLabel}</Select.ItemText>
              <Select.ItemIndicator className="quickadd-project-item-indicator">
                <Icon path="M5 13l4 4L19 7" />
              </Select.ItemIndicator>
            </Select.Item>
            {options.map((option) => (
              <Select.Item key={option.value} value={option.value} className="quickadd-project-item">
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="quickadd-project-item-indicator">
                  <Icon path="M5 13l4 4L19 7" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}

function AdminSelect({
  value,
  onValueChange,
  options,
  ariaLabel,
  disabled = false,
}: {
  value: string
  onValueChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  ariaLabel: string
  disabled?: boolean
}) {
  return (
    <Select.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <Select.Trigger
        className="quickadd-project-trigger taskdrawer-select-trigger admin-select-trigger"
        aria-label={ariaLabel}
        disabled={disabled}
      >
        <Select.Value />
        <Select.Icon asChild>
          <span className="quickadd-project-trigger-icon" aria-hidden="true">
            <Icon path="M6 9l6 6 6-6" />
          </span>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="quickadd-project-content admin-select-content" position="popper" sideOffset={6}>
          <Select.Viewport className="quickadd-project-viewport">
            {options.map((option) => (
              <Select.Item key={option.value} value={option.value} className="quickadd-project-item">
                <Select.ItemText>{option.label}</Select.ItemText>
                <Select.ItemIndicator className="quickadd-project-item-indicator">
                  <Icon path="M5 13l4 4L19 7" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}

export function SearchPanel({
  searchQ,
  setSearchQ,
  searchStatus,
  setSearchStatus,
  searchSpecificationStatus,
  setSearchSpecificationStatus,
  searchPriority,
  setSearchPriority,
  searchArchived,
  setSearchArchived,
  taskTagSuggestions,
  searchTags,
  toggleSearchTag,
  clearSearchTags,
  getTagUsage,
  onClose,
}: {
  searchQ: string
  setSearchQ: React.Dispatch<React.SetStateAction<string>>
  searchStatus: string
  setSearchStatus: React.Dispatch<React.SetStateAction<string>>
  searchSpecificationStatus: string
  setSearchSpecificationStatus: React.Dispatch<React.SetStateAction<string>>
  searchPriority: string
  setSearchPriority: React.Dispatch<React.SetStateAction<string>>
  searchArchived: boolean
  setSearchArchived: React.Dispatch<React.SetStateAction<boolean>>
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
  clearSearchTags: () => void
  getTagUsage: (tag: string) => number
  onClose: () => void
}) {
  const activeAdvancedFilterCount = React.useMemo(() => {
    let count = 0
    if (String(searchStatus || '').trim()) count += 1
    if (String(searchSpecificationStatus || '').trim()) count += 1
    if (String(searchPriority || '').trim()) count += 1
    if (searchArchived) count += 1
    return count
  }, [searchArchived, searchPriority, searchSpecificationStatus, searchStatus])
  const [advancedOpen, setAdvancedOpen] = React.useState<boolean>(activeAdvancedFilterCount > 0)

  React.useEffect(() => {
    if (activeAdvancedFilterCount > 0) setAdvancedOpen(true)
  }, [activeAdvancedFilterCount])

  const resetAllFilters = React.useCallback(() => {
    setSearchQ('')
    setSearchStatus('')
    setSearchSpecificationStatus('')
    setSearchPriority('')
    setSearchArchived(false)
    clearSearchTags()
    setAdvancedOpen(false)
  }, [
    clearSearchTags,
    setSearchArchived,
    setSearchPriority,
    setSearchQ,
    setSearchSpecificationStatus,
    setSearchStatus,
  ])

  return (
    <section className="card search-panel-card">
      <div className="row search-panel-header">
        <h2 style={{ margin: 0 }}>Search</h2>
        <div className="search-panel-header-actions">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="action-icon" type="button" title="Search actions" aria-label="Search actions">
                <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="task-group-menu-content search-panel-menu-content" sideOffset={8} align="end">
                <DropdownMenu.Item className="task-group-menu-item" onSelect={resetAllFilters}>
                  <Icon path="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
                  <span>Reset all filters</span>
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
          <button className="action-icon" onClick={onClose} title="Close search" aria-label="Close search">
            <Icon path="M6 6l12 12M18 6 6 18" />
          </button>
        </div>
      </div>

      <Collapsible.Root open={advancedOpen} onOpenChange={setAdvancedOpen} className="search-panel-collapsible">
        <div className="search-panel-primary-row">
          <input
            className="search-panel-input"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="Search tasks, notes, and specifications"
            aria-label="Search query"
          />
          <Collapsible.Trigger asChild>
            <button
              className={`status-chip search-panel-advanced-trigger ${advancedOpen ? 'active' : ''}`}
              type="button"
              aria-expanded={advancedOpen}
            >
              <Icon path={advancedOpen ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} />
              <span>Advanced</span>
              {activeAdvancedFilterCount > 0 ? (
                <span className="search-panel-filter-count">{activeAdvancedFilterCount}</span>
              ) : null}
            </button>
          </Collapsible.Trigger>
        </div>
        <Collapsible.Content className="search-panel-advanced-grid">
          <SearchFilterSelect
            value={searchStatus}
            onValueChange={setSearchStatus}
            anyLabel="Any task status"
            options={SEARCH_TASK_STATUS_OPTIONS}
            ariaLabel="Filter by task status"
          />
          <SearchFilterSelect
            value={searchSpecificationStatus}
            onValueChange={setSearchSpecificationStatus}
            anyLabel="Any specification status"
            options={SEARCH_SPEC_STATUS_OPTIONS}
            ariaLabel="Filter by specification status"
          />
          <SearchFilterSelect
            value={searchPriority}
            onValueChange={setSearchPriority}
            anyLabel="Any priority"
            options={SEARCH_PRIORITY_OPTIONS}
            ariaLabel="Filter by task priority"
          />
          <label className="search-panel-checkbox-row" htmlFor="search-archived-only">
            <Checkbox.Root
              className="search-panel-checkbox-root"
              id="search-archived-only"
              checked={searchArchived}
              onCheckedChange={(checked: boolean | 'indeterminate') => setSearchArchived(checked === true)}
            >
              <Checkbox.Indicator className="search-panel-checkbox-indicator">
                <Icon path="M5 13l4 4L19 7" />
              </Checkbox.Indicator>
            </Checkbox.Root>
            <span>Archived only</span>
          </label>
        </Collapsible.Content>
      </Collapsible.Root>

      <div className="search-panel-tags-row">
        <div className="search-panel-tags-title-row">
          <span className="meta">Tag filters</span>
          {searchTags.length > 0 ? <span className="badge">{searchTags.length} selected</span> : null}
        </div>
        <div className="search-panel-tags-scroll">
          <div className="row wrap search-panel-tags-wrap">
            <PopularTagFilters
              tags={taskTagSuggestions}
              selectedTags={searchTags}
              onToggleTag={toggleSearchTag}
              onClear={clearSearchTags}
              getTagUsage={getTagUsage}
              idPrefix="search-tag"
            />
          </div>
        </div>
      </div>
    </section>
  )
}

export function ProfilePanel({
  userName,
  theme,
  speechLang,
  frontendVersion,
  backendVersion,
  backendBuild,
  deployedAtUtc,
  license,
  licenseLoading,
  licenseError,
  onLogout,
  onToggleTheme,
  onChangeSpeechLang,
  changePassword,
  passwordChangePending,
  submitFeedback,
  feedbackSubmitting,
}: {
  userName: string
  theme: 'light' | 'dark'
  speechLang: string
  frontendVersion: string
  backendVersion: string
  backendBuild: string | null
  deployedAtUtc: string | null
  license: LicenseStatus | null | undefined
  licenseLoading: boolean
  licenseError: string | null
  onLogout: () => void
  onToggleTheme: () => void
  onChangeSpeechLang: (value: string) => void
  changePassword: (payload: { current_password: string; new_password: string }) => Promise<unknown>
  passwordChangePending: boolean
  submitFeedback: (payload: {
    title: string
    description: string
    feedback_type: 'general' | 'feature_request' | 'question' | 'other'
    context?: Record<string, unknown>
    metadata?: Record<string, unknown>
  }) => Promise<unknown>
  feedbackSubmitting: boolean
}) {
  const nextTheme = theme === 'light' ? 'dark' : 'light'
  const licenseStatus = String(license?.status || '').trim().toLowerCase() || 'unknown'
  const licenseStatusLabel = licenseStatus.charAt(0).toUpperCase() + licenseStatus.slice(1)
  const formatDateTime = (value: string | null): string => {
    if (!value) return 'n/a'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  }
  const formatLabel = (value: string): string => {
    const normalized = String(value || '').trim().replace(/_/g, ' ')
    if (!normalized) return 'n/a'
    return normalized
      .split(/\s+/)
      .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
      .join(' ')
  }
  const licenseMetadata = (license?.metadata && typeof license.metadata === 'object'
    ? (license.metadata as Record<string, unknown>)
    : {}) as Record<string, unknown>
  const subscriptionStatus = String(licenseMetadata.subscription_status ?? '').trim().toLowerCase()
  const subscriptionValidUntil = String(licenseMetadata.subscription_valid_until ?? '').trim() || null
  const publicBetaEnabled = licenseMetadata.public_beta === true
  const publicBetaFreeUntil = String(licenseMetadata.public_beta_free_until ?? '').trim() || null
  const entitlementSource = publicBetaEnabled
    ? `Public beta until ${formatDateTime(publicBetaFreeUntil)}`
    : subscriptionStatus
      ? `Subscription (${formatLabel(subscriptionStatus)})`
      : 'Trial fallback'
  const showTrialWindow = licenseStatus === 'trial' || licenseStatus === 'grace'
  const [profileTab, setProfileTab] = React.useState<'preferences' | 'security' | 'feedback' | 'runtime' | 'license'>('preferences')
  const [currentPasswordInput, setCurrentPasswordInput] = React.useState('')
  const [newPasswordInput, setNewPasswordInput] = React.useState('')
  const [confirmPasswordInput, setConfirmPasswordInput] = React.useState('')
  const [passwordFeedback, setPasswordFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [feedbackTitleInput, setFeedbackTitleInput] = React.useState('')
  const [feedbackDescriptionInput, setFeedbackDescriptionInput] = React.useState('')
  const [feedbackTypeInput, setFeedbackTypeInput] = React.useState<'general' | 'feature_request' | 'question' | 'other'>('general')
  const [feedbackResult, setFeedbackResult] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [installationCopyState, setInstallationCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const [runtimeCopyState, setRuntimeCopyState] = React.useState<'idle' | 'copied' | 'error'>('idle')
  const voiceFactRef = React.useRef<HTMLDivElement | null>(null)
  const voiceSelectTriggerRef = React.useRef<HTMLButtonElement | null>(null)
  const browserTimeZone = React.useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'n/a'
    } catch {
      return 'n/a'
    }
  }, [])
  const selectedVoiceLabel = React.useMemo(() => {
    return VOICE_LANG_OPTIONS.find((item) => item.value === speechLang)?.label || speechLang
  }, [speechLang])
  const selectedFeedbackTypeLabel = React.useMemo(() => {
    return PROFILE_FEEDBACK_TYPE_OPTIONS.find((item) => item.value === feedbackTypeInput)?.label || 'General'
  }, [feedbackTypeInput])
  const runtimeSnapshotText = React.useMemo(() => {
    return [
      `Frontend version: ${frontendVersion || 'n/a'}`,
      `Backend version: ${backendVersion || 'n/a'}`,
      `Backend build: ${backendBuild || 'n/a'}`,
      `Deployed UTC: ${deployedAtUtc || 'unknown'}`,
      `Theme: ${theme}`,
      `Voice language: ${selectedVoiceLabel}`,
      `Browser timezone: ${browserTimeZone}`,
    ].join('\n')
  }, [backendBuild, backendVersion, browserTimeZone, deployedAtUtc, frontendVersion, selectedVoiceLabel, theme])

  const scrollVoiceLanguageIntoView = React.useCallback(() => {
    if (typeof window === 'undefined') return

    const scrollNearestContainer = () => {
      const target = voiceFactRef.current
      if (!target) return

      const findScrollableParent = (node: HTMLElement | null): HTMLElement | null => {
        let current = node?.parentElement ?? null
        while (current) {
          const styles = window.getComputedStyle(current)
          const overflowY = styles.overflowY
          const isScrollable =
            (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') &&
            current.scrollHeight > current.clientHeight + 1
          if (isScrollable) return current
          current = current.parentElement
        }
        return null
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })

      const parent = findScrollableParent(target)
      if (parent) {
        const targetRect = target.getBoundingClientRect()
        const parentRect = parent.getBoundingClientRect()
        const nextTop = parent.scrollTop + (targetRect.top - parentRect.top) - parent.clientHeight * 0.35
        parent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
      }
    }

    const focusVoiceSelect = () => {
      try {
        voiceSelectTriggerRef.current?.focus({ preventScroll: true })
      } catch {
        voiceSelectTriggerRef.current?.focus()
      }
    }

    scrollNearestContainer()
    window.setTimeout(scrollNearestContainer, 120)
    window.setTimeout(scrollNearestContainer, 300)
    window.setTimeout(focusVoiceSelect, 340)
  }, [])

  React.useEffect(() => {
    if (typeof window === 'undefined') return
    const handleVoiceFocus = () => {
      setProfileTab('preferences')
      window.setTimeout(() => {
        scrollVoiceLanguageIntoView()
      }, 80)
    }

    window.addEventListener('ui:focus-voice-language', handleVoiceFocus)

    let shouldScroll = false
    try {
      shouldScroll = window.sessionStorage.getItem('ui_profile_scroll_target') === 'voice_language'
      if (shouldScroll) {
        window.sessionStorage.removeItem('ui_profile_scroll_target')
      }
    } catch {
      shouldScroll = false
    }
    if (!shouldScroll) {
      return () => {
        window.removeEventListener('ui:focus-voice-language', handleVoiceFocus)
      }
    }

    const frameId = window.requestAnimationFrame(() => {
      handleVoiceFocus()
    })
    return () => {
      window.cancelAnimationFrame(frameId)
      window.removeEventListener('ui:focus-voice-language', handleVoiceFocus)
    }
  }, [scrollVoiceLanguageIntoView])

  const resetPasswordForm = React.useCallback(() => {
    setCurrentPasswordInput('')
    setNewPasswordInput('')
    setConfirmPasswordInput('')
  }, [])

  const resetFeedbackForm = React.useCallback(() => {
    setFeedbackTitleInput('')
    setFeedbackDescriptionInput('')
    setFeedbackTypeInput('general')
  }, [])

  const handleSubmitPasswordChange = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const currentPassword = String(currentPasswordInput || '').trim()
      const nextPassword = String(newPasswordInput || '').trim()
      const confirmedPassword = String(confirmPasswordInput || '').trim()
      if (!currentPassword) {
        setPasswordFeedback({ tone: 'error', message: 'Current password is required.' })
        return
      }
      if (nextPassword.length < 8) {
        setPasswordFeedback({ tone: 'error', message: 'New password must be at least 8 characters.' })
        return
      }
      if (nextPassword !== confirmedPassword) {
        setPasswordFeedback({ tone: 'error', message: 'Password confirmation does not match.' })
        return
      }
      if (currentPassword === nextPassword) {
        setPasswordFeedback({ tone: 'error', message: 'New password must be different from current password.' })
        return
      }
      try {
        await changePassword({
          current_password: currentPassword,
          new_password: nextPassword,
        })
        resetPasswordForm()
        setPasswordFeedback({ tone: 'success', message: 'Password changed successfully.' })
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to change password.'
        setPasswordFeedback({ tone: 'error', message })
      }
    },
    [changePassword, confirmPasswordInput, currentPasswordInput, newPasswordInput, resetPasswordForm]
  )

  const handleSubmitFeedback = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const title = String(feedbackTitleInput || '').trim()
      const description = String(feedbackDescriptionInput || '').trim()
      if (title.length < 3) {
        setFeedbackResult({ tone: 'error', message: 'Feedback title must be at least 3 characters.' })
        return
      }
      if (description.length < 5) {
        setFeedbackResult({ tone: 'error', message: 'Feedback description must be at least 5 characters.' })
        return
      }
      try {
        await submitFeedback({
          title,
          description,
          feedback_type: feedbackTypeInput,
          context: {
            tab: 'profile',
          },
        })
        resetFeedbackForm()
        setFeedbackResult({ tone: 'success', message: 'Feedback sent successfully.' })
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to send feedback.'
        setFeedbackResult({ tone: 'error', message })
      }
    },
    [feedbackDescriptionInput, feedbackTitleInput, feedbackTypeInput, resetFeedbackForm, submitFeedback]
  )

  const handleThemeCheckedChange = React.useCallback(
    (checked: boolean) => {
      const nextTheme = checked ? 'dark' : 'light'
      if (nextTheme !== theme) onToggleTheme()
    },
    [onToggleTheme, theme]
  )

  const copyInstallationId = React.useCallback(async () => {
    const value = String(license?.installation_id || '').trim()
    if (!value) return
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setInstallationCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(value)
      setInstallationCopyState('copied')
      window.setTimeout(() => setInstallationCopyState('idle'), 1400)
    } catch {
      setInstallationCopyState('error')
      window.setTimeout(() => setInstallationCopyState('idle'), 1800)
    }
  }, [license?.installation_id])

  const copyRuntimeSnapshot = React.useCallback(async () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      setRuntimeCopyState('error')
      return
    }
    try {
      await navigator.clipboard.writeText(runtimeSnapshotText)
      setRuntimeCopyState('copied')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1400)
    } catch {
      setRuntimeCopyState('error')
      window.setTimeout(() => setRuntimeCopyState('idle'), 1800)
    }
  }, [runtimeSnapshotText])

  return (
    <Tooltip.Provider delayDuration={180}>
      <section className="card profile-panel">
        <div className="profile-panel-head">
          <div className="profile-panel-identity">
            <div className="profile-avatar" aria-hidden="true">
              <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
            </div>
            <div className="profile-head-copy">
              <h2>Profile</h2>
              <p className="meta">Personal settings and runtime details</p>
            </div>
          </div>
          <div className="profile-head-chips">
            <span className="status-chip profile-theme-chip">{theme} mode</span>
            <span className="status-chip">{licenseStatusLabel}</span>
          </div>
        </div>

        <Tabs.Root
          className="profile-tabs"
          value={profileTab}
          onValueChange={(nextValue) => {
            if (
              nextValue === 'preferences' ||
              nextValue === 'security' ||
              nextValue === 'feedback' ||
              nextValue === 'runtime' ||
              nextValue === 'license'
            ) {
              setProfileTab(nextValue)
            }
          }}
        >
          <Tabs.List className="profile-tabs-list" aria-label="Profile sections">
            <Tabs.Trigger className="profile-tab-trigger" value="preferences">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M3 6h18M3 12h18M3 18h18" />
              </span>
              <span>Preferences</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="security">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M12 2l7 4v6c0 5-3.5 9-7 10-3.5-1-7-5-7-10V6l7-4zM9 12h6M12 9v6" />
              </span>
              <span>Security</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="feedback">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M21 15a2 2 0 0 1-2 2H8l-5 5V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </span>
              <span>Feedback</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="runtime">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M4 4h16v12H4zM10 20h4M12 16v4" />
              </span>
              <span>Runtime</span>
            </Tabs.Trigger>
            <Tabs.Trigger className="profile-tab-trigger" value="license">
              <span className="profile-tab-trigger-icon" aria-hidden="true">
                <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
              </span>
              <span>License</span>
            </Tabs.Trigger>
          </Tabs.List>

          <Tabs.Content className="profile-tab-content" value="preferences">
            <div className="profile-pane-grid">
              <section className="profile-pane-card" aria-label="Appearance">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M12 3l8 4v5c0 6-5 9-8 9s-8-3-8-9V7l8-4zM8 12h8M12 8v8" />
                    </span>
                    <span>Appearance</span>
                  </h3>
                  <span className="status-chip">Theme</span>
                </div>
                <div className="profile-theme-row">
                  <label className="profile-switch-label" htmlFor="profile-theme-switch">Dark mode</label>
                  <div className="profile-theme-controls">
                    <Tooltip.Root>
                      <Tooltip.Trigger asChild>
                        <Switch.Root
                          id="profile-theme-switch"
                          className="profile-theme-switch"
                          checked={theme === 'dark'}
                          onCheckedChange={handleThemeCheckedChange}
                          aria-label={`Switch to ${nextTheme} mode`}
                        >
                          <Switch.Thumb className="profile-theme-switch-thumb" />
                        </Switch.Root>
                      </Tooltip.Trigger>
                      <Tooltip.Portal>
                        <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                          Toggle between light and dark themes
                          <Tooltip.Arrow className="header-tooltip-arrow" />
                        </Tooltip.Content>
                      </Tooltip.Portal>
                    </Tooltip.Root>
                    <button className="button-secondary profile-action-button" type="button" onClick={onToggleTheme}>
                      <Icon path="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79" />
                      <span>{`Switch to ${nextTheme}`}</span>
                    </button>
                  </div>
                </div>
                <p className="meta">Current mode: {theme}.</p>
              </section>

              <section className="profile-pane-card" aria-label="Voice language" id="profile-voice-language" ref={voiceFactRef}>
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3M6 11a6 6 0 0 0 12 0M12 17v4M8 21h8" />
                    </span>
                    <span>Voice language</span>
                  </h3>
                  <span className="status-chip">Speech</span>
                </div>
                <Select.Root value={speechLang} onValueChange={onChangeSpeechLang}>
                  <Select.Trigger
                    ref={voiceSelectTriggerRef}
                    className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger"
                    aria-label="Voice recognition language"
                  >
                    <Select.Value />
                    <Select.Icon asChild>
                      <span className="quickadd-project-trigger-icon" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Select.Icon>
                  </Select.Trigger>
                  <Select.Portal>
                    <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                      <Select.Viewport className="quickadd-project-viewport">
                        {VOICE_LANG_OPTIONS.map((option) => (
                          <Select.Item key={option.value} value={option.value} className="quickadd-project-item">
                            <Select.ItemText>{option.label}</Select.ItemText>
                            <Select.ItemIndicator className="quickadd-project-item-indicator">
                              <Icon path="M5 13l4 4L19 7" />
                            </Select.ItemIndicator>
                          </Select.Item>
                        ))}
                      </Select.Viewport>
                    </Select.Content>
                  </Select.Portal>
                </Select.Root>
                <p className="meta">Selected: {selectedVoiceLabel}</p>
              </section>

              <section className="profile-pane-card" aria-label="Account actions">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
                    </span>
                    <span>Account</span>
                  </h3>
                  <span className="status-chip">Session</span>
                </div>
                <div className="profile-account-row">
                  <div className="profile-fact-user-name">{userName}</div>
                  <button className="button-secondary profile-action-button" type="button" onClick={onLogout} title="Logout">
                    <Icon path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                    <span>Logout</span>
                  </button>
                </div>
              </section>
            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="security">
            <section className="profile-pane-card profile-password" aria-label="Password settings">
              <Accordion.Root className="profile-accordion" type="single" collapsible defaultValue="change-password">
                <Accordion.Item className="profile-accordion-item" value="change-password">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">Change password</span>
                        <span className="profile-accordion-meta">Current password required · minimum 8 chars</span>
                      </span>
                      <span className="status-chip">Security</span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <form className="profile-bug-form" onSubmit={handleSubmitPasswordChange}>
                      <label className="field-control">
                        <span className="field-label">Current password</span>
                        <input
                          type="password"
                          value={currentPasswordInput}
                          onChange={(event) => setCurrentPasswordInput(event.target.value)}
                          autoComplete="current-password"
                          placeholder="Current password"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">New password</span>
                        <input
                          type="password"
                          value={newPasswordInput}
                          onChange={(event) => setNewPasswordInput(event.target.value)}
                          autoComplete="new-password"
                          placeholder="New password"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Confirm new password</span>
                        <input
                          type="password"
                          value={confirmPasswordInput}
                          onChange={(event) => setConfirmPasswordInput(event.target.value)}
                          autoComplete="new-password"
                          placeholder="Confirm new password"
                        />
                      </label>
                      <div className="row wrap profile-actions">
                        <button
                          className="primary"
                          type="submit"
                          disabled={
                            passwordChangePending ||
                            !currentPasswordInput.trim() ||
                            !newPasswordInput.trim() ||
                            !confirmPasswordInput.trim()
                          }
                        >
                          {passwordChangePending ? 'Saving...' : 'Save new password'}
                        </button>
                        <button
                          className="button-secondary"
                          type="button"
                          onClick={resetPasswordForm}
                          disabled={passwordChangePending}
                        >
                          Reset
                        </button>
                      </div>
                    </form>
                    {passwordFeedback ? (
                      <div className={`notice ${passwordFeedback.tone === 'error' ? 'notice-error' : ''}`.trim()}>
                        {passwordFeedback.message}
                      </div>
                    ) : null}
                  </Accordion.Content>
                </Accordion.Item>
              </Accordion.Root>
            </section>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="feedback">
            <div className="profile-pane-grid">
              <section className="profile-pane-card profile-bug-report" aria-label="Feedback">
                <Accordion.Root className="profile-accordion" type="single" collapsible defaultValue="submit-feedback">
                  <Accordion.Item className="profile-accordion-item" value="submit-feedback">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Leave feedback</span>
                          <span className="profile-accordion-meta">Product feedback routed to support pipeline</span>
                        </span>
                        <span className="status-chip">Support</span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <form className="profile-bug-form" onSubmit={handleSubmitFeedback}>
                        <label className="field-control">
                          <span className="field-label">Topic</span>
                          <input
                            value={feedbackTitleInput}
                            onChange={(event) => setFeedbackTitleInput(event.target.value)}
                            placeholder="Short feedback title"
                          />
                        </label>
                        <label className="field-control">
                          <span className="field-label">Type</span>
                          <Select.Root
                            value={feedbackTypeInput}
                            onValueChange={(value: 'general' | 'feature_request' | 'question' | 'other') => setFeedbackTypeInput(value)}
                          >
                            <Select.Trigger
                              className="quickadd-project-trigger taskdrawer-select-trigger profile-select-trigger"
                              aria-label="Feedback type"
                            >
                              <Select.Value />
                              <Select.Icon asChild>
                                <span className="quickadd-project-trigger-icon" aria-hidden="true">
                                  <Icon path="M6 9l6 6 6-6" />
                                </span>
                              </Select.Icon>
                            </Select.Trigger>
                            <Select.Portal>
                              <Select.Content className="quickadd-project-content profile-select-content" position="popper" sideOffset={6}>
                                <Select.Viewport className="quickadd-project-viewport">
                                  {PROFILE_FEEDBACK_TYPE_OPTIONS.map((option) => (
                                    <Select.Item key={option.value} value={option.value} className="quickadd-project-item">
                                      <Select.ItemText>{option.label}</Select.ItemText>
                                      <Select.ItemIndicator className="quickadd-project-item-indicator">
                                        <Icon path="M5 13l4 4L19 7" />
                                      </Select.ItemIndicator>
                                    </Select.Item>
                                  ))}
                                </Select.Viewport>
                              </Select.Content>
                            </Select.Portal>
                          </Select.Root>
                          <span className="meta">{selectedFeedbackTypeLabel}</span>
                        </label>
                        <label className="field-control">
                          <span className="field-label">Details</span>
                          <textarea
                            rows={5}
                            value={feedbackDescriptionInput}
                            onChange={(event) => setFeedbackDescriptionInput(event.target.value)}
                            placeholder="Describe your feedback"
                          />
                        </label>
                        <div className="row wrap profile-actions">
                          <button
                            className="primary"
                            type="submit"
                            disabled={feedbackSubmitting || !feedbackTitleInput.trim() || !feedbackDescriptionInput.trim()}
                          >
                            {feedbackSubmitting ? 'Sending...' : 'Send feedback'}
                          </button>
                          <button
                            className="button-secondary"
                            type="button"
                            onClick={resetFeedbackForm}
                            disabled={feedbackSubmitting}
                          >
                            Reset
                          </button>
                        </div>
                      </form>
                      {feedbackResult ? (
                        <div className={`notice ${feedbackResult.tone === 'error' ? 'notice-error' : ''}`.trim()}>
                          {feedbackResult.message}
                        </div>
                      ) : null}
                    </Accordion.Content>
                  </Accordion.Item>
                </Accordion.Root>
              </section>

              <section className="profile-pane-card" aria-label="GitHub issues">
                <div className="profile-pane-head">
                  <h3>
                    <span className="profile-pane-head-icon" aria-hidden="true">
                      <Icon path="M9 3h6l1 2h3v4h-2l-1 8H8L7 9H5V5h3zM10 11h4M10 14h4" />
                    </span>
                    <span>Bug reports</span>
                  </h3>
                  <span className="status-chip">GitHub</span>
                </div>
                <p className="meta">For reproducible defects and stack traces, open an issue in the project repository.</p>
                <div className="row wrap profile-actions" style={{ marginTop: 4 }}>
                  <a
                    className="primary"
                    href={GITHUB_ISSUES_URL}
                    target="_blank"
                    rel="noreferrer"
                    style={{ textDecoration: 'none' }}
                  >
                    Open GitHub Issues
                  </a>
                </div>
              </section>
            </div>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="runtime">
            <section className="profile-pane-card profile-runtime" aria-label="Build details">
              <div className="profile-pane-head">
                <h3>
                  <span className="profile-pane-head-icon" aria-hidden="true">
                    <Icon path="M4 4h16v12H4zM10 20h4M12 16v4" />
                  </span>
                  <span>Runtime</span>
                </h3>
                <span className="status-chip">Live</span>
              </div>
              <div className="profile-runtime-chip-row">
                <span className="status-chip">Frontend {frontendVersion}</span>
                <span className="status-chip">Backend {backendVersion}</span>
                <span className="status-chip">{backendBuild ? `Build ${backendBuild}` : 'Build n/a'}</span>
              </div>
              <div className="row wrap profile-actions profile-runtime-actions">
                <button className="button-secondary profile-action-button" type="button" onClick={copyRuntimeSnapshot}>
                  <Icon path="M16 1H4a2 2 0 0 0-2 2v12h2V3h12V1zM19 5H8a2 2 0 0 0-2 2v14h13a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z" />
                  <span>Copy runtime snapshot</span>
                </button>
                {runtimeCopyState === 'copied' ? <span className="status-chip">Copied</span> : null}
                {runtimeCopyState === 'error' ? <span className="status-chip">Copy failed</span> : null}
              </div>
              <Accordion.Root
                className="profile-accordion profile-runtime-accordion"
                type="multiple"
                defaultValue={['versions', 'deployment', 'preferences']}
              >
                <Accordion.Item className="profile-accordion-item" value="versions">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">
                          <span className="profile-accordion-title-icon" aria-hidden="true">
                            <Icon path="M4 5h16M4 12h16M4 19h16" />
                          </span>
                          <span>Version matrix</span>
                        </span>
                        <span className="profile-accordion-meta">Frontend, backend, and build identifiers</span>
                      </span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <dl className="profile-facts profile-runtime-facts">
                      <div className="profile-fact">
                        <dt>Frontend version</dt>
                        <dd>{frontendVersion || 'n/a'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Backend version</dt>
                        <dd>{backendVersion || 'n/a'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Backend build</dt>
                        <dd>{backendBuild || 'n/a'}</dd>
                      </div>
                    </dl>
                  </Accordion.Content>
                </Accordion.Item>
                <Accordion.Item className="profile-accordion-item" value="deployment">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">
                          <span className="profile-accordion-title-icon" aria-hidden="true">
                            <Icon path="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z" />
                          </span>
                          <span>Deployment</span>
                        </span>
                        <span className="profile-accordion-meta">Timestamp and local environment details</span>
                      </span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <dl className="profile-facts profile-runtime-facts">
                      <div className="profile-fact">
                        <dt>Deployed (UTC)</dt>
                        <dd>{deployedAtUtc ?? 'unknown'}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Deployed (local)</dt>
                        <dd>{formatDateTime(deployedAtUtc)}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Browser timezone</dt>
                        <dd>{browserTimeZone}</dd>
                      </div>
                    </dl>
                  </Accordion.Content>
                </Accordion.Item>
                <Accordion.Item className="profile-accordion-item" value="preferences">
                  <Accordion.Header className="profile-accordion-header">
                    <Accordion.Trigger className="profile-accordion-trigger">
                      <span className="profile-accordion-head">
                        <span className="profile-accordion-title">
                          <span className="profile-accordion-title-icon" aria-hidden="true">
                            <Icon path="M4 7h16M7 12h10M9 17h6" />
                          </span>
                          <span>Active preferences</span>
                        </span>
                        <span className="profile-accordion-meta">Theme and speech language currently in use</span>
                      </span>
                      <span className="profile-accordion-chevron" aria-hidden="true">
                        <Icon path="M6 9l6 6 6-6" />
                      </span>
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="profile-accordion-content">
                    <dl className="profile-facts profile-runtime-facts">
                      <div className="profile-fact">
                        <dt>Theme</dt>
                        <dd>{theme}</dd>
                      </div>
                      <div className="profile-fact">
                        <dt>Voice language</dt>
                        <dd>{selectedVoiceLabel}</dd>
                      </div>
                    </dl>
                    <div className="row wrap profile-actions profile-runtime-actions">
                      <button
                        className="button-secondary"
                        type="button"
                        onClick={() => {
                          setProfileTab('preferences')
                          window.setTimeout(() => {
                            scrollVoiceLanguageIntoView()
                          }, 60)
                        }}
                      >
                        Open preference controls
                      </button>
                    </div>
                  </Accordion.Content>
                </Accordion.Item>
              </Accordion.Root>
            </section>
          </Tabs.Content>

          <Tabs.Content className="profile-tab-content" value="license">
            <section className="profile-pane-card profile-license" aria-label="License details">
              <div className="profile-pane-head">
                <h3>
                  <span className="profile-pane-head-icon" aria-hidden="true">
                    <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
                  </span>
                  <span>License</span>
                </h3>
                <span className="status-chip">{licenseStatusLabel}</span>
              </div>
              {licenseLoading ? (
                <p className="meta">Loading license status...</p>
              ) : licenseError ? (
                <div className="notice notice-error">{licenseError}</div>
              ) : !license ? (
                <p className="meta">License status is unavailable.</p>
              ) : (
                <Accordion.Root className="profile-accordion profile-license-accordion" type="multiple" defaultValue={['entitlement', 'lifecycle', 'installation']}>
                  <Accordion.Item className="profile-accordion-item" value="entitlement">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Entitlement</span>
                          <span className="profile-accordion-meta">{entitlementSource}</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Entitlement status</dt>
                          <dd>{formatLabel(license.status)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Subscription status</dt>
                          <dd>{formatLabel(subscriptionStatus)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Entitlement source</dt>
                          <dd>{entitlementSource}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Plan</dt>
                          <dd>{license.plan_code || 'n/a'}</dd>
                        </div>
                      </dl>
                    </Accordion.Content>
                  </Accordion.Item>

                  <Accordion.Item className="profile-accordion-item" value="lifecycle">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Lifecycle dates</span>
                          <span className="profile-accordion-meta">Subscription, trial, and grace windows</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Subscription valid until</dt>
                          <dd>{formatDateTime(subscriptionValidUntil)}</dd>
                        </div>
                        <div className="profile-fact">
                          <dt>Public beta free until</dt>
                          <dd>{formatDateTime(publicBetaFreeUntil)}</dd>
                        </div>
                        {showTrialWindow ? (
                          <div className="profile-fact">
                            <dt>Trial ends</dt>
                            <dd>{formatDateTime(license.trial_ends_at)}</dd>
                          </div>
                        ) : null}
                        {showTrialWindow ? (
                          <div className="profile-fact">
                            <dt>Grace ends</dt>
                            <dd>{formatDateTime(license.grace_ends_at)}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </Accordion.Content>
                  </Accordion.Item>

                  <Accordion.Item className="profile-accordion-item" value="installation">
                    <Accordion.Header className="profile-accordion-header">
                      <Accordion.Trigger className="profile-accordion-trigger">
                        <span className="profile-accordion-head">
                          <span className="profile-accordion-title">Installation details</span>
                          <span className="profile-accordion-meta">Local installation and license identity</span>
                        </span>
                        <span className="profile-accordion-chevron" aria-hidden="true">
                          <Icon path="M6 9l6 6 6-6" />
                        </span>
                      </Accordion.Trigger>
                    </Accordion.Header>
                    <Accordion.Content className="profile-accordion-content">
                      <dl className="profile-facts profile-license-facts">
                        <div className="profile-fact">
                          <dt>Installation ID</dt>
                          <dd>
                            <code>{license.installation_id || 'n/a'}</code>
                          </dd>
                        </div>
                      </dl>
                      <div className="row wrap profile-actions">
                        <button
                          type="button"
                          className="button-secondary profile-action-button"
                          onClick={() => {
                            void copyInstallationId()
                          }}
                          disabled={!String(license.installation_id || '').trim()}
                        >
                          <Icon path="M9 9h11v11H9zM4 4h11v2H6v9H4z" />
                          <span>Copy installation ID</span>
                        </button>
                        {installationCopyState === 'copied' ? <span className="status-chip">Copied</span> : null}
                        {installationCopyState === 'error' ? <span className="status-chip">Copy failed</span> : null}
                      </div>
                    </Accordion.Content>
                  </Accordion.Item>
                </Accordion.Root>
              )}
            </section>
          </Tabs.Content>
        </Tabs.Root>
      </section>
    </Tooltip.Provider>
  )
}

export function AdminPanel({
  canManageUsers,
  workspaceId,
  users,
  usersLoading,
  usersError,
  username,
  setUsername,
  fullName,
  setFullName,
  role,
  setRole,
  createPending,
  onCreate,
  lastTempPassword,
  onResetPassword,
  resetPendingUserId,
  onUpdateRole,
  updateRolePendingUserId,
  onDeactivateUser,
  deactivatePendingUserId,
  workspaceSkills,
  workspaceSkillsLoading,
  importWorkspaceSkillPending,
  importWorkspaceSkillFilePending,
  patchWorkspaceSkillPending,
  deleteWorkspaceSkillPending,
  onImportWorkspaceSkill,
  onImportWorkspaceSkillFile,
  onPatchWorkspaceSkill,
  onDeleteWorkspaceSkill,
}: {
  canManageUsers: boolean
  workspaceId: string
  users: AdminWorkspaceUser[]
  usersLoading: boolean
  usersError: string | null
  username: string
  setUsername: (value: string) => void
  fullName: string
  setFullName: (value: string) => void
  role: string
  setRole: (value: string) => void
  createPending: boolean
  onCreate: () => void
  lastTempPassword: string | null
  onResetPassword: (userId: string) => void
  resetPendingUserId: string | null
  onUpdateRole: (userId: string, role: string) => void
  updateRolePendingUserId: string | null
  onDeactivateUser: (userId: string) => void
  deactivatePendingUserId: string | null
  workspaceSkills: WorkspaceSkillsPage | undefined
  workspaceSkillsLoading: boolean
  importWorkspaceSkillPending: boolean
  importWorkspaceSkillFilePending: boolean
  patchWorkspaceSkillPending: boolean
  deleteWorkspaceSkillPending: boolean
  onImportWorkspaceSkill: (payload: {
    source_url: string
    skill_key?: string
    mode?: 'advisory' | 'enforced'
    trust_level?: 'verified' | 'reviewed' | 'untrusted'
  }) => Promise<unknown>
  onImportWorkspaceSkillFile: (payload: {
    file: File
    skill_key?: string
    mode?: 'advisory' | 'enforced'
    trust_level?: 'verified' | 'reviewed' | 'untrusted'
  }) => Promise<unknown>
  onPatchWorkspaceSkill: (payload: {
    skillId: string
    patch: {
      name?: string
      summary?: string
      content?: string
      mode?: 'advisory' | 'enforced'
      trust_level?: 'verified' | 'reviewed' | 'untrusted'
    }
  }) => Promise<unknown>
  onDeleteWorkspaceSkill: (skillId: string) => Promise<unknown>
}) {
  const [skillSourceUrl, setSkillSourceUrl] = React.useState('')
  const [skillKey, setSkillKey] = React.useState('')
  const [skillMode, setSkillMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [skillTrustLevel, setSkillTrustLevel] = React.useState<'verified' | 'reviewed' | 'untrusted'>('reviewed')
  const [workspaceSkillContentView, setWorkspaceSkillContentView] = React.useState<'write' | 'preview' | 'split'>('write')
  const [workspaceSkillEditorName, setWorkspaceSkillEditorName] = React.useState('')
  const [workspaceSkillEditorSummary, setWorkspaceSkillEditorSummary] = React.useState('')
  const [workspaceSkillEditorContent, setWorkspaceSkillEditorContent] = React.useState('')
  const [workspaceSkillEditorMode, setWorkspaceSkillEditorMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [workspaceSkillEditorTrustLevel, setWorkspaceSkillEditorTrustLevel] = React.useState<
    'verified' | 'reviewed' | 'untrusted'
  >('reviewed')
  const [adminTab, setAdminTab] = React.useState<'users' | 'skills'>('users')
  const [skillsSearchQ, setSkillsSearchQ] = React.useState('')
  const [selectedWorkspaceSkillId, setSelectedWorkspaceSkillId] = React.useState<string | null>(null)
  const workspaceSkillFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const workspaceSkillItems = workspaceSkills?.items ?? []
  const totalUsers = users.length
  const totalSkills = workspaceSkills?.total ?? workspaceSkillItems.length
  const activeUsers = React.useMemo(() => users.filter((item) => Boolean(item.is_active)).length, [users])
  const inactiveUsers = Math.max(0, totalUsers - activeUsers)
  const normalizedCreateRole = React.useMemo(
    () => normalizeOptionValue(role, ADMIN_ROLE_OPTIONS, 'Member'),
    [role]
  )
  const getWorkspaceSkillSourceContent = React.useCallback((manifest: Record<string, unknown> | undefined): string => {
    if (!manifest || typeof manifest !== 'object') return ''
    const raw = (manifest as Record<string, unknown>).source_content
    return typeof raw === 'string' ? raw : ''
  }, [])
  const selectedWorkspaceSkill = React.useMemo(
    () => workspaceSkillItems.find((item) => item.id === selectedWorkspaceSkillId) ?? null,
    [selectedWorkspaceSkillId, workspaceSkillItems]
  )
  const filteredWorkspaceSkillItems = React.useMemo(() => {
    const query = String(skillsSearchQ || '').trim().toLowerCase()
    if (!query) return workspaceSkillItems
    return workspaceSkillItems.filter((item) => {
      const haystack = [
        String(item.name || ''),
        String(item.skill_key || ''),
        String(item.summary || ''),
        String(item.source_locator || ''),
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(query)
    })
  }, [skillsSearchQ, workspaceSkillItems])
  const workspaceSkillEditorDirty = React.useMemo(() => {
    if (!selectedWorkspaceSkill) return false
    const currentMode = String(selectedWorkspaceSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory'
    const currentTrustLevel =
      String(selectedWorkspaceSkill.trust_level || '').toLowerCase() === 'verified'
        ? 'verified'
        : String(selectedWorkspaceSkill.trust_level || '').toLowerCase() === 'untrusted'
          ? 'untrusted'
          : 'reviewed'
    return (
      workspaceSkillEditorName.trim() !== String(selectedWorkspaceSkill.name || '').trim() ||
      workspaceSkillEditorSummary !== String(selectedWorkspaceSkill.summary || '') ||
      workspaceSkillEditorContent !==
        getWorkspaceSkillSourceContent(selectedWorkspaceSkill?.manifest as Record<string, unknown> | undefined) ||
      workspaceSkillEditorMode !== currentMode ||
      workspaceSkillEditorTrustLevel !== currentTrustLevel
    )
  }, [
    selectedWorkspaceSkill,
    getWorkspaceSkillSourceContent,
    workspaceSkillEditorContent,
    workspaceSkillEditorMode,
    workspaceSkillEditorName,
    workspaceSkillEditorSummary,
    workspaceSkillEditorTrustLevel,
  ])

  React.useEffect(() => {
    if (workspaceSkillItems.length === 0) {
      setSelectedWorkspaceSkillId(null)
      return
    }
    if (!selectedWorkspaceSkillId) return
    if (workspaceSkillItems.some((item) => item.id === selectedWorkspaceSkillId)) return
    setSelectedWorkspaceSkillId(null)
  }, [selectedWorkspaceSkillId, workspaceSkillItems])

  React.useEffect(() => {
    if (!selectedWorkspaceSkill) {
      setWorkspaceSkillEditorName('')
      setWorkspaceSkillEditorSummary('')
      setWorkspaceSkillEditorContent('')
      setWorkspaceSkillEditorMode('advisory')
      setWorkspaceSkillEditorTrustLevel('reviewed')
      return
    }
    setWorkspaceSkillEditorName(String(selectedWorkspaceSkill.name || ''))
    setWorkspaceSkillEditorSummary(String(selectedWorkspaceSkill.summary || ''))
    setWorkspaceSkillEditorContent(
      getWorkspaceSkillSourceContent(selectedWorkspaceSkill?.manifest as Record<string, unknown> | undefined)
    )
    setWorkspaceSkillEditorMode(
      String(selectedWorkspaceSkill.mode || '').toLowerCase() === 'enforced' ? 'enforced' : 'advisory'
    )
    const nextTrustLevel = String(selectedWorkspaceSkill.trust_level || '').toLowerCase()
    if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
      setWorkspaceSkillEditorTrustLevel(nextTrustLevel)
    } else {
      setWorkspaceSkillEditorTrustLevel('reviewed')
    }
  }, [getWorkspaceSkillSourceContent, selectedWorkspaceSkill])

  if (!canManageUsers) {
    return (
      <section className="card">
        <h2>Admin</h2>
        <p className="meta">Admin access required.</p>
      </section>
    )
  }

  return (
    <Tooltip.Provider delayDuration={180}>
      <section className="card admin-panel">
      <div className="admin-panel-head">
        <div>
          <h2>Admin</h2>
          <p className="meta">Create users, assign workspace roles, and rotate credentials.</p>
        </div>
        <span className="status-chip admin-workspace-chip">Workspace: {workspaceId || 'n/a'}</span>
      </div>
      <div className="admin-panel-summary">
        <span className="status-chip admin-summary-chip">
          <Icon path="M16 11c1.66 0 3-1.57 3-3.5S17.66 4 16 4s-3 1.57-3 3.5 1.34 3.5 3 3.5M8 11c1.66 0 3-1.57 3-3.5S9.66 4 8 4 5 5.57 5 7.5 6.34 11 8 11M8 13c-2.67 0-8 1.34-8 4v3h10v-3c0-1.53.82-2.75 2.05-3.73C10.72 13.09 9.32 13 8 13M16 13c-.26 0-.54.02-.83.05 1.43 1 2.33 2.39 2.33 3.95v3H24v-3c0-2.66-5.33-4-8-4" />
          <span>Users: {totalUsers}</span>
        </span>
        <span className="status-chip admin-summary-chip">
          <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8.5-7 9.5-3.5-1-7-4.5-7-9.5V7l7-4z" />
          <span>Active: {activeUsers}</span>
        </span>
        {inactiveUsers > 0 ? (
          <span className="status-chip admin-summary-chip">
            <Icon path="M6 6l12 12M18 6 6 18" />
            <span>Inactive: {inactiveUsers}</span>
          </span>
        ) : null}
        <span className="status-chip admin-summary-chip">
          <Icon path="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 7H20M6.5 7A2.5 2.5 0 0 1 4 9.5v10" />
          <span>Skills: {totalSkills}</span>
        </span>
      </div>

      <Tabs.Root
        className="admin-tabs"
        value={adminTab}
        onValueChange={(nextTab) => {
          if (nextTab === 'users' || nextTab === 'skills') setAdminTab(nextTab)
        }}
      >
        <Tabs.List className="admin-tabs-list" aria-label="Admin sections">
          <Tabs.Trigger className="admin-tab-trigger" value="users">
            <span className="admin-tab-trigger-icon" aria-hidden="true">
              <Icon path="M16 11c1.66 0 3-1.57 3-3.5S17.66 4 16 4s-3 1.57-3 3.5 1.34 3.5 3 3.5M8 11c1.66 0 3-1.57 3-3.5S9.66 4 8 4 5 5.57 5 7.5 6.34 11 8 11M8 13c-2.67 0-8 1.34-8 4v3h10v-3c0-1.53.82-2.75 2.05-3.73C10.72 13.09 9.32 13 8 13M16 13c-.26 0-.54.02-.83.05 1.43 1 2.33 2.39 2.33 3.95v3H24v-3c0-2.66-5.33-4-8-4" />
            </span>
            <span>Users</span>
            <span className="status-chip admin-tab-count">{totalUsers}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="admin-tab-trigger" value="skills">
            <span className="admin-tab-trigger-icon" aria-hidden="true">
              <Icon path="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 7H20M6.5 7A2.5 2.5 0 0 1 4 9.5v10" />
            </span>
            <span>Skills catalog</span>
            <span className="status-chip admin-tab-count">{totalSkills}</span>
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className="admin-tab-content" value="users">
          <Accordion.Root className="profile-accordion admin-accordion" type="single" collapsible defaultValue="create-user">
            <Accordion.Item className="profile-accordion-item" value="create-user">
              <Accordion.Header className="profile-accordion-header">
                <Accordion.Trigger className="profile-accordion-trigger">
                  <span className="profile-accordion-head">
                    <span className="profile-accordion-title">Create user</span>
                    <span className="profile-accordion-meta">Provision a human account with initial workspace role.</span>
                  </span>
                  <span className="status-chip">Workspace</span>
                  <span className="profile-accordion-chevron" aria-hidden="true">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="profile-accordion-content">
                <div className="admin-create">
                  <div className="admin-create-grid">
                    <label className="field-control">
                      <span className="field-label">Username</span>
                      <input
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        placeholder="3-64 chars"
                        autoComplete="off"
                      />
                    </label>
                    <label className="field-control">
                      <span className="field-label">Full name</span>
                      <input
                        value={fullName}
                        onChange={(event) => setFullName(event.target.value)}
                        placeholder="Optional"
                        autoComplete="off"
                      />
                    </label>
                    <label className="field-control">
                      <span className="field-label">Role</span>
                      <AdminSelect
                        value={normalizedCreateRole}
                        onValueChange={setRole}
                        options={ADMIN_ROLE_OPTIONS}
                        ariaLabel="New user workspace role"
                        disabled={createPending}
                      />
                    </label>
                    <div className="admin-create-actions">
                      <button className="primary" type="button" onClick={onCreate} disabled={createPending || !username.trim()}>
                        {createPending ? 'Creating...' : 'Create user'}
                      </button>
                    </div>
                  </div>
                </div>
              </Accordion.Content>
            </Accordion.Item>
          </Accordion.Root>

          {lastTempPassword ? (
            <div className="notice admin-temp-password">
              Temporary password: <code>{lastTempPassword}</code>
            </div>
          ) : null}

          <div className="admin-users">
            <div className="admin-users-head">
              <h3>Workspace users</h3>
              <span className="meta">{totalUsers} total</span>
            </div>
            {usersLoading ? (
              <div className="meta">Loading users...</div>
            ) : usersError ? (
              <div className="notice notice-error">{usersError}</div>
            ) : users.length === 0 ? (
              <div className="meta">No users.</div>
            ) : (
              <div className="admin-user-list">
                {users.map((item) => {
                  const canResetPassword = item.can_reset_password ?? item.user_type === 'human'
                  const canDeactivate = item.can_deactivate ?? (item.user_type === 'human' && item.is_active)
                  const roleUpdatePending = updateRolePendingUserId === item.id
                  const resetPending = resetPendingUserId === item.id
                  const deactivatePending = deactivatePendingUserId === item.id
                  const normalizedUserRole = normalizeOptionValue(String(item.role || ''), ADMIN_ROLE_OPTIONS, 'Member')
                  return (
                    <article key={item.id} className="admin-user-row">
                      <div className="admin-user-main">
                        <div className="admin-user-title">
                          <strong>{item.full_name || item.username}</strong>
                          <span className="admin-user-username">@{item.username}</span>
                        </div>
                        <div className="admin-user-badges">
                          <span className="status-chip">{item.role}</span>
                          <span className="status-chip">{item.user_type}</span>
                          {canResetPassword && item.must_change_password ? <span className="status-chip">must change password</span> : null}
                          {!canResetPassword ? <span className="status-chip">service account</span> : null}
                          {!item.is_active ? <span className="status-chip">inactive</span> : null}
                        </div>
                      </div>
                      <div className="admin-user-actions">
                        <label className="field-control admin-role-field">
                          <span className="field-label">Role</span>
                          <AdminSelect
                            value={normalizedUserRole}
                            onValueChange={(nextRole) => {
                              if (nextRole === normalizedUserRole) return
                              onUpdateRole(item.id, nextRole)
                            }}
                            options={ADMIN_ROLE_OPTIONS}
                            disabled={roleUpdatePending}
                            ariaLabel={`Set workspace role for ${item.username}`}
                          />
                        </label>
                        {item.is_active && canResetPassword ? (
                          <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                              <button
                                className="admin-reset-btn"
                                type="button"
                                onClick={() => onResetPassword(item.id)}
                                disabled={resetPending}
                              >
                                <Icon path="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" />
                                <span>{resetPending ? 'Resetting...' : 'Reset password'}</span>
                              </button>
                            </Tooltip.Trigger>
                            <Tooltip.Portal>
                              <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                Generate a temporary password for this user
                                <Tooltip.Arrow className="header-tooltip-arrow" />
                              </Tooltip.Content>
                            </Tooltip.Portal>
                          </Tooltip.Root>
                        ) : null}
                        {item.is_active && canDeactivate ? (
                          <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                              <button
                                className="admin-deactivate-btn"
                                type="button"
                                onClick={() => {
                                  const confirmDeactivate = window.confirm(
                                    `Deactivate ${item.username}? They will be signed out and unable to log in.`
                                  )
                                  if (!confirmDeactivate) return
                                  onDeactivateUser(item.id)
                                }}
                                disabled={deactivatePending}
                              >
                                <Icon path="M6 6l12 12M18 6 6 18" />
                                <span>{deactivatePending ? 'Deactivating...' : 'Deactivate user'}</span>
                              </button>
                            </Tooltip.Trigger>
                            <Tooltip.Portal>
                              <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                Disable login and revoke active sessions
                                <Tooltip.Arrow className="header-tooltip-arrow" />
                              </Tooltip.Content>
                            </Tooltip.Portal>
                          </Tooltip.Root>
                        ) : null}
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </Tabs.Content>

        <Tabs.Content className="admin-tab-content" value="skills">
          <div className="admin-skills">
            <Accordion.Root className="profile-accordion admin-accordion" type="single" collapsible defaultValue="import-skill">
              <Accordion.Item className="profile-accordion-item" value="import-skill">
                <Accordion.Header className="profile-accordion-header">
                  <Accordion.Trigger className="profile-accordion-trigger">
                    <span className="profile-accordion-head">
                      <span className="profile-accordion-title">Add new skill</span>
                      <span className="profile-accordion-meta">Import from URL or upload a local file.</span>
                    </span>
                    <span className="status-chip">Catalog</span>
                    <span className="profile-accordion-chevron" aria-hidden="true">
                      <Icon path="M6 9l6 6 6-6" />
                    </span>
                  </Accordion.Trigger>
                </Accordion.Header>
                <Accordion.Content className="profile-accordion-content">
                  <div className="admin-create">
                    <div className="admin-skill-import-grid">
                      <label className="field-control">
                        <span className="field-label">Source URL</span>
                        <input
                          value={skillSourceUrl}
                          onChange={(event) => setSkillSourceUrl(event.target.value)}
                          placeholder="https://example.com/skills/jira-execution.md"
                          autoComplete="off"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Skill key (optional)</span>
                        <input
                          value={skillKey}
                          onChange={(event) => setSkillKey(event.target.value)}
                          placeholder="github_delivery"
                          autoComplete="off"
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Mode</span>
                        <AdminSelect
                          value={skillMode}
                          onValueChange={(nextMode) => setSkillMode(nextMode === 'enforced' ? 'enforced' : 'advisory')}
                          options={SKILL_MODE_OPTIONS}
                          ariaLabel="Skill mode"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                        />
                      </label>
                      <label className="field-control">
                        <span className="field-label">Trust level</span>
                        <AdminSelect
                          value={skillTrustLevel}
                          onValueChange={(nextTrustLevel) => {
                            if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
                              setSkillTrustLevel(nextTrustLevel)
                            } else {
                              setSkillTrustLevel('reviewed')
                            }
                          }}
                          options={SKILL_TRUST_OPTIONS}
                          ariaLabel="Skill trust level"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                        />
                      </label>
                      <div className="admin-skill-import-actions row wrap">
                        <button
                          className="status-chip admin-skill-action-btn"
                          type="button"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending || !String(skillSourceUrl || '').trim()}
                          title="Add skill from URL"
                          aria-label="Add skill from URL"
                          onClick={() => {
                            const sourceUrl = String(skillSourceUrl || '').trim()
                            if (!sourceUrl) return
                            void onImportWorkspaceSkill({
                              source_url: sourceUrl,
                              skill_key: String(skillKey || '').trim() || undefined,
                              mode: skillMode,
                              trust_level: skillTrustLevel,
                            })
                              .then(() => {
                                setSkillSourceUrl('')
                                setSkillKey('')
                                setSkillMode('advisory')
                                setSkillTrustLevel('reviewed')
                              })
                              .catch(() => {
                                // Error feedback is handled by app-level UI notice.
                              })
                          }}
                        >
                          <Icon path={importWorkspaceSkillPending ? 'M12 5v14M5 12h14' : 'M12 5v10m0 0l4-4m-4 4l-4-4M4 21h16'} />
                          <span>{importWorkspaceSkillPending ? 'Adding...' : 'Add from URL'}</span>
                        </button>
                        <button
                          className="status-chip admin-skill-action-btn"
                          type="button"
                          disabled={importWorkspaceSkillPending || importWorkspaceSkillFilePending}
                          title="Upload skill file"
                          aria-label="Upload skill file"
                          onClick={() => workspaceSkillFileInputRef.current?.click()}
                        >
                          <Icon
                            path={
                              importWorkspaceSkillFilePending
                                ? 'M12 5v14M5 12h14'
                                : 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6'
                            }
                          />
                          <span>{importWorkspaceSkillFilePending ? 'Uploading...' : 'Upload file'}</span>
                        </button>
                        <input
                          ref={workspaceSkillFileInputRef}
                          type="file"
                          accept=".md,.markdown,.txt,.json,text/plain,text/markdown,application/json"
                          style={{ display: 'none' }}
                          onChange={(event) => {
                            const file = event.target.files?.[0]
                            event.currentTarget.value = ''
                            if (!file) return
                            void onImportWorkspaceSkillFile({
                              file,
                              skill_key: String(skillKey || '').trim() || undefined,
                              mode: skillMode,
                              trust_level: skillTrustLevel,
                            })
                              .then(() => {
                                setSkillSourceUrl('')
                                setSkillKey('')
                                setSkillMode('advisory')
                                setSkillTrustLevel('reviewed')
                              })
                              .catch(() => {
                                // Error feedback is handled by app-level UI notice.
                              })
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </Accordion.Content>
              </Accordion.Item>
            </Accordion.Root>

            <div className="row wrap" style={{ marginTop: 8, marginBottom: 8 }}>
              <input
                value={skillsSearchQ}
                onChange={(event) => setSkillsSearchQ(event.target.value)}
                placeholder="Filter catalog by name, key, summary, or source"
                style={{ flex: 1, minWidth: 240 }}
              />
            </div>
            <div className="rules-list">
              {workspaceSkillsLoading ? (
                <div className="notice">Loading workspace catalog...</div>
              ) : filteredWorkspaceSkillItems.length === 0 ? (
                <div className="notice">No workspace skills found.</div>
              ) : (
                filteredWorkspaceSkillItems.map((skill) => {
                  const isExpanded = selectedWorkspaceSkillId === skill.id
                  const selectedThisSkill = isExpanded && selectedWorkspaceSkill?.id === skill.id
                  return (
                    <div
                      key={skill.id}
                      className={`task-item rule-item ${isExpanded ? 'selected' : ''}`.trim()}
                      onClick={() => setSelectedWorkspaceSkillId((current) => (current === skill.id ? null : skill.id))}
                      role="button"
                      aria-expanded={isExpanded}
                    >
                      <div className="task-main">
                        <div className="task-title">
                          <div className="row" style={{ gap: 6, minWidth: 0 }}>
                            {skill.is_seeded ? <span className="rule-kind-chip">[SEEDED]</span> : null}
                            <strong>{skill.name || skill.skill_key || 'Untitled catalog skill'}</strong>
                          </div>
                          <Tooltip.Root>
                            <Tooltip.Trigger asChild>
                              <button
                                className="action-icon danger-ghost"
                                type="button"
                                disabled={deleteWorkspaceSkillPending}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  const confirmed = window.confirm(`Delete catalog skill "${skill.name || skill.skill_key}"?`)
                                  if (!confirmed) return
                                  void onDeleteWorkspaceSkill(skill.id).catch(() => {
                                    // Error feedback is handled by app-level UI notice.
                                  })
                                }}
                                title="Delete catalog skill"
                                aria-label="Delete catalog skill"
                              >
                                <Icon path="M6 7h12M9 7V5h6v2m-7 3v10m4-10v10m4-10v10M8 7l1 14h6l1-14" />
                              </button>
                            </Tooltip.Trigger>
                            <Tooltip.Portal>
                              <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
                                Remove skill from workspace catalog
                                <Tooltip.Arrow className="header-tooltip-arrow" />
                              </Tooltip.Content>
                            </Tooltip.Portal>
                          </Tooltip.Root>
                        </div>
                        <div className="meta">
                          key: {skill.skill_key || '-'} | mode: {skill.mode || '-'} | trust: {skill.trust_level || '-'}
                        </div>
                        <div className="meta">{(skill.summary || '').replace(/\s+/g, ' ').slice(0, 160) || '(no summary)'}</div>
                        <div className="meta">source: {skill.source_locator || '(none)'}</div>
                        {selectedThisSkill ? (
                          <div
                            className="note-accordion"
                            onClick={(event) => event.stopPropagation()}
                            role="region"
                            aria-label="Catalog skill details"
                          >
                            <div className="row rule-title-row" style={{ marginBottom: 8, justifyContent: 'space-between', gap: 8 }}>
                              <input
                                className="rule-title-input"
                                value={workspaceSkillEditorName}
                                onChange={(event) => setWorkspaceSkillEditorName(event.target.value)}
                                placeholder="Skill name"
                              />
                              <button
                                className="action-icon primary"
                                type="button"
                                disabled={!workspaceSkillEditorName.trim() || !workspaceSkillEditorDirty || patchWorkspaceSkillPending}
                                onClick={() => {
                                  void onPatchWorkspaceSkill({
                                    skillId: skill.id,
                                    patch: {
                                      name: workspaceSkillEditorName.trim(),
                                      summary: workspaceSkillEditorSummary,
                                      content: workspaceSkillEditorContent,
                                      mode: workspaceSkillEditorMode,
                                      trust_level: workspaceSkillEditorTrustLevel,
                                    },
                                  }).catch(() => {
                                    // Error feedback is handled by app-level UI notice.
                                  })
                                }}
                                title="Save skill changes"
                                aria-label="Save skill changes"
                              >
                                <Icon path="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zM12 19a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM6 8h9" />
                              </button>
                            </div>
                            <div className="row wrap" style={{ gap: 8, marginBottom: 8 }}>
                              <label className="field-control admin-inline-field" style={{ minWidth: 150, marginBottom: 0 }}>
                                <span className="field-label">Mode</span>
                                <AdminSelect
                                  value={workspaceSkillEditorMode}
                                  onValueChange={(nextMode) =>
                                    setWorkspaceSkillEditorMode(nextMode === 'enforced' ? 'enforced' : 'advisory')
                                  }
                                  options={SKILL_MODE_OPTIONS}
                                  ariaLabel="Catalog skill mode"
                                  disabled={patchWorkspaceSkillPending}
                                />
                              </label>
                              <label className="field-control admin-inline-field" style={{ minWidth: 170, marginBottom: 0 }}>
                                <span className="field-label">Trust level</span>
                                <AdminSelect
                                  value={workspaceSkillEditorTrustLevel}
                                  onValueChange={(nextTrustLevel) => {
                                    if (nextTrustLevel === 'verified' || nextTrustLevel === 'untrusted') {
                                      setWorkspaceSkillEditorTrustLevel(nextTrustLevel)
                                    } else {
                                      setWorkspaceSkillEditorTrustLevel('reviewed')
                                    }
                                  }}
                                  options={SKILL_TRUST_OPTIONS}
                                  ariaLabel="Catalog skill trust level"
                                  disabled={patchWorkspaceSkillPending}
                                />
                              </label>
                            </div>
                            <div className="md-editor-surface">
                              <div className="md-editor-content">
                                <textarea
                                  className="md-textarea"
                                  value={workspaceSkillEditorSummary}
                                  onChange={(event) => setWorkspaceSkillEditorSummary(event.target.value)}
                                  placeholder="Skill summary"
                                  style={{ width: '100%', minHeight: 96 }}
                                />
                              </div>
                            </div>
                            <div className="meta" style={{ marginTop: 8 }}>
                              Source: {skill.source_locator || '(none)'}
                            </div>
                            <div className="meta" style={{ marginTop: 8 }}>Skill content</div>
                            <div className="md-editor-surface">
                              <MarkdownModeToggle
                                view={workspaceSkillContentView}
                                onChange={setWorkspaceSkillContentView}
                                ariaLabel="Catalog skill content editor view"
                              />
                              <div className="md-editor-content">
                                {workspaceSkillContentView === 'write' ? (
                                  <textarea
                                    className="md-textarea"
                                    value={workspaceSkillEditorContent}
                                    onChange={(event) => setWorkspaceSkillEditorContent(event.target.value)}
                                    placeholder="Write skill content in Markdown..."
                                    style={{ width: '100%', minHeight: 180 }}
                                  />
                                ) : workspaceSkillContentView === 'split' ? (
                                  <MarkdownSplitPane
                                    left={(
                                      <textarea
                                        className="md-textarea"
                                        value={workspaceSkillEditorContent}
                                        onChange={(event) => setWorkspaceSkillEditorContent(event.target.value)}
                                        placeholder="Write skill content in Markdown..."
                                        style={{ width: '100%', minHeight: 180 }}
                                      />
                                    )}
                                    right={<MarkdownView value={workspaceSkillEditorContent} />}
                                    ariaLabel="Resize workspace skill editor and preview panels"
                                  />
                                ) : (
                                  <MarkdownView value={workspaceSkillEditorContent} />
                                )}
                              </div>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </Tabs.Content>
      </Tabs.Root>
      </section>
    </Tooltip.Provider>
  )
}

export function TaskResultsPanel({
  tasks,
  total,
  showProject,
  projectNames,
  specificationNames,
  onOpenSpecification,
  onOpen,
  onTagClick,
  onRestore,
  onReopen,
  onComplete,
}: {
  tasks: Task[]
  total: number
  showProject: boolean
  projectNames: Record<string, string>
  specificationNames: Record<string, string>
  onOpenSpecification: (specificationId: string, projectId: string) => void
  onOpen: (taskId: string) => void
  onTagClick?: (tag: string) => void
  onRestore: (taskId: string) => void
  onReopen: (taskId: string) => void
  onComplete: (taskId: string) => void
}) {
  return (
    <section className="card">
      <h2>Tasks ({total})</h2>
      <div className="task-list">
        {tasks.map((task) => (
          <TaskListItem
            key={task.id}
            task={task}
            onOpen={onOpen}
            onOpenSpecification={onOpenSpecification}
            onTagClick={onTagClick}
            onRestore={onRestore}
            onReopen={onReopen}
            onComplete={onComplete}
            showProject={showProject}
            projectName={projectNames[task.project_id]}
            specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
          />
        ))}
      </div>
    </section>
  )
}

export function GlobalSearchResultsPanel({
  tasks,
  tasksTotal,
  notes,
  notesTotal,
  specifications,
  specificationsTotal,
  searchQuery,
  semanticMode,
  semanticSearching,
  semanticTaskIds,
  semanticNoteIds,
  semanticSpecificationIds,
  lexicalTaskIds,
  lexicalNoteIds,
  lexicalSpecificationIds,
  projectNames,
  specificationNames,
  onOpenSpecification,
  onOpenTask,
  onTaskTagClick,
  onNoteTagClick,
  onSpecificationTagClick,
  onRestoreTask,
  onReopenTask,
  onCompleteTask,
  onOpenNote,
}: {
  tasks: Task[]
  tasksTotal: number
  notes: Note[]
  notesTotal: number
  specifications: Specification[]
  specificationsTotal: number
  searchQuery: string
  semanticMode: string
  semanticSearching: boolean
  semanticTaskIds: string[]
  semanticNoteIds: string[]
  semanticSpecificationIds: string[]
  lexicalTaskIds: string[]
  lexicalNoteIds: string[]
  lexicalSpecificationIds: string[]
  projectNames: Record<string, string>
  specificationNames: Record<string, string>
  onOpenSpecification: (specificationId: string, projectId: string) => void
  onOpenTask: (taskId: string) => void
  onTaskTagClick: (tag: string) => void
  onNoteTagClick: (tag: string) => void
  onSpecificationTagClick: (tag: string) => void
  onRestoreTask: (taskId: string) => void
  onReopenTask: (taskId: string) => void
  onCompleteTask: (taskId: string) => void
  onOpenNote: (noteId: string, projectId?: string | null) => boolean
}) {
  const normalizedQuery = String(searchQuery || '').trim()
  const normalizedSemanticMode = String(semanticMode || 'empty').trim().toLowerCase()
  const semanticTaskSet = React.useMemo(() => new Set((semanticTaskIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [semanticTaskIds])
  const semanticNoteSet = React.useMemo(() => new Set((semanticNoteIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [semanticNoteIds])
  const semanticSpecificationSet = React.useMemo(
    () => new Set((semanticSpecificationIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)),
    [semanticSpecificationIds]
  )
  const lexicalTaskSet = React.useMemo(() => new Set((lexicalTaskIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [lexicalTaskIds])
  const lexicalNoteSet = React.useMemo(() => new Set((lexicalNoteIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)), [lexicalNoteIds])
  const lexicalSpecificationSet = React.useMemo(
    () => new Set((lexicalSpecificationIds ?? []).map((id) => String(id || '').trim()).filter(Boolean)),
    [lexicalSpecificationIds]
  )
  const semanticAddedTaskSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticTaskSet) {
      if (!lexicalTaskSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalTaskSet, semanticTaskSet])
  const semanticAddedNoteSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticNoteSet) {
      if (!lexicalNoteSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalNoteSet, semanticNoteSet])
  const semanticAddedSpecificationSet = React.useMemo(() => {
    const out = new Set<string>()
    for (const id of semanticSpecificationSet) {
      if (!lexicalSpecificationSet.has(id)) out.add(id)
    }
    return out
  }, [lexicalSpecificationSet, semanticSpecificationSet])
  const semanticAddedCount = semanticAddedTaskSet.size + semanticAddedNoteSet.size + semanticAddedSpecificationSet.size
  const totalResults = tasksTotal + notesTotal + specificationsTotal

  const semanticModeLabel = (() => {
    if (normalizedSemanticMode === 'graph+vector') return 'Graph + vector'
    if (normalizedSemanticMode === 'vector-only') return 'Vector only'
    if (normalizedSemanticMode === 'graph-only') return 'Graph only'
    if (normalizedSemanticMode === 'empty') return 'No semantic context'
    return normalizedSemanticMode || 'Unknown'
  })()
  const semanticModeClassSuffix = (() => {
    if (normalizedSemanticMode === 'graph+vector') return 'graph-vector'
    if (normalizedSemanticMode === 'vector-only') return 'vector-only'
    if (normalizedSemanticMode === 'graph-only') return 'graph-only'
    return 'empty'
  })()

  const renderTasksSection = () => (
    <section className="card">
      <h2>Tasks ({tasksTotal})</h2>
      <div className="task-list">
        {tasks.length === 0 ? (
          <div className="notice">No matching tasks.</div>
        ) : (
          tasks.map((task) => (
            <TaskListItem
              key={task.id}
              task={task}
              onOpen={onOpenTask}
              onOpenSpecification={onOpenSpecification}
              onTagClick={onTaskTagClick}
              onRestore={onRestoreTask}
              onReopen={onReopenTask}
              onComplete={onCompleteTask}
              semanticHit={semanticAddedTaskSet.has(String(task.id))}
              showProject
              projectName={projectNames[task.project_id]}
              specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
            />
          ))
        )}
      </div>
    </section>
  )

  const renderNotesSection = () => (
    <section className="card">
      <h2>Notes ({notesTotal})</h2>
      <div className="task-list">
        {notes.length === 0 ? (
          <div className="notice">No matching notes.</div>
        ) : (
          notes.map((note) => {
            const semanticHit = semanticAddedNoteSet.has(String(note.id))
            return (
              <div key={note.id} className="note-row search-result-row">
                <div className="note-title">
                  <div className="note-title-main">
                    {note.archived && <span className="badge">Archived</span>}
                    {note.pinned && <span className="badge">Pinned</span>}
                    <strong>{note.title || 'Untitled'}</strong>
                  </div>
                  <div className="task-title-badges">
                    {semanticHit ? <span className="task-kind-pill task-kind-pill-semantic">SEMANTIC</span> : null}
                  </div>
                  <div className="note-row-actions">
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          className="action-icon note-row-actions-trigger"
                          type="button"
                          title="Note result actions"
                          aria-label="Note result actions"
                        >
                          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                          <DropdownMenu.Item className="task-group-menu-item" onSelect={() => onOpenNote(note.id, note.project_id)}>
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                            <span>Open note</span>
                          </DropdownMenu.Item>
                          {note.specification_id ? (
                            <DropdownMenu.Item
                              className="task-group-menu-item"
                              onSelect={() => onOpenSpecification(note.specification_id as string, note.project_id)}
                            >
                              <Icon path="M6 2h12a2 2 0 0 1 2 2v16l-4 2-4-2-4 2-4-2V4a2 2 0 0 1 2-2zm3 5h6m-6 4h6m-6 4h4" />
                              <span>Open specification</span>
                            </DropdownMenu.Item>
                          ) : null}
                          {(note.tags ?? []).length > 0 ? (
                            <>
                              <DropdownMenu.Separator className="task-group-menu-separator" />
                              {(note.tags ?? []).map((tag) => (
                                <DropdownMenu.Item
                                  key={`note-result-tag-${note.id}-${tag}`}
                                  className="task-group-menu-item"
                                  onSelect={() => onNoteTagClick(tag)}
                                >
                                  <Icon path="M20 10V4a1 1 0 0 0-1-1h-6l-9 9 8 8 9-9zM14.5 7.5h.01" />
                                  <span>Filter by #{tag}</span>
                                </DropdownMenu.Item>
                              ))}
                            </>
                          ) : null}
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </div>
                <div className="meta" style={{ marginTop: 6 }}>{projectNames[note.project_id] || 'Unknown project'}</div>
                <div className="note-snippet">{(note.body || '').replace(/\s+/g, ' ').slice(0, 180) || '(empty)'}</div>
                {(note.tags ?? []).length > 0 && (
                  <div className="note-tags" style={{ marginTop: 8 }}>
                    {(note.tags ?? []).map((tag) => (
                      <button
                        key={`${note.id}-${tag}`}
                        type="button"
                        className="tag-mini tag-clickable"
                        onClick={() => onNoteTagClick(tag)}
                        title={`Filter by tag: ${tag}`}
                        style={{
                          backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                          borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                          color: `hsl(${tagHue(tag)}, 55%, 28%)`
                        }}
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                )}
                <div className="row wrap" style={{ marginTop: 8, gap: 6 }}>
                  <button className="status-chip" onClick={() => onOpenNote(note.id, note.project_id)}>
                    Open note
                  </button>
                  {note.specification_id && (
                    <button
                      className="status-chip"
                      onClick={() => onOpenSpecification(note.specification_id as string, note.project_id)}
                    >
                      Open specification
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </section>
  )

  const renderSpecificationsSection = () => (
    <section className="card">
      <h2>Specifications ({specificationsTotal})</h2>
      <div className="task-list">
        {specifications.length === 0 ? (
          <div className="notice">No matching specifications.</div>
        ) : (
          specifications.map((specification) => {
            const semanticHit = semanticAddedSpecificationSet.has(String(specification.id))
            return (
              <div key={specification.id} className="note-row search-result-row">
                <div className="note-title">
                  <div className="note-title-main">
                    {specification.archived && <span className="badge">Archived</span>}
                    <strong>{specification.title || 'Untitled spec'}</strong>
                  </div>
                  <div className="task-title-badges">
                    {semanticHit ? <span className="task-kind-pill task-kind-pill-semantic">SEMANTIC</span> : null}
                  </div>
                  <div className="note-row-actions">
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <button
                          className="action-icon note-row-actions-trigger"
                          type="button"
                          title="Specification result actions"
                          aria-label="Specification result actions"
                        >
                          <Icon path="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0m7 0a1 1 0 1 1-2 0 1 1 0 0 1 2 0" />
                        </button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="task-group-menu-content note-row-menu-content" sideOffset={8} align="end">
                          <DropdownMenu.Item
                            className="task-group-menu-item"
                            onSelect={() => onOpenSpecification(specification.id, specification.project_id)}
                          >
                            <Icon path="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zm9 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z" />
                            <span>Open specification</span>
                          </DropdownMenu.Item>
                          {(specification.tags ?? []).length > 0 ? (
                            <>
                              <DropdownMenu.Separator className="task-group-menu-separator" />
                              {(specification.tags ?? []).map((tag) => (
                                <DropdownMenu.Item
                                  key={`spec-result-tag-${specification.id}-${tag}`}
                                  className="task-group-menu-item"
                                  onSelect={() => onSpecificationTagClick(tag)}
                                >
                                  <Icon path="M20 10V4a1 1 0 0 0-1-1h-6l-9 9 8 8 9-9zM14.5 7.5h.01" />
                                  <span>Filter by #{tag}</span>
                                </DropdownMenu.Item>
                              ))}
                            </>
                          ) : null}
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  </div>
                </div>
                <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
                  <span className="status-chip">{specification.status}</span>
                  <span className="meta">{projectNames[specification.project_id] || 'Unknown project'}</span>
                </div>
                <div className="note-snippet">{(specification.body || '').replace(/\s+/g, ' ').slice(0, 180) || '(empty)'}</div>
                {(specification.tags ?? []).length > 0 && (
                  <div className="task-tags" style={{ marginTop: 8 }}>
                    {(specification.tags ?? []).map((tag) => (
                      <button
                        key={`${specification.id}-${tag}`}
                        type="button"
                        className="tag-mini tag-clickable"
                        onClick={() => onSpecificationTagClick(tag)}
                        title={`Filter by tag: ${tag}`}
                        style={{
                          backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                          borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                          color: `hsl(${tagHue(tag)}, 55%, 28%)`
                        }}
                      >
                        #{tag}
                      </button>
                    ))}
                  </div>
                )}
                <div className="row wrap" style={{ marginTop: 8 }}>
                  <button
                    className="status-chip"
                    onClick={() => onOpenSpecification(specification.id, specification.project_id)}
                  >
                    Open specification
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>
    </section>
  )

  return (
    <>
      <section className="card search-results-summary-card">
        <div className="search-results-summary-row">
          <div className="search-results-summary-title">
            <h2 style={{ margin: 0 }}>Results ({totalResults})</h2>
            {normalizedQuery ? (
              <span className="meta">Query: "{normalizedQuery}"</span>
            ) : (
              <span className="meta">Enter a query to narrow results.</span>
            )}
          </div>
          <div className="search-results-summary-badges">
            {semanticSearching ? (
              <span className="badge">Semantic: Searching...</span>
            ) : (
              <span className={`badge search-semantic-mode-badge mode-${semanticModeClassSuffix}`}>
                Semantic: {semanticModeLabel}
              </span>
            )}
            {semanticAddedCount > 0 ? <span className="badge">Semantic additions: {semanticAddedCount}</span> : null}
          </div>
        </div>
      </section>

      <Tabs.Root className="search-results-tabs" defaultValue="all">
        <Tabs.List className="search-results-tabs-list" aria-label="Search result sections">
          <Tabs.Trigger className="search-results-tab-trigger" value="all">
            All
            <span className="search-results-tab-count">{totalResults}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="tasks">
            Tasks
            <span className="search-results-tab-count">{tasksTotal}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="notes">
            Notes
            <span className="search-results-tab-count">{notesTotal}</span>
          </Tabs.Trigger>
          <Tabs.Trigger className="search-results-tab-trigger" value="specifications">
            Specs
            <span className="search-results-tab-count">{specificationsTotal}</span>
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content className="search-results-tab-content" value="all">
          {renderTasksSection()}
          {renderNotesSection()}
          {renderSpecificationsSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="tasks">
          {renderTasksSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="notes">
          {renderNotesSection()}
        </Tabs.Content>
        <Tabs.Content className="search-results-tab-content" value="specifications">
          {renderSpecificationsSection()}
        </Tabs.Content>
      </Tabs.Root>

      {normalizedQuery.length >= 3 && !semanticSearching && semanticAddedCount === 0 ? (
        <section className="card">
          <div className="notice">
            Semantic search is active, but this query currently has no additional semantic matches.
          </div>
        </section>
      ) : null}
    </>
  )
}
