# 18 Codex Session Resume and Token Efficiency Implementation Plan

## 1. Objective

Implement true multi-turn Codex thread continuation for chat sessions and reduce token overhead without removing existing chat capabilities.

Primary outcomes:

1. Reuse `codex_session_id` with `thread/resume` on subsequent chat turns.
2. Persist Codex thread state across requests by replacing ephemeral `HOME` with persistent per-session storage.
3. Keep current UX and API behavior (`/api/agents/chat` and `/api/agents/chat/stream`) while reducing uncached input token usage.

This plan assumes a non-production environment and does not use feature flags.

## 2. Current State and Root Cause

Current behavior:

1. A temporary Codex home is created for each run (`tempfile.TemporaryDirectory`) and deleted at the end of the request.
2. The adapter always starts a new thread via `thread/start`.
3. `codex_session_id` is stored in `chat_sessions.codex_session_id` but is not used for continuation.

Root cause:

1. `codex_session_id` is only an identifier, not the full thread state.
2. `thread/resume` depends on persisted thread state available under Codex storage.
3. Because storage is ephemeral per request, there is no reliable state to resume.

Impact:

1. Every turn behaves like a fresh conversation.
2. Prompt must repeatedly include large static context and manual history.
3. Uncached token usage is significantly higher than necessary.

## 3. Target Architecture

## 3.1 High-level flow

1. Chat session has a stable app session key (`session_id`) and optional `codex_session_id`.
2. Each chat session maps to a persistent Codex home directory.
3. Adapter attempts `thread/resume` when `codex_session_id` exists.
4. On resume failure, adapter falls back to `thread/start` and saves new thread id.
5. Subsequent turns reuse the same Codex thread and local persisted thread state.

## 3.2 Storage model

Persistent path pattern:

`/data/codex-home/workspace/<workspace_id>/chat/<session_id>/`

Inside each session directory:

1. `.codex/config.toml` generated from selected MCP servers for that chat session.
2. `.codex/auth.json` copied from host user/home if available.
3. Codex-managed thread files persisted by app-server.

## 4. Scope

In scope:

1. Chat endpoints (`/api/agents/chat`, `/api/agents/chat/stream`) and executor path.
2. App-server adapter path (`codex app-server`).
3. Prompt shaping adjustments for resumed chat.
4. Test coverage updates.

Out of scope:

1. Major redesign of task automation runner behavior outside chat.
2. Remote distributed thread storage.

## 5. Detailed Implementation Plan

## 5.1 Pass session identifiers through execution context

Goal:

Ensure adapter receives enough information to map to persistent storage and to request resume.

Changes:

1. Extend `execute_task_automation` and `execute_task_automation_stream` signatures with:
   - `chat_session_id: str | None = None`
   - `codex_session_id: str | None = None`
2. Add these fields to `context` payload forwarded to `AGENT_CODEX_COMMAND`.
3. In chat API handlers, load current chat session row and pass stored `codex_session_id` into executor calls.
4. Keep task-automation paths compatible by passing `None` values.

Files:

1. `app/features/agents/executor.py`
2. `app/features/agents/api.py`

Acceptance criteria:

1. Adapter stdin context contains `chat_session_id` and prior `codex_session_id` for chat runs.
2. Existing non-chat automation calls still execute unchanged.

## 5.2 Replace ephemeral Codex home with persistent per-session home

Goal:

Persist Codex thread state across requests.

Changes:

1. Replace `_isolated_codex_home_env` with `_session_codex_home_env`.
2. Build deterministic safe path from `workspace_id` + `chat_session_id`.
3. Ensure directory creation is idempotent.
4. Write/update `.codex/config.toml` each run to reflect current MCP selection.
5. Copy `auth.json` only when missing in session home.
6. Keep temporary home fallback for contexts without `chat_session_id` (for non-chat callers).

Files:

1. `app/features/agents/codex_mcp_adapter.py`

Acceptance criteria:

1. Repeated requests for same chat session reuse same `HOME`.
2. Session directory remains after request completion.
3. Different chat sessions isolate Codex state.

## 5.3 Implement `thread/resume` with fallback to `thread/start`

Goal:

Actually use stored `codex_session_id`.

Changes:

1. Extend `_run_codex_app_server_with_optional_stream` with `preferred_thread_id: str | None`.
2. After `initialize`:
   - if `preferred_thread_id` is present, send `thread/resume` first.
   - else send `thread/start`.
3. Handle response IDs for both methods uniformly.
4. On resume errors (thread missing/corrupted/incompatible), retry once with `thread/start`.
5. Always capture resulting active `thread_id` and return as `codex_session_id`.

Files:

1. `app/features/agents/codex_mcp_adapter.py`

