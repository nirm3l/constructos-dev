#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOYED_AT_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
DEPLOY_LABEL="${DEPLOY_LABEL:-default}"
DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
DEPLOY_SOURCE="${DEPLOY_SOURCE:-local}"
GHCR_OWNER="${GHCR_OWNER:-nirm3l}"
# Prefer GHCR_IMAGE_PREFIX and keep GHCR_REPO as a legacy fallback.
GHCR_IMAGE_PREFIX="${GHCR_IMAGE_PREFIX:-${GHCR_REPO:-constructos}}"
DEPLOY_BASE_COMPOSE_FILE="${DEPLOY_BASE_COMPOSE_FILE:-docker-compose.yml}"
IMAGE_TAG="${IMAGE_TAG:-}"
TASK_APP_IMAGE="${TASK_APP_IMAGE:-}"
MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-}"
CODEX_AUTH_FILE="${CODEX_AUTH_FILE:-/home/m4tr1x/.codex/auth.json}"
DEPLOY_EXTRA_COMPOSE_FILES="${DEPLOY_EXTRA_COMPOSE_FILES:-}"
DEPLOY_EXTRA_UP_SERVICES="${DEPLOY_EXTRA_UP_SERVICES:-}"

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

  # Read plain KEY=VALUE lines from .env without sourcing shell code.
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
if [[ ! -f "$DEPLOY_BASE_COMPOSE_FILE" ]]; then
  echo "Base compose file not found: ${DEPLOY_BASE_COMPOSE_FILE}"
  exit 1
fi
COMPOSE_ARGS=(-f "$DEPLOY_BASE_COMPOSE_FILE")

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

if [[ -n "$DEPLOY_EXTRA_COMPOSE_FILES" ]]; then
  read -r -a EXTRA_COMPOSE_FILES <<< "$DEPLOY_EXTRA_COMPOSE_FILES"
  for compose_file in "${EXTRA_COMPOSE_FILES[@]}"; do
    COMPOSE_ARGS+=(-f "$compose_file")
  done
fi

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
      echo "Example: DEPLOY_SOURCE=ghcr IMAGE_TAG=v0.1.227 ./scripts/deploy-client.sh"
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

BASE_DEPLOY_SERVICES=(task-app mcp-tools)
if [[ "$TARGET_RESOLVED" != "macos-m4" ]]; then
  BASE_DEPLOY_SERVICES+=(ollama)
fi

DEPLOY_SERVICES=("${BASE_DEPLOY_SERVICES[@]}")
if [[ -n "$DEPLOY_EXTRA_UP_SERVICES" ]]; then
  read -r -a EXTRA_UP_SERVICES <<< "$DEPLOY_EXTRA_UP_SERVICES"
  DEPLOY_SERVICES+=("${EXTRA_UP_SERVICES[@]}")
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

echo "Deploy profile: ${DEPLOY_LABEL}"
echo "Deploying version ${APP_VERSION} (${APP_BUILD}) at ${DEPLOYED_AT_UTC}"
echo "Resolved deploy target: ${TARGET_RESOLVED}"
echo "Deploy source: ${DEPLOY_SOURCE}"
echo "task-app image: ${TASK_APP_IMAGE}"
echo "mcp-tools image: ${MCP_TOOLS_IMAGE}"
echo "Base compose file: ${DEPLOY_BASE_COMPOSE_FILE}"
echo "Compose files: ${COMPOSE_ARGS[*]}"
echo "Deploy services: ${DEPLOY_SERVICES[*]}"

if [[ "$DEPLOY_SOURCE" == "ghcr" ]]; then
  echo "Pulling images..."
  docker compose "${COMPOSE_ARGS[@]}" --env-file .deploy.env pull "${BASE_DEPLOY_SERVICES[@]}"
  docker compose "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --no-build "${DEPLOY_SERVICES[@]}"
else
  docker compose "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --build "${DEPLOY_SERVICES[@]}"
fi
