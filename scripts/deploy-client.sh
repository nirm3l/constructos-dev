#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export DEPLOY_LABEL="client"
export DEPLOY_BASE_COMPOSE_FILE="docker-compose.client.yml"
exec ./scripts/deploy-core.sh "$@"
