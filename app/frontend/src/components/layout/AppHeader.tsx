import React from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Popover from '@radix-ui/react-popover'
import * as Select from '@radix-ui/react-select'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { BootstrapPayload, Notification } from '../../types'
import type { Tab } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'

type AppHeaderProps = {
  bootstrapData: BootstrapPayload
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
  onMarkAllRead: () => void
  isMarkAllReadPending: boolean
  onOpenTask: (taskId: string, projectId?: string | null) => boolean
  onOpenNote: (noteId: string, projectId?: string | null) => boolean
  onOpenSpecification: (specificationId: string, projectId?: string | null) => void
  onOpenProject: (projectId: string) => void
}

function parseLegacyTaskId(message: string): string | null {
  const match = message.match(/\btask\s+#([0-9a-fA-F-]{8,})\b/i)
  return match?.[1] ?? null
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
  onMarkAllRead,
  isMarkAllReadPending,
  onOpenTask,
  onOpenNote,
  onOpenSpecification,
  onOpenProject,
}: AppHeaderProps) {
  const brandSubTop = 'From spec to ship,'
  const brandSubBottom = 'with context under control...'
  const isDarkTheme = theme === 'dark'
  const themeToggleTooltip = isDarkTheme ? 'Switch to light mode' : 'Switch to dark mode'
  const projectSelectValue = React.useMemo(() => {
    if (!selectedProjectId) return undefined
    return bootstrapData.projects.some((project) => project.id === selectedProjectId) ? selectedProjectId : undefined
  }, [bootstrapData.projects, selectedProjectId])

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
                        const taskId = n.task_id || parseLegacyTaskId(n.message)
                        return (
                          <div key={n.id} className={`notif ${n.is_read ? 'read' : 'unread'}`}>
                            <div className="notif-dotline" aria-hidden="true" />
                            <div className="notif-main">
                              <div className="notif-message">{n.message}</div>
                              <div className="notif-actions">
                                {taskId && (
                                  <button
                                    className="status-chip"
                                    onClick={() => {
                                      onOpenTask(taskId, n.project_id)
                                      if (!n.is_read) onMarkRead(n.id)
                                      setShowNotificationsPanel(false)
                                    }}
                                  >
                                    Open task
                                  </button>
                                )}
                                {n.note_id && (
                                  <button
                                    className="status-chip"
                                    onClick={() => {
                                      onOpenNote(n.note_id as string, n.project_id)
                                      if (!n.is_read) onMarkRead(n.id)
                                      setShowNotificationsPanel(false)
                                    }}
                                  >
                                    Open note
                                  </button>
                                )}
                                {n.specification_id && (
                                  <button
                                    className="status-chip"
                                    onClick={() => {
                                      onOpenSpecification(n.specification_id as string, n.project_id)
                                      if (!n.is_read) onMarkRead(n.id)
                                      setShowNotificationsPanel(false)
                                    }}
                                  >
                                    Open specification
                                  </button>
                                )}
                                {!taskId && !n.note_id && !n.specification_id && n.project_id && (
                                  <button
                                    className="status-chip"
                                    onClick={() => {
                                      onOpenProject(n.project_id as string)
                                      if (!n.is_read) onMarkRead(n.id)
                                      setShowNotificationsPanel(false)
                                    }}
                                  >
                                    Open project
                                  </button>
                                )}
                                {!n.is_read && (
                                  <button className="status-chip" onClick={() => onMarkRead(n.id)}>
                                    Mark read
                                  </button>
                                )}
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
                className={`top-graph-btn ${tab === 'knowledge-graph' ? 'active' : ''}`.trim()}
                onClick={() => setTab('knowledge-graph')}
                aria-label="Knowledge Graph"
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

            <DropdownMenu.Root>
              <HeaderTooltip content="Open settings and navigation">
                <DropdownMenu.Trigger asChild>
                  <button className={`top-profile-btn ${tab === 'profile' ? 'active' : ''}`.trim()} aria-label="Open settings menu">
                    <Icon path="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm8 3.5-1.9.7a6.9 6.9 0 0 1-.6 1.5l.9 1.8-2 2-.6-.3-1.2-.6a6.9 6.9 0 0 1-1.5.6L12 20l-1-.1-1-.2-.7-1.9a6.9 6.9 0 0 1-1.5-.6l-1.8.9-2-2 .9-1.8a6.9 6.9 0 0 1-.6-1.5L4 12l.1-1 .2-1 .6-.2 1.3-.5a6.9 6.9 0 0 1 .6-1.5L5.9 6l2-2 1.8.9a6.9 6.9 0 0 1 1.5-.6L12 4l1 .1 1 .2.7 1.9a6.9 6.9 0 0 1 1.5.6L18 5.9l2 2-.9 1.8a6.9 6.9 0 0 1 .6 1.5L20 12z" />
                  </button>
                </DropdownMenu.Trigger>
              </HeaderTooltip>
              <DropdownMenu.Portal>
                <DropdownMenu.Content className="header-settings-menu-content" sideOffset={8} align="end">
                  <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('profile')}>
                    Profile settings
                  </DropdownMenu.Item>
                  <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('projects')}>
                    Manage projects
                  </DropdownMenu.Item>
                  <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('knowledge-graph')}>
                    Knowledge Graph
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator className="header-settings-menu-separator" />
                  <DropdownMenu.Item className="header-settings-menu-item" onSelect={() => setTab('search')}>
                    Global search
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </div>
        </div>
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
            />
          </div>
          <div className="header-project-scope">
            <span className="meta">Project</span>
            <Select.Root value={projectSelectValue} onValueChange={setSelectedProjectId}>
              <Select.Trigger className="header-project-trigger" aria-label="Select project">
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
