# Orchestration Hardening Plan (Prompt-Agnostic Source of Truth)

## Objective

Make orchestration deterministic, schema-first, and reactive for any prompt while preserving ConstructOS core architecture:

- CQRS/event-sourced write model
- Team Mode / Git Delivery / Docker Compose plugin policy model
- Task-first UX and SSE-driven reactivity
- No heuristic fallback for ambiguous workflow decisions

This plan targets systemic execution quality issues (retry-heavy flows, contract drift, graph mutation surprises, bootstrap jitter) rather than prompt-specific behavior.

## Current Systemic Gaps

1. API contract drift between tools/endpoints causes avoidable retries.
2. Plugin configuration application is not always one-pass deterministic in runtime flows.
3. Kickoff and task graph execution can require corrective follow-up instead of failing early with explicit blockers.
4. Read-after-write orchestration paths are chatty and increase latency/jitter.
5. Delivery verification is treated as hard blocker too early for setup-only trajectories.
6. Runtime state is spread across multiple payload surfaces; UX must infer too much.

## Design Constraints

1. Keep existing domain boundaries and plugin model intact.
2. Keep Team Mode semantics and persisted task state as source of truth.
3. Keep SSE as wake-up/refresh channel; do not replace with ad hoc polling loops.
4. For ambiguous classification, require structured LLM output and safe unknown outcome.
5. Avoid fallback heuristics in control-path decisions.

## Target Architecture

### A. Deterministic Orchestration Compiler

Introduce a canonical compile stage before side effects:

`intent -> compile(plan + contracts + dag + policy) -> validate -> apply -> dispatch -> finalize`

Compile output must include:

- normalized identifiers (`workspace_id`, `project_id`)
- normalized plugin intents and full config payloads
- deterministic task graph plan
- dispatch strategy and expected phase transitions
- explicit blocking reasons when compile/validate fails

No side effects are allowed before compile+validate success.

### B. Unified API Contract Layer

Create/normalize request contracts so caller payloads are stable and idempotent:

- shared contract validator for orchestration-facing calls
- strict unknown-field policy per endpoint family
- machine-readable error codes for all validation failures
- response envelope with `contract_version`, `execution_state`, `blocking`, `blockers[]`

### C. Task Graph Compile-Then-Apply

Move dependency logic to deterministic pre-dispatch compile:

- produce one DAG artifact per orchestration run
- validate cycles/inconsistent delivery modes before kickoff
- forbid post-dispatch auto-mutation of structural dependencies
- if graph invalid: stop with blocker code and required fix action

### D. Execution State Machine Normalization

Use one canonical run state model for setup/kickoff execution visibility:

- stable phases (`compile`, `validate`, `apply`, `dispatch`, `verify`, `finalize`)
- stable task runtime states (`idle`, `queued`, `running`, `blocked`, `completed`, `failed`)
- persisted run/session summary as source of truth for UI

### E. Bootstrap and Registry Efficiency

Keep reactive UX while reducing backend jitter:

- cache heavy bootstrap substructures with short TTL + explicit invalidation channels
- deduplicate concurrent bootstrap computations per cache key
- batch read-after-write verification into one final aggregation read

### F. UX Reliability Rules

Frontend should consume backend truth with minimal inference:

- subscribe once per workspace/project scope for SSE
- refresh only affected slices from typed reason codes
- optimistic UI only after backend acceptance token
- never require full page refresh for new project/task visibility

## Implementation Phases

## Phase 1: Contract and Compiler Foundation

Scope:

- add orchestration compile contract types
- implement compile validation entrypoint in orchestration service path
- normalize error code surface

Acceptance:

- no orchestration side effect when compile fails
- all compile failures return blocker codes and actionable details

## Phase 2: Plugin Config Determinism

Scope:

- generate full plugin config payloads before apply
- remove runtime partial-config paths from orchestrated flow
- enforce config validation before first apply

Acceptance:

- plugin config steps pass in one application cycle without corrective retries

## Phase 3: Deterministic DAG Pipeline

Scope:

- centralize dependency compilation
- persist compile-time DAG artifact per orchestration run
- block kickoff when compiled graph is invalid/incomplete

Acceptance:

- no post-kickoff structural dependency corrections required

## Phase 4: Runtime State Unification

Scope:

- expose canonical run/session state envelope to API/UI
- align setup/kickoff status surfaces and blocker narratives

Acceptance:

- UI can render run progress from one payload source without synthetic state derivation

## Phase 5: Performance and Reactivity Hardening

Scope:

- reduce bootstrap call amplification and duplicate computations
- tighten SSE invalidation mapping to affected read models
- minimize redundant read-after-write calls

Acceptance:

- stable first-load latency budget
- new/updated entities appear reactively without manual refresh

## Phase 6: Verification and Regression Gates

Scope:

- add end-to-end orchestration tests for representative prompt classes
- add deterministic replay tests (same prompt -> same orchestration transitions)
- add latency/retry metrics assertions for orchestration hot path

Acceptance:

- no uncontrolled retries in happy-path flows
- reproducible orchestration outcomes across reruns

## Non-Goals

1. Replacing CQRS/event store model.
2. Replacing Team Mode domain semantics.
3. Introducing heuristic fallback routing.
4. Prompt-specific hardcoded logic.

## Rollout and Safety

1. Ship behind internal feature flag per phase.
2. Keep old path available only as temporary rollback guard during migration.
3. Remove legacy fallback paths after phase-level validation is complete.

## Definition of Done

The orchestration path is considered hardened when:

1. A generic create/configure/spec/tasks/kickoff prompt executes without ad hoc retries.
2. API contract mismatches are rejected at compile/validate stage, not during dispatch.
3. Task graph remains stable after dispatch (no corrective structural mutation).
4. Bootstrap/SSE behavior stays reactive while meeting latency budget.
5. Final run report exposes deterministic state, blockers, and completion evidence.
