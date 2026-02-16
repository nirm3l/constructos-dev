import React from 'react'
import type { Task } from '../types'
import { TaskListItem } from './tasks/taskViews'

export function SearchPanel({
  searchQ,
  setSearchQ,
  searchStatus,
  setSearchStatus,
  searchPriority,
  setSearchPriority,
  searchArchived,
  setSearchArchived,
  taskTagSuggestions,
  searchTags,
  toggleSearchTag,
  onClose,
}: {
  searchQ: string
  setSearchQ: React.Dispatch<React.SetStateAction<string>>
  searchStatus: string
  setSearchStatus: React.Dispatch<React.SetStateAction<string>>
  searchPriority: string
  setSearchPriority: React.Dispatch<React.SetStateAction<string>>
  searchArchived: boolean
  setSearchArchived: React.Dispatch<React.SetStateAction<boolean>>
  taskTagSuggestions: string[]
  searchTags: string[]
  toggleSearchTag: (tag: string) => void
  onClose: () => void
}) {
  return (
    <section className="card">
      <h2>Search</h2>
      <div className="row wrap">
        <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} placeholder="Search text" />
        <select value={searchStatus} onChange={(e) => setSearchStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="To do">To do</option>
          <option value="In progress">In progress</option>
          <option value="Done">Done</option>
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
          {taskTagSuggestions.slice(0, 10).map((tag) => (
            <button
              key={`search-tag-${tag}`}
              className={`status-chip tag-filter-chip ${searchTags.includes(tag.toLowerCase()) ? 'active' : ''}`}
              onClick={() => toggleSearchTag(tag)}
              aria-pressed={searchTags.includes(tag.toLowerCase())}
            >
              #{tag}
            </button>
          ))}
        </div>
        <button onClick={onClose}>Close</button>
      </div>
    </section>
  )
}

export function ProfilePanel({
  userName,
  theme,
  frontendVersion,
  backendVersion,
  backendBuild,
  deployedAtUtc,
  onToggleTheme,
}: {
  userName: string
  theme: 'light' | 'dark'
  frontendVersion: string
  backendVersion: string
  backendBuild: string | null
  deployedAtUtc: string | null
  onToggleTheme: () => void
}) {
  return (
    <section className="card">
      <h2>Profile</h2>
      <p className="meta">User: {userName}</p>
      <p className="meta">Theme: {theme}</p>
      <p className="meta">Frontend version: {frontendVersion}</p>
      <p className="meta">
        Backend version: {backendVersion}
        {backendBuild ? ` (${backendBuild})` : ''}
      </p>
      <p className="meta">Deployed (UTC): {deployedAtUtc ?? 'unknown'}</p>
      <div className="row">
        <button onClick={onToggleTheme}>Toggle Theme</button>
      </div>
    </section>
  )
}

export function TaskResultsPanel({
  tasks,
  total,
  showProject,
  projectNames,
  onOpen,
  onRestore,
  onReopen,
  onComplete,
}: {
  tasks: Task[]
  total: number
  showProject: boolean
  projectNames: Record<string, string>
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
            onRestore={onRestore}
            onReopen={onReopen}
            onComplete={onComplete}
            showProject={showProject}
            projectName={projectNames[task.project_id]}
          />
        ))}
      </div>
    </section>
  )
}
