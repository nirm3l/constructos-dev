# 05 Operations Runbook

## 1. Runtime Components
The default Docker Compose stack includes:
- `task-app` (FastAPI + automation runner)
- `mcp-tools` (FastMCP server)
- `postgres`
- `kurrentdb`
- `neo4j`

Owner/internal stack also includes:
- `license-control-plane` (local licensing server)

## 2. Standard Operating Flow
### 2.1 Deploy
```bash
./scripts/deploy.sh
```
Effects:
- bumps patch version (`VERSION` + frontend package version) for `DEPLOY_SOURCE=local`,
- generates `.deploy.env` (`APP_VERSION`, `APP_BUILD`, `APP_DEPLOYED_AT_UTC`),
- resolves `DEPLOY_TARGET` (`auto|base|ubuntu-gpu|macos-m4`),
- resolves `DEPLOY_SOURCE` (`local|ghcr`),
- runs `docker compose ... up -d --build` with target-specific override files.

### 2.2 Deploy Targets
- `auto` resolves to `macos-m4` on `Darwin`.
- `auto` resolves to `ubuntu-gpu` on `Linux` when `/dev/dri` exists.
- `auto` resolves to `base` on all other cases.
- `ubuntu-gpu`: enables Linux GPU-backed Ollama container config from `docker-compose.owner.ubuntu-gpu.yml`.
- `macos-m4`: disables in-stack Ollama and points services to host-native Ollama (`host.docker.internal`), and forces `kurrentdb` on `linux/amd64`.
- `base`: platform-neutral stack without GPU-specific overrides.

### 2.3 Full Reset
```bash
./scripts/recreate_from_zero.sh
```
Does:
- uses the same resolved compose files as deploy target for `down` and `ps`,
- clears local DB/upload paths,
- performs fresh deploy + health/version checks.

### 2.4 Private Image Release (GHCR)
- Workflow file: `.github/workflows/release-images.yml`.
- Trigger: push tag matching `v*` (for example `v1.3.0`) or manual dispatch.
- Output image: `ghcr.io/<owner>/constructos-task-app:<tag>`.
- Output image: `ghcr.io/<owner>/constructos-mcp-tools:<tag>`.
- Platforms: `linux/amd64` and `linux/arm64`.

### 2.5 Pull-Based Deployment From GHCR
Use this when clients should only pull private images and not build from source.
```bash
DEPLOY_SOURCE=ghcr IMAGE_TAG=v0.1.227 ./scripts/deploy.sh
```
Required env for private pulls:
- `GHCR_OWNER` (default: `nirm3l`)
- `GHCR_IMAGE_PREFIX` (default: `constructos`)
- `IMAGE_TAG` (required when `DEPLOY_SOURCE=ghcr`)

### 2.6 Client Distribution Repository
Client deployment artifacts are maintained in:
`https://github.com/nirm3l/constructos`

### 2.7 Client Remote Installer (`curl | bash`)
```bash
curl -fsSL https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh | IMAGE_TAG=v0.1.230 bash
```

### 2.8 Local Licensing Control Plane
Included by default in owner/internal deploy (`./scripts/deploy.sh`).
Default local URL used by app services in this mode:
- `http://license-control-plane:8092`
Local admin UI:
- `http://localhost:8092`
Optional hardening for signed entitlement tokens:
- `LCP_SIGNING_PRIVATE_KEY_PEM` (Ed25519 private key in PEM form)
- `LCP_SIGNING_KEY_ID` (token key identifier)
- `LCP_REQUIRE_SIGNED_TOKENS=true`
External billing sync:
- Update subscription state through `PUT /v1/admin/installations/{installation_id}/subscription` from your billing application.
Activation code flow (multi-device seat control):
- Issue customer deployment token via `POST /v1/admin/client-tokens` and set that value as `LICENSE_SERVER_TOKEN` for the customer deployment.
- Issue activation code via `POST /v1/admin/activation-codes` (`customer_ref`, `max_installations`, `valid_until`).
- Customer enters activation code in app (`POST /api/license/activate` -> control-plane `POST /v1/installations/activate`).
- Control-plane binds installation to `customer_ref` and enforces seat limit (default `3`).

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

### 3.7 Licensing
- License server endpoint is fixed in application runtime and is not customer-configurable.
- Required client-side variables:
  - `LICENSE_SERVER_TOKEN`
- Optional advanced variables:
  - `LICENSE_PUBLIC_KEY` (require signed entitlement tokens from control-plane)
  - `LICENSE_INSTALLATION_ID` (manual override; otherwise app auto-generates stable `inst-<uuid>`)
  - `LICENSE_HEARTBEAT_SECONDS` (default `900`)
  - `LICENSE_GRACE_HOURS` (default `72`)
  - `LICENSE_TRIAL_DAYS` (default `7`)
- Write endpoints (`POST|PUT|PATCH|DELETE`) are blocked with `HTTP 402` when enforcement is enabled and license state is `expired` or `unlicensed`.
- If `LICENSE_PUBLIC_KEY` is configured, app accepts only valid signed `entitlement_token` payloads from control-plane.
- `POST /api/license/activate` is write-exempt from license lock so expired installations can re-activate.

### 3.8 Control-Plane Licensing
- `LCP_API_TOKEN`
- `LCP_TRIAL_DAYS`
- `LCP_TOKEN_TTL_SECONDS`
- `LCP_DEFAULT_MAX_INSTALLATIONS` (default seat limit used when creating activation codes)
- `LCP_SIGNING_PRIVATE_KEY_PEM`
- `LCP_SIGNING_KEY_ID`
- `LCP_REQUIRE_SIGNED_TOKENS`
- Admin endpoints require `LCP_API_TOKEN`.
- Installation endpoints (`/v1/installations/*`) accept either:
  - admin token, or
  - active customer-specific client token issued from `/v1/admin/client-tokens`.

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
- `GET /api/license/status`
- `GET /api/metrics`
- `GET /api/events/{aggregate_type}/{aggregate_id}`
- KurrentDB UI: `http://localhost:2113/web/index.html`
- KurrentDB all-events feed: `http://localhost:2113/streams/%24all/head/backward/50?embed=body`
- Optional control-plane admin UI: `GET http://localhost:8092/`
- Optional control-plane local health: `GET http://localhost:8092/api/health`

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
