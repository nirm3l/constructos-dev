#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOYED_AT_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
DEPLOY_SOURCE="${DEPLOY_SOURCE:-local}"
APP_COMPOSE_PROJECT_NAME="${APP_COMPOSE_PROJECT_NAME:-constructos-app}"
GHCR_OWNER="${GHCR_OWNER:-nirm3l}"
GHCR_IMAGE_PREFIX="${GHCR_IMAGE_PREFIX:-${GHCR_REPO:-constructos}}"
IMAGE_TAG="${IMAGE_TAG:-}"
TASK_APP_IMAGE="${TASK_APP_IMAGE:-}"
MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-}"
CODEX_AUTH_FILE="${CODEX_AUTH_FILE:-/home/m4tr1x/.codex/auth.json}"

resolve_compose_env_value() {
  local var_name="$1"
  local current_value="${!var_name:-}"
  if [[ -n "$current_value" ]]; then
    printf '%s' "$current_value"
    return 0
  fi
  if [[ ! -f .env ]]; then
    return 1
  fi

  local line
  line="$(grep -E "^[[:space:]]*${var_name}=" .env | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi

  line="${line#*=}"
  line="${line%$'\r'}"
  printf '%s' "$line"
}

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
    COMPOSE_ARGS+=(-f docker-compose.owner.ubuntu-gpu.yml)
    ;;
  macos-m4)
    COMPOSE_ARGS+=(-f docker-compose.owner.macos-m4.yml)
    ;;
  *)
    echo "Unsupported DEPLOY_TARGET: $TARGET_RESOLVED"
    echo "Supported values: auto, base, ubuntu-gpu, macos-m4"
    exit 1
    ;;
esac

case "$DEPLOY_SOURCE" in
  local)
    APP_VERSION="$(python3 scripts/bump_version.py)"
    APP_BUILD="$(date -u +"%Y%m%d%H%M%S")-${GIT_SHA}"
    TASK_APP_IMAGE="${TASK_APP_IMAGE:-task-management-task-app:local}"
    MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-task-management-mcp-tools:local}"
    ;;
  ghcr)
    if [[ -z "$IMAGE_TAG" ]]; then
      echo "IMAGE_TAG is required when DEPLOY_SOURCE=ghcr"
      echo "Example: DEPLOY_SOURCE=ghcr IMAGE_TAG=v0.1.227 ./scripts/deploy.sh"
      exit 1
    fi
    APP_VERSION="$IMAGE_TAG"
    APP_BUILD="ghcr-${IMAGE_TAG}-${GIT_SHA}"
    TASK_APP_IMAGE="${TASK_APP_IMAGE:-ghcr.io/${GHCR_OWNER}/${GHCR_IMAGE_PREFIX}-task-app:${IMAGE_TAG}}"
    MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-ghcr.io/${GHCR_OWNER}/${GHCR_IMAGE_PREFIX}-mcp-tools:${IMAGE_TAG}}"
    ;;
  *)
    echo "Unsupported DEPLOY_SOURCE: $DEPLOY_SOURCE"
    echo "Supported values: local, ghcr"
    exit 1
    ;;
esac

DEPLOY_SERVICES=(task-app mcp-tools)
if [[ "$TARGET_RESOLVED" != "macos-m4" ]]; then
  DEPLOY_SERVICES+=(ollama)
fi
LICENSE_SERVER_TOKEN_VALUE="$(resolve_compose_env_value "LICENSE_SERVER_TOKEN" || true)"

cat > .deploy.env <<EOF
APP_VERSION=${APP_VERSION}
APP_BUILD=${APP_BUILD}
APP_DEPLOYED_AT_UTC=${DEPLOYED_AT_UTC}
TASK_APP_IMAGE=${TASK_APP_IMAGE}
MCP_TOOLS_IMAGE=${MCP_TOOLS_IMAGE}
EOF

if [[ -n "$LICENSE_SERVER_TOKEN_VALUE" ]]; then
  printf 'LICENSE_SERVER_TOKEN=%s\n' "$LICENSE_SERVER_TOKEN_VALUE" >> .deploy.env
fi

if [[ -f "$CODEX_AUTH_FILE" ]]; then
  if ! chmod a+r "$CODEX_AUTH_FILE" 2>/dev/null; then
    echo "Warning: unable to adjust read permissions for $CODEX_AUTH_FILE"
    echo "Codex chat in task-app may fail if the mounted auth file is not readable by container user."
  fi
fi

echo "Deploy profile: internal"
echo "Deploying version ${APP_VERSION} (${APP_BUILD}) at ${DEPLOYED_AT_UTC}"
echo "Resolved deploy target: ${TARGET_RESOLVED}"
echo "Deploy source: ${DEPLOY_SOURCE}"
echo "task-app image: ${TASK_APP_IMAGE}"
echo "mcp-tools image: ${MCP_TOOLS_IMAGE}"
echo "Compose project: ${APP_COMPOSE_PROJECT_NAME}"
echo "Compose files: ${COMPOSE_ARGS[*]}"
echo "Deploy services: ${DEPLOY_SERVICES[*]}"

if [[ "$DEPLOY_SOURCE" == "ghcr" ]]; then
  echo "Pulling images..."
  docker compose -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env pull "${DEPLOY_SERVICES[@]}"
  docker compose -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --no-build "${DEPLOY_SERVICES[@]}"
else
  docker compose -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --build "${DEPLOY_SERVICES[@]}"
fi
