# OMC Adoption Backlog v2 (ConstructOS)

## Goal

Polish Team Mode and runtime UX by reimplementing proven OMC patterns inside ConstructOS persisted architecture, without introducing tmux/file-local runtime assumptions.

## Constraints

- Keep core ConstructOS primitives: CQRS/eventing, plugin policies, required checks, graph context.
- No heuristic-only classification fallbacks for ambiguous workflow decisions.
- Preserve task-first UX and reactive SSE behavior.

## Priority Roadmap

## P0 - Reliability and Runtime Truth (must ship first)

### 1) Persisted Execution Session State Machine

- Scope:
  - Introduce/complete single persisted `execution_session` model (or equivalent) for Team/Autopilot-like runs.
  - Canonical phases: `plan -> prd -> exec -> verify -> fix -> complete|failed|cancelled`.
  - Enforce legal transitions and guard checks server-side.
- Why:
  - Replace fragmented runtime truth with one source of truth.
- Acceptance:
  - Every kickoff run has one session row/document with phase history.
  - Illegal transitions are rejected and logged with explicit reason.

### 2) Team Mode Operational Snapshot API

- Scope:
  - Add runtime snapshot surface derived from tasks + automation states + team slots + dependency graph.
  - Include `Now / Next / Blocked` counts, per-task blocked reasons, slot occupancy.
- Why:
  - Users need runtime clarity beyond static config validation.
- Acceptance:
  - Snapshot explains why each blocked task is blocked.
  - Kickoff waiting reason is explicit and deterministic.

### 3) Verify/Fix Loop Contract (bounded, explicit)

- Scope:
  - Standardize verify/fix iteration policy: max attempts, stop reasons, final failure artifact.
  - Persist loop metadata under execution session.
- Why:
  - Keep “finish the job” behavior without silent infinite retries.
- Acceptance:
  - Each failed run contains verifiable stop reason and loop attempt history.

## P1 - Throughput and UX Smoothness

### 4) Dispatcher Capacity Planner

- Scope:
  - Add deterministic planner that matches runnable tasks to available team slots.
  - Produce dispatch plan preview in snapshot.
- Why:
  - Team Mode should feel smooth, not “stuck then jump”.
- Acceptance:
  - New task waves are predictable and visible before dispatch.

### 5) Bootstrap/MCP Call Budget and Caching

- Scope:
  - Cache MCP list/capabilities on backend with TTL + invalidation.
  - Ensure bootstrap endpoints do not repeatedly re-resolve unchanged provider metadata.
- Why:
  - Remove startup jitter and redundant bootstrap work.
- Acceptance:
  - Repeated bootstrap calls in one session hit cache.
  - New project still appears reactively through SSE without page refresh.

### 6) Task-Size Pre-Gate (LLM structured classification)

- Scope:
  - Add lightweight pre-gate deciding simple vs orchestrated path.
  - Use structured LLM output; failure -> safe negative/unknown (no guess).
- Why:
  - Avoid over-orchestrating small requests.
- Acceptance:
  - Small tasks bypass heavy Team orchestration when appropriate.
  - No keyword-heuristic-only fallback path.

## P2 - Intelligence and Cost Surfaces

### 7) Skill Reuse Upgrade (project/workspace)

- Scope:
  - Strengthen trigger matching + context injection from existing skills.
  - Store match evidence and usefulness feedback.
- Why:
  - Reuse successful solutions systematically.
- Acceptance:
  - Execution logs show when and why skill context was injected.

### 8) Model Routing + Cost Telemetry

- Scope:
  - Explicit provider/model routing policy per role/task type.
  - Persist usage/cost telemetry per task/run.
- Why:
  - Lower cost with observability, not blind claims.
- Acceptance:
  - Per-run report includes model/provider usage and totals.

### 9) Runtime Board UI (web, not terminal HUD clone)

- Scope:
  - Add board panel: phase timeline, Now/Next/Blocked, active slots, recent events.
  - Realtime updates through existing SSE stream.
- Why:
  - Make orchestration legible to users in project/task views.
- Acceptance:
  - User can answer “what is happening now and why blocked” without logs/refresh.

## Implementation Order

1. P0.1 state machine
2. P0.2 operational snapshot
3. P0.3 verify/fix contract
4. P1.5 bootstrap/MCP caching and call reduction
5. P1.4 dispatcher capacity planner
6. P1.6 task-size pre-gate
7. P2.9 runtime board UI
8. P2.8 model/cost telemetry
9. P2.7 skill reuse upgrade

## Definition of Done (Program Level)

- Team Mode runs are explainable end-to-end from persisted state only.
- No regression in reactive UX (new project/task visibility via SSE).
- Failed runs always have explicit, user-readable blocked/failure reasons.
- Bootstrap path no longer introduces avoidable repeated MCP listing jitter.
- Core plugin/check architecture remains unchanged.
