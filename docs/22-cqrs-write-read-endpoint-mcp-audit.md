# CQRS Audit: Endpoints and MCP Tools (Write/Read Boundary, Validation, Idempotency)

Date: 2026-03-01

## Scope
- Audited all mutating HTTP endpoints under `app/features/*/api.py`.
- Audited all mutating MCP tools exposed from `app/features/agents/mcp_server.py` and implemented in `app/features/agents/service.py`.
- Focus rules:
  - Write side must validate invariants (prefer aggregate state/invariants).
  - Read/projection side must not reject writes already accepted by write side.
  - Operations should be idempotent where practical.
  - Create operations may return created resource from aggregate state (without depending on projection catch-up).

## Executive Summary
- Critical violation exists in task patch flow: write-side allows invalid `assignee_id` in `PATCH`, then projection/DB FK rejects it.
- Multiple write handlers still validate cross-aggregate scope via read-model tables (`db.get(...)` / `select(...)`) instead of aggregate-backed command state.
- Many MCP mutating tools default to random `command_id` (`uuid4`) when omitted, so retries are non-idempotent by default.
- Projection worker retries non-duplicate `IntegrityError` indefinitely; this can create poison-event lag when write-side validation is incomplete.
- Several create handlers perform post-commit read-model lookup and fail if projection row is unavailable (`...not found after create`).

## Findings

## 1) Critical: Write validation gap in task patch (`assignee_id`)
Severity: Critical

Rule breach:
- Write side is not fully validating invariant for `assignee_id` on patch.
- Read/projection side (via FK constraint) becomes the effective validator.

Evidence:
- Assignee validator exists and enforces UUID + existing user:
  - [`app/features/tasks/command_handlers.py:128`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:128)
- Create task calls that validator:
  - [`app/features/tasks/command_handlers.py:437`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:437)
- Patch task path does not call `_validate_assignee_id` before persisting changes:
  - [`app/features/tasks/command_handlers.py:579`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:579)
- Read model has FK on `tasks.assignee_id -> users.id`:
  - [`app/shared/models.py:176`](/home/m4tr1x/task-management/app/shared/models.py:176)

Affected API endpoint:
- `PATCH /api/tasks/{task_id}` via [`app/features/tasks/api.py:138`](/home/m4tr1x/task-management/app/features/tasks/api.py:138)

Affected MCP tool:
- `update_task` (tool) -> `service.update_task` -> same patch handler:
  - [`app/features/agents/mcp_server.py:1161`](/home/m4tr1x/task-management/app/features/agents/mcp_server.py:1161)
  - [`app/features/agents/service.py:2654`](/home/m4tr1x/task-management/app/features/agents/service.py:2654)

Impact:
- Accepted command payload can fail at projection/persistence boundary.
- Violates rule: if write accepted, read should eventually reflect it.

Recommendation:
- Apply `_validate_assignee_id(...)` in `PatchTaskHandler` when `assignee_id` is present.
- Reject invalid assignee on write path with `422` before event append.

## 2) High: Read-side tables used as write-side scope validator in multiple handlers
Severity: High

Rule breach:
- Cross-aggregate invariants are checked directly via projection/read tables, not aggregate state (except where explicitly unavoidable).

Evidence examples:
- Task write scope validators (`project/spec/task_group`) use `db.get(...)`:
  - [`app/features/tasks/command_handlers.py:205`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:205)
  - [`app/features/tasks/command_handlers.py:214`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:214)
  - [`app/features/tasks/command_handlers.py:227`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:227)
- Note write scope validators use projection tables:
  - [`app/features/notes/command_handlers.py:146`](/home/m4tr1x/task-management/app/features/notes/command_handlers.py:146)
  - [`app/features/notes/command_handlers.py:155`](/home/m4tr1x/task-management/app/features/notes/command_handlers.py:155)
  - [`app/features/notes/command_handlers.py:166`](/home/m4tr1x/task-management/app/features/notes/command_handlers.py:166)
  - [`app/features/notes/command_handlers.py:177`](/home/m4tr1x/task-management/app/features/notes/command_handlers.py:177)
