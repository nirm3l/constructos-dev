import { describe, expect, it } from 'vitest'

import { parseTeamModeAutomationSessionLog } from './ProjectsInlineEditor'

describe('Project Checks Replay Parser Smoke', () => {
  it('falls back to summary execution fields when provider_context is missing', () => {
    const parsed = parseTeamModeAutomationSessionLog({
      id: 'session-1',
      status: 'completed',
      trigger: 'kickoff',
      provider_context: {},
      transcript: [
        {
          event_type: 'summary',
          index: 0,
          payload: {
            execution_provider: 'codex',
            execution_model: 'gpt-5',
            execution_reasoning_effort: 'high',
          },
        },
      ],
    })

    expect(parsed).toBeTruthy()
    expect(parsed?.provider).toBe('codex')
    expect(parsed?.model).toBe('gpt-5')
    expect(parsed?.reasoning_effort).toBe('high')
    expect(parsed?.transcript[0]?.summary_text).toBe(null)
  })

  it('falls back to verify_fix attempts when summary provider fields are absent', () => {
    const parsed = parseTeamModeAutomationSessionLog({
      id: 'session-2',
      status: 'completed',
      trigger: 'kickoff',
      transcript: [
        {
          event_type: 'verify_fix',
          index: 1,
          attempt_count: 2,
          fix_attempt_count: 1,
          runner_error_count: 0,
          attempts: [
            {
              attempt_index: 1,
              provider: 'claude',
              model: 'sonnet',
              reasoning_effort: 'medium',
              status: 'passed',
            },
          ],
        },
      ],
    })

    expect(parsed).toBeTruthy()
    expect(parsed?.provider).toBe('claude')
    expect(parsed?.model).toBe('sonnet')
    expect(parsed?.reasoning_effort).toBe('medium')
    expect(parsed?.transcript[0]?.verify_fix_attempt_count).toBe(2)
    expect(parsed?.transcript[0]?.verify_fix_fix_attempt_count).toBe(1)
    expect(parsed?.transcript[0]?.verify_fix_runner_error_count).toBe(0)
  })
})
