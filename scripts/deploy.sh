#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

resolve_compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    printf '%s' "docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    printf '%s' "docker-compose"
    return 0
  fi
  return 1
}

if ! COMPOSE_CMD="$(resolve_compose_cmd)"; then
  echo "Docker Compose is required but unavailable."
  echo "Install Docker Compose plugin ('docker compose') or legacy 'docker-compose' before deploy."
  exit 1
fi

DEPLOYED_AT_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
DEPLOY_STAMP_UTC="$(date -u +"%Y%m%d%H%M%S")"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "nogit")"
DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
DEPLOY_SOURCE="${DEPLOY_SOURCE:-local}"
DEPLOY_SYNC_FRONTEND_PACKAGE_VERSION="${DEPLOY_SYNC_FRONTEND_PACKAGE_VERSION:-false}"
APP_COMPOSE_PROJECT_NAME="${APP_COMPOSE_PROJECT_NAME:-constructos-app}"
GHCR_OWNER="${GHCR_OWNER:-nirm3l}"
GHCR_IMAGE_PREFIX="${GHCR_IMAGE_PREFIX:-${GHCR_REPO:-constructos}}"
IMAGE_TAG="${IMAGE_TAG:-}"
TASK_APP_IMAGE="${TASK_APP_IMAGE:-}"
MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-}"
CODEX_AUTH_FILE="${CODEX_AUTH_FILE:-${HOME}/.codex/auth.json}"
CODEX_CONFIG_FILE="${CODEX_CONFIG_FILE:-${ROOT_DIR}/codex.config.toml}"
CODEX_AUTH_PLACEHOLDER_FILE="${ROOT_DIR}/codex.auth.placeholder.json"
CLAUDE_AUTH_FILE="${CLAUDE_AUTH_FILE:-${HOME}/.claude.json}"
CLAUDE_AUTH_PLACEHOLDER_FILE="${ROOT_DIR}/claude.auth.placeholder.json"
OLLAMA_MODELS_MOUNT="${OLLAMA_MODELS_MOUNT:-}"
AGENT_WORKSPACE_MOUNT="${AGENT_WORKSPACE_MOUNT:-${AGENT_CODEX_WORKSPACE_MOUNT:-}}"
DEPLOY_SERVICES_OVERRIDE="${DEPLOY_SERVICES_OVERRIDE:-}"

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

