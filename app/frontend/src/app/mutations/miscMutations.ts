import { useMutation } from '@tanstack/react-query'
import { addComment, deleteComment, markNotificationRead, patchMyPreferences, runAgentChat } from '../../api'

export function useMiscMutations(c: any) {
  const markReadMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(c.userId, id),
    onSuccess: async () => {
      c.setUiError(null)
      await c.invalidateAll()
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Mark read failed')
  })

  const themeMutation = useMutation({
    mutationFn: (nextTheme: 'light' | 'dark') => patchMyPreferences(c.userId, { theme: nextTheme }),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['bootstrap'] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Theme update failed')
  })

  const addCommentMutation = useMutation({
    mutationFn: () => addComment(c.userId, c.selectedTaskId as string, c.commentBody.trim()),
    onSuccess: async () => {
      c.setUiError(null)
      c.setCommentBody('')
      c.setScrollToNewestComment(true)
      await c.qc.invalidateQueries({ queryKey: ['comments', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Comment failed')
  })

  const deleteCommentMutation = useMutation({
    mutationFn: (commentId: number) => deleteComment(c.userId, c.selectedTaskId as string, commentId),
    onSuccess: async () => {
      c.setUiError(null)
      await c.qc.invalidateQueries({ queryKey: ['comments', c.userId, c.selectedTaskId] })
      await c.qc.invalidateQueries({ queryKey: ['activity', c.userId, c.selectedTaskId] })
    },
    onError: (err) => c.setUiError(err instanceof Error ? err.message : 'Delete comment failed')
  })

  const runAgentChatMutation = useMutation({
    mutationFn: (payload: { instruction: string; history: Array<{ role: 'user' | 'assistant'; content: string }>; projectId: string | null }) =>
      runAgentChat(c.userId, {
        workspace_id: c.workspaceId,
        project_id: payload.projectId,
        session_id: c.codexChatSessionId,
        instruction: payload.instruction,
        history: payload.history,
        allow_mutations: true
      }),
    onSuccess: async (payload) => {
      c.setUiError(null)
      const reply = [payload.summary, payload.comment].filter(Boolean).join('\n\n').trim()
      if (reply) {
        c.setCodexChatTurns((prev: any[]) => [
          ...prev,
          {
            id: globalThis.crypto?.randomUUID?.() ?? `a-${Date.now()}`,
            role: 'assistant',
            content: reply,
            createdAt: Date.now()
          }
        ])
      }
      if (payload.ok === false) {
        c.setUiError(payload.summary || payload.comment || 'Codex request failed')
      }
      c.setIsCodexChatRunning(false)
      c.setCodexChatRunStartedAt(null)
      c.setCodexChatElapsedSeconds(0)
      c.setCodexChatInstruction('')
      await c.invalidateAll()
    },
    onError: (err) => {
      c.setIsCodexChatRunning(false)
      c.setCodexChatRunStartedAt(null)
      c.setCodexChatElapsedSeconds(0)
      const msg = err instanceof Error ? err.message : 'Codex chat failed'
      c.setUiError(msg)
      c.setCodexChatTurns((prev: any[]) => [
        ...prev,
        {
          id: globalThis.crypto?.randomUUID?.() ?? `aerr-${Date.now()}`,
          role: 'assistant',
          content: `Error: ${msg}`,
          createdAt: Date.now()
        }
      ])
    }
  })

  return {
    markReadMutation,
    themeMutation,
    addCommentMutation,
    deleteCommentMutation,
    runAgentChatMutation,
  }
}
