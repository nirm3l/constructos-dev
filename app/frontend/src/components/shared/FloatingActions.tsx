import React from 'react'
import { Icon } from './uiHelpers'

export function FloatingActions({ state }: { state: any }) {
  return (
    <>
      <button
        className={`fab fab-task ${state.fabHidden ? 'fab-hide' : ''}`}
        onClick={() => {
          state.setQuickProjectId(state.selectedProjectId || state.bootstrap.data?.projects?.[0]?.id || '')
          state.setQuickTaskGroupId('')
          state.setQuickTaskAssigneeId('')
          state.setQuickTaskExternalRefsText('')
          state.setQuickTaskAttachmentRefsText('')
          state.setShowQuickAdd(true)
        }}
        title="New Task"
        aria-label="New Task"
        data-tour-id="fab-new-task"
      >
        <Icon path="M12 4v16M4 12h16" />
      </button>

      <button
        className={`fab ${state.isCodexChatRunning ? 'busy' : ''} ${state.fabHidden ? 'fab-hide' : ''}`}
        onClick={() => {
          // Preserve the exact last chat context (project + session), including "No project".
          state.setShowCodexChat(true)
        }}
        title="Chat"
        aria-label="Chat"
        data-tour-id="fab-chat"
      >
        <Icon path="M4 4h16v11H7l-3 3V4z" />
        <span>{state.isCodexChatRunning ? `Chat (${state.codexChatElapsedSeconds}s)` : 'Chat'}</span>
      </button>
    </>
  )
}