- Specification write scope validator uses `db.get(Project, ...)`:
  - [`app/features/specifications/command_handlers.py:129`](/home/m4tr1x/task-management/app/features/specifications/command_handlers.py:129)

Affected endpoint families:
- `/api/tasks` create/patch and related spec/group links.
- `/api/notes` create/patch.
- `/api/specifications` create/patch.
- Similar pattern in task groups, note groups, rules, projects membership checks.

Affected MCP tools:
- All mutating tools that route into these handlers (e.g. `create_task`, `update_task`, `create_note`, `update_note`, `create_specification`, `update_specification`, group/rule tools).

Impact:
- Write acceptance can depend on freshness/availability of projection tables.
- Weakens strict CQRS separation.

Recommendation:
- For key aggregates, use aggregate-backed command state (`load_*_command_state` / event rebuild) for invariants.
- Keep projection reads only for query/read concerns.
- If projection-read is retained for pragmatic reasons, document as explicit exception (ADR) and guard with consistent fallback.

## 3) High: Projection worker can repeatedly NACK non-duplicate integrity failures
Severity: High

Rule breach:
- Projection side can repeatedly reject events after write path accepted append.

Evidence:
- Persistent worker retries non-duplicate `IntegrityError` via `nack(..., "retry")`:
  - [`app/shared/eventing_projections.py:136`](/home/m4tr1x/task-management/app/shared/eventing_projections.py:136)
  - [`app/shared/eventing_projections.py:141`](/home/m4tr1x/task-management/app/shared/eventing_projections.py:141)
- Write path does write-through projection and rethrows non-duplicate integrity errors:
  - [`app/shared/eventing.py:50`](/home/m4tr1x/task-management/app/shared/eventing.py:50)
  - [`app/shared/eventing.py:56`](/home/m4tr1x/task-management/app/shared/eventing.py:56)

Impact:
- Poison events can cause lag/retry storms.
- System behavior depends on projection DB constraints instead of explicit write-side validation.

Recommendation:
- Move invariant checks to write side first (especially FK-like domain refs such as assignee/spec/group).
- Add dead-letter/quarantine strategy for repeated non-duplicate projection failures.

## 4) Medium: Non-idempotent default behavior for many MCP mutating tools
Severity: Medium

Rule breach:
- Retried MCP mutation without explicit `command_id` frequently generates new random IDs, so duplicate execution is possible.

Evidence:
- Deterministic fallback exists (`_fallback_command_id`) for some methods:
  - [`app/features/agents/service.py:557`](/home/m4tr1x/task-management/app/features/agents/service.py:557)
- But many mutators still use `command_id or f"...{uuid.uuid4()}"` (non-deterministic), e.g.:
  - `update_task_group` [`app/features/agents/service.py:1801`](/home/m4tr1x/task-management/app/features/agents/service.py:1801)
  - `update_note_group` [`app/features/agents/service.py:1901`](/home/m4tr1x/task-management/app/features/agents/service.py:1901)
  - `apply_project_skill` [`app/features/agents/service.py:2142`](/home/m4tr1x/task-management/app/features/agents/service.py:2142)
  - `update_specification` [`app/features/agents/service.py:2551`](/home/m4tr1x/task-management/app/features/agents/service.py:2551)
  - `update_note` [`app/features/agents/service.py:2597`](/home/m4tr1x/task-management/app/features/agents/service.py:2597)
  - `update_task` [`app/features/agents/service.py:2665`](/home/m4tr1x/task-management/app/features/agents/service.py:2665)
  - `bulk_task_action` [`app/features/agents/service.py:2743`](/home/m4tr1x/task-management/app/features/agents/service.py:2743)

