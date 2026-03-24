# Install, Uninstall, and COS CLI

This guide explains how to deploy ConstructOS locally, remove a deployment cleanly, and use `cos` for common operational workflows.

## Prerequisites

- Docker Engine with Docker Compose support (`docker compose` preferred).
- `bash`, `python3`, and Git available on the host.
- Access to the repository checkout that contains `scripts/deploy.sh` and `scripts/recreate_from_zero.sh`.

## Local Deploy

Use local source images and build directly from the repository:

```bash
./scripts/deploy.sh
```

Useful environment variables:

- `DEPLOY_SOURCE=local` (default): builds images from local source.
- `DEPLOY_TARGET=auto|base|ubuntu-gpu|macos-m4`: chooses compose overlay.
- `APP_COMPOSE_PROJECT_NAME=constructos-app`: fixed project scope for app stack.

The deploy script writes `.deploy.env` and starts the app stack through Compose.

## Deploy From Public Images

Use prebuilt GHCR images for client deployments:

```bash
DEPLOY_SOURCE=ghcr IMAGE_TAG=vX.Y.Z ./scripts/deploy.sh
```

In this mode, app containers pull tagged public images instead of building locally.

## Full Reset (Recreate From Zero)

To reset local app data and redeploy fresh:

```bash
./scripts/recreate_from_zero.sh
```

This script:

1. Stops the app stack (`constructos-app`).
2. Removes app data volumes (preserving Codex home/auth volume).
3. Cleans local DB and workspace artifacts.
4. Runs a fresh `deploy.sh`.

## Uninstall / Stop

Stop app services without touching protected control-plane services:

```bash
docker compose -p constructos-app -f docker-compose.yml down
```

If you need target-specific overlays, include the same `-f` files used at deploy time.

## COS CLI Basics

The `cos` CLI is used for operations, diagnostics, and structured automation workflows.

Typical commands:

```bash
cos --help
cos doctor
cos tasks list
```

Use `cos doctor` to validate runtime wiring, plugin setup, and delivery expectations before handing work to agents.

## Troubleshooting

- Verify API health:

```bash
curl -sS http://localhost:1102/api/health
```

- Inspect running services:

```bash
docker compose -p constructos-app -f docker-compose.yml ps
```

- If authentication files are missing, deploy scripts fall back to placeholders. Configure real credentials in mounted auth files for full agent functionality.
