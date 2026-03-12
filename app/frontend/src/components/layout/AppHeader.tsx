import React from 'react'
import * as AlertDialog from '@radix-ui/react-alert-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { BootstrapPayload, LicenseStatus, Notification } from '../../types'
import type { Tab } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'
import { MarkdownView } from '../../markdown/MarkdownView'

type AppHeaderProps = {
  bootstrapData: BootstrapPayload
  license?: LicenseStatus | null
  tab: Tab
  setTab: (tab: Tab) => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  searchQ: string
  setSearchQ: (value: string) => void
  selectedProjectId: string
  setSelectedProjectId: (projectId: string) => void
  showNotificationsPanel: boolean
  setShowNotificationsPanel: React.Dispatch<React.SetStateAction<boolean>>
  notifications: Notification[]
  unreadCount: number
  onMarkRead: (notificationId: string) => void
  onMarkUnread: (notificationId: string) => void
  onMarkAllRead: () => void
  isMarkAllReadPending: boolean
  onNotificationAction: (notificationId: string, action: string) => void
  onOpenTask: (taskId: string, projectId?: string | null) => boolean
  onOpenNote: (noteId: string, projectId?: string | null) => boolean
  onOpenSpecification: (specificationId: string, projectId?: string | null) => void
  onOpenProject: (projectId: string) => void
  onStartQuickTour: () => void
  onStartAdvancedTour: () => void
}

function notificationPayloadId(notification: Notification, key: string): string | null {
  const payload = notification.payload
  if (!payload || typeof payload !== 'object') return null
  const value = (payload as Record<string, unknown>)[key]
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized || null
}

function notificationPayloadText(notification: Notification, key: string): string | null {
  const payload = notification.payload
  if (!payload || typeof payload !== 'object') return null
  const value = (payload as Record<string, unknown>)[key]
  if (typeof value !== 'string' && typeof value !== 'number') return null
  const normalized = String(value).trim()
  return normalized || null
}

function notificationDisplayMessage(notification: Notification): string {
  const type = String(notification.notification_type || '').trim()
  const fallback = String(notification.message || '').trim() || 'Notification'
  if (!type || type === 'Legacy') return fallback
  const title = notificationPayloadText(notification, 'title')
  const fromStatus = notificationPayloadText(notification, 'from_status')
  const toStatus = notificationPayloadText(notification, 'to_status')
  const role = notificationPayloadText(notification, 'role')
  const error = notificationPayloadText(notification, 'error')
  const hoursRemaining = notificationPayloadText(notification, 'hours_remaining')
  switch (type) {
    case 'TaskAssignedToMe':
      return title ? `Assigned to you: ${title}` : fallback
    case 'WatchedTaskStatusChanged':
      if (title && fromStatus && toStatus) return `${title} moved from ${fromStatus} to ${toStatus}`
      if (title && toStatus) return `${title} moved to ${toStatus}`
      return fallback
    case 'TaskAutomationFailed':
      return title && error ? `Automation failed on ${title}: ${error}` : fallback
    case 'TaskScheduleFailed':
      return title && error ? `Scheduled run failed on ${title}: ${error}` : fallback
    case 'ProjectMembershipChanged':
      if (role) return `Project membership updated. New role: ${role}`
      return fallback
    case 'LicenseGraceEndingSoon':
      return hoursRemaining ? `License grace ends in about ${hoursRemaining}h.` : fallback
    default:
      return fallback
  }
}

function notificationMarkdownMessage(notification: Notification): string {
  const payload = notification.payload
  if (payload && typeof payload === 'object') {
    const messageMarkdown = (payload as Record<string, unknown>).message_markdown
    if (typeof messageMarkdown === 'string' && messageMarkdown.trim()) return messageMarkdown.trim()
    const markdown = (payload as Record<string, unknown>).markdown
    if (typeof markdown === 'string' && markdown.trim()) return markdown.trim()
  }
  const raw = String(notification.message || '').trim()
  if (raw) return raw
  return notificationDisplayMessage(notification)
}

