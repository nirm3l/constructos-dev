#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_VERSION="$(python3 scripts/bump_version.py)"
DEPLOYED_AT_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
APP_BUILD="$(date -u +"%Y%m%d%H%M%S")-${GIT_SHA}"
DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"

resolve_deploy_target() {
  if [[ "$DEPLOY_TARGET" != "auto" ]]; then
    echo "$DEPLOY_TARGET"
    return
  fi

  local host_os
  host_os="$(uname -s)"
  case "$host_os" in
    Darwin)
      echo "macos-m4"
      ;;
    Linux)
      if [[ -e /dev/dri ]]; then
        echo "ubuntu-gpu"
      else
        echo "base"
      fi
      ;;
    *)
      echo "base"
      ;;
  esac
}

TARGET_RESOLVED="$(resolve_deploy_target)"
COMPOSE_ARGS=(-f docker-compose.yml)

case "$TARGET_RESOLVED" in
  base)
    ;;
  ubuntu-gpu)
    COMPOSE_ARGS+=(-f docker-compose.ubuntu-gpu.yml)
    ;;
  macos-m4)
    COMPOSE_ARGS+=(-f docker-compose.macos-m4.yml)
    ;;
  *)
    echo "Unsupported DEPLOY_TARGET: $TARGET_RESOLVED"
    echo "Supported values: auto, base, ubuntu-gpu, macos-m4"
    exit 1
    ;;
esac

cat > .deploy.env <<EOF
APP_VERSION=${APP_VERSION}
APP_BUILD=${APP_BUILD}
APP_DEPLOYED_AT_UTC=${DEPLOYED_AT_UTC}
EOF

echo "Deploying version ${APP_VERSION} (${APP_BUILD}) at ${DEPLOYED_AT_UTC}"
echo "Resolved deploy target: ${TARGET_RESOLVED}"
echo "Compose files: ${COMPOSE_ARGS[*]}"
docker compose "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --build
