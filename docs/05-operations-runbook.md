# 05 Operations Runbook

## 1. Runtime Components
The default Docker Compose stack includes:
- `task-app` (FastAPI + automation runner)
- `mcp-tools` (FastMCP server)
- `postgres`
- `kurrentdb`
- `neo4j`

## 2. Standard Operating Flow
### 2.1 Deploy
```bash
./scripts/deploy.sh
```
Effects:
- bumps patch version (`VERSION` + frontend package version),
- generates `.deploy.env` (`APP_VERSION`, `APP_BUILD`, `APP_DEPLOYED_AT_UTC`),
- runs `docker compose up -d --build`.

### 2.2 Full Reset
```bash
./scripts/recreate_from_zero.sh
```
Does:
- `docker compose down -v`,
- clears local DB/upload paths,
- performs fresh deploy + health/version checks.

## 3. Critical Environment Variables

### 3.1 Core
- `DATABASE_URL`
- `EVENTSTORE_URI`
- `APP_VERSION`, `APP_BUILD`, `APP_DEPLOYED_AT_UTC`
- `SYSTEM_NOTIFICATIONS_INTERVAL_SECONDS`

### 3.2 Automation
- `AGENT_RUNNER_ENABLED`
- `AGENT_RUNNER_INTERVAL_SECONDS`
- `AGENT_EXECUTOR_MODE` (`placeholder|command`)
- `AGENT_CODEX_COMMAND`
- `AGENT_EXECUTOR_TIMEOUT_SECONDS`

### 3.3 MCP Security
- `MCP_AUTH_TOKEN`
- `MCP_TOOL_AUTH_TOKEN`
- `MCP_ACTOR_USER_ID`
- `MCP_DEFAULT_WORKSPACE_ID`
- `MCP_ALLOWED_WORKSPACE_IDS`
- `MCP_ALLOWED_PROJECT_IDS`

### 3.4 Knowledge Graph
- `KNOWLEDGE_GRAPH_ENABLED`
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `GRAPH_PROJECTION_BATCH_SIZE`
- `GRAPH_CONTEXT_MAX_HOPS`, `GRAPH_CONTEXT_MAX_TOKENS`

### 3.5 Persistent Subscriptions
- `PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP`
- `PERSISTENT_SUBSCRIPTION_GRAPH_GROUP`
- `PERSISTENT_SUBSCRIPTION_VECTOR_GROUP`
- `PERSISTENT_SUBSCRIPTION_EVENT_BUFFER_SIZE`
- `PERSISTENT_SUBSCRIPTION_MAX_ACK_BATCH_SIZE`
- `PERSISTENT_SUBSCRIPTION_MAX_ACK_DELAY_SECONDS`
- `PERSISTENT_SUBSCRIPTION_STOPPING_GRACE_SECONDS`
- `PERSISTENT_SUBSCRIPTION_RETRY_BACKOFF_SECONDS`

### 3.6 Email Tool
- `MCP_EMAIL_SMTP_*`
- `MCP_EMAIL_FROM`
- `MCP_EMAIL_ALLOWED_RECIPIENTS`
- `MCP_EMAIL_ALLOWED_DOMAINS`

## 4. Bootstrap and Migration Behavior
`startup_bootstrap()` performs:
- schema/table create/update,
- default user/workspace/project/task seed,
- system agent user setup,
- event stream backfill from read models if event store was reset,
- project tag index rebuild,
- project member backfill for existing projects.

## 5. Observability

### 5.1 Endpoints
- `GET /api/health`
- `GET /api/version`
- `GET /api/metrics`
- `GET /api/events/{aggregate_type}/{aggregate_id}`
- KurrentDB UI: `http://localhost:2113/web/index.html`
- KurrentDB all-events feed: `http://localhost:2113/streams/%24all/head/backward/50?embed=body`

### 5.2 Runtime Metrics
`/api/metrics` currently exposes:
- `commands_total`, `commands_retried`, `command_conflicts`
- `sse_connections`, `notifications_emitted`
- `graph_projection_events_processed`, `graph_projection_failures`, `graph_projection_lag_commits`
- `graph_context_requests`, `graph_context_failures`

## 6. Test Strategy
Current test coverage (unit + API integration):
- total: `87` test functions (`app/tests/*`).
- focus areas:
  - task/project/note/spec lifecycle,
  - idempotency and concurrency,
  - graph endpoints and context pack,
  - runner behavior and MCP security checks,
  - scheduled/recurring automation flows.

Run tests:
```bash
docker compose run --rm --build task-app pytest
```

## 7. Troubleshooting
| Problem | Symptom | Quick check | Action |
|---|---|---|---|
| Graph endpoints return 503 | `/knowledge-graph/*` errors | verify `KNOWLEDGE_GRAPH_ENABLED`, Neo4j health, credentials | restart Neo4j + verify env |
| Duplicate side effects on retries | same request mutates state multiple times | verify stable `X-Command-Id` reuse | enforce command_id reuse |
| Runner does not process queued tasks | automation stays `queued` | verify `AGENT_RUNNER_ENABLED`, runner logs | verify `AGENT_CODEX_COMMAND`, timeout |
| SSE does not deliver updates | stale notifications/activity in UI | check `/api/notifications/stream` connectivity | verify proxy idle timeout |
| Projection consumer is stuck | lagging read models/graph/vector | inspect persistent subscription group info and parked count | nack policy review, fix handler error, replay parked messages |
| Attachment download returns 404 | upload succeeded but file not found | verify `ATTACHMENTS_DIR` and scoped path | verify volume mounts and workspace path |

## 8. Pre-Production Hardening Checklist
1. Remove default tokens and static credentials from compose/env.
2. Restrict CORS origins (`CORS_ORIGINS`).
3. Tighten MCP workspace/project allowlists.
4. Use secret manager for SMTP/Neo4j/EventStore credentials.
5. Add centralized logging and alerting on `graph_projection_failures` and runner failure rates.