resolve_first_compose_env_value() {
  local var_name
  local value
  for var_name in "$@"; do
    value="$(resolve_compose_env_value "$var_name" || true)"
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done
  return 1
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

resolve_ollama_models_mount() {
  local configured
  configured="$(resolve_compose_env_value "OLLAMA_MODELS_MOUNT" || true)"
  if [[ -n "$configured" ]]; then
    printf '%s' "$configured"
    return 0
  fi
  if [[ -d "${HOME}/.ollama" ]]; then
    printf '%s' "${HOME}/.ollama"
    return 0
  fi
  printf '%s' "ollama-data"
}

resolve_agent_workspace_mount() {
  local configured
  configured="$(resolve_first_compose_env_value "AGENT_WORKSPACE_MOUNT" "AGENT_CODEX_WORKSPACE_MOUNT" || true)"
  if [[ -n "$configured" ]]; then
    printf '%s' "$configured"
    return 0
  fi
  printf '%s' "${ROOT_DIR}/data/workspace"
}

TARGET_RESOLVED="$(resolve_deploy_target)"
COMPOSE_ARGS=(-f docker-compose.yml)
OLLAMA_MODELS_MOUNT="$(resolve_ollama_models_mount)"
AGENT_WORKSPACE_MOUNT="$(resolve_agent_workspace_mount)"

if [[ "$OLLAMA_MODELS_MOUNT" == "~/"* ]]; then
  OLLAMA_MODELS_MOUNT="${HOME}/${OLLAMA_MODELS_MOUNT#~/}"
fi
if [[ "$AGENT_WORKSPACE_MOUNT" == "~/"* ]]; then
  AGENT_WORKSPACE_MOUNT="${HOME}/${AGENT_WORKSPACE_MOUNT#~/}"
fi

if [[ "$OLLAMA_MODELS_MOUNT" == /* ]]; then
  OLLAMA_MODELS_MOUNT_MODE="host-bind"
else
  OLLAMA_MODELS_MOUNT_MODE="named-volume"
fi

if [[ "$AGENT_WORKSPACE_MOUNT" == /* ]]; then
  AGENT_WORKSPACE_MOUNT_MODE="host-bind"
else
  AGENT_WORKSPACE_MOUNT_MODE="named-volume"
fi

if [[ "$AGENT_WORKSPACE_MOUNT_MODE" == "host-bind" ]]; then
  if [[ -e "$AGENT_WORKSPACE_MOUNT" && ! -w "$AGENT_WORKSPACE_MOUNT" ]]; then
    echo "Configured AGENT_WORKSPACE_MOUNT is not writable: ${AGENT_WORKSPACE_MOUNT}"
    AGENT_WORKSPACE_MOUNT="${ROOT_DIR}/data/workspace"
    AGENT_WORKSPACE_MOUNT_MODE="host-bind"
  fi
fi

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
    BUMP_VERSION_ARGS=()
    if [[ "${DEPLOY_SYNC_FRONTEND_PACKAGE_VERSION,,}" == "true" ]]; then
      BUMP_VERSION_ARGS+=(--update-frontend-package)
    fi
    APP_VERSION="$(python3 scripts/bump_version.py "${BUMP_VERSION_ARGS[@]}")"
    APP_BUILD="$(date -u +"%Y%m%d%H%M%S")-${GIT_SHA}"
    TASK_APP_IMAGE="${TASK_APP_IMAGE:-task-management-task-app:local}"
    MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-task-management-mcp-tools:local}"
    SEED_CONSTRUCTOS_INTERNAL_ENABLED="true"
    COMPOSE_ARGS+=(-f docker-compose.owner.local-docs.yml)
    ;;
  ghcr)
    if [[ -z "$IMAGE_TAG" ]]; then
      echo "IMAGE_TAG is required when DEPLOY_SOURCE=ghcr"
      echo "Example: DEPLOY_SOURCE=ghcr IMAGE_TAG=v0.1.227 ./scripts/deploy.sh"
      exit 1
    fi
    APP_VERSION="$IMAGE_TAG"
    if [[ "${IMAGE_TAG}" == "main" ]]; then
      # Ensure each main-tag redeploy is visible in UI as a unique build marker.
      APP_BUILD="ghcr-${IMAGE_TAG}-${DEPLOY_STAMP_UTC}-${GIT_SHA}"
    else
      APP_BUILD="ghcr-${IMAGE_TAG}-${GIT_SHA}"
    fi
    TASK_APP_IMAGE="${TASK_APP_IMAGE:-ghcr.io/${GHCR_OWNER}/${GHCR_IMAGE_PREFIX}-task-app:${IMAGE_TAG}}"
    MCP_TOOLS_IMAGE="${MCP_TOOLS_IMAGE:-ghcr.io/${GHCR_OWNER}/${GHCR_IMAGE_PREFIX}-mcp-tools:${IMAGE_TAG}}"
    SEED_CONSTRUCTOS_INTERNAL_ENABLED="false"
    ;;
  *)
    echo "Unsupported DEPLOY_SOURCE: $DEPLOY_SOURCE"
    echo "Supported values: local, ghcr"
    exit 1
    ;;
esac

DEPLOY_SERVICES=(task-app mcp-tools docker-socket-proxy)
if [[ "$TARGET_RESOLVED" != "macos-m4" ]]; then
  DEPLOY_SERVICES+=(ollama)
fi
if [[ -n "$DEPLOY_SERVICES_OVERRIDE" ]]; then
  IFS=',' read -r -a DEPLOY_SERVICES <<<"$DEPLOY_SERVICES_OVERRIDE"
fi
LICENSE_SERVER_TOKEN_VALUE="$(resolve_compose_env_value "LICENSE_SERVER_TOKEN" || true)"

cat > .deploy.env <<EOF
APP_VERSION=${APP_VERSION}
APP_BUILD=${APP_BUILD}
APP_DEPLOYED_AT_UTC=${DEPLOYED_AT_UTC}
TASK_APP_IMAGE=${TASK_APP_IMAGE}
MCP_TOOLS_IMAGE=${MCP_TOOLS_IMAGE}
SEED_CONSTRUCTOS_INTERNAL_ENABLED=${SEED_CONSTRUCTOS_INTERNAL_ENABLED}
OLLAMA_MODELS_MOUNT=${OLLAMA_MODELS_MOUNT}
AGENT_WORKSPACE_MOUNT=${AGENT_WORKSPACE_MOUNT}
AGENT_CODEX_WORKSPACE_MOUNT=${AGENT_WORKSPACE_MOUNT}
EOF

if [[ -n "$LICENSE_SERVER_TOKEN_VALUE" ]]; then
  printf 'LICENSE_SERVER_TOKEN=%s\n' "$LICENSE_SERVER_TOKEN_VALUE" >> .deploy.env
fi

declare -a AGENT_RUNTIME_ENV_KEYS=(
  AGENT_DEFAULT_EXECUTION_PROVIDER
  AGENT_CODEX_DEFAULT_MODEL
  AGENT_CODEX_DEFAULT_REASONING_EFFORT
  AGENT_CLAUDE_DEFAULT_MODEL
  AGENT_CLAUDE_DEFAULT_REASONING_EFFORT
  AGENT_OPENCODE_DEFAULT_MODEL
  AGENT_OPENCODE_DEFAULT_REASONING_EFFORT
  AGENT_ENABLED_PLUGINS
)

for env_key in "${AGENT_RUNTIME_ENV_KEYS[@]}"; do
  case "$env_key" in
    AGENT_CODEX_DEFAULT_MODEL)
      env_value="$(resolve_first_compose_env_value "AGENT_CODEX_DEFAULT_MODEL" "AGENT_CODEX_MODEL" || true)"
      ;;
    AGENT_CODEX_DEFAULT_REASONING_EFFORT)
      env_value="$(resolve_first_compose_env_value "AGENT_CODEX_DEFAULT_REASONING_EFFORT" "AGENT_CODEX_REASONING_EFFORT" || true)"
      ;;
    AGENT_CLAUDE_DEFAULT_MODEL)
      env_value="$(resolve_first_compose_env_value "AGENT_CLAUDE_DEFAULT_MODEL" "AGENT_CLAUDE_MODEL" || true)"
      ;;
    AGENT_CLAUDE_DEFAULT_REASONING_EFFORT)
      env_value="$(resolve_first_compose_env_value "AGENT_CLAUDE_DEFAULT_REASONING_EFFORT" "AGENT_CLAUDE_REASONING_EFFORT" || true)"
      ;;
    AGENT_OPENCODE_DEFAULT_MODEL)
      env_value="$(resolve_first_compose_env_value "AGENT_OPENCODE_DEFAULT_MODEL" "AGENT_OPENCODE_MODEL" || true)"
      ;;
    AGENT_OPENCODE_DEFAULT_REASONING_EFFORT)
      env_value="$(resolve_first_compose_env_value "AGENT_OPENCODE_DEFAULT_REASONING_EFFORT" "AGENT_OPENCODE_REASONING_EFFORT" || true)"
      ;;
    *)
      env_value="$(resolve_compose_env_value "$env_key" || true)"
      ;;
  esac
  if [[ -n "${env_value:-}" ]]; then
    printf '%s=%s\n' "$env_key" "$env_value" >> .deploy.env
  fi
done

if [[ "$CODEX_AUTH_FILE" != /* ]]; then
  CODEX_AUTH_FILE="${ROOT_DIR}/${CODEX_AUTH_FILE#./}"
fi
if [[ "$CLAUDE_AUTH_FILE" != /* ]]; then
  CLAUDE_AUTH_FILE="${ROOT_DIR}/${CLAUDE_AUTH_FILE#./}"
fi
if [[ "$CODEX_CONFIG_FILE" != /* ]]; then
  CODEX_CONFIG_FILE="${ROOT_DIR}/${CODEX_CONFIG_FILE#./}"
fi

if [[ ! -f "$CODEX_AUTH_FILE" ]]; then
  echo "Host Codex auth file not found: $CODEX_AUTH_FILE"
  echo "Falling back to placeholder auth mount so Codex can be configured from the UI."
  CODEX_AUTH_FILE="$CODEX_AUTH_PLACEHOLDER_FILE"
fi
if ! chmod a+r "$CODEX_AUTH_FILE" 2>/dev/null; then
  echo "Warning: unable to adjust read permissions for $CODEX_AUTH_FILE"
  echo "Codex chat in task-app may fail if the mounted auth file is not readable by container user."
fi

if [[ ! -f "$CLAUDE_AUTH_FILE" ]]; then
  echo "Host Claude auth file not found: $CLAUDE_AUTH_FILE"
  echo "Falling back to placeholder Claude auth mount so Claude can be configured from the UI."
  CLAUDE_AUTH_FILE="$CLAUDE_AUTH_PLACEHOLDER_FILE"
fi
if ! chmod a+r "$CLAUDE_AUTH_FILE" 2>/dev/null; then
  echo "Warning: unable to adjust read permissions for $CLAUDE_AUTH_FILE"
  echo "Claude chat in task-app may fail if the mounted auth file is not readable by container user."
fi

if [[ ! -f "$CODEX_CONFIG_FILE" ]]; then
  echo "Missing Codex config file: $CODEX_CONFIG_FILE"
  echo "Create it first (or set CODEX_CONFIG_FILE) before deploy."
  exit 1
fi
if ! chmod a+r "$CODEX_CONFIG_FILE" 2>/dev/null; then
  echo "Warning: unable to adjust read permissions for $CODEX_CONFIG_FILE"
  echo "Codex chat in task-app may fail if the mounted config file is not readable by container user."
fi

export CODEX_AUTH_FILE
export CODEX_CONFIG_FILE
export CLAUDE_AUTH_FILE

if [[ "$AGENT_WORKSPACE_MOUNT" == /* ]]; then
  mkdir -p "$AGENT_WORKSPACE_MOUNT"
  if ! chmod 0777 "$AGENT_WORKSPACE_MOUNT" 2>/dev/null; then
    if [[ ! -w "$AGENT_WORKSPACE_MOUNT" ]]; then
      echo "Warning: workspace mount remains non-writable: ${AGENT_WORKSPACE_MOUNT}"
      echo "Automation may fall back to /tmp/constructos-workspace if /home/app/workspace is not writable."
    fi
  fi
fi

echo "Deploy profile: internal"
echo "Deploying version ${APP_VERSION} (${APP_BUILD}) at ${DEPLOYED_AT_UTC}"
echo "Resolved deploy target: ${TARGET_RESOLVED}"
echo "Deploy source: ${DEPLOY_SOURCE}"
echo "task-app image: ${TASK_APP_IMAGE}"
echo "mcp-tools image: ${MCP_TOOLS_IMAGE}"
echo "Seed ConstructOS Internal: ${SEED_CONSTRUCTOS_INTERNAL_ENABLED}"
echo "Ollama models mount: ${OLLAMA_MODELS_MOUNT} (${OLLAMA_MODELS_MOUNT_MODE})"
echo "Agent workspace mount: ${AGENT_WORKSPACE_MOUNT} (${AGENT_WORKSPACE_MOUNT_MODE})"
echo "Compose project: ${APP_COMPOSE_PROJECT_NAME}"
echo "Compose files: ${COMPOSE_ARGS[*]}"
echo "Deploy services: ${DEPLOY_SERVICES[*]}"

if [[ "$DEPLOY_SOURCE" == "ghcr" ]]; then
  echo "Pulling images..."
  ${COMPOSE_CMD} -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env pull "${DEPLOY_SERVICES[@]}"
  ${COMPOSE_CMD} -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --no-build "${DEPLOY_SERVICES[@]}"
else
  ${COMPOSE_CMD} -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" --env-file .deploy.env up -d --build "${DEPLOY_SERVICES[@]}"
fi
