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

## Migration Phases
1. `User` domain (completed first slice)
- Keep actor/target policy in gateway.
- Keep API and MCP adapters thin.

2. `Task` domain (next)
- Introduce `TaskOperationGateway`.
- Move overlapping operations first: create, patch, complete, reopen, archive, restore, comment, bulk action.

3. `Note` and `Specification` domains
- Apply same pattern for create/update/archive/delete/link operations shared by UI and MCP.

4. `Project` and group/rule domains
- Move project create/update/delete and task/note group operations.

5. Consolidation
- Remove duplicated policy/scoping code from adapters.
- Keep end-to-end parity tests for each shared operation.

## Testing Strategy
- For each migrated operation pair (UI + MCP), add a parity test that verifies:
  - same authorization outcomes
  - same state transition
  - same realtime side-effects (notifications/SSE signal path where applicable)
