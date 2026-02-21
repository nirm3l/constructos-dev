# Operation Gateway Rollout

## Goal
Route identical UI and MCP operations through a shared gateway layer so behavior, authorization, idempotency, and realtime side-effects are consistent regardless of ingress path.

## Common Gateway Contract
- `actor_user_id`: authenticated principal that initiates the action.
- `explicit_target_user_id`: optional direct target provided by caller.
- `implicit_target_user_id`: fallback target when caller does not explicitly target.
- `command_id`: idempotency token for mutating actions.
- `policy`: per-action policy flags (for example, admin requirement for explicit cross-user actions).

## Current Status
- Implemented first gateway slice: `features/users/gateway.py` (`UserOperationGateway`).
- Moved user preference operations to shared gateway path for:
  - UI: `PATCH /api/me/preferences`
  - MCP-backed agent: `get_my_preferences`, `toggle_my_theme`, `set_my_theme`
- Explicit cross-user targeting now goes through one policy check (admin required in shared workspace).
- Introduced shared operation gateway builder: `features/agents/gateway.py`.
- MCP now uses `build_mcp_gateway()` and UI adapters use `build_ui_gateway(actor_user_id=...)`.
- Migrated overlapping UI and MCP operations to the same gateway/service path:
  - tasks: list, create, patch, complete, bulk, add comment, automation run/status
  - notes: list, create, get, patch, archive, restore, pin, unpin, delete
  - task groups: list, create, patch, delete, reorder
  - note groups: list, create, patch, delete, reorder
  - project rules: list, create, get, patch, delete
  - specifications: list, create, get, patch, bulk task create, link/unlink task, link/unlink note, archive, restore, delete
  - projects/templates overlap: create project, template list/get/preview/create
  - project knowledge overlap: graph overview, context-pack, knowledge search

## Migration Phases
1. `User` domain (completed)
- Keep actor/target policy in gateway.
- Keep API and MCP adapters thin.

2. Shared operations gateway (completed for overlap scope)
- Reused `AgentTaskService` as a configurable shared gateway for both ingress paths.
- Added mode configuration (`require_token`, actor override, scope allowlists/default workspace).

3. Remaining non-overlap UI-only endpoints (pending)
- Keep current adapters for now (reopen/archive/restore task endpoints, task reorder/watch/delete-comment, calendar/export, project subgraph/members board helpers).
- Move these only if they need MCP parity later.

4. Consolidation
- Remove duplicated policy/scoping code from adapters.
- Keep end-to-end parity tests for each shared operation.

## Testing Strategy
- For each migrated operation pair (UI + MCP), add a parity test that verifies:
  - same authorization outcomes
  - same state transition
  - same realtime side-effects (notifications/SSE signal path where applicable)
