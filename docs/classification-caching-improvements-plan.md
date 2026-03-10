# Classification Caching Improvements Plan

## Goal
Make structured LLM classification efficient and reusable across the project without turning cache into a substitute for correct architecture.

The intended model is:
- classify once at the highest relevant entry point,
- persist the structured intent envelope,
- propagate it downstream,
- use a reusable cache layer only to absorb unavoidable duplicate calls.

## Why this is needed
- Some entry points already classify once and persist results.
- Some lower-level paths still classify again because structured intent was not propagated.
- Prompt-cache support exists, but that alone is not enough:
  - it reduces latency and cost,
  - it does not simplify control flow,
  - it does not prove that the same instruction is not being classified repeatedly in different layers.

## Principles
- Cache is an optimization, not the source of truth.
- Persisted structured classification beats cache.
- Reclassification is allowed only for genuinely new instruction payloads.
- Cache must fail closed:
  - stale, malformed, or incompatible cache entries must be ignored,
  - correctness may not depend on cache availability.
- The cache layer should be generic and reusable across Team Mode, Git Delivery, Docker Compose, and general task automation.

## Audit Scope

### Primary entry points to review
- Chat/orchestration request entry
- MCP `request_task_automation_run`
- REST `/api/tasks/{task_id}/automation/run`
- REST `/api/tasks/{task_id}/automation/stream`
- Internal orchestration helpers that synthesize kickoff or follow-up automation requests

### What to detect
- repeated classification of the same instruction in multiple layers
- entry points that do not pass through structured intent fields
- places where cache exists but propagation is missing
- places where runtime falls back to task text because no structured request envelope was propagated

## Proposed Shared Abstraction

### Interface
- Introduce a shared helper with a shape like:
  - `classify_instruction_intent_cached(...)`
  - or a reusable `ClassificationService`

### Required inputs
- normalized instruction text
- `workspace_id`
- `project_id`
- classifier/schema version
- optional session/request metadata when it changes the expected output

### Required outputs
- the same normalized structured intent envelope already used by the runtime:
  - `execution_intent`
  - `execution_kickoff_intent`
  - `project_creation_intent`
  - `workflow_scope`
  - `execution_mode`
  - `task_completion_requested`
  - optional delivery flags such as deploy/docker-compose/port/task-count
  - `reason`

### Cache key
- hash of normalized instruction payload
- `workspace_id`
- `project_id`
- classifier version
- output schema version

## Implementation Phases

### Phase 1: Inventory
- Enumerate every call site of `classify_instruction_intent(...)`.
- Tag each call site:
  - `primary`
  - `consumer_only`
  - `duplicate`
- Record whether the call site already has structured fields available.

### Phase 2: Shared cache wrapper
- Add a reusable shared helper for cached classification.
- Centralize cache-key building and schema-version handling.
- Keep the existing lower-level prompt cache if useful, but wrap it with an application-level helper.

### Phase 3: Propagation cleanup
- Convert entry points so they pass structured classification through request models and service layers.
- Remove lower-level reclassification where upstream already supplied structured fields.
- Keep cached fallback only for legacy or partial call paths that still lack propagated structured intent.

### Phase 4: Observability
- Add metrics or structured logs for:
  - classifier invocation count
  - cache hit/miss count
  - duplicate-classification count for the same instruction/request scope
- Use this to confirm the architecture is actually improving.

### Phase 5: Hardening
- Add tests for:
  - same request classified once in happy path
  - repeated path uses cache without changing behavior
  - stale or incompatible cache entry is ignored safely
  - propagated structured intent wins over reclassification

## Recommended First Targets
- `features/agents/api.py`
- `features/agents/service.py`
- `features/tasks/api.py`
- `features/tasks/command_handlers.py`
- any internal kickoff/helper path that currently synthesizes `TaskAutomationRun`

## Acceptance Criteria
- Happy-path chat request: one classification call.
- Happy-path MCP task run: one classification call.
- Happy-path REST task run: one classification call.
- Lower layers consume structured intent instead of reclassifying.
- Repeated classification, when still present, is intentional and cache-backed.
- Cache implementation is generic enough to be reused outside Team Mode.
