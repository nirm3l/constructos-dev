import React from 'react'
import { Icon } from './uiHelpers'

export function FloatingActions({ state }: { state: any }) {
  return (
    <>
      <button
        className={`fab fab-task ${state.fabHidden ? 'fab-hide' : ''}`}
        onClick={() => {
          state.setQuickProjectId(state.selectedProjectId || state.bootstrap.data?.projects?.[0]?.id || '')
          state.setQuickTaskExternalRefsText('')
          state.setQuickTaskAttachmentRefsText('')
          state.setShowQuickAdd(true)
        }}
        title="New Task"
        aria-label="New Task"
      >
        <Icon path="M12 5v14M5 12h14" />
      </button>

      <button
        className={`fab ${state.isCodexChatRunning ? 'busy' : ''} ${state.fabHidden ? 'fab-hide' : ''}`}
        onClick={() => {
          const targetProjectId = state.selectedProjectId || state.codexChatProjectId || ''
          state.selectCodexChatProject(targetProjectId)
          state.setShowCodexChat(true)
        }}
        title="Chat"
        aria-label="Chat"
      >
        <Icon path="M4 4h16v11H7l-3 3V4z" />
        <span>{state.isCodexChatRunning ? `Chat (${state.codexChatElapsedSeconds}s)` : 'Chat'}</span>
      </button>
    </>
  )
}