function truncateMarkdownForNotificationList(value: string, maxChars = 260): string {
  const normalized = String(value || '').trim()
  if (!normalized) return ''
  if (normalized.length <= maxChars) return normalized
  return `${normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`
}

function HeaderTooltip({
  content,
  children,
}: {
  content: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="header-tooltip-content" sideOffset={6}>
          {content}
          <Tooltip.Arrow className="header-tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

export function AppHeader({
  bootstrapData,
  license,
  tab,
  setTab,
  theme,
  onToggleTheme,
  searchQ,
  setSearchQ,
  selectedProjectId,
  setSelectedProjectId,
  showNotificationsPanel,
  setShowNotificationsPanel,
  notifications,
  unreadCount,
  onMarkRead,
  onMarkUnread,
  onMarkAllRead,
  isMarkAllReadPending,
  onNotificationAction,
  onOpenTask,
  onOpenNote,
  onOpenSpecification,
  onOpenProject,
  onStartQuickTour,
  onStartAdvancedTour,
}: AppHeaderProps) {
  const brandSubTop = 'From spec to ship,'
  const brandSubBottom = 'with context under control...'
  const isDarkTheme = theme === 'dark'
  const themeToggleTooltip = isDarkTheme ? 'Switch to light mode' : 'Switch to dark mode'
  const licenseStatus = String(license?.status || '').trim().toLowerCase()
  const licensePlanCode = String(license?.plan_code || '').trim().toLowerCase()
  const betaSubscription = licenseStatus === 'beta' || licensePlanCode.includes('beta')
  const graphPagesActive = tab === 'knowledge-graph' || tab === 'task-flow'
  const projectSelectValue = React.useMemo(() => {
    if (!selectedProjectId) return undefined
    return bootstrapData.projects.some((project) => project.id === selectedProjectId) ? selectedProjectId : undefined
  }, [bootstrapData.projects, selectedProjectId])
  const [notificationPreviewOpen, setNotificationPreviewOpen] = React.useState(false)
  const [notificationPreviewMarkdown, setNotificationPreviewMarkdown] = React.useState('')
  const [notificationPreviewTitle, setNotificationPreviewTitle] = React.useState('Notification')
  const [notificationPreviewId, setNotificationPreviewId] = React.useState('')
  const [notificationPreviewAction, setNotificationPreviewAction] = React.useState('')
  const [notificationPreviewActionLabel, setNotificationPreviewActionLabel] = React.useState('')
  const [notificationPreviewView] = React.useState<'preview'>('preview')

  React.useEffect(() => {
    if (!notificationPreviewOpen) return
    document.body.classList.add('md-fullscreen-open')
    return () => {
      document.body.classList.remove('md-fullscreen-open')
    }
  }, [notificationPreviewOpen])

  React.useEffect(() => {
    if (!notificationPreviewOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setNotificationPreviewOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [notificationPreviewOpen])

  return (
    <Tooltip.Provider delayDuration={180}>
      <header className="header card">
        <div className="title-row">
          <div className="brand" role="banner">
            <div className="brand-badge" role="img" aria-label="ConstructOS.dev logo">
              <div className="brand-mark" data-text="C" aria-hidden="true">C</div>
              <div className="brand-lockup">
                <div className="brand-name" aria-hidden="true">
                  ConstructOS.dev
                </div>
                <div className="brand-sub-stack">
                  <div className="brand-sub brand-sub-top" data-text={brandSubTop}>{brandSubTop}</div>
                  <div className="brand-sub brand-sub-bottom" data-text={brandSubBottom}>{brandSubBottom}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="top-actions">
            <Popover.Root open={showNotificationsPanel} onOpenChange={setShowNotificationsPanel}>
              <HeaderTooltip content="Notifications">
                <Popover.Trigger asChild>
                  <button
                    className={`top-notif-btn ${showNotificationsPanel ? 'active' : ''}`.trim()}
                    aria-label="Notifications"
                    data-tour-id="header-notifications"
                  >
                    <Icon path="M12 22a2 2 0 0 0 2-2H10a2 2 0 0 0 2 2zm6-6V11a6 6 0 1 0-12 0v5L4 18v1h16v-1l-2-2z" />
                    {unreadCount > 0 && <span className="notif-dot">{Math.min(99, unreadCount)}</span>}
                  </button>
                </Popover.Trigger>
              </HeaderTooltip>
              <Popover.Portal>
                <Popover.Content className="header-notifications-popover" side="bottom" align="end" sideOffset={8}>
                  <div className="row header-notifications-header">
                    <div className="row" style={{ gap: 10 }}>
                      <strong>Notifications</strong>
                      <span className="meta">{unreadCount} unread</span>
                    </div>
                    <div className="row header-notifications-actions">
                      <button
                        className="status-chip"
                        onClick={() => onMarkAllRead()}
                        disabled={isMarkAllReadPending || unreadCount === 0}
                        aria-label="Mark all notifications as read"
                      >
                        {isMarkAllReadPending ? 'Marking...' : 'Mark all read'}
                      </button>
                      <button className="action-icon" onClick={() => setShowNotificationsPanel(false)} aria-label="Close notifications">
                        <Icon path="M6 6l12 12M18 6 6 18" />
                      </button>
                    </div>
                  </div>
                  <div className="notifications-list header-notifications-list">
                    {notifications.length === 0 ? (
                      <div className="meta">No notifications.</div>
                    ) : (
                      notifications.map((n) => {
                        const taskId = n.task_id || notificationPayloadId(n, 'task_id')
                        const noteId = n.note_id || notificationPayloadId(n, 'note_id')
                        const specificationId = n.specification_id || notificationPayloadId(n, 'specification_id')
                        const projectId = n.project_id || notificationPayloadId(n, 'project_id')
                        const markdownMessage = notificationMarkdownMessage(n)
                        const markdownPreview = truncateMarkdownForNotificationList(markdownMessage)
                        const notificationTitle = notificationPayloadText(n, 'title') || 'Notification'
                        const payload = n.payload && typeof n.payload === 'object' ? (n.payload as Record<string, unknown>) : null
                        const notificationAction = String(payload?.action || '').trim()
                        const notificationActionLabel = String(payload?.action_label || '').trim()
                        const canRunNotificationAction = Boolean(notificationAction)
                        const inlineNotificationAction = notificationAction === 'auto_update_app_images'
                        const markNotificationRead = () => {
                          if (!n.is_read) onMarkRead(n.id)
                        }
                        const openNotificationPreview = () => {
                          setNotificationPreviewMarkdown(markdownMessage)
                          setNotificationPreviewTitle(notificationTitle)
                          setNotificationPreviewId(String(n.id || '').trim())
                          setNotificationPreviewAction(notificationAction)
                          setNotificationPreviewActionLabel(notificationActionLabel)
                          setNotificationPreviewOpen(true)
                          setShowNotificationsPanel(false)
                          markNotificationRead()
                        }
                        return (
                          <div
                            key={n.id}
                            className={`notif notif-openable ${n.is_read ? 'read' : 'unread'}`}
                            onClick={markNotificationRead}
                            onKeyDown={(event) => {
                              if (event.key !== 'Enter' && event.key !== ' ') return
                              event.preventDefault()
                              markNotificationRead()
                            }}
                            role="button"
                            tabIndex={0}
                            aria-label={n.is_read ? 'Notification is read' : 'Mark notification as read'}
                            title={n.is_read ? 'Notification is read' : 'Mark as read'}
                          >
                            <div className="notif-dotline" aria-hidden="true" />
                            <div className="notif-main">
                              <div className="notif-copy">
                                <div className="notif-message notif-message-md">
                                  <MarkdownView value={markdownPreview} />
                                </div>
                              </div>
                              <div className="notif-hint-row">
                                <div className="notif-hint">
                                  {!n.is_read ? 'Click to mark as read' : 'Read'}
                                </div>
                                <div className="notif-hint-actions">
                                  <button
                                    className="notif-inline-action"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      openNotificationPreview()
                                    }}
                                  >
                                    Open full notification
                                  </button>
                                  {inlineNotificationAction && canRunNotificationAction ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onNotificationAction(n.id, notificationAction)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      {notificationActionLabel || 'Update app'}
                                    </button>
                                  ) : null}
                                  {n.is_read ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onMarkUnread(n.id)
                                      }}
                                    >
                                      Mark unread
                                    </button>
                                  ) : null}
                                  {(taskId || noteId || specificationId || (canRunNotificationAction && !inlineNotificationAction) || (!taskId && !noteId && !specificationId && projectId)) ? (
                                    <span className="notif-inline-separator" aria-hidden="true">
                                      |
                                    </span>
                                  ) : null}
                                  {taskId ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onOpenTask(taskId, projectId)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      Open task
                                    </button>
                                  ) : null}
                                  {noteId ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onOpenNote(noteId, projectId)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      Open note
                                    </button>
                                  ) : null}
                                  {specificationId ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onOpenSpecification(specificationId, projectId)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      Open specification
                                    </button>
                                  ) : null}
                                  {canRunNotificationAction && !inlineNotificationAction ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onNotificationAction(n.id, notificationAction)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      {notificationActionLabel || (notificationAction === 'auto_update_app_images' ? 'Update app' : 'Run action')}
                                    </button>
                                  ) : null}
                                  {!taskId && !noteId && !specificationId && projectId ? (
                                    <button
                                      className="notif-inline-action"
                                      onClick={(event) => {
                                        event.stopPropagation()
                                        onOpenProject(projectId)
                                        markNotificationRead()
                                        setShowNotificationsPanel(false)
                                      }}
                                    >
                                      Open project
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                  <Popover.Arrow className="header-notifications-popover-arrow" />
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>

            <HeaderTooltip content="Open Knowledge Graph">
              <button
                className={`top-graph-btn ${graphPagesActive ? 'active' : ''}`.trim()}
                onClick={() => setTab('knowledge-graph')}
                aria-label="Knowledge Graph"
                data-tour-id="header-knowledge-graph"
              >
                <Icon path="M6 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm12 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm-6 15a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.4 6.6l3.9 10.8M16.6 6.6l-3.9 10.8" />
              </button>
            </HeaderTooltip>

            <HeaderTooltip content={themeToggleTooltip}>
              <button
                className={`top-theme-btn ${isDarkTheme ? 'active' : ''}`.trim()}
                onClick={onToggleTheme}
                aria-label={themeToggleTooltip}
                title={themeToggleTooltip}
              >
                <Icon
                  path={
                    isDarkTheme
                      ? 'M12 3v2M12 19v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8'
                      : 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z'
                  }
                />
              </button>
            </HeaderTooltip>

            <div className="top-settings-stack">
              <DropdownMenu.Root>
                <HeaderTooltip content="Open settings and navigation">
                  <DropdownMenu.Trigger asChild>
                    <button
                      className={`top-profile-btn ${tab === 'settings' ? 'active' : ''}`.trim()}
                      aria-label="Open settings menu"
                      data-tour-id="header-settings-menu"
                    >
                      <Icon path="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm8 3.5-1.9.7a6.9 6.9 0 0 1-.6 1.5l.9 1.8-2 2-.6-.3-1.2-.6a6.9 6.9 0 0 1-1.5.6L12 20l-1-.1-1-.2-.7-1.9a6.9 6.9 0 0 1-1.5-.6l-1.8.9-2-2 .9-1.8a6.9 6.9 0 0 1-.6-1.5L4 12l.1-1 .2-1 .6-.2 1.3-.5a6.9 6.9 0 0 1 .6-1.5L5.9 6l2-2 1.8.9a6.9 6.9 0 0 1 1.5-.6L12 4l1 .1 1 .2.7 1.9a6.9 6.9 0 0 1 1.5.6L18 5.9l2 2-.9 1.8a6.9 6.9 0 0 1 .6 1.5L20 12z" />
                    </button>
                  </DropdownMenu.Trigger>
                </HeaderTooltip>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content className="header-settings-menu-content" sideOffset={8} align="end">
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('settings')}>
                      Settings
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('projects')}>
                      Manage projects
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('knowledge-graph')}>
                      Knowledge Graph
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('search')}>
                      Global search
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('task-flow')}>
                      Task Flow
                    </DropdownMenu.Item>
                    <DropdownMenu.Separator className="header-settings-menu-separator" />
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={onStartQuickTour}>
                      Start quick tour
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className="header-settings-menu-item" onSelect={onStartAdvancedTour}>
                      Start advanced tour
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              {betaSubscription ? (
                <HeaderTooltip content="You are using a beta subscription and features may evolve.">
                  <span className="top-beta-compact" aria-label="Beta subscription">BETA</span>
                </HeaderTooltip>
              ) : null}
            </div>
          </div>
        </div>
        <AlertDialog.Root open={notificationPreviewOpen} onOpenChange={setNotificationPreviewOpen}>
          <AlertDialog.Portal>
            <AlertDialog.Overlay className="codex-chat-alert-overlay" />
            <AlertDialog.Content className="codex-chat-alert-content docker-runtime-dialog notification-preview-dialog">
              <div className="notification-markdown-header">
                <div>
                  <AlertDialog.Title className="codex-chat-alert-title notification-markdown-title">
                    {notificationPreviewTitle}
                  </AlertDialog.Title>
                  <AlertDialog.Description className="codex-chat-alert-description">
                    Notification details and linked actions.
                  </AlertDialog.Description>
                </div>
                {notificationPreviewAction ? (
                  <button
                    className="status-chip"
                    onClick={() => {
                      if (!notificationPreviewId) return
                      onNotificationAction(notificationPreviewId, notificationPreviewAction)
                    }}
                  >
                    {notificationPreviewActionLabel || (notificationPreviewAction === 'auto_update_app_images' ? 'Update app' : 'Run action')}
                  </button>
                ) : null}
                <AlertDialog.Cancel asChild>
                  <button
                    type="button"
                    className="action-icon docker-runtime-dialog-close notification-preview-close"
                    aria-label="Close notification preview"
                    title="Close"
                  >
                    <Icon path="M6 6l12 12M18 6L6 18" />
                  </button>
                </AlertDialog.Cancel>
              </div>
              <div className="md-editor-content notification-markdown-content notification-preview-body">
                <MarkdownView value={notificationPreviewMarkdown} />
              </div>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        </AlertDialog.Root>
        <div className="header-lower">
          <div className="top-search-wrap" role="search">
            <Icon path="M20 20l-3.5-3.5M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14z" />
            <input
              className="top-search"
              value={searchQ}
              onChange={(e) => {
                setSearchQ(e.target.value)
                if (tab !== 'search') setTab('search')
              }}
              placeholder="Search tasks, notes, specifications..."
              data-tour-id="header-search"
            />
          </div>
          <div className="header-project-scope">
            <span className="meta">Project</span>
            <Select.Root value={projectSelectValue} onValueChange={setSelectedProjectId}>
              <Select.Trigger className="header-project-trigger" aria-label="Select project" data-tour-id="header-project-select">
                <Select.Value placeholder="Select project" />
                <Select.Icon asChild>
                  <span className="header-project-trigger-icon">
                    <Icon path="M6 9l6 6 6-6" />
                  </span>
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Content className="header-project-content" position="popper" sideOffset={6}>
                  <Select.Viewport className="header-project-viewport">
                    {bootstrapData.projects.map((project) => (
                      <Select.Item key={project.id} value={project.id} className="header-project-item">
                        <Select.ItemText>{project.name}</Select.ItemText>
                        <Select.ItemIndicator className="header-project-item-indicator">
                          <Icon path="M5 13l4 4L19 7" />
                        </Select.ItemIndicator>
                      </Select.Item>
                    ))}
                  </Select.Viewport>
                </Select.Content>
              </Select.Portal>
            </Select.Root>
            <HeaderTooltip content="Manage projects">
              <button className="action-icon" onClick={() => setTab('projects')} aria-label="Manage projects">
                <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
              </button>
            </HeaderTooltip>
          </div>
        </div>
      </header>
    </Tooltip.Provider>
  )
}