Affected MCP tools (non-exhaustive, all mapped to methods above):
- `update_task_group`, `delete_task_group`, `update_note_group`, `delete_note_group`
- `apply_project_skill`
- `link_task_to_spec`, `unlink_task_from_spec`, `link_note_to_spec`, `unlink_note_from_spec`
- `update_project_rule`, `delete_project_rule`
- `update_specification`, `archive_specification`, `restore_specification`, `delete_specification`
- `update_note`, `archive_note`, `restore_note`, `pin_note`, `unpin_note`, `delete_note`
- `update_task`, `complete_task`, `add_task_comment`, `run_task_with_codex`, `bulk_task_action`, `archive_all_tasks`

Impact:
- Retry semantics are unpredictable unless caller always provides stable `command_id`.

Recommendation:
- Standardize all mutating MCP methods on deterministic fallback IDs from normalized payload.
- Keep UUID fallback only for intentionally non-idempotent operations, and document them.

## 5) Medium: Several state-transition commands are not idempotent (return 409 on already-target state)
Severity: Medium

Evidence:
- `complete` returns `409` if already done:
  - [`app/features/tasks/command_handlers.py:779`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:779)
- `archive` returns `409` if already archived:
  - [`app/features/tasks/command_handlers.py:842`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:842)
- `restore` returns `409` if not archived:
  - [`app/features/tasks/command_handlers.py:866`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:866)

Affected API endpoints:
- `POST /api/tasks/{task_id}/complete`
- `POST /api/tasks/{task_id}/archive`
- `POST /api/tasks/{task_id}/restore`

Affected MCP tools:
- `complete_task` and related wrappers on same handlers.

Impact:
- Retried identical command can fail instead of no-op success.

Recommendation:
- For idempotent semantics, convert already-target-state to no-op success with current representation.

## 6) Medium: Post-create handlers depend on immediate read-model availability
Severity: Medium

Rule breach:
- Create path commits, then reads projection view and throws if missing.

Evidence examples:
- Task create:
  - [`app/features/tasks/command_handlers.py:572`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:572)
  - [`app/features/tasks/command_handlers.py:574`](/home/m4tr1x/task-management/app/features/tasks/command_handlers.py:574)
- Project create:
  - [`app/features/projects/command_handlers.py:260`](/home/m4tr1x/task-management/app/features/projects/command_handlers.py:260)
  - [`app/features/projects/command_handlers.py:262`](/home/m4tr1x/task-management/app/features/projects/command_handlers.py:262)
- Specification create:
  - [`app/features/specifications/command_handlers.py:211`](/home/m4tr1x/task-management/app/features/specifications/command_handlers.py:211)
  - [`app/features/specifications/command_handlers.py:213`](/home/m4tr1x/task-management/app/features/specifications/command_handlers.py:213)
- Same pattern exists in notes/task groups/note groups/rules.

Impact:
- Tight coupling to projection timing/health.

Recommendation:
- Return aggregate-derived response directly from command state (or event payload + aggregate id/version).
- Keep read-model fetch as optional enrichment, not a hard failure path.

## What already aligns well
- Command deduplication mechanism exists when `command_id` is supplied:
  - [`app/shared/commanding.py:24`](/home/m4tr1x/task-management/app/shared/commanding.py:24)
- Several MCP create methods already use deterministic fallback command IDs (`_fallback_command_id`).
- Deterministic aggregate IDs for several creates (`uuid5`) reduce duplicate resource creation risk.

## Prioritized Fix Plan
1. Fix `PatchTaskHandler` assignee validation (`assignee_id`) to close critical write/projection split.
2. Standardize MCP mutator fallback `command_id` generation to deterministic hashes.
3. Decide and document cross-aggregate validation strategy (aggregate-first vs pragmatic projection checks), then refactor high-traffic task/note/spec flows first.
4. Make state-transition commands idempotent no-op where practical.
5. Replace post-create hard readback with aggregate-state response pattern.
6. Add projection poison-event handling (DLQ/quarantine after retry threshold).

## Endpoint/MCP Coverage Note
- All mutating HTTP endpoints and MCP mutating tools were reviewed.
- This report lists only places that currently violate, or materially weaken, the requested ruleset.
