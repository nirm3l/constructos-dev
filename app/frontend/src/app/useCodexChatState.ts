import React from 'react'

export type ChatRole = 'user' | 'assistant'
export type ChatTurn = { id: string; role: ChatRole; content: string; createdAt: number }

export function useCodexChatState() {
  const [showCodexChat, setShowCodexChat] = React.useState(false)
  const [codexChatProjectId, setCodexChatProjectId] = React.useState<string>('')
  const [codexChatInstruction, setCodexChatInstruction] = React.useState('')
  const [codexChatTurns, setCodexChatTurns] = React.useState<ChatTurn[]>([])
  const [codexChatSessionId] = React.useState<string>(() => globalThis.crypto?.randomUUID?.() ?? `chat-${Date.now()}`)
  const [isCodexChatRunning, setIsCodexChatRunning] = React.useState(false)
  const [codexChatRunStartedAt, setCodexChatRunStartedAt] = React.useState<number | null>(null)
  const [codexChatElapsedSeconds, setCodexChatElapsedSeconds] = React.useState(0)
  const [codexChatLastTaskEventAt, setCodexChatLastTaskEventAt] = React.useState<number | null>(null)

  return {
    showCodexChat,
    setShowCodexChat,
    codexChatProjectId,
    setCodexChatProjectId,
    codexChatInstruction,
    setCodexChatInstruction,
    codexChatTurns,
    setCodexChatTurns,
    codexChatSessionId,
    isCodexChatRunning,
    setIsCodexChatRunning,
    codexChatRunStartedAt,
    setCodexChatRunStartedAt,
    codexChatElapsedSeconds,
    setCodexChatElapsedSeconds,
    codexChatLastTaskEventAt,
    setCodexChatLastTaskEventAt,
  }
}
