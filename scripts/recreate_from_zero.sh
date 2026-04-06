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
  echo "Install Docker Compose plugin ('docker compose') or legacy 'docker-compose' before reset."
  exit 1
fi

DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
APP_COMPOSE_PROJECT_NAME="${APP_COMPOSE_PROJECT_NAME:-constructos-app}"
PROXY_DOCKER_PROJECT_NAME="${AGENT_DOCKER_PROJECT_NAME:-}"
CODEX_AUTH_FILE="${CODEX_AUTH_FILE:-${HOME}/.codex/auth.json}"
CODEX_CONFIG_FILE="${CODEX_CONFIG_FILE:-${ROOT_DIR}/codex.config.toml}"
CODEX_AUTH_PLACEHOLDER_FILE="${ROOT_DIR}/codex.auth.placeholder.json"

resolve_absolute_path() {
  local raw_path="$1"
  if [[ "$raw_path" == /* ]]; then
    printf '%s' "$raw_path"
  else
    printf '%s/%s' "$ROOT_DIR" "${raw_path#./}"
  fi
}

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

CODEX_AUTH_FILE="$(resolve_absolute_path "$CODEX_AUTH_FILE")"
CODEX_CONFIG_FILE="$(resolve_absolute_path "$CODEX_CONFIG_FILE")"

if [[ ! -f "$CODEX_AUTH_FILE" ]]; then
  echo "Host Codex auth file not found: $CODEX_AUTH_FILE"
  echo "Falling back to placeholder auth mount so Codex can be configured from the UI."
  CODEX_AUTH_FILE="$CODEX_AUTH_PLACEHOLDER_FILE"
fi
if [[ ! -f "$CODEX_CONFIG_FILE" ]]; then
  echo "Missing Codex config file: $CODEX_CONFIG_FILE"
  echo "Create it first (or set CODEX_CONFIG_FILE) before reset."
  exit 1
fi

export CODEX_AUTH_FILE
export CODEX_CONFIG_FILE

if [[ -z "${PROXY_DOCKER_PROJECT_NAME}" ]]; then
  PROXY_DOCKER_PROJECT_NAME="$(resolve_compose_env_value "AGENT_DOCKER_PROJECT_NAME" || true)"
fi
if [[ -z "${PROXY_DOCKER_PROJECT_NAME}" ]]; then
  PROXY_DOCKER_PROJECT_NAME="constructos-ws-default"
fi

echo "Using compose project: ${APP_COMPOSE_PROJECT_NAME}"
echo "Using proxy docker project scope: ${PROXY_DOCKER_PROJECT_NAME}"

echo "[1/6] Stopping app stack..."
${COMPOSE_CMD} -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" down || true

echo "[1b/6] Removing app data volumes (preserving codex home auth/session volume)..."
for volume_name in \
  "task-management_neo4j-data" \
  "task-management_postgres-data" \
  "task-management_kurrent-data"
do
  if docker volume inspect "${volume_name}" >/dev/null 2>&1; then
    docker volume rm "${volume_name}" || true
  fi
done

echo "[1c/6] Cleaning stale task-automation Codex sessions from codex-home volume..."
if docker volume inspect "task-management_codex-home-data" >/dev/null 2>&1; then
  docker run --rm -v "task-management_codex-home-data:/codex-home" alpine:3.20 \
    sh -lc 'find /codex-home/workspace -mindepth 3 -maxdepth 3 -type d -name "task-automation_*" -exec rm -rf {} + 2>/dev/null || true'
fi

echo "[2/6] Cleaning proxy stack resources (containers/networks/volumes) for ${PROXY_DOCKER_PROJECT_NAME}..."
proxy_containers="$(docker ps -aq --filter "label=com.docker.compose.project=${PROXY_DOCKER_PROJECT_NAME}" || true)"
if [[ -n "${proxy_containers}" ]]; then
  docker rm -f ${proxy_containers} || true
fi
proxy_networks="$(docker network ls -q --filter "label=com.docker.compose.project=${PROXY_DOCKER_PROJECT_NAME}" || true)"
if [[ -n "${proxy_networks}" ]]; then
  docker network rm ${proxy_networks} || true
fi
proxy_volumes="$(docker volume ls -q --filter "label=com.docker.compose.project=${PROXY_DOCKER_PROJECT_NAME}" || true)"
if [[ -n "${proxy_volumes}" ]]; then
  docker volume rm ${proxy_volumes} || true
fi

echo "[3/6] Cleaning local projection DB, uploads, and workspace..."
rm -f data/*.db
rm -f app/*.db
rm -rf data/uploads
rm -rf app/uploads
if [[ -d data/workspace ]]; then
  if ! find data/workspace -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null; then
    echo "Workspace cleanup via host permissions failed; retrying via container root..."
    docker run --rm -v "${ROOT_DIR}/data/workspace:/workspace" alpine:3.20 \
      sh -lc 'rm -rf /workspace/* /workspace/.[!.]* /workspace/..?* 2>/dev/null || true'
  fi
fi
mkdir -p data
mkdir -p data/workspace

echo "[4/6] Running fresh deploy..."
DOCTOR_RECOVERY_AFTER_DEPLOY=false ./scripts/deploy.sh

echo "[5/6] Waiting for API health..."
for i in {1..60}; do
  if curl -sS "http://localhost:1102/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[6/7] Running Doctor wiring + contract audit and validating runtime health..."
DOCTOR_RECOVERY_ENABLED="${DOCTOR_RECOVERY_ENABLED:-true}"
if [[ "$DOCTOR_RECOVERY_ENABLED" == "true" ]]; then
  doctor_username="${DOCTOR_RECOVERY_USERNAME:-$(resolve_compose_env_value "BOOTSTRAP_USERNAME" || true)}"
  doctor_password="${DOCTOR_RECOVERY_PASSWORD:-$(resolve_compose_env_value "BOOTSTRAP_PASSWORD" || true)}"
  legacy_password="${DOCTOR_LEGACY_PASSWORD:-$(resolve_compose_env_value "LEGACY_BOOTSTRAP_PASSWORD" || true)}"
  workspace_id="${DOCTOR_WORKSPACE_ID:-10000000-0000-0000-0000-000000000001}"
  if [[ -z "$doctor_username" ]]; then
    doctor_username="admin"
  fi
  if [[ -z "$doctor_password" ]]; then
    doctor_password="admin"
  fi
  if [[ -z "$legacy_password" ]]; then
    legacy_password="testtest"
  fi

  cookie_jar="$(mktemp)"
  trap 'rm -f "$cookie_jar"' EXIT

  login_status="$(curl -sS -o /tmp/doctor-login.json -w "%{http_code}" -c "$cookie_jar" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${doctor_username}\",\"password\":\"${doctor_password}\"}" \
    "http://localhost:1102/api/auth/login" || true)"

  if [[ "$login_status" != "200" ]]; then
    login_status="$(curl -sS -o /tmp/doctor-login.json -w "%{http_code}" -c "$cookie_jar" \
      -H "Content-Type: application/json" \
      -d "{\"username\":\"${doctor_username}\",\"password\":\"${legacy_password}\"}" \
      "http://localhost:1102/api/auth/login" || true)"
  fi

  if [[ "$login_status" != "200" ]]; then
    echo "Doctor recovery login failed (HTTP ${login_status})."
    cat /tmp/doctor-login.json || true
    rm -f /tmp/doctor-login.json
    exit 1
  fi

  rm -f /tmp/doctor-login.json

  wiring_status="$(curl -sS -o /tmp/doctor-wiring.json -w "%{http_code}" -b "$cookie_jar" \
    -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/actions/doctor-plugin-wiring" || true)"
  if [[ "$wiring_status" != "200" ]]; then
    echo "Doctor plugin wiring quick action failed (HTTP ${wiring_status}); retrying with direct seed."
    cat /tmp/doctor-wiring.json || true
    seed_status="$(curl -sS -o /tmp/doctor-seed.json -w "%{http_code}" -b "$cookie_jar" \
      -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/seed" || true)"
    if [[ "$seed_status" != "200" ]]; then
      echo "Doctor seed fallback failed (HTTP ${seed_status})."
      cat /tmp/doctor-seed.json || true
      rm -f /tmp/doctor-wiring.json /tmp/doctor-seed.json
      exit 1
    fi
    rm -f /tmp/doctor-seed.json
  fi
  rm -f /tmp/doctor-wiring.json

  audit_action_status="$(curl -sS -o /tmp/doctor-audit-action.json -w "%{http_code}" -b "$cookie_jar" \
    -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/actions/runtime-contract-audit" || true)"
  if [[ "$audit_action_status" != "200" ]]; then
    echo "Doctor runtime-contract-audit quick action failed (HTTP ${audit_action_status}); retrying with direct audit then quick action."
    cat /tmp/doctor-audit-action.json || true
    audit_status="$(curl -sS -o /tmp/doctor-audit.json -w "%{http_code}" -b "$cookie_jar" \
      -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/audit" || true)"
    if [[ "$audit_status" != "200" ]]; then
      echo "Doctor audit fallback failed (HTTP ${audit_status})."
      cat /tmp/doctor-audit.json || true
      rm -f /tmp/doctor-audit-action.json /tmp/doctor-audit.json
      exit 1
    fi
    audit_action_status="$(curl -sS -o /tmp/doctor-audit-action-retry.json -w "%{http_code}" -b "$cookie_jar" \
      -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/actions/runtime-contract-audit" || true)"
    if [[ "$audit_action_status" != "200" ]]; then
      echo "Doctor runtime-contract-audit retry failed (HTTP ${audit_action_status})."
      cat /tmp/doctor-audit-action-retry.json || true
      rm -f /tmp/doctor-audit-action.json /tmp/doctor-audit.json /tmp/doctor-audit-action-retry.json
      exit 1
    fi
    rm -f /tmp/doctor-audit-action-retry.json /tmp/doctor-audit.json
  fi
  rm -f /tmp/doctor-audit-action.json

  warm_status="$(curl -sS -o /tmp/doctor-warm.json -w "%{http_code}" -b "$cookie_jar" \
    -X POST "http://localhost:1102/api/workspaces/${workspace_id}/doctor/actions/warm-bootstrap-caches" || true)"
  if [[ "$warm_status" != "200" ]]; then
    echo "Doctor warm-bootstrap-caches quick action failed (HTTP ${warm_status}); retrying with direct bootstrap read."
    cat /tmp/doctor-warm.json || true
    bootstrap_status="$(curl -sS -o /tmp/doctor-bootstrap.json -w "%{http_code}" -b "$cookie_jar" \
      "http://localhost:1102/api/bootstrap" || true)"
    if [[ "$bootstrap_status" != "200" ]]; then
      echo "Bootstrap warm fallback failed (HTTP ${bootstrap_status})."
      cat /tmp/doctor-bootstrap.json || true
      rm -f /tmp/doctor-warm.json /tmp/doctor-bootstrap.json
      exit 1
    fi
    rm -f /tmp/doctor-bootstrap.json
  fi
  rm -f /tmp/doctor-warm.json

  doctor_payload="$(curl -sS -b "$cookie_jar" "http://localhost:1102/api/workspaces/${workspace_id}/doctor")"
  if ! grep -q '"overall_status":"healthy"' <<<"$doctor_payload"; then
    echo "Doctor runtime health is not healthy after recovery."
    echo "$doctor_payload"
    exit 1
  fi

  rm -f "$cookie_jar"
  trap - EXIT
else
  echo "Doctor recovery skipped (DOCTOR_RECOVERY_ENABLED=${DOCTOR_RECOVERY_ENABLED})."
fi

echo "[7/7] Current stack status:"
${COMPOSE_CMD} -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" ps
echo "---"
echo "Health:"
curl -sS "http://localhost:1102/api/health"
echo
echo "---"
echo "Version:"
curl -sS "http://localhost:1102/api/version"
echo
