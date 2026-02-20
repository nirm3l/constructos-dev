import React from 'react'
import type { AdminWorkspaceUser, Note, Specification, Task } from '../types'
import { tagHue } from '../utils/ui'
import { PopularTagFilters } from './shared/PopularTagFilters'
import { Icon } from './shared/uiHelpers'
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
  onLogout,
  onToggleTheme,
  onChangeSpeechLang,
}: {
  userName: string
  theme: 'light' | 'dark'
  speechLang: string
  frontendVersion: string
  backendVersion: string
  backendBuild: string | null
  deployedAtUtc: string | null
  onLogout: () => void
  onToggleTheme: () => void
  onChangeSpeechLang: (value: string) => void
}) {
  const nextTheme = theme === 'light' ? 'dark' : 'light'

  return (
    <section className="card profile-panel">
      <div className="profile-panel-head">
        <div className="profile-panel-identity">
          <div className="profile-avatar" aria-hidden="true">
            <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 20a8 8 0 0 1 16 0" />
          </div>
          <div className="profile-head-copy">
            <h2>Profile</h2>
            <p className="meta">Session and build details</p>
          </div>
        </div>
        <span className="status-chip profile-theme-chip">{theme} mode</span>
      </div>

      <dl className="profile-facts">
        <div className="profile-fact">
          <dt>User</dt>
          <dd>{userName}</dd>
        </div>
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
        <div className="profile-fact">
          <dt>Voice language</dt>
          <dd>
            <select
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

      <div className="row wrap profile-actions">
        <button className="primary" onClick={onToggleTheme}>
          Switch to {nextTheme} theme
        </button>
        <button className="danger-ghost" onClick={onLogout}>
          Logout
        </button>
      </div>
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
}) {
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
                      <span
                        key={`${note.id}-${tag}`}
                        className="tag-mini"
                        style={{
                          backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                          borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                          color: `hsl(${tagHue(tag)}, 55%, 28%)`
                        }}
                      >
                        #{tag}
                      </span>
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
                      <span
                        key={`${specification.id}-${tag}`}
                        className="tag-mini"
                        style={{
                          backgroundColor: `hsl(${tagHue(tag)}, 70%, 92%)`,
                          borderColor: `hsl(${tagHue(tag)}, 70%, 78%)`,
                          color: `hsl(${tagHue(tag)}, 55%, 28%)`
                        }}
                      >
                        #{tag}
                      </span>
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
