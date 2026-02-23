# 12 macOS M4, Licensing, and Private Distribution Plan

## Scope
This plan defines the changes needed to:
- run the platform on both Ubuntu and macOS M4,
- introduce licensing (7-day free trial + monthly subscription),
- harden Python code delivery in Docker images,
- publish source and private images through private GitHub/GHCR.

## Implementation Status (Current Snapshot)
- Phase 1 completed: base + Ubuntu GPU + macOS M4 compose split is implemented.
- Phase 2 completed: GHCR release workflow exists and deploy scripts support GHCR pull-only deployment mode for clients.
- Phase 3 completed (baseline): runtime image now runs as non-root and compose drops capabilities with `no-new-privileges`.
- Phase 4 in progress: license models, bootstrap seed, status API, health summary, write-lock middleware, control-plane sync worker, and signed entitlement token verification are implemented.
- Phase 6 in progress: frontend now fetches `/api/license/status` and shows trial/grace/expired notice states.

## Constraints and Facts
- Current `docker-compose.yml` contains Linux-specific Ollama GPU settings (`/dev/dri`, `group_add`), which are not portable to macOS.
- Docker Desktop GPU support is currently available only on Windows with WSL2 backend, not on macOS containers.
- Ollama Docker GPU docs are Linux-focused (`--gpus=all` for NVIDIA, AMD ROCm variants). For macOS, Ollama supports Apple M-series natively outside containers.
- Current `eventstore/eventstore:24.10.0-jammy` image is effectively `linux/amd64` only (verified via local `docker pull --platform linux/arm64` warning).

## Target Runtime Matrix
### Ubuntu (primary production)
- Keep Docker Compose stack.
- Keep containerized Ollama with Linux GPU path.
- Run all services native `linux/amd64`.

### macOS M4 (local/dev/sales demo and optionally client-hosted)
- Run app stack in Docker Desktop (`linux/arm64` where supported).
- Run Ollama natively on macOS host, not GPU-through-container.
- Point app services to host Ollama via `http://host.docker.internal:11434`.
- Run KurrentDB as `linux/amd64` emulated service (or provide a non-Kurrent local mode if emulation performance is unacceptable).

## Phase 1: Compose Refactor for Cross-Platform
### Goal
Keep one shared Compose baseline and platform-specific overrides.

### Changes
- Refactor `docker-compose.yml` into a platform-neutral base by removing Linux-only Ollama device/group settings and keeping `OLLAMA_BASE_URL` externally configurable.
- Add `docker-compose.ubuntu-gpu.yml` that defines containerized Ollama with Linux GPU config and sets `OLLAMA_BASE_URL=http://ollama:11434`.
- Add `docker-compose.macos-m4.yml` that sets `OLLAMA_BASE_URL=http://host.docker.internal:11434` and forces `kurrentdb.platform=linux/amd64`.

### Run Commands
- Ubuntu:
```bash
docker compose -f docker-compose.yml -f docker-compose.ubuntu-gpu.yml up -d --build
```
- macOS M4:
```bash
docker compose -f docker-compose.yml -f docker-compose.macos-m4.yml up -d --build
```

## Phase 2: Multi-Arch Build and Private Image Distribution
### Goal
Publish private, versioned images usable on amd64 and arm64 where possible.

### Changes
- Add GitHub Actions workflow `.github/workflows/release-images.yml` with tag-based release trigger, Buildx setup, GHCR login, and push for `linux/amd64,linux/arm64` for `task-app` and `mcp-tools`.
- Use tag strategy `vX.Y.Z` plus immutable `sha-<gitsha>`.
- Generate SBOM/provenance artifacts if possible.
- Keep repository private and package visibility private in GHCR.
- Add deploy docs for image pulls with least-privilege credentials.

### Suggested Image Naming
- `ghcr.io/nirm3l/constructos-task-app:<tag>`
- `ghcr.io/nirm3l/constructos-mcp-tools:<tag>`

## Phase 3: Dockerfile Hardening and Python Code Protection
### Reality Check
If the client controls the host and runtime, code extraction/tampering risk can be reduced but not eliminated.

### Baseline Hardening (recommended for all releases)
- Convert `app/Dockerfile` to strict multi-stage build.
- Run as non-root user.
- Set filesystem to read-only at runtime where feasible.
- Drop Linux capabilities and set `no-new-privileges`.
- Pin base images by digest for reproducibility.
- Remove unnecessary build tools from runtime image.

### Code Protection Layers (pragmatic)
- Compile all Python modules to bytecode in build stage and avoid shipping editable source where possible.
- Move the most sensitive licensing checks to compiled modules first (Cython/Nuitka path).
- Keep license decision authority server-side (control plane), not only in local container code.
- Sign release images and verify signatures before deployment.

### Deliverables
- Updated `app/Dockerfile`.
- Optional `app/Dockerfile.protected` variant if compiled distribution introduces compatibility overhead.

## Phase 4: Licensing Architecture (7-Day Trial + Monthly Subscription)
### Goal
Enforce entitlement with central validation and graceful but strict degradation.

