import React from 'react'

export function useBootstrapDerived(args: {
  bootstrapData: any
  selectedProjectId: string
  notifications: any[]
}) {
  const { bootstrapData, selectedProjectId, notifications } = args

  const workspaceId = bootstrapData?.workspaces[0]?.id ?? ''
  const userTimezone = bootstrapData?.current_user?.timezone

  const workspaceUsers = React.useMemo(
    () => [...(bootstrapData?.users ?? [])].sort((a, b) => a.full_name.localeCompare(b.full_name)),
    [bootstrapData?.users]
  )

  const projectMemberCounts = React.useMemo(() => {
    const counts: Record<string, number> = {}
    for (const pm of bootstrapData?.project_members ?? []) {
      counts[pm.project_id] = (counts[pm.project_id] ?? 0) + 1
    }
    return counts
  }, [bootstrapData?.project_members])

  const selectedProject = React.useMemo(
    () => bootstrapData?.projects.find((p: any) => p.id === selectedProjectId) ?? null,
    [bootstrapData?.projects, selectedProjectId]
  )

  const unreadCount = (notifications ?? []).filter((n) => !n.is_read).length
  const actorNames = Object.fromEntries((bootstrapData?.users ?? []).map((u: any) => [u.id, u.username]))
  const projectNames = Object.fromEntries((bootstrapData?.projects ?? []).map((p: any) => [p.id, p.name]))

  return {
    workspaceId,
    userTimezone,
    workspaceUsers,
    projectMemberCounts,
    selectedProject,
    unreadCount,
    actorNames,
    projectNames,
  }
}
