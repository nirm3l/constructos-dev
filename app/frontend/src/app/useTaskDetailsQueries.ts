import { useQuery } from '@tanstack/react-query'
import { getTaskAutomationStatus, listActivity, listComments } from '../api'
import type { TaskAutomationStatus } from '../types'

export function useTaskDetailsQueries(c: { userId: string; selectedTaskId: string | null }) {
  const comments = useQuery({
    queryKey: ['comments', c.userId, c.selectedTaskId],
    queryFn: () => listComments(c.userId, c.selectedTaskId as string),
    enabled: Boolean(c.selectedTaskId)
  })

  const activity = useQuery({
    queryKey: ['activity', c.userId, c.selectedTaskId],
    queryFn: () => listActivity(c.userId, c.selectedTaskId as string),
    enabled: Boolean(c.selectedTaskId)
  })

  const automationStatus = useQuery({
    queryKey: ['automation-status', c.userId, c.selectedTaskId],
    queryFn: () => getTaskAutomationStatus(c.userId, c.selectedTaskId as string),
    enabled: Boolean(c.selectedTaskId),
    refetchInterval: (q) => {
      const state = (q.state.data as TaskAutomationStatus | undefined)?.automation_state
      if (state === 'queued' || state === 'running') return 2000
      return false
    }
  })

  return { comments, activity, automationStatus }
}