### Design
- Add new vertical slice `app/features/licensing/` (`domain.py`, `application.py`, `api.py`, `read_models.py`).
- Add license data model `LicenseInstallation` in `app/shared/models.py`.
- Add license data model `LicenseEntitlement` in `app/shared/models.py`.
- Add license data model `LicenseValidationLog` in `app/shared/models.py`.
- Add bootstrap schema guards in `app/shared/bootstrap.py`.
- Use a fixed internal license server endpoint in `app/shared/settings.py` (not customer-configurable at runtime).
- Add config `LICENSE_PUBLIC_KEY` in `app/shared/settings.py`.
- Add config `LICENSE_HEARTBEAT_SECONDS` in `app/shared/settings.py`.
- Add config `LICENSE_GRACE_HOURS` in `app/shared/settings.py`.
- Add dependency/middleware gate in `app/shared/deps.py` to allow read-only endpoints when expired.
- Add dependency/middleware gate in `app/shared/deps.py` to block write/mutation endpoints after grace period.

### Runtime Flow
1. First startup registers installation fingerprint with license server.
2. Server creates 7-day trial entitlement.
3. App receives signed entitlement token (short TTL).
4. App revalidates periodically.
5. After trial expires without active subscription, app enters a short grace mode.
6. After grace mode, write operations are blocked (or full lock is applied based on policy).

### Security Controls
- Signed tokens (asymmetric keys).
- Server time as source of truth, not client clock.
- Installation binding (installation ID + customer account).
- Audit log for each license decision.
- App verifies `entitlement_token` using `LICENSE_PUBLIC_KEY` when configured.

## Phase 5: Billing Integration (External App)
### Recommendation
Keep billing outside this repository and treat this application as licensing enforcement only.

### Minimal External Billing Setup
- One product: `m4tr1x Self-Hosted`.
- One recurring monthly price.
- 7-day trial configured in entitlement policy at control-plane level.
- Hosted payment page for subscription start.
- Merchant self-service flow for card updates/cancel/reactivate.
- External billing application updates installation-to-customer mapping.
- External billing application updates subscription lifecycle and renewal state.
- Failed recurring charge events in billing system start dunning/grace logic, then billing app updates control-plane.
- Integration endpoint in this app: `PUT /v1/admin/installations/{installation_id}/subscription` with control-plane token.

### Entitlement Mapping
- Active/trialing subscription => active entitlement.
- Past due/canceled => grace then lock policy.
- All entitlement state transitions stored server-side and pushed to installations on next heartbeat.

## Phase 6: API/UI Integration
### Backend
- Add `/api/license/status` for UI and health diagnostics.
- Include license status in `/api/health` extended payload for operators.

### Frontend
- Show `Trial: X days left` banner state in app shell.
- Show `Active subscription` banner state in app shell.
- Show `Payment issue / read-only mode` banner state in app shell.
- Add admin page link to billing portal.

## Phase 7: Rollout Plan
### Step 1
Cross-platform compose refactor and macOS M4 smoke tests.

### Step 2
GHCR private image publishing workflow with multi-arch outputs.

### Step 3
License control-plane service + app-side enforcement in read-only mode first.

### Step 4
External billing app integration and entitlement updates via control-plane admin API.

### Step 5
Enable strict write-lock after grace period and complete operational runbook.

## Implementation Checklist (Repository-Level)
- `docker-compose.yml`
- `docker-compose.ubuntu-gpu.yml` (new)
- `docker-compose.macos-m4.yml` (new)
- `docker-compose.license-control-plane.yml` (new)
- `app/Dockerfile`
- `.github/workflows/release-images.yml` (new)
- `app/shared/settings.py`
- `app/shared/models.py`
- `app/shared/bootstrap.py`
- `app/shared/deps.py`
- `app/main.py` (router include)
- `app/features/licensing/*` (new)
- `license_control_plane/*` (new)
- `app/frontend/src/*` (license status UI)
- `docs/05-operations-runbook.md` (deployment/licensing ops update)

## Acceptance Criteria
- Ubuntu deployment works with containerized Ollama GPU profile.
- macOS M4 deployment works with host-native Ollama and no Linux GPU flags.
- Licensing supports a 7-day trial from first activation.
- Licensing supports monthly paid entitlement.
- Licensing enforces write lock after grace expiration.
- Private GHCR images are pulled only with valid credentials.
- App image runtime is non-root and hardened.

## Risks and Mitigations
- Risk: KurrentDB amd64 emulation on M4 performance.
- Mitigation: provide optional non-Kurrent local mode or run KurrentDB on remote amd64 host.
- Risk: Determined customer reverse engineers local container.
- Mitigation: server-authoritative entitlement, short-lived tokens, compiled sensitive modules, image signing.
- Risk: External billing sync outages desynchronize entitlements.
- Mitigation: idempotent admin update calls + periodic reconciliation job from billing app.

## Suggested Order of Execution
1. Cross-platform compose split and M4 smoke test.
2. GHCR private image pipeline.
3. Dockerfile hardening.
4. Licensing backend slice.
5. External billing app integration.
6. UI status and operator runbook.

## References (verified 2026-02-21)
- Docker Desktop GPU support: https://docs.docker.com/desktop/features/gpu/
- Docker Desktop networking (`host.docker.internal`): https://docs.docker.com/desktop/features/networking/
- Docker multi-platform builds: https://docs.docker.com/build/building/multi-platform/
- Ollama Docker usage: https://docs.ollama.com/docker
- Ollama macOS install (Apple M series): https://docs.ollama.com/installation/mac
- GitHub Container Registry docs: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- GitHub Actions publishing Docker images: https://docs.github.com/en/actions/use-cases-and-examples/publishing-packages/publishing-docker-images
