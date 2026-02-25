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

## 2. Current State Snapshot (2026-02-25)

### 2.1 Delivered Since Plan Draft
- P0 is completed:
  - empty daily digest is suppressed,
  - digest is actionable with top tasks,
  - preference gating is enforced for system and mention paths,
  - mention notifications are emitted via event path,
  - notification query index exists (`user_id + created_at`).
- P1 is completed:
  - `/api/bootstrap`, `/api/notifications`, and notification stream init are read-only,
  - mark-read and mark-all-read emit realtime refresh signals across tabs,
  - SSE resume supports `Last-Event-ID` and tail default behavior,
  - API and runbook docs were aligned to current SSE event contract.
- P2 is completed:
  - typed notification schema is available in read model and API payloads,
  - event-driven typed notifications are emitted for assignment/watch/failure/membership/license paths,
  - typed dedupe keys are enforced per type via `user_id + dedupe_key`,
  - frontend consumes typed fields with `message` fallback for legacy rows.

### 2.2 Remaining Gaps
- No open functional gaps for P0/P1/P2 scope.
- Message-based system notification dedupe is intentionally retained for legacy due-soon/overdue/digest notices.
- Next iterations should focus on channel expansion (email/push/mobile) and UX polish.

### 2.3 Changes That Affect the Remaining Plan
- Shared operation gateway rollout is now active for overlapping UI/MCP mutations.
  - New notification triggers should be event-driven (projection-time reaction to domain events), not adapter-specific.
- SSE contract is now stable and must remain backward-compatible:
  - `notification`, `task_event`, `license_event`, `ping`,
  - tail-by-default stream behavior,
  - resume by explicit cursor or `Last-Event-ID`.
- Licensing model now includes stable `status`, `grace_ends_at`, and validation timestamps.
  - License-related notifications should use these read-model fields and threshold dedupe.

## 3. Scope

### In Scope
- System notifications (due soon, overdue, daily digest).
- Mention notifications from task comments.
- Notification read-state propagation and SSE behavior.
- Typed notification evolution with backward-compatible API payloads.
- New high-value notifications derived from existing task/project/licensing events.

### Out of Scope
- Push/email/mobile channel delivery in this phase.
- Full notification center redesign in frontend visuals.

## 4. Phase Plan

## Phase P0: Immediate Quality Fixes (Completed)

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

## Phase P1: Architectural Consistency and Realtime Hardening (Completed)

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

## Phase P2: Typed Notification Domain + New High-Value Notifications (Completed)

### P2.1 Typed Notification Schema (Additive)
- Add nullable notification columns:
  - `notification_type` (string),
  - `severity` (string),
  - `dedupe_key` (string),
  - `payload_json` (JSON string),
  - `source_event` (string).
- Add supporting index for dedupe lookup:
  - `(user_id, dedupe_key, created_at DESC)`.
- Keep `message` as required for backward compatibility.
- Extend serialization and DTOs to return typed fields while preserving old fields.
- Add event upcaster behavior for legacy `NotificationCreated` events:
  - default `notification_type="Legacy"`,
  - default `severity="info"`,
  - default empty payload/dedupe metadata.

### P2.2 New Notification Types and Trigger Contracts
- Implement typed notification emission for existing domain events:
1. `TaskAssignedToMe`
2. `WatchedTaskStatusChanged`
3. `TaskAutomationFailed`
4. `TaskScheduleFailed`
5. `ProjectMembershipChanged`
6. `LicenseGraceEndingSoon`

Type trigger matrix:

