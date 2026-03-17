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
  echo "Install Docker Compose plugin ('docker compose') or legacy 'docker-compose' before control-plane operations."
  exit 1
fi

CP_COMPOSE_PROJECT_NAME="${CP_COMPOSE_PROJECT_NAME:-constructos-cp}"
COMPOSE_ARGS=(-f docker-compose.license-control-plane.yml)
LCP_BACKUP_HOST_DIR="${LCP_BACKUP_HOST_DIR:-data/license-control-plane-backups}"
LCP_LEGACY_BACKUP_VOLUME="${LCP_LEGACY_BACKUP_VOLUME:-task-management_license-control-plane-backups}"
LCP_BACKUP_RUN_AS="${LCP_BACKUP_RUN_AS:-$(id -u):$(id -g)}"
SERVICES=(
  license-control-plane
  license-control-plane-backup
)
ACTION="${1:-up}"

resolve_backup_host_dir() {
  local raw="${LCP_BACKUP_HOST_DIR}"
  if [[ "$raw" == "~/"* ]]; then
    raw="${HOME}/${raw#~/}"
  fi
  if [[ "$raw" == /* ]]; then
    printf '%s\n' "$raw"
  else
    printf '%s\n' "${ROOT_DIR}/${raw}"
  fi
}

prepare_backup_host_dir() {
  LCP_BACKUP_HOST_DIR="$(resolve_backup_host_dir)"
  mkdir -p "${LCP_BACKUP_HOST_DIR}"
  export LCP_BACKUP_HOST_DIR
  export LCP_BACKUP_RUN_AS
}

migrate_legacy_backups_if_needed() {
  if ! docker volume inspect "${LCP_LEGACY_BACKUP_VOLUME}" >/dev/null 2>&1; then
    return 0
  fi
  if find "${LCP_BACKUP_HOST_DIR}" -maxdepth 1 -type f -name 'license-control-plane-*.sqlite3' | grep -q .; then
    return 0
  fi

  local first_legacy_backup
  first_legacy_backup="$(
    docker run --rm \
      -v "${LCP_LEGACY_BACKUP_VOLUME}:/legacy:ro" \
      alpine:3.20 \
      sh -lc "ls -1 /legacy/license-control-plane-*.sqlite3 2>/dev/null | head -n 1"
  )"
  if [[ -z "${first_legacy_backup}" ]]; then
    return 0
  fi

  echo "Migrating legacy backups from volume ${LCP_LEGACY_BACKUP_VOLUME} to ${LCP_BACKUP_HOST_DIR}..."
  docker run --rm \
    --user "${LCP_BACKUP_RUN_AS}" \
    -v "${LCP_LEGACY_BACKUP_VOLUME}:/legacy:ro" \
    -v "${LCP_BACKUP_HOST_DIR}:/host" \
    alpine:3.20 \
    sh -lc "cp -n /legacy/license-control-plane-*.sqlite3 /host/ 2>/dev/null || true"
}

echo "Using compose project: ${CP_COMPOSE_PROJECT_NAME}"
echo "Backup host directory: $(resolve_backup_host_dir)"
echo "Backup run user: ${LCP_BACKUP_RUN_AS}"

case "$ACTION" in
  up)
    prepare_backup_host_dir
    migrate_legacy_backups_if_needed
    ${COMPOSE_CMD} -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  down)
    # Intentionally no `-v` so control-plane data is preserved.
    ${COMPOSE_CMD} -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" down
    ;;
  restart)
    prepare_backup_host_dir
    migrate_legacy_backups_if_needed
    ${COMPOSE_CMD} -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  status)
    ${COMPOSE_CMD} -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" ps
    ;;
  logs)
    ${COMPOSE_CMD} -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" logs -f "${SERVICES[@]}"
    ;;
  *)
    echo "Usage: ./scripts/deploy-control-plane.sh [up|down|restart|status|logs]"
    exit 1
    ;;
esac
