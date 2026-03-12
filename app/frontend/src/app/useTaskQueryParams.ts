import React from 'react'

export function useTaskQueryParams(args: {
  tab: string
  selectedProjectId: string
  tasksPageLimit: number
  searchQ: string
  searchStatus: string
  searchPriority: string
  searchArchived: boolean
  searchTags: string[]
}) {
  const { tab, selectedProjectId, tasksPageLimit, searchQ, searchStatus, searchPriority, searchArchived, searchTags } = args

  return React.useMemo(() => {
    if (!selectedProjectId) return null
    if (tab === 'inbox') return { project_id: selectedProjectId, view: 'inbox' as const, tags: searchTags }
    if (tab === 'tasks') {
      return {
        project_id: selectedProjectId,
        q: searchQ || undefined,
        status: searchStatus || undefined,
        priority: searchPriority || undefined,
        archived: searchArchived,
        tags: searchTags,
        limit: tasksPageLimit,
        offset: 0,
      }
    }
    if (tab === 'search') {
      return {
        project_id: selectedProjectId,
        q: searchQ || undefined,
        status: searchStatus || undefined,
        priority: searchPriority || undefined,
        tags: searchTags,
        archived: searchArchived,
      }
    }
    return null
  }, [tab, selectedProjectId, tasksPageLimit, searchQ, searchStatus, searchPriority, searchArchived, searchTags])
}