Acceptance criteria:

1. Second turn of same chat session issues `thread/resume`.
2. Resume failure does not fail the request; request continues via fresh thread.
3. Fresh thread id is persisted back to session.

## 5.4 Prompt shaping for resumed chat sessions

Goal:

Stop paying duplicate token cost for manual chat history when Codex thread already has memory.

Changes:

1. In chat API preparation:
   - If a valid stored `codex_session_id` exists for the session, do not prepend manual conversation history via `_compose_chat_instruction`.
   - Keep attachment context and latest user instruction.
2. Keep manual history composition only for:
   - first turn (no `codex_session_id`)
   - resume fallback turn where new thread had to be started.
3. Keep existing `/compact` command support, but skip automatic compaction if thread resume is active and context usage remains within limits.

Files:

1. `app/features/agents/api.py`

Acceptance criteria:

1. Resumed turns no longer include large stitched "Conversation history" blocks.
2. First-turn behavior remains stable.
3. `/compact` still works when explicitly requested.

## 5.5 Tighten default MCP footprint

Goal:

Reduce tool schema/context overhead by default.

Changes:

1. In chat drawer selection logic, default to core server only unless user explicitly enables optional servers.
2. Persist explicit server choices per session as today.

Files:

1. `app/frontend/src/components/chat/CodexChatDrawer.tsx`

Acceptance criteria:

1. New sessions start with core MCP only.
2. User can still opt into GitHub/Jira per session.

## 5.6 Add Codex home retention cleanup

Goal:

Prevent unbounded disk growth from persistent per-session homes.

Changes:

1. Add cleanup routine:
   - remove session homes older than retention threshold (for example 14 days since last write),
   - optional max total size guard.
2. Trigger cleanup opportunistically at app startup and periodically from runner loop.

Files:

1. `app/features/agents/codex_mcp_adapter.py` or new helper module under `app/features/agents/`
2. startup wiring (`main.py` or existing startup hooks)

Acceptance criteria:

1. Stale session directories are removed.
2. Active/recent sessions are unaffected.

## 6. Testing Plan

## 6.1 Unit tests

Add tests for:

1. Persistent home path creation and sanitization.
2. Resume-first request sequencing (`thread/resume` then `turn/start`).
3. Resume failure fallback (`thread/start` path).
4. Context payload includes `chat_session_id` and `codex_session_id`.
5. Prompt composition branch with and without resume state.

Likely files:

1. `app/tests/test_agents_context_pack.py`
2. `app/tests/test_api.py`

## 6.2 Integration tests

Add API tests:

1. First chat call stores returned `codex_session_id`.
2. Second call on same `session_id` uses stored `codex_session_id`.
3. If stored id is invalid, chat still returns success and updates `codex_session_id`.

## 6.3 Manual verification checklist

1. Start a new chat session, send first message, capture usage.
2. Send second and third messages in same session, verify:
   - lower uncached input tokens,
   - stable `codex_session_id`.
3. Restart app container, send another message in same session, verify resume still works.
4. Switch to another chat session and verify separate thread id and isolated context.

## 7. Metrics and Success Criteria

Track per chat turn:

1. `input_tokens`
2. `cached_input_tokens`
3. `uncached_input_tokens = input_tokens - cached_input_tokens`
4. latency and timeout rate

Success targets:

1. Same-session turn 2+ shows meaningful cached token reuse.
2. Median uncached input tokens reduced by at least 30%.
3. No regression in chat success rate.

## 8. Implementation Order (Commit Sequence)

1. Backend context plumbing (`chat_session_id`, `codex_session_id`) through API and executor.
2. Persistent Codex home manager.
3. Resume + fallback logic in adapter.
4. Prompt/history behavior adjustment for resumed sessions.
5. Frontend MCP default narrowing.
6. Retention cleanup.
7. Tests and docs update.

## 9. Risks and Mitigations

Risk: Resume may fail due to model/config mismatches.

Mitigation:

1. Keep automatic fallback to fresh thread start.
2. Update persisted `codex_session_id` after fallback.

Risk: Session homes consume disk rapidly.

Mitigation:

1. Add retention cleanup policy.
2. Track directory sizes.

Risk: Concurrent requests on same chat session corrupt Codex state.

Mitigation:

1. Add per-session lock around adapter execution.
2. Reject or queue concurrent run attempts for same session.

## 10. Definition of Done

Done when all conditions hold:

1. Chat turns for same session reliably use `thread/resume`.
2. Persistent session storage is in place and cleanup policy exists.
3. Current chat features remain functional (streaming, attachments, MCP tools, mutation behavior).
4. Tests cover resume, fallback, and token-usage expectations.
5. Measured uncached token reduction is visible on local validation scenarios.
