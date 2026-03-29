# ConstructOS OMC Adoption Implementation Report

Date: 2026-03-29
Scope: ConstructOS architecture/UX hardening inspired by `oh-my-claudecode` patterns
Status: Implementation complete (code-level), pending only operational steps (`commit`, `push`, user-triggered deploy/recreate).

## 1. Executive Summary

The planned OMC-inspired adoption work was implemented across backend orchestration, runtime state contracts, bootstrap performance, Team Mode execution session persistence, and UX/runtime visibility.

Key outcomes:
- Team Mode runtime now has stronger deterministic state semantics and blocker-code contracts.
- Kickoff behavior now uses a bounded verify/fix loop with explicit terminal failure reasons and persisted phase history.
- Bootstrap now avoids repeated expensive discovery paths and exposes cache/registry telemetry.
- Real-time UX remained reactive while reducing over-refresh behavior.
- Run-level usage/cost and skill-trace metadata are now propagated and visible in Team runtime surfaces.
- Structured pre-gate classification was added to avoid unnecessary heavy orchestration for clearly small requests.

## 2. Completed Plan Areas

### Phase 1. Runtime Truth Stabilization

Implemented:
- Canonical Team runtime state shape and invariant tightening.
- Blocker-code contract for blocked/missing-instruction tasks.
- Disjoint `Now/Next/Blocked` focus sets and dispatch/kickoff target sanitization.

Primary files:
- `app/plugins/team_mode/runtime_snapshot.py`

Behavioral impact:
- No mixed-state task ambiguity in runtime focus.
- Blocked tasks carry machine-readable cause (`blocker_code`) and human-readable reason.

### Phase 2. Bootstrap and Registry Performance

Implemented:
- Bootstrap discovery cache extracted to dedicated cache module.
- Bootstrap avoids runtime-heavy discovery (`allow_runtime_discovery=False`, `include_codex_cli=False` for bootstrap path).
- MCP registry telemetry expanded with refresh lifecycle and stale-serve counters.

Primary files:
- `app/features/bootstrap/cache.py`
- `app/features/bootstrap/read_models.py`
- `app/features/agents/mcp_registry.py`
- `app/features/agents/model_registry.py`

Behavioral impact:
- Lower bootstrap jitter and fewer expensive repeated calls.
- Better observability for MCP/model registry cache behavior.

### Phase 3. Reactive UX Without Over-refresh

Implemented:
- SSE/bootstrap invalidation smoothing (debounced refresh scheduling).
- Runtime freshness UX (last snapshot update + explicit refresh action).

Primary files:
- `app/frontend/src/app/useRealtimeEffects.ts`
- `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`

Behavioral impact:
- Preserved project-list reactivity while reducing refetch churn.
- Clearer runtime panel freshness and manual recovery action.

### Phase 4. Execution Sessions + Verify/Fix

Implemented:
- Persisted Team execution session artifact model and helper module.
- Kickoff flow now creates/advances/completes sessions with phase history.
- Bounded verify/fix loop for kickoff propagation, explicit blocker reasons on failure.
- Session exposure via project checks API and UI panel.

Primary files:
- `app/shared/models.py`
- `app/plugins/team_mode/execution_sessions.py`
- `app/plugins/team_mode/api_kickoff.py`
- `app/features/projects/api.py`

Behavioral impact:
- Durable run narrative per kickoff.
- No silent “queue only” success when developer dispatch is not confirmed.

### Phase 5. Routing, Skill Traceability, Usage/Cost Surfaces

Implemented:
- Structured task-size pre-gate classifier before default heavy kickoff behavior.
- Skill trace metadata propagation in run usage payload.
- Runtime usage surface with provider/model/tokens/cost aggregate and task-level visibility.
- Optional provider/model rate-card fallback for `cost_usd` when provider omits direct cost.

Primary files:
- `app/features/agents/task_size_classifier.py`
- `app/shared/prompt_templates/codex/task_size_pre_gate_classifier.md`
- `app/features/tasks/command_handlers.py`
- `app/features/agents/codex_mcp_adapter.py`
- `app/features/agents/executor.py`
- `app/plugins/team_mode/runtime_snapshot.py`
- `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`

Behavioral impact:
- Small/local requests are less likely to auto-trigger heavy kickoff orchestration.
- Skill-usage reasoning and cost/usage surfaces are now visible and auditable.

## 3. API and Data Contract Changes

Added/extended:
- `team_mode_execution_session` in checks payload with richer summary fields.
- Team runtime task rows now include blocker and usage fields (`blocker_code`, token/cost/provider/model/skill-trace markers).
- Bootstrap payload includes `agent_chat_registry_debug` with cache status and registry telemetry.

## 4. UI Changes

Checks panel (`ProjectsInlineEditor`) now includes:
- Team runtime freshness indicator (`Snapshot: <time> (<age>)`).
- Explicit runtime refresh button.
- Execution session status details including verify/fix attempt metadata.
- Runtime usage badges:
  - token totals (`in/out`)
  - skill-trace task count
  - cost (when available)
- Task-level runtime rows show:
  - blocker code/reason
  - provider/model
  - token/cost footprint
  - skill-trace count

## 5. Test Coverage Added/Updated

Added:
- `app/tests/core/contexts/platform/test_team_mode_kickoff_verify_fix_loop.py`
- `app/tests/core/contexts/platform/test_team_mode_execution_sessions.py`
- `app/tests/core/contexts/platform/test_bootstrap_runtime_discovery_flags.py`
- `app/tests/core/contexts/platform/test_bootstrap_cache.py`
- `app/tests/core/contexts/agents/test_task_size_classifier.py`
- `app/tests/core/contexts/agents/test_executor_usage_metadata.py`

Updated:
- `app/tests/core/contexts/platform/test_doctor_api.py`
- `app/tests/core/contexts/agents/test_mcp_registry.py`

Validation status (latest targeted run):
- Backend targeted suites: passing.
- Frontend build: passing.

## 6. Operational Status

Completed:
- Implementation and local validation.

Pending (operational only):
- Commit changes.
- Push branch.
- User-triggered recreate/deploy workflow.

## 7. Notes and Constraints Applied

- No heuristic fallback was introduced for ambiguous workflow classification decisions.
- Control-plane safety constraints were respected (no control-plane stack destructive operations performed as part of implementation).
- No auto-deploy was executed from implementation flow.
