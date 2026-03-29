# ConstructOS OMC-Inspired Implementation Plan

## Objective

Implement OMC-grade orchestration smoothness in ConstructOS while preserving ConstructOS core architecture:

- persisted domain/runtime truth
- plugin policy + required checks
- task-first UX
- reactive SSE behavior
- no heuristic-only fallback for ambiguous workflow decisions

## OMC Pattern Mapping (Authoritative References)

- Team phase machine and guards:
  - `oh-my-claudecode/src/hooks/team-pipeline/types.ts`
  - `oh-my-claudecode/src/hooks/team-pipeline/transitions.ts`
- Persistent execution and verify/fix loop:
  - `oh-my-claudecode/src/hooks/persistent-mode/index.ts`
  - `oh-my-claudecode/src/hooks/ralph/loop.ts`
  - `oh-my-claudecode/src/hooks/ralph/verifier.ts`
- Runtime visibility and statusline/HUD concepts:
  - `oh-my-claudecode/src/hud/index.ts`
  - `oh-my-claudecode/src/hud/state.ts`
- Follow-up orchestration shortcuts:
  - `oh-my-claudecode/src/team/followup-planner.ts`
- Cost/model routing and usage reporting:
  - `oh-my-claudecode/src/config/loader.ts`
  - `oh-my-claudecode/src/team/usage-tracker.ts`

## Current ConstructOS Baseline (already present)

- Team runtime context exists:
  - `app/plugins/team_mode/runtime_context.py`
- Team runtime snapshot exists:
  - `app/plugins/team_mode/runtime_snapshot.py`
- Team transition guard primitive exists:
  - `app/plugins/team_mode/state_machine.py`
- Team runtime UI is already rendered:
  - `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`
- Bootstrap pulls model + MCP registries:
  - `app/features/bootstrap/read_models.py`
- MCP and model registries already have in-process caches:
  - `app/features/agents/mcp_registry.py`
  - `app/features/agents/model_registry.py`

## Delivery Strategy

Ship in narrow vertical slices. Each slice must improve real behavior and remain deploy-safe.

## Implementation Status (2026-03-29)

- Completed:
  - Phase 1.1-1.3 runtime invariants and blocker-code contract in Team runtime snapshot.
  - Phase 2.3 bootstrap discovery budget reduction (`allow_runtime_discovery=False`, no Codex CLI MCP discovery in bootstrap).
  - Phase 3.1 SSE/bootstrap invalidation smoothing with debounced refresh scheduling.
  - Phase 4.1 persisted Team execution session artifact (DB model + kickoff wiring + checks endpoint exposure).
  - Phase 4.2 bounded kickoff verify/fix loop with explicit terminal blocker reason and phase transitions.
  - Phase 3.3 runtime snapshot freshness UX (last update timestamp + explicit refresh action).
  - Phase 5.1 structured task-size pre-gate classifier wired into Team kickoff-default path.
  - Phase 5.2 skill traceability metadata persisted in run usage payload (`project_skill_trace`).
  - Phase 5.3 usage surface extended in Team runtime snapshot/UI (provider/model/token totals).
  - Phase 2.1/2.2 bootstrap cache extracted into dedicated module + MCP refresh telemetry (refresh lifecycle, stale serve counters, last error).
  - Optional provider-specific rate-card fallback for cost when provider usage omits `cost_usd` (`AGENT_USAGE_COST_RATE_CARD_JSON`).
- Remaining:
  - No open plan items in this document; remaining work is iterative hardening and additional e2e coverage.

## Phase 1 - Runtime Truth Stabilization (Backend)

### 1.1 Canonical Team Runtime State Shape

- Scope:
  - Normalize runtime-state taxonomy used by snapshot (`active`, `runnable`, `blocked`, `waiting`, `missing_instruction`, `out_of_scope`).
  - Remove drift between snapshot classification and state-machine semantics.
- Files:
  - `app/plugins/team_mode/runtime_snapshot.py`
  - `app/plugins/team_mode/state_machine.py`
  - `app/plugins/team_mode/semantics.py`
- Acceptance:
  - A task cannot be simultaneously interpreted as runnable and blocked.
  - Runtime state classification is deterministic for same input snapshot.

### 1.2 Blocked-Reason Contract

- Scope:
  - Produce explicit machine-readable blocker categories in runtime snapshot:
    - `dependency_not_satisfied`
    - `missing_instruction`
    - `dispatch_slot_unavailable`
    - `status_semantics_mismatch`
    - `team_mode_disabled`
  - Keep existing human-readable `blocker_reason` text for UI.
- Files:
  - `app/plugins/team_mode/runtime_snapshot.py`
  - `app/features/projects/api.py`
- Acceptance:
  - Every blocked task has `blocker_code` and `blocker_reason`.

### 1.3 Dispatch/Kickoff Readiness Invariants

- Scope:
  - Tighten `dispatch` and `kickoff` payload consistency:
    - no task in queue unless runtime-state is runnable
    - no duplicate task ids across now/next/blocked sets
  - Add integrity checks in snapshot builder.
- Files:
  - `app/plugins/team_mode/runtime_snapshot.py`
  - `app/plugins/team_mode/workflow_orchestrator.py`
- Acceptance:
  - Snapshot passes invariant checks in tests for edge cases.

