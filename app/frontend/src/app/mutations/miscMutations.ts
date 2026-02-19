import { useMutation } from '@tanstack/react-query'
import { addComment, deleteComment, markNotificationRead, patchMyPreferences, runAgentChat } from '../../api'

const ENTITY_ID_SOURCE = '[0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){0,4}'
const ENTITY_ID_PATTERN = /([0-9a-fA-F]{8,}(?:-[0-9a-fA-F]{4,}){0,4})/

type AgentEntityKind = 'projects' | 'notes' | 'tasks' | 'specifications'

function buildAgentEntityLink(kind: AgentEntityKind, id: string, projectId?: string | null): string {
  const params = new URLSearchParams()
  params.set('tab', kind)
  if (kind === 'projects') {
    params.set('project', id)
  } else if (projectId) {
    params.set('project', projectId)
  }
  if (kind === 'projects') return `?${params.toString()}`
  if (kind === 'notes') params.set('note', id)
  if (kind === 'tasks') params.set('task', id)
  if (kind === 'specifications') params.set('specification', id)
  return `?${params.toString()}`
}

function linkifyEntityLine(
  line: string,
  label: string,
  kind: AgentEntityKind,
  projectId?: string | null
): string {
  const prefixPattern = new RegExp(`(^|\\b)${label}\\s*:\\s*`, 'i')
  if (!prefixPattern.test(line)) return line
  if (line.includes('](')) return line
  const idMatch = line.match(ENTITY_ID_PATTERN)
  const id = idMatch?.[1]
  if (!id) return line
  const url = buildAgentEntityLink(kind, id, projectId)
  const prettyLabel = label.replace(/\s+ID$/i, '')
  return line.replace(
    new RegExp(`${label}\\s*:\\s*${id}`, 'i'),
    `${prettyLabel}: [${id}](${url})`
  )
}

function linkifyEntityKeyValue(
  line: string,
  key: string,
  kind: AgentEntityKind,
  projectId?: string | null
): string {
  const pattern = new RegExp(`\\b(${key})\\b\\s*([:=])\\s*(${ENTITY_ID_SOURCE})`, 'gi')
  return line.replace(pattern, (_match, rawKey: string, delimiter: string, id: string) => {
    const url = buildAgentEntityLink(kind, id, projectId)
    if (delimiter === ':') return `${rawKey}: [${id}](${url})`
    return `${rawKey}=[${id}](${url})`
  })
}

function detectProjectId(content: string): string | null {
  const match = content.match(new RegExp(`\\bproject_id\\b\\s*[:=]\\s*(${ENTITY_ID_SOURCE})`, 'i'))
  const id = match?.[1]
  return id ? String(id) : null
}

function linkifyAgentReply(content: string, projectId?: string | null): string {
  if (!content) return content
  const inferredProjectId = detectProjectId(content)
  const resolvedProjectId = inferredProjectId || projectId || null
  return content
    .split('\n')
    .map((line) => {
      let next = line
      next = linkifyEntityKeyValue(next, 'project_id', 'projects', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'task_id', 'tasks', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'note_id', 'notes', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'specification_id', 'specifications', resolvedProjectId)
      next = linkifyEntityKeyValue(next, 'spec_id', 'specifications', resolvedProjectId)
      next = linkifyEntityLine(next, 'Project ID', 'projects', resolvedProjectId)
      next = linkifyEntityLine(next, 'Note ID', 'notes', resolvedProjectId)
      next = linkifyEntityLine(next, 'Task ID', 'tasks', resolvedProjectId)
      next = linkifyEntityLine(next, 'Specification ID', 'specifications', resolvedProjectId)
      next = linkifyEntityLine(next, 'Spec ID', 'specifications', resolvedProjectId)
      return next
    })
    .join('\n')
}

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
    mutationFn: (payload: {
      instruction: string
      history: Array<{ role: 'user' | 'assistant'; content: string }>
      projectId: string | null
      sessionId: string
    }) =>
      runAgentChat(c.userId, {
        workspace_id: c.workspaceId,
        project_id: payload.projectId,
        session_id: payload.sessionId || c.codexChatSessionId,
        instruction: payload.instruction,
        history: payload.history,
        allow_mutations: true
      }),
    onSuccess: async (response, variables) => {
      c.setUiError(null)
      if (response.usage) {
        if (variables.sessionId && typeof c.setCodexChatUsageForSession === 'function') {
          c.setCodexChatUsageForSession(variables.sessionId, response.usage)
        } else {
          c.setCodexChatUsage(response.usage)
        }
      }
      const reply = linkifyAgentReply(
        [response.summary, response.comment].filter(Boolean).join('\n\n').trim(),
        variables.projectId || c.codexChatProjectId || c.selectedProjectId || null
      )
      if (reply) {
        if (variables.sessionId && typeof c.setCodexChatTurnsForSession === 'function') {
          c.setCodexChatTurnsForSession(variables.sessionId, (prev: any[]) => [
            ...prev,
            {
              id: globalThis.crypto?.randomUUID?.() ?? `a-${Date.now()}`,
              role: 'assistant',
              content: reply,
              createdAt: Date.now()
            }
          ])
        } else {
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
      }
      if (response.ok === false) {
        c.setUiError(response.summary || response.comment || 'Chat request failed')
      }
      c.setIsCodexChatRunning(false)
      c.setCodexChatRunStartedAt(null)
      c.setCodexChatElapsedSeconds(0)
      c.setCodexChatInstruction('')
      await c.invalidateAll()
    },
    onError: (err, variables) => {
      c.setIsCodexChatRunning(false)
      c.setCodexChatRunStartedAt(null)
      c.setCodexChatElapsedSeconds(0)
      const msg = err instanceof Error ? err.message : 'Chat failed'
      c.setUiError(msg)
      if (variables?.sessionId && typeof c.setCodexChatTurnsForSession === 'function') {
        c.setCodexChatTurnsForSession(variables.sessionId, (prev: any[]) => [
          ...prev,
          {
            id: globalThis.crypto?.randomUUID?.() ?? `aerr-${Date.now()}`,
            role: 'assistant',
            content: `Error: ${msg}`,
            createdAt: Date.now()
          }
        ])
      } else {
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
