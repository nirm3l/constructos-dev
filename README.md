# Task Management (CQRS + Event Sourcing + KurrentDB)

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

## Project Layout
- `app/main.py`: app bootstrap and router wiring
- `app/features/*`: vertical slices by bounded area
- `app/shared/*`: cross-cutting infrastructure (eventing, deps, serializers, bootstrap)
- `app/frontend/*`: React app
- `docker-compose.yml`: local stack (app + kurrentdb)

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
docker compose up -d --build
```

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