| Notification type | Trigger source | Target users | Payload minimum |
| --- | --- | --- | --- |
| `TaskAssignedToMe` | `TaskCreated`/`TaskUpdated` where assignee changes | new assignee (excluding actor self-assignment) | `task_id`, `project_id`, `assignee_id`, `title`, `status` |
| `WatchedTaskStatusChanged` | `TaskUpdated` where `status` changed | task watchers (excluding actor) | `task_id`, `project_id`, `from_status`, `to_status`, `title` |
| `TaskAutomationFailed` | `TaskAutomationFailed` | assignee + watchers (deduped) | `task_id`, `project_id`, `error`, `summary`, `failed_at` |
| `TaskScheduleFailed` | `TaskScheduleFailed` | assignee + watchers (deduped) | `task_id`, `project_id`, `error`, `failed_at`, `scheduled_at_utc` |
| `ProjectMembershipChanged` | `ProjectMemberUpserted` / `ProjectMemberRemoved` | affected user | `project_id`, `workspace_id`, `action`, `role`, `actor_id` |
| `LicenseGraceEndingSoon` | license status polling (`grace_ends_at`) | workspace owners/admins | `installation_id`, `grace_ends_at`, `hours_remaining`, `status` |

### P2.3 Add Dedupe Rules per Type
- Replace raw message dedupe with typed dedupe keys.
- Baseline dedupe keys:
  - `TaskAssignedToMe`: `task-assigned:{task_id}:{assignee_id}:{event_version}`
  - `WatchedTaskStatusChanged`: `watch-status:{task_id}:{watcher_id}:{to_status}:{event_version}`
  - `TaskAutomationFailed`: `automation-failed:{task_id}:{error_hash}:{hour_bucket}`
  - `TaskScheduleFailed`: `schedule-failed:{task_id}:{error_hash}:{hour_bucket}`
  - `ProjectMembershipChanged`: `project-member:{project_id}:{user_id}:{action}:{role}:{event_version}`
  - `LicenseGraceEndingSoon`: `license-grace:{installation_id}:{threshold_hours}`
- Thresholds for license grace notices:
  - 72h, 24h, and 6h before `grace_ends_at`.

### P2.4 Frontend and API Consumption
- Extend frontend `Notification` type to include typed fields and payload.
- Keep existing rendering path (`message`) as fallback.
- Replace message parsing fallback (`parseLegacyTaskId`) with typed references where available.
- Keep all current action buttons functional for legacy rows.

### P2 Acceptance Criteria
- New notifications are typed, linked, and actionable.
- Dedupe behavior is deterministic and test-covered per type and threshold.
- Legacy notifications remain readable and actionable after rollout.

## 5. Data Model and Compatibility Strategy

### Migration Approach
- Add new nullable columns first.
- Backfill minimal defaults for old rows in a background-safe way.
- Keep existing API fields stable until frontend migration is complete.

### Backward Compatibility
- Existing clients continue using `message`, `is_read`, and references.
- New clients can consume structured type/payload fields immediately after additive release.

## 6. Testing Plan

### Unit / Integration
- Existing P0/P1 coverage stays as regression suite.
- Add migration tests for new notification columns and defaulting.
- Add upcaster tests for legacy notification events.
- Add per-type trigger tests for all P2 notification types.
- Add dedupe tests per type (including license thresholds and replay/catch-up scenarios).
- Add frontend tests for typed notification rendering and legacy fallback.

### Regression Guardrails
- Add tests proving GET endpoints do not append new events.
- Validate dedupe under retries, replay, and projection catch-up.
- Validate SSE contract remains unchanged (`notification`, `task_event`, `license_event`, `ping`).

## 7. Rollout Plan

1. P0 delivered.
2. P1 delivered.
3. Ship P2 in additive mode:
   - Release 1: schema + API additive fields + no UI dependency.
   - Release 2: typed emissions for new notification types.
   - Release 3: frontend typed rendering, then optional legacy parser removal.

## 8. Success Metrics
- Reduced notification noise:
  - near-zero rate of zero-value digests.
- Improved usefulness:
  - increased open/interaction rate on notifications.
- Improved consistency:
  - reduced stale-read-state incidents across tabs.
- Improved reliability:
  - no duplicate mention notifications under replay tests.
  - no duplicate typed notifications under replay/catch-up tests.

## 9. Open Decisions
- Severity taxonomy resolved as `info` / `warning` / `critical`.
- `LicenseGraceEndingSoon` recipients resolved to workspace `Owner`/`Admin` members.
- Keep one combined digest in current phase; revisit workspace/project split in a later phase.
