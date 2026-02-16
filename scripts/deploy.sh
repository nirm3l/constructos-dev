#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_VERSION="$(python3 scripts/bump_version.py)"
DEPLOYED_AT_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
APP_BUILD="$(date -u +"%Y%m%d%H%M%S")-${GIT_SHA}"

cat > .deploy.env <<EOF
APP_VERSION=${APP_VERSION}
APP_BUILD=${APP_BUILD}
APP_DEPLOYED_AT_UTC=${DEPLOYED_AT_UTC}
EOF

echo "Deploying version ${APP_VERSION} (${APP_BUILD}) at ${DEPLOYED_AT_UTC}"
docker compose --env-file .deploy.env up -d --build
