# 05 Operations Runbook

## 1. Runtime Komponente
Docker compose stack pokrece:
- `task-app` (FastAPI + runner)
- `mcp-tools` (FastMCP server)
- `postgres`
- `kurrentdb`
- `neo4j`

## 2. Standardni Operativni Tok
### 2.1 Deploy
```bash
./scripts/deploy.sh
```
Efekat:
- bump patch verzije (`VERSION` + frontend package version),
- generisanje `.deploy.env` (`APP_VERSION`, `APP_BUILD`, `APP_DEPLOYED_AT_UTC`),
- `docker compose up -d --build`.

### 2.2 Full Reset
```bash
./scripts/recreate_from_zero.sh
```
Radi:
- `docker compose down -v`,
- ciscenje lokalnih db/upload path-ova,
- fresh deploy + health/version check.

## 3. Kriticne Env Varijable

### 3.1 Core
- `DATABASE_URL`
- `EVENTSTORE_URI`
- `APP_VERSION`, `APP_BUILD`, `APP_DEPLOYED_AT_UTC`

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
- `GRAPH_PROJECTION_POLL_INTERVAL_SECONDS`
- `GRAPH_CONTEXT_MAX_HOPS`, `GRAPH_CONTEXT_MAX_TOKENS`

### 3.5 Email Tool
- `MCP_EMAIL_SMTP_*`
- `MCP_EMAIL_FROM`
- `MCP_EMAIL_ALLOWED_RECIPIENTS`
- `MCP_EMAIL_ALLOWED_DOMAINS`

## 4. Bootstrap i Migration Behavior
`startup_bootstrap()` radi:
- schema/table create/update,
- default user/workspace/project/task seed,
- sistemskog agent user-a,
- backfill event stream-a iz read modela ako je event store resetovan,
- rebuild project tag index-a,
- backfill project member-a za postojeci projekat.

## 5. Observability

### 5.1 Endpoints
- `GET /api/health`
- `GET /api/version`
- `GET /api/metrics`
- `GET /api/events/{aggregate_type}/{aggregate_id}`

### 5.2 Runtime Metrics
`/api/metrics` trenutno iznosi:
- `commands_total`, `commands_retried`, `command_conflicts`
- `sse_connections`, `notifications_emitted`
- `graph_projection_events_processed`, `graph_projection_failures`, `graph_projection_lag_commits`
- `graph_context_requests`, `graph_context_failures`

## 6. Test Strategija
Postojece test pokrice (unit + API integration):
- ukupno: `87` test funkcija (`app/tests/*`).
- fokus:
  - task/project/note/spec lifecycle,
  - idempotency i concurrency,
  - graph endpoint-i i context pack,
  - agent runner i MCP security pravila,
  - scheduled/recurring automation tokovi.

Pokretanje:
```bash
docker compose run --rm --build task-app pytest
```

## 7. Troubleshooting
| Problem | Simptom | Brza provera | Akcija |
|---|---|---|---|
| Graph endpoint vraca 503 | `/knowledge-graph/*` error | proveri `KNOWLEDGE_GRAPH_ENABLED`, neo4j health, creds | restart neo4j + proveri env |
| Mutacije dupliraju side-effect | isti zahtev vise puta menja stanje | proveri da li je `X-Command-Id` stabilan | uvedi/reuse command_id |
| Runner ne obradjuje queued taskove | automation ostaje `queued` | proveri `AGENT_RUNNER_ENABLED`, runner logs | proveri `AGENT_CODEX_COMMAND`, timeout |
| SSE ne isporucuje evente | UI notifikacije stale | proveri `/api/notifications/stream` i mrezu | proveri reverse proxy idle timeout |
| Attachment download 404 | upload uspeo ali nema fajla | proveri `ATTACHMENTS_DIR` i path scope | proveri volume mount i workspace path |

## 8. Hardening Checklist (Pre-Prod)
1. Ukloniti default tokene i staticke credential-e iz compose-a.
2. Zakljucati CORS origin-e (`CORS_ORIGINS`).
3. Ograniciti MCP workspace/project allowlist.
4. Uvesti secret manager za SMTP/Neo4j/EventStore kredencijale.
5. Dodati centralizovan log shipping i alerting na `graph_projection_failures` + runner failure rate.
