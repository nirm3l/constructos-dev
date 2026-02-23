import React from 'react'
import type {
  AdminWorkspaceUser,
  BugReportCreateRequest,
  BugReportCreateResponse,
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
import { Icon, MarkdownModeToggle } from './shared/uiHelpers'
import { TaskListItem } from './tasks/taskViews'

const VOICE_LANG_OPTIONS = [
  { value: 'bs-BA', label: 'Bosnian (bs-BA)' },
  { value: 'en-US', label: 'English (en-US)' },
]

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
  return (
    <section className="card">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0 }}>Search</h2>
        <button className="action-icon" onClick={onClose} title="Close search" aria-label="Close search">
          <Icon path="M6 6l12 12M18 6 6 18" />
        </button>
      </div>
      <div className="row wrap" style={{ marginTop: 10 }}>
        <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} placeholder="Search text" />
        <select value={searchStatus} onChange={(e) => setSearchStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="To do">To do</option>
          <option value="In progress">In progress</option>
          <option value="Done">Done</option>
        </select>
        <select value={searchSpecificationStatus} onChange={(e) => setSearchSpecificationStatus(e.target.value)}>
          <option value="">Any spec status</option>
          <option value="Draft">Draft</option>
          <option value="Ready">Ready</option>
          <option value="In progress">In progress</option>
          <option value="Implemented">Implemented</option>
          <option value="Archived">Archived</option>
        </select>
        <select value={searchPriority} onChange={(e) => setSearchPriority(e.target.value)}>
          <option value="">Any priority</option>
          <option value="Low">Low</option>
          <option value="Med">Med</option>
          <option value="High">High</option>
        </select>
        <label className="row archived-toggle">
          <input type="checkbox" checked={searchArchived} onChange={(e) => setSearchArchived(e.target.checked)} />
          Archived only
        </label>
        <div className="row wrap">
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
  submitBugReport,
  bugReportSubmitting,
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
  submitBugReport: (payload: BugReportCreateRequest) => Promise<BugReportCreateResponse>
  bugReportSubmitting: boolean
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
  const [bugTitle, setBugTitle] = React.useState('')
  const [bugDescription, setBugDescription] = React.useState('')
  const [bugSeverity, setBugSeverity] = React.useState<'low' | 'medium' | 'high' | 'critical'>('medium')
  const [bugSteps, setBugSteps] = React.useState('')
  const [bugExpected, setBugExpected] = React.useState('')
  const [bugActual, setBugActual] = React.useState('')
  const [bugReportExpanded, setBugReportExpanded] = React.useState(false)
  const [bugFeedback, setBugFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const [passwordExpanded, setPasswordExpanded] = React.useState(false)
  const [currentPasswordInput, setCurrentPasswordInput] = React.useState('')
  const [newPasswordInput, setNewPasswordInput] = React.useState('')
  const [confirmPasswordInput, setConfirmPasswordInput] = React.useState('')
  const [passwordFeedback, setPasswordFeedback] = React.useState<{ tone: 'success' | 'error'; message: string } | null>(null)
  const voiceFactRef = React.useRef<HTMLDivElement | null>(null)
  const voiceSelectRef = React.useRef<HTMLSelectElement | null>(null)

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
        voiceSelectRef.current?.focus({ preventScroll: true })
      } catch {
        voiceSelectRef.current?.focus()
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
      scrollVoiceLanguageIntoView()
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

  const resetBugForm = React.useCallback(() => {
    setBugTitle('')
    setBugDescription('')
    setBugSeverity('medium')
    setBugSteps('')
    setBugExpected('')
    setBugActual('')
  }, [])

  const resetPasswordForm = React.useCallback(() => {
    setCurrentPasswordInput('')
    setNewPasswordInput('')
    setConfirmPasswordInput('')
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

  const handleSubmitBugReport = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      const title = String(bugTitle || '').trim()
      const description = String(bugDescription || '').trim()
      if (!title) {
        setBugFeedback({ tone: 'error', message: 'Bug title is required.' })
        return
      }
      if (!description) {
        setBugFeedback({ tone: 'error', message: 'Bug description is required.' })
        return
      }
      try {
        const result = await submitBugReport({
          title,
          description,
          steps_to_reproduce: String(bugSteps || '').trim() || null,
          expected_behavior: String(bugExpected || '').trim() || null,
          actual_behavior: String(bugActual || '').trim() || null,
          severity: bugSeverity,
          context: {},
          metadata: {},
        })
        resetBugForm()
        if (result.queued) {
          setBugFeedback({
            tone: 'success',
            message: 'Control plane unavailable. Bug report was queued and will retry automatically.',
          })
        } else {
          setBugFeedback({ tone: 'success', message: 'Bug report was sent successfully.' })
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to submit bug report.'
        setBugFeedback({ tone: 'error', message })
      }
    },
    [
      bugActual,
      bugDescription,
      bugExpected,
      bugSeverity,
      bugSteps,
      bugTitle,
      resetBugForm,
      submitBugReport,
    ]
  )

  return (
    <section className="card profile-panel">
      <div className="profile-panel-head">
        <div className="profile-panel-identity">
          <div className="profile-avatar" aria-hidden="true">
            <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
          </div>
          <div className="profile-head-copy">
            <h2>Profile</h2>
            <p className="meta">Account settings</p>
          </div>
        </div>
        <span className="status-chip profile-theme-chip">{theme} mode</span>
      </div>

      <dl className="profile-facts">
        <div className="profile-fact">
          <dt>User</dt>
          <dd>
            <div className="profile-fact-user-row">
              <div className="profile-fact-user-name">{userName}</div>
              <div className="row profile-fact-actions">
                <button
                  className="primary profile-action-button"
                  onClick={onToggleTheme}
                  title={`Switch to ${nextTheme} theme`}
                >
                  <Icon path="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79" />
                  <span>{nextTheme === 'dark' ? 'Dark mode' : 'Light mode'}</span>
                </button>
                <button className="danger-ghost profile-action-button" onClick={onLogout} title="Logout">
                  <Icon path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
                  <span>Logout</span>
                </button>
              </div>
            </div>
          </dd>
        </div>
        <div className="profile-fact" id="profile-voice-language" ref={voiceFactRef}>
          <dt>Voice language</dt>
          <dd>
            <select
              ref={voiceSelectRef}
              className="profile-voice-select"
              value={speechLang}
              onChange={(e) => onChangeSpeechLang(e.target.value)}
              aria-label="Voice recognition language"
            >
              {VOICE_LANG_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </dd>
        </div>
      </dl>

      <section className="profile-password" aria-label="Password settings">
        <div className="profile-license-head">
          <button
            type="button"
            className="profile-section-toggle"
            aria-expanded={passwordExpanded}
            aria-controls="profile-password-panel"
            onClick={() => setPasswordExpanded((current) => !current)}
          >
            <span>Change password</span>
            <span className="profile-section-toggle-icon" aria-hidden="true">
              <Icon path="M9 6l6 6-6 6" />
            </span>
          </button>
          <span className="status-chip">Security</span>
        </div>
        {passwordExpanded ? (
          <div id="profile-password-panel">
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
          </div>
        ) : null}
      </section>

      <section className="profile-runtime" aria-label="Build details">
        <div className="profile-license-head">
          <h3>Build details</h3>
          <span className="status-chip">Runtime</span>
        </div>
        <dl className="profile-facts">
          <div className="profile-fact">
            <dt>Frontend version</dt>
            <dd>{frontendVersion}</dd>
          </div>
          <div className="profile-fact">
            <dt>Backend version</dt>
            <dd>
              {backendVersion}
              {backendBuild ? ` (${backendBuild})` : ''}
            </dd>
          </div>
          <div className="profile-fact">
            <dt>Deployed (UTC)</dt>
            <dd>{deployedAtUtc ?? 'unknown'}</dd>
          </div>
        </dl>
      </section>

      <section className="profile-bug-report" aria-label="Bug reporting">
        <div className="profile-license-head">
          <button
            type="button"
            className="profile-section-toggle"
            aria-expanded={bugReportExpanded}
            aria-controls="profile-bug-report-panel"
            onClick={() => setBugReportExpanded((current) => !current)}
          >
            <span>Report a bug</span>
            <span className="profile-section-toggle-icon" aria-hidden="true">
              <Icon path="M9 6l6 6-6 6" />
            </span>
          </button>
          <span className="status-chip">Control Plane</span>
        </div>
        {bugReportExpanded && (
          <div id="profile-bug-report-panel">
            <form className="profile-bug-form" onSubmit={handleSubmitBugReport}>
              <label className="field-control">
                <span className="field-label">Title</span>
                <input
                  value={bugTitle}
                  onChange={(event) => setBugTitle(event.target.value)}
                  placeholder="Short summary"
                  maxLength={140}
                  autoComplete="off"
                />
              </label>
              <label className="field-control">
                <span className="field-label">Severity</span>
                <select value={bugSeverity} onChange={(event) => setBugSeverity(event.target.value as 'low' | 'medium' | 'high' | 'critical')}>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                  <option value="critical">critical</option>
                </select>
              </label>
              <label className="field-control">
                <span className="field-label">Description</span>
                <textarea
                  value={bugDescription}
                  onChange={(event) => setBugDescription(event.target.value)}
                  rows={4}
                  placeholder="What is happening?"
                />
              </label>
              <label className="field-control">
                <span className="field-label">Steps to reproduce (optional)</span>
                <textarea
                  value={bugSteps}
                  onChange={(event) => setBugSteps(event.target.value)}
                  rows={3}
                  placeholder="Exact steps"
                />
              </label>
              <label className="field-control">
                <span className="field-label">Expected behavior (optional)</span>
                <textarea
                  value={bugExpected}
                  onChange={(event) => setBugExpected(event.target.value)}
                  rows={2}
                  placeholder="What should happen?"
                />
              </label>
              <label className="field-control">
                <span className="field-label">Actual behavior (optional)</span>
                <textarea
                  value={bugActual}
                  onChange={(event) => setBugActual(event.target.value)}
                  rows={2}
                  placeholder="What actually happens?"
                />
              </label>
              <div className="row wrap profile-actions">
                <button className="primary" type="submit" disabled={bugReportSubmitting || !bugTitle.trim() || !bugDescription.trim()}>
                  {bugReportSubmitting ? 'Submitting...' : 'Submit Bug Report'}
                </button>
                <button className="button-secondary" type="button" onClick={resetBugForm} disabled={bugReportSubmitting}>
                  Reset
                </button>
              </div>
            </form>
            {bugFeedback && (
              <div className={`notice ${bugFeedback.tone === 'error' ? 'notice-error' : ''}`.trim()}>
                {bugFeedback.message}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="profile-license" aria-label="License details">
        <div className="profile-license-head">
          <h3>License</h3>
          <span className="status-chip">{licenseStatusLabel}</span>
        </div>
        {licenseLoading ? (
          <p className="meta">Loading license status...</p>
        ) : licenseError ? (
          <div className="notice notice-error">{licenseError}</div>
        ) : !license ? (
          <p className="meta">License status is unavailable.</p>
        ) : (
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
              <dt>Installation ID</dt>
              <dd>
                <code>{license.installation_id || 'n/a'}</code>
              </dd>
            </div>
            <div className="profile-fact">
              <dt>Plan</dt>
              <dd>{license.plan_code || 'n/a'}</dd>
            </div>
            <div className="profile-fact">
              <dt>Subscription valid until</dt>
              <dd>{formatDateTime(subscriptionValidUntil)}</dd>
            </div>
            {showTrialWindow && (
              <div className="profile-fact">
                <dt>Trial ends</dt>
                <dd>{formatDateTime(license.trial_ends_at)}</dd>
              </div>
            )}
            {showTrialWindow && (
              <div className="profile-fact">
                <dt>Grace ends</dt>
                <dd>{formatDateTime(license.grace_ends_at)}</dd>
              </div>
            )}
          </dl>
        )}
      </section>
    </section>
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
  const [workspaceSkillContentView, setWorkspaceSkillContentView] = React.useState<'write' | 'preview'>('write')
  const [workspaceSkillEditorName, setWorkspaceSkillEditorName] = React.useState('')
  const [workspaceSkillEditorSummary, setWorkspaceSkillEditorSummary] = React.useState('')
  const [workspaceSkillEditorContent, setWorkspaceSkillEditorContent] = React.useState('')
  const [workspaceSkillEditorMode, setWorkspaceSkillEditorMode] = React.useState<'advisory' | 'enforced'>('advisory')
  const [workspaceSkillEditorTrustLevel, setWorkspaceSkillEditorTrustLevel] = React.useState<
    'verified' | 'reviewed' | 'untrusted'
  >('reviewed')
  const [skillsSearchQ, setSkillsSearchQ] = React.useState('')
  const [selectedWorkspaceSkillId, setSelectedWorkspaceSkillId] = React.useState<string | null>(null)
  const workspaceSkillFileInputRef = React.useRef<HTMLInputElement | null>(null)
  const workspaceSkillItems = workspaceSkills?.items ?? []
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
    <section className="card admin-panel">
      <div className="admin-panel-head">
        <div>
          <h2>Admin</h2>
          <p className="meta">Create users, assign workspace roles, and rotate credentials.</p>
        </div>
        <span className="status-chip admin-workspace-chip">Workspace: {workspaceId || 'n/a'}</span>
      </div>

      <div className="admin-create">
        <div className="admin-create-grid">
          <label className="field-control">
            <span className="field-label">Username</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="3-64 chars"
              autoComplete="off"
            />
          </label>
          <label className="field-control">
            <span className="field-label">Full name</span>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Optional"
              autoComplete="off"
            />
          </label>
          <label className="field-control">
            <span className="field-label">Role</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              aria-label="New user workspace role"
            >
              <option value="Member">Member</option>
              <option value="Admin">Admin</option>
              <option value="Guest">Guest</option>
              <option value="Owner">Owner</option>
            </select>
          </label>
          <div className="admin-create-actions">
            <button className="primary" onClick={onCreate} disabled={createPending || !username.trim()}>
              {createPending ? 'Creating...' : 'Create user'}
            </button>
          </div>
        </div>
      </div>

      {lastTempPassword && (
        <div className="notice admin-temp-password">
          Temporary password: <code>{lastTempPassword}</code>
        </div>
      )}

      <div className="admin-users">
        <div className="admin-users-head">
          <h3>Workspace users</h3>
          <span className="meta">{users.length} total</span>
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
                      {canResetPassword && item.must_change_password && <span className="status-chip">must change password</span>}
                      {!canResetPassword && <span className="status-chip">service account</span>}
                      {!item.is_active && <span className="status-chip">inactive</span>}
                    </div>
                  </div>
                  <div className="admin-user-actions">
                    <label className="field-control admin-role-field">
                      <span className="field-label">Role</span>
                      <select
                        value={item.role}
                        onChange={(e) => {
                          const nextRole = e.target.value
                          if (nextRole === item.role) return
                          onUpdateRole(item.id, nextRole)
                        }}
                        disabled={roleUpdatePending}
                        title="Workspace role"
                        aria-label={`Set workspace role for ${item.username}`}
                      >
                        <option value="Owner">Owner</option>
                        <option value="Admin">Admin</option>
                        <option value="Member">Member</option>
                        <option value="Guest">Guest</option>
                      </select>
                    </label>
                    {item.is_active && canResetPassword ? (
                      <button
                        className="admin-reset-btn"
                        onClick={() => onResetPassword(item.id)}
                        disabled={resetPending}
                      >
                        <Icon path="M20 11a8 8 0 1 0 2.3 5.6M20 4v7h-7" />
                        <span>{resetPending ? 'Resetting...' : 'Reset password'}</span>
                      </button>
                    ) : null}
                    {item.is_active && canDeactivate ? (
                      <button
                        className="admin-deactivate-btn"
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
                    ) : null}
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </div>

      <div className="admin-skills">
        <div className="admin-users-head">
          <h3>Skills Catalog</h3>
          <span className="meta">{workspaceSkills?.total ?? workspaceSkillItems.length} total</span>
        </div>
        <div className="admin-create">
          <div className="row wrap" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8 }}>
            <strong>Add New Skill</strong>
            <span className="meta">Import from URL or upload a local file.</span>
          </div>
          <div className="admin-skill-import-grid">
            <label className="field-control">
              <span className="field-label">Source URL</span>
              <input
                value={skillSourceUrl}
                onChange={(e) => setSkillSourceUrl(e.target.value)}
                placeholder="https://example.com/skills/jira-execution.md"
                autoComplete="off"
              />
            </label>
            <label className="field-control">
              <span className="field-label">Skill key (optional)</span>
              <input
                value={skillKey}
                onChange={(e) => setSkillKey(e.target.value)}
                placeholder="github_delivery"
                autoComplete="off"
              />
            </label>
            <label className="field-control">
              <span className="field-label">Mode</span>
              <select
                value={skillMode}
                onChange={(e) => setSkillMode(e.target.value === 'enforced' ? 'enforced' : 'advisory')}
              >
                <option value="advisory">advisory</option>
                <option value="enforced">enforced</option>
              </select>
            </label>
            <label className="field-control">
              <span className="field-label">Trust level</span>
              <select
                value={skillTrustLevel}
                onChange={(e) => {
                  const next = e.target.value
                  if (next === 'verified' || next === 'untrusted') {
                    setSkillTrustLevel(next)
                  } else {
                    setSkillTrustLevel('reviewed')
                  }
                }}
              >
                <option value="reviewed">reviewed</option>
                <option value="verified">verified</option>
                <option value="untrusted">untrusted</option>
              </select>
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
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.currentTarget.value = ''
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
        <div className="row wrap" style={{ marginTop: 8, marginBottom: 8 }}>
          <input
            value={skillsSearchQ}
            onChange={(e) => setSkillsSearchQ(e.target.value)}
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
                    </div>
                    <div className="meta">
                      key: {skill.skill_key || '-'} | mode: {skill.mode || '-'} | trust: {skill.trust_level || '-'}
                    </div>
                    <div className="meta">{(skill.summary || '').replace(/\s+/g, ' ').slice(0, 160) || '(no summary)'}</div>
                    <div className="meta">source: {skill.source_locator || '(none)'}</div>
                    {selectedThisSkill ? (
                      <div className="note-accordion" onClick={(event) => event.stopPropagation()} role="region" aria-label="Catalog skill details">
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
                          <label className="field-control" style={{ minWidth: 150, marginBottom: 0 }}>
                            <span className="field-label">Mode</span>
                            <select
                              value={workspaceSkillEditorMode}
                              onChange={(event) =>
                                setWorkspaceSkillEditorMode(event.target.value === 'enforced' ? 'enforced' : 'advisory')
                              }
                            >
                              <option value="advisory">advisory</option>
                              <option value="enforced">enforced</option>
                            </select>
                          </label>
                          <label className="field-control" style={{ minWidth: 170, marginBottom: 0 }}>
                            <span className="field-label">Trust level</span>
                            <select
                              value={workspaceSkillEditorTrustLevel}
                              onChange={(event) => {
                                const next = event.target.value
                                if (next === 'verified' || next === 'untrusted') {
                                  setWorkspaceSkillEditorTrustLevel(next)
                                } else {
                                  setWorkspaceSkillEditorTrustLevel('reviewed')
                                }
                              }}
                            >
                              <option value="reviewed">reviewed</option>
                              <option value="verified">verified</option>
                              <option value="untrusted">untrusted</option>
                            </select>
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
    </section>
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
  return (
    <>
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
                showProject
                projectName={projectNames[task.project_id]}
                specificationName={task.specification_id ? specificationNames[task.specification_id] : undefined}
              />
            ))
          )}
        </div>
      </section>

      <section className="card">
        <h2>Notes ({notesTotal})</h2>
        <div className="task-list">
          {notes.length === 0 ? (
            <div className="notice">No matching notes.</div>
          ) : (
            notes.map((note) => (
              <div key={note.id} className="note-row">
                <div className="note-title">
                  {note.archived && <span className="badge">Archived</span>}
                  {note.pinned && <span className="badge">Pinned</span>}
                  <strong>{note.title || 'Untitled'}</strong>
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
            ))
          )}
        </div>
      </section>

      <section className="card">
        <h2>Specifications ({specificationsTotal})</h2>
        <div className="task-list">
          {specifications.length === 0 ? (
            <div className="notice">No matching specifications.</div>
          ) : (
            specifications.map((specification) => (
              <div key={specification.id} className="note-row">
                <div className="note-title">
                  {specification.archived && <span className="badge">Archived</span>}
                  <strong>{specification.title || 'Untitled spec'}</strong>
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
            ))
          )}
        </div>
      </section>
    </>
  )
}