## Phase 2 - Bootstrap and Registry Performance (Backend)

### 2.1 Cross-request Bootstrap Cache Layer

- Scope:
  - Add short-lived cached sub-structures for bootstrap heavy sections:
    - `agent_chat_available_models`
    - `agent_chat_available_mcp_servers`
  - Keep per-user dynamic data uncached.
- Files:
  - `app/features/bootstrap/read_models.py`
  - new helper: `app/features/bootstrap/cache.py` (or shared cache utility)
- Acceptance:
  - Repeated `/api/bootstrap` calls in same process do not trigger repeated expensive discovery.

### 2.2 MCP Registry Refresh Behavior Hardening

- Scope:
  - Keep stale-while-refresh behavior but add bounded refresh frequency guard and explicit telemetry fields.
  - Ensure timeout path does not block bootstrap response path.
- Files:
  - `app/features/agents/mcp_registry.py`
- Acceptance:
  - Bootstrap always returns quickly with stale snapshot when refresh is in-flight/slow.

### 2.3 Model Registry Discovery Budget

- Scope:
  - Ensure model discovery path follows same stale-while-refresh pattern as MCP where possible.
  - Keep default fallback deterministic when discovery fails.
- Files:
  - `app/features/agents/model_registry.py`
- Acceptance:
  - No repeated model-list subprocess jitter during frequent bootstrap invalidations.

## Phase 3 - Reactive UX Without Over-refresh (Frontend)

### 3.1 Bootstrap Invalidation Policy Cleanup

- Scope:
  - Keep project list reactive, but avoid broad bootstrap invalidation on unrelated task events.
  - Introduce targeted query updates for project lifecycle events vs task events.
- Files:
  - `app/frontend/src/app/useRealtimeEffects.ts`
  - `app/frontend/src/app/AppShell.tsx`
- Acceptance:
  - Newly created project appears without page refresh.
  - Task event bursts do not trigger unnecessary bootstrap refetch loops.

### 3.2 Team Runtime Board Polish

- Scope:
  - Improve `Now / Next / Blocked` UX with blocker badges and role/slot visibility.
  - Surface dispatch/kickoff blocked reasons clearly in panel.
- Files:
  - `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`
  - CSS surface in related frontend stylesheets.
- Acceptance:
  - User can determine why execution is blocked from panel only.

### 3.3 Runtime Snapshot Freshness UX

- Scope:
  - Show snapshot age / last refresh timestamp.
  - Provide explicit “refresh runtime snapshot” action if needed.
- Files:
  - `app/frontend/src/components/projects/ProjectsInlineEditor.tsx`
- Acceptance:
  - No ambiguity whether panel is stale.

## Phase 4 - Verification Loop and Execution Sessions

### 4.1 Persisted Execution Session Artifact

- Scope:
  - Introduce persisted run/session artifact for Team execution cycles with phase history.
  - Attach verify/fix attempts and terminal outcome.
- Files:
  - `app/features/agents/*` (new execution session module)
  - `app/plugins/team_mode/service_orchestration.py`
  - DB model/migration in `app/shared/models.py` + migration files.
- Acceptance:
  - Every kickoff run has durable execution session with timeline.

### 4.2 Bounded Verify/Fix Policy

- Scope:
  - Standardize max verify/fix attempts and explicit terminal failure contract.
- Files:
  - `app/features/agents/service.py`
  - `app/plugins/team_mode/service_orchestration.py`
- Acceptance:
  - No silent partial completion; failures have explicit reason and evidence payload.

## Phase 5 - Routing, Skills, Cost Surfaces

### 5.1 Structured Task-size Pre-gate

- Scope:
  - Add LLM-structured classifier before heavy orchestration.
  - If unavailable/failure -> safe negative/unknown outcome.
- Files:
  - `app/shared/prompt_templates/codex/*`
  - `app/features/agents/service.py`
- Acceptance:
  - Small tasks avoid heavy orchestration where valid.

### 5.2 Skill Reuse and Traceability

- Scope:
  - Improve project skill matching and include “why skill was applied” metadata.
- Files:
  - `app/features/project_skills/*`
  - `app/features/agents/service.py`
- Acceptance:
  - Run metadata includes skill match evidence.

### 5.3 Usage/Cost Reporting

- Scope:
  - Persist execution usage by task/run and expose UI summary.
- Files:
  - `app/features/agents/*`
  - `app/frontend/src/components/projects/*`
- Acceptance:
  - Per-run model/provider usage is visible.

## Test Plan

- Backend:
  - extend Team runtime snapshot tests under:
    - `app/tests/core/contexts/platform/test_team_mode_workflow_orchestrator.py`
    - new tests for runtime snapshot invariants and blocker categories
- Frontend:
  - add/update tests for SSE invalidation and runtime panel state mapping.
- End-to-end:
  - Tetris prompt regression:
    - create project + specification + 3 tasks
    - Team mode setup
    - docker compose port 6768
    - kickoff
    - verify no failed-task drift and project appears reactively.

## Execution Order (Immediate)

1. Phase 1.1-1.3 (runtime snapshot/state consistency)
2. Phase 3.1 (SSE/invalidations) in same branch to preserve reactive UX
3. Phase 2.1-2.3 (bootstrap perf hardening)
4. Validate with Tetris end-to-end
5. Continue with execution sessions and verify/fix persistence
