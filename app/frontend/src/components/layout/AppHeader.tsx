import React from 'react'
import type { BootstrapPayload, Notification } from '../../types'
import type { Tab } from '../../utils/ui'
import { Icon } from '../shared/uiHelpers'

type AppHeaderProps = {
  bootstrapData: BootstrapPayload
  tab: Tab
  setTab: (tab: Tab) => void
  searchQ: string
  setSearchQ: (value: string) => void
  selectedProjectId: string
  setSelectedProjectId: (projectId: string) => void
  showNotificationsPanel: boolean
  setShowNotificationsPanel: React.Dispatch<React.SetStateAction<boolean>>
  notifications: Notification[]
  unreadCount: number
  onMarkRead: (notificationId: string) => void
  onOpenTask: (taskId: string, projectId?: string | null) => boolean
  onOpenNote: (noteId: string, projectId?: string | null) => boolean
  onOpenSpecification: (specificationId: string, projectId?: string | null) => void
  onOpenProject: (projectId: string) => void
}

function parseLegacyTaskId(message: string): string | null {
  const match = message.match(/\btask\s+#([0-9a-fA-F-]{8,})\b/i)
  return match?.[1] ?? null
}

export function AppHeader({
  bootstrapData,
  tab,
  setTab,
  searchQ,
  setSearchQ,
  selectedProjectId,
  setSelectedProjectId,
  showNotificationsPanel,
  setShowNotificationsPanel,
  notifications,
  unreadCount,
  onMarkRead,
  onOpenTask,
  onOpenNote,
  onOpenSpecification,
  onOpenProject,
}: AppHeaderProps) {
  return (
    <header className="header card">
      <div className="title-row">
        <div className="brand" role="banner">
          <div className="brand-mark" aria-hidden="true">m</div>
          <div className="brand-stack">
            <div className="brand-name">m4tr1x</div>
            <div className="brand-sub">c0d3 w1th m3m0ry</div>
          </div>
        </div>

        <div className="brand-meta" aria-label="Context">
          <div className="brand-meta-row">
            <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
            <span className="brand-meta-text">
              <strong>{bootstrapData.current_user.username}</strong>
            </span>
          </div>
          <div className="brand-meta-row">
            <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
            <span className="brand-meta-text">
              <strong>{bootstrapData.workspaces[0]?.name}</strong>
            </span>
          </div>
        </div>

        <div className="top-actions">
          <button onClick={() => setTab('profile')} title="Profile" aria-label="Profile">
            <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
          </button>
          <button
            className={showNotificationsPanel ? 'primary' : ''}
            onClick={() => setShowNotificationsPanel((v) => !v)}
            title="Notifications"
            aria-label="Notifications"
          >
            <Icon path="M12 22a2 2 0 0 0 2-2H10a2 2 0 0 0 2 2zm6-6V11a6 6 0 1 0-12 0v5L4 18v1h16v-1l-2-2z" />
            {unreadCount > 0 && <span className="notif-dot">{Math.min(99, unreadCount)}</span>}
          </button>
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
            placeholder="Search tasks..."
          />
        </div>
        <div className="header-project-scope">
          <span className="meta">Project</span>
          <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}>
            {bootstrapData.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="action-icon" onClick={() => setTab('projects')} title="Manage projects" aria-label="Manage projects">
            <Icon path="M3 7h7l2 2h9v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2" />
          </button>
        </div>
      </div>
      {showNotificationsPanel && (
        <div className="header-panel">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <div className="row" style={{ gap: 10 }}>
              <strong>Notifications</strong>
              <span className="meta">{unreadCount} unread</span>
            </div>
            <button className="action-icon" onClick={() => setShowNotificationsPanel(false)} title="Close" aria-label="Close">
              <Icon path="M6 6l12 12M18 6 6 18" />
            </button>
          </div>
          <div className="notifications-list" style={{ marginTop: 10 }}>
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
        </div>
      )}
    </header>
  )
}
