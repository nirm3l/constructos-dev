# ConstructOS Doctor Improvement Plan (P0-P1)

## Goal

Improve ConstructOS reliability and diagnostics by strengthening Doctor checks, making failures explainable, and reducing false-positive "healthy" states.

## Scope

- Doctor backend checks and quick-action event contract.
- Doctor regression tests for slot drift and quick-action failure semantics.
- Initial UI/UX alignment work is tracked but deferred to a follow-up implementation batch.

## Problem Statement

- Doctor currently validates seeded team tasks with a count-only check (`>= 4`) which can miss slot drift.
- Quick actions currently persist `passed|warning` only, which blurs real failures.
- Existing tests cover broad Doctor behavior but do not lock slot-integrity and failed-action status contracts.

## Implementation Phases

### Phase 1 - Slot Integrity Contract (P0)

- Add deterministic seeded slot integrity analysis for `dev-a`, `dev-b`, `qa-a`, `lead-a`.
- Expose slot-integrity summary in Doctor status checks.
- Add explicit Doctor run check `seeded_team_slot_integrity`.

Exit criteria:

- Doctor run fails when slot duplicates or missing slots are present.
- Check details include missing/duplicate slots and title mismatches.

### Phase 2 - Quick Action Failure Semantics (P0)

- Persist quick-action status as `passed|failed` based on action result (`ok` flag).
- Keep analytics compatibility for existing stats fields.

Exit criteria:

- Failed quick actions appear as `failed` in `last_action` and `recent_actions`.

### Phase 3 - Regression Coverage (P0)

- Add test for slot-drift regression that must fail Doctor run.
- Add test for quick-action failed status persistence.

Exit criteria:

- New tests pass reliably in local test runtime.

### Phase 4 - UX Follow-Up (P1, next batch)

- Clarify task `status` vs `automation_state` semantics in task cards and board.
- Expand Doctor check details panel with direct fix guidance and issue grouping.

### Phase 5 - Check Runbook Contract (P1)

- Add backend-enriched `runbook` payload per Doctor run check (`suggested_quick_action_id`, `severity`, `rationale`).
- Prefer backend runbook guidance in frontend check triage UX.
- Add tests that verify runbook-driven suggested fix execution path.

### Phase 6 - Diagnose vs Repair Flow (P1)

- Keep `doctor/run` diagnostic-first so slot drift is visible as a failed check.
- Keep `doctor-plugin-wiring` as explicit repair path that reconciles seeded slot assignments.
- Add end-to-end regression coverage: drift -> failed check -> repair action -> passed slot integrity.

### Phase 7 - Executor Worktree Guardrails (P0)

- Add deterministic Doctor diagnostics for executor task-worktree isolation guardrails.
- Expose executor guardrails as a runtime-health domain and as a dedicated Doctor run check.
- Add a dedicated quick action (`executor-worktree-guard-diagnostics`) with actionable guidance.
- Extend frontend Doctor incident panel to surface and execute the new guardrails diagnostics path.

### Phase 8 - Automation Failure Codes (P0)

- Standardize executor/worktree automation failure codes for machine-readable triage.
- Propagate error classification through task automation status and streaming failure responses.
- Expose actionable Doctor recommendation id on task automation failures.
- Surface automation error code/type directly in Task Drawer execution insights.

### Phase 9 - Task Drawer Doctor Bridge (P1)

- Add direct Task Drawer action to execute recommended Doctor quick action from automation failure metadata.
- Auto-open Doctor incident view after Task Drawer quick-action execution to continue triage.
- Track recent executor worktree incidents as a dedicated Doctor run check.

### Phase 10 - Recommended Action Prioritization (P1)

- Add deterministic ranking for Doctor recommended actions based on severity, stale audits, and incident blast radius.
- Expose `recommended_primary_action_id` in runtime health to remove UI guesswork.
- Force executor guardrails diagnostics as primary whenever open worktree incidents exist.

### Phase 11 - Incident Triage UX + Cooldown Visibility (P1)

- Enrich backend worktree-incident payload with aggregated code/source counters and direct task deep links.
- Expose quick-action cooldown state in Doctor status so UI can disable actions before duplicate execution.
- Surface cooldown-aware action labels (`Retry in Xs`) and richer incident list rendering in Doctor checks.

### Phase 12 - Task Workflow/Automation Clarity (P1)

