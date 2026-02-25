import React from 'react'

export function useTaskQueryParams(args: {
  tab: string
  selectedProjectId: string
  searchQ: string
  searchStatus: string
  searchPriority: string
  searchArchived: boolean
  searchTags: string[]
}) {
  const { tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived, searchTags } = args

  return React.useMemo(() => {
    if (!selectedProjectId) return null
    if (tab === 'inbox') return { project_id: selectedProjectId, view: 'inbox' as const, tags: searchTags }
    if (tab === 'tasks') {
      return {
        project_id: selectedProjectId,
        tags: searchTags,
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
  }, [tab, selectedProjectId, searchQ, searchStatus, searchPriority, searchArchived, searchTags])
}
