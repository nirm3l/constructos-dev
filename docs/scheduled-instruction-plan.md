# Scheduled Instruction Tasks Plan

## Goal
Introduce a task type that automatically executes its instruction at a configured time.

## Phase 1 (MVP): One-shot scheduled instruction

1. Data model updates
- Add `task_type` to `Task` (`manual`, `scheduled_instruction`), default `manual`.
- Add nullable schedule fields:
  - `scheduled_instruction`
  - `scheduled_at_utc`
  - `schedule_timezone`
  - `schedule_state` (`idle`, `queued`, `running`, `done`, `failed`), default `idle`
  - `last_schedule_run_at`
  - `last_schedule_error`

2. API/contracts updates
- Extend `TaskCreate` and `TaskPatch` with schedule fields.
- Validation rules:
  - If `task_type=scheduled_instruction`, require `scheduled_instruction` and `scheduled_at_utc`.
  - Reject invalid combinations (e.g. schedule fields on `manual` unless explicitly allowed).
  - Ensure `scheduled_at_utc` is valid UTC timestamp.
- Include schedule metadata in task list/detail read models.

3. Event-sourcing/domain updates
- Add events:
  - `TaskScheduleConfigured`
  - `TaskScheduleQueued`
  - `TaskScheduleStarted`
  - `TaskScheduleCompleted`
  - `TaskScheduleFailed`
  - `TaskScheduleDisabled` (optional)
- Update rebuild/projection logic so schedule state is derived from events.

4. Scheduler worker
- Add scheduler loop (or extend existing runner) to detect due tasks:
  - `task_type=scheduled_instruction`
  - `schedule_state=idle`
  - `scheduled_at_utc <= now_utc`
- Emit `TaskScheduleQueued` then `TaskScheduleStarted`.
- Reuse existing Codex execution pipeline with `scheduled_instruction`.
- Emit `TaskScheduleCompleted` or `TaskScheduleFailed`.

5. Idempotency and safety
- Ensure each scheduled run is queued once.
- Use command/event version guards to prevent duplicate execution after restart.
- If worker crashes mid-run, ensure retry behavior is explicit and deterministic.

6. UI changes
- Task form/drawer additions:
  - Task type selector.
  - Scheduled datetime picker.
  - Instruction textarea.
  - Schedule state badge and last run/error.
- Show local time + normalized UTC to avoid timezone confusion.

7. Observability
- Metrics:
  - scheduled tasks due
  - queued/running/completed/failed counts
  - schedule lag (`now - scheduled_at_utc`)
- Structured logs with task id, scheduled time, run duration, status.

8. Tests
- Validation tests for create/patch schedule fields.
- Worker test: due task transitions `idle -> queued -> running -> completed/failed`.
- Idempotency test across worker restarts.
- Timezone parsing/normalization tests.

## Phase 2 (Optional): Recurrence

1. Add recurrence field (`rrule` or cron-like expression).
2. Add `next_scheduled_at_utc` computation after each run.
3. Add pause/resume semantics.
4. Add recurrence edge-case tests (DST, month boundaries, invalid rules).

## Rollout strategy

1. Add feature flag: `SCHEDULED_TASKS_ENABLED`.
2. Deploy schema + read paths first.
3. Enable UI controls.
4. Enable scheduler execution in controlled environment.
5. Monitor metrics/logs and adjust retry/timeout policy.

## Definition of done (MVP)
- A `scheduled_instruction` task can be created with instruction + time.
- At configured time, system automatically executes instruction once.
- Result status and errors are visible in UI without page reload.
- No duplicate executions for the same schedule.
- Test suite covers validation, execution path, and idempotency.