- Add explicit "execution attention" signals on task list and board cards when workflow status and automation state diverge.
- Surface high-signal labels for active incidents (`Execution incident`) and workflow/automation mismatches.
- Add Tasks panel incident summary strip with direct entry point to Doctor incident mode.
- Add global notice-layer incident banner for open executor worktree incidents with direct diagnostics and Doctor-incident CTA actions.

### Phase 13 - Frontend Load Performance (P1)

- Lazy-load heavy project graph/task-flow pages so XYFlow/cytoscape-heavy code is not eagerly included in initial entry bundle.
- Keep UX responsive with fallback loading cards during deferred chunk fetch.

### Phase 14 - Executor Diagnostics Deep Output (P1)

- Enrich `executor-worktree-guard-diagnostics` quick action result with live incident summary (`open/resolved`, `latest_incident_at`, code/source aggregates, top incidents).
- Treat open incidents as a non-OK diagnostics outcome even when static guardrail checks are healthy.

## Tracking Checklist

- [x] Draft and commit this plan document.
- [x] Implement slot-integrity analyzer and run check integration.
- [x] Implement failed quick-action status persistence.
- [x] Add regression tests for slot drift and failed quick-action status.
- [x] Run focused Doctor test suite and fix failures.
- [x] Prepare next UI/UX implementation batch.
- [x] Add backend check runbook enrichment and frontend consumption.
- [x] Add frontend tests for Doctor runbook triage and task workflow/automation labels.
- [x] Separate diagnostic run from repair flow and add end-to-end repair regression test.
- [x] Add frontend interaction coverage for check-group UX and suggested-fix state matrix.
- [x] Add backend runbook contract assertions for non-passed checks.
- [x] Add strict runbook contract gate test for all Doctor run checks.
- [x] Add frontend incident failure feedback test for suggested-fix quick action.
- [x] Add frontend transition test for suggested fix (`Run suggested fix` -> `Running...` -> success feedback).
- [x] Add Doctor executor worktree guardrails diagnostics helper with explicit issue codes.
- [x] Add runtime-health `executor_guardrails` domain and high-priority recommended action wiring.
- [x] Add `executor_worktree_isolation_guard` run check with runbook mapping.
- [x] Add `executor-worktree-guard-diagnostics` quick action and API regression coverage.
- [x] Extend Doctor frontend panel domain rendering and quick-action routing for executor guardrails.
- [x] Add shared automation error classifier and unit tests for worktree isolation failures.
- [x] Prefix executor worktree guardrail runtime failures with stable error codes.
- [x] Propagate classified automation error metadata to task automation status/read model.
- [x] Surface automation error code/type/recommended Doctor action in Task Drawer insights.
- [x] Add Task Drawer `Run Doctor fix` action for automation failures with recommended Doctor action id.
- [x] Add frontend test coverage for Task Drawer Doctor quick-action execution flow.
- [x] Add Doctor check for recent executor worktree incidents.
- [x] Add backend rank scoring for Doctor recommended actions (`rank_score`).
- [x] Expose `recommended_primary_action_id` in runtime health and surface it in Doctor UI.
- [x] Enforce executor guardrails as primary action when open worktree incidents exist.
- [x] Enrich recent worktree incidents payload with `code_counts`, `source_counts`, `incident_state`, and `task_link`.
- [x] Expose `quick_action_cooldowns` map in Doctor status payload.
- [x] Make Doctor UI cooldown-aware for recommended/suggested actions.
- [x] Extend Doctor incident check UI with incident code rollups and direct task links.
- [x] Add incident triage filters in Doctor check details (`Open only`, code filter, source filter) with scoped incident list rendering.
- [x] Add task-card execution attention indicators for workflow/automation mismatch states.
- [x] Add Tasks panel automation incident summary strip with `Open Doctor incidents` shortcut.
- [x] Add AppNotices open-incident banner with `Run executor diagnostics` + `Open Doctor incidents` actions.
- [x] Add anti-duplication gating so Tasks panel incident strip can be suppressed when global incident banner is active.
- [x] Lazy-load knowledge graph/task-flow pages to reduce initial frontend entry bundle weight.
- [x] Enrich executor guard diagnostics quick action with live incident summary and incident-aware `ok` semantics.
- [x] Prioritize specific open-incident notice over generic runtime-failing notice to reduce duplicate alerting noise.
