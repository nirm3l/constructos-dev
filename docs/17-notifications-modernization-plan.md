# 17 Notifications Modernization Plan

## 1. Objective
Modernize the notification system to be:
- higher signal, lower noise,
- CQRS-consistent,
- replay-safe and idempotent,
- predictable for realtime clients,
- extensible for new notification types.

Primary driver: remove low-value notifications such as:
- `Daily digest for YYYY-MM-DD: 0 due today, 0 overdue, 0 high priority.`

## 2. Current Problems

### 2.1 Product / UX
- Daily digest is emitted even when all counters are zero.
- Notification content is mostly plain text and not strongly typed.
- UI still has fallback parsing from message text for task linking.

### 2.2 Behavior Consistency
- `notifications_enabled` is honored by the worker, but not consistently in all request paths that can emit system notifications.
- Query endpoints (`GET`) can trigger notification writes, which blurs read/write boundaries.

### 2.3 Reliability / Realtime
- Read-state updates do not broadcast dedicated realtime refresh for all clients/tabs.
- SSE reconnection currently lacks robust cursor resume semantics.

### 2.4 Data / Scale
- Notification query pattern (`user_id + time order`) is not fully index-optimized.
- Replay/idempotency risk exists for projection-time direct inserts (mention notifications).

## 3. Scope

### In Scope
- System notifications (due soon, overdue, daily digest).
- Mention notifications from task comments.
- Notification read-state propagation and SSE behavior.
- Data model and API-compatible evolution.

### Out of Scope
- Push/email/mobile channel delivery in this phase.
- Full notification center redesign in frontend visuals.

## 4. Phase Plan

## Phase P0: Immediate Quality Fixes (Highest Priority)

### P0.1 Suppress Empty Daily Digest
- Do not create daily digest when:
  - `due_today == 0`
  - `overdue == 0`
  - `high_priority == 0`

### P0.2 Make Digest Actionable
- Include only non-zero counters in message.
- Add top actionable tasks (max 3) sorted by urgency:
  - overdue first,
  - then due today,
  - then high priority.

### P0.3 Respect User Preference Everywhere
- Enforce `notifications_enabled` in every emission path, not only worker ticks.

### P0.4 Replay-Safe Mention Notifications
- Remove projection-time direct notification inserts for mentions.
- Emit mention notifications through event path with idempotent handling.

### P0.5 Minimal Query Performance Upgrade
- Add index for notification listing by user and recency:
  - `(user_id, created_at DESC)` (or equivalent engine-compatible variant).

### P0 Acceptance Criteria
- No more zero-value digest notifications.
- Disabling notifications prevents system notification creation in all paths.
- Mention notifications are idempotent under replay.
- Notification list query remains fast under larger history.

## Phase P1: Architectural Consistency and Realtime Hardening

### P1.1 Remove Write Side Effects from GET
- Stop emitting system notifications from:
  - `/api/bootstrap`
  - `/api/notifications`
  - stream initialization
- Keep emission in worker/scheduler only.

### P1.2 Realtime Read-State Propagation
- On `NotificationMarkedRead`, enqueue realtime user channel signal.
- Ensure multiple tabs/devices converge quickly.

### P1.3 Cursor Resume Semantics
- Support `Last-Event-ID` and/or explicit cursor contract.
- Default stream behavior should avoid replaying entire historical notification list.

### P1.4 Documentation Alignment
- Update API docs and runbook with all emitted SSE event types and resume semantics.

### P1 Acceptance Criteria
- Read endpoints are read-only.
- Mark-as-read is visible on concurrent clients without manual refresh.
- Reconnect resumes correctly without full-history replay.

## Phase P2: Typed Notification Domain + New High-Value Notifications

### P2.1 Introduce Typed Notification Schema
- Add structured fields:
  - `type` (enum/string)
  - `severity`
  - `dedupe_key`
  - `payload_json`
  - `source_event`
- Keep backward-compatible `message` for existing clients.

### P2.2 Add New Notification Types (Existing Features)
Recommended additions:
1. `TaskAssignedToMe`
2. `WatchedTaskStatusChanged`
3. `TaskAutomationFailed`
4. `TaskScheduleFailed`
5. `ProjectMembershipChanged`
6. `LicenseGraceEndingSoon` (threshold-based, non-spammy)

### P2.3 Add Dedupe Rules per Type
- Define dedupe windows/keys per notification type instead of raw message matching.

### P2 Acceptance Criteria
- New notifications are typed, linked, and actionable.
- Dedupe behavior is deterministic and test-covered per type.

## 5. Data Model and Compatibility Strategy

### Migration Approach
- Add new nullable columns first (non-breaking).
- Backfill minimal defaults where required.
- Keep existing API fields stable until frontend migration is complete.

### Backward Compatibility
- Existing clients continue to read `message`, `is_read`, references.
- New clients can consume structured type/payload fields.

## 6. Testing Plan

### Unit / Integration
- Digest suppression tests for zero counters.
- Preference gating tests (`notifications_enabled=false`) across all emission paths.
- Replay/idempotency tests for mention notifications.
- SSE tests for read-state refresh and cursor resume.
- Query performance smoke checks with larger seeded notification volumes.

### Regression Guardrails
- Add tests proving GET endpoints do not append new events.
- Validate dedupe behavior under retries and event replay.

## 7. Rollout Plan

1. Release P0 behind safe defaults (no feature flag needed).
2. Ship P1 with docs update and SSE compatibility fallback.
3. Ship P2 in additive mode:
   - old fields preserved,
   - new typed payload consumed progressively by frontend.

## 8. Success Metrics
- Reduced notification noise:
  - near-zero rate of zero-value digests.
- Improved usefulness:
  - increased open/interaction rate on notifications.
- Improved consistency:
  - reduced stale-read-state incidents across tabs.
- Improved reliability:
  - no duplicate mention notifications under replay tests.

## 9. Open Decisions
- Preferred digest schedule time (local 08:00 vs configurable per user/workspace).
- Whether to keep one combined digest or split by workspace/project.
- Priority and thresholds for license-related alerts.
