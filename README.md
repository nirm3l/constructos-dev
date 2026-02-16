# m4tr1x (CQRS + Event Sourcing + KurrentDB + PostgreSQL Projections)

## Backend Architecture Status
Short answer: mostly yes, with caveats.

What is in good shape now:
- Vertical-slice modules by feature (`features/tasks`, `features/projects`, `features/notifications`, etc.).
- CQRS direction:
  - command flow in application services
  - read flow through dedicated read model (`features/tasks/read_models.py`)
- Event sourcing as source of truth (`append_event()`, rebuild/projection pipeline).
- Optimistic concurrency + retry middleware (`run_command_with_retry()`).
- Command idempotency support via `X-Command-Id` / `command_id` (`shared/commanding.py`, `command_executions` table).
- SSE notifications stream (`/api/notifications/stream`).
- Basic runtime metrics (`/api/metrics`).

What still needs improvement:
- More explicit read models for every major screen (not only tasks list).
- OpenAPI docs/examples for `X-Command-Id`.
- Expanded E2E coverage (SSE reconnect, mobile UX, conflict-heavy scenarios).
- Stronger event schema evolution policy (currently basic upcaster hook exists).

## Tech Stack
- Backend: FastAPI, SQLAlchemy, Pydantic
- Event sourcing libs: `eventsourcing`, `eventsourcing-kurrentdb`
- Event store: KurrentDB/EventStoreDB
- Frontend: React + TypeScript + TanStack Query
- Runtime: Docker Compose
- Projection DB: PostgreSQL (`DATABASE_URL`)

## Project Layout
- `app/main.py`: app bootstrap and router wiring
- `app/features/*`: vertical slices by bounded area
- `app/shared/*`: cross-cutting infrastructure (eventing, deps, serializers, bootstrap)
- `app/frontend/*`: React app
- `docker-compose.yml`: local stack (app + postgres + kurrentdb)

## Command and Query Model
### Commands
Commands go through feature handlers and eventually `execute_command()`:
1. Optional idempotency key (`X-Command-Id` header or `command_id` query).
2. Conflict-safe execution with retry (`run_command_with_retry()`).
3. Event append (`append_event()`), commit, projection/read return.
4. If same `command_id` repeats, stored response is returned (no duplicate side effects).

Relevant files:
- `app/shared/commanding.py`
- `app/shared/deps.py`
- `app/features/tasks/application.py`

### Queries
Queries read projected/read-model data and do not append events.

Task list query path:
- `GET /api/tasks` -> `features/tasks/read_models.py:list_tasks_read_model()`

## Eventing and Projections
- Event append: `app/shared/eventing.py:append_event()`
- Rebuild and projection logic: `app/shared/eventing_rebuild.py`
- Startup catch-up + worker loop: `app/shared/eventing_projections.py`
- KurrentDB adapter: `app/shared/eventing_store.py`

`append_event()` writes `schema_version=2` into metadata for new events.

## Event Schema Evolution
Upcaster hook:
- `app/shared/event_upcasters.py:upcast_event()`

It is applied while loading historical events so old payload shapes can be normalized before replay.

## Notifications and SSE
- Poll/list: `GET /api/notifications`
- Stream: `GET /api/notifications/stream` (SSE)
- Mark read: `POST /api/notifications/{id}/read`

SSE sends:
- `event: notification` with serialized notification data
- periodic `event: ping`

## Codex MCP (FastMCP)
- MCP server entrypoint: `app/features/agents/mcp_server.py`
- Exposed tools:
  - `list_tasks`
  - `get_task`
  - `create_task`
  - `send_email`
  - `update_task`
  - `complete_task`
  - `add_task_comment`
  - `run_task_with_codex`
  - `get_task_automation_status`
- Run server (example):
```bash
cd app
python -m features.agents.mcp_server
```
- Docker endpoint (current compose): `http://localhost:8091/mcp`
- Example JSON-RPC call:
```bash
curl -sS http://localhost:8091/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"auth_token":"dev-mcp-token"}}'
```
- Example tool execution:
```bash
curl -sS http://localhost:8091/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_tasks","arguments":{"workspace_id":"10000000-0000-0000-0000-000000000001","auth_token":"dev-mcp-token","limit":5}}}'
```
- MCP security environment variables:
  - `MCP_AUTH_TOKEN`: if set, every MCP tool call must include matching `auth_token`
  - `MCP_ACTOR_USER_ID`: fixed app user used for MCP actions (default is bootstrap user)
  - `MCP_DEFAULT_WORKSPACE_ID`: fallback workspace for MCP `create_task` when `workspace_id` is omitted
  - `MCP_ALLOWED_WORKSPACE_IDS`: comma-separated workspace allowlist
  - `MCP_ALLOWED_PROJECT_IDS`: comma-separated project allowlist
  - `create_task` workspace resolution order: `project_id` -> explicit `workspace_id` -> `MCP_DEFAULT_WORKSPACE_ID` -> single value from `MCP_ALLOWED_WORKSPACE_IDS`
- MCP email tool environment variables (optional; used by `send_email`):
  - `MCP_EMAIL_SMTP_HOST`, `MCP_EMAIL_SMTP_PORT`
  - `MCP_EMAIL_SMTP_USERNAME`, `MCP_EMAIL_SMTP_PASSWORD`
  - `MCP_EMAIL_SMTP_STARTTLS` (default `true`), `MCP_EMAIL_SMTP_SSL` (default `false`)
  - `MCP_EMAIL_FROM`
  - allowlist (recommended): `MCP_EMAIL_ALLOWED_RECIPIENTS` (comma-separated) and/or `MCP_EMAIL_ALLOWED_DOMAINS` (comma-separated)
- Optional local automation runner:
  - worker module: `app/features/agents/runner.py`
  - enable via env: `AGENT_RUNNER_ENABLED=true`
  - polling interval: `AGENT_RUNNER_INTERVAL_SECONDS` (default `5`)
  - executor mode: `AGENT_EXECUTOR_MODE=placeholder|command` (default `placeholder`)
  - command mode input: `AGENT_CODEX_COMMAND` (command reads JSON context from stdin and outputs JSON result to stdout)
  - executor timeout: `AGENT_EXECUTOR_TIMEOUT_SECONDS` (default `45`)
  - expected command output JSON:
    - `{"action":"complete","summary":"...","comment":"optional"}`
    - or `{"action":"comment","summary":"...","comment":"..."}`
  - local adapter example: `python -m features.agents.command_adapter`

## Metrics and Debug
- `GET /api/metrics`
  - `commands_total`
  - `commands_retried`
  - `command_conflicts`
  - `sse_connections`
  - `notifications_emitted`
- `GET /api/events/{aggregate_type}/{aggregate_id}` for event inspection

## Local Run
```bash
./scripts/deploy.sh
```

`./scripts/deploy.sh` auto-increments app version (`VERSION` + frontend `package.json`), writes deploy metadata to `.deploy.env`, then rebuilds and restarts Docker Compose services.

App URLs:
- Backend/API: `http://localhost:8080`
- Health: `http://localhost:8080/api/health`

## Testing
```bash
docker compose run --rm --build task-app pytest tests/test_api.py
```

## Important Headers
- `X-User-Id`: selects active user
- `X-Command-Id`: idempotency key for command endpoints

## Current Default Seed
- Single default user: `m4tr1x`
- Default workspace/project/task IDs are in `app/shared/settings.py`
