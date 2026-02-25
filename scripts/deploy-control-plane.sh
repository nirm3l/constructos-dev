#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CP_COMPOSE_PROJECT_NAME="${CP_COMPOSE_PROJECT_NAME:-constructos-cp}"
COMPOSE_ARGS=(-f docker-compose.license-control-plane.yml)
SERVICES=(
  license-control-plane
  license-control-plane-backup
)
ACTION="${1:-up}"

echo "Using compose project: ${CP_COMPOSE_PROJECT_NAME}"

case "$ACTION" in
  up)
    docker compose -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  down)
    # Intentionally no `-v` so control-plane data is preserved.
    docker compose -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" down
    ;;
  restart)
    docker compose -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  status)
    docker compose -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" ps
    ;;
  logs)
    docker compose -p "${CP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" logs -f "${SERVICES[@]}"
    ;;
  *)
    echo "Usage: ./scripts/deploy-control-plane.sh [up|down|restart|status|logs]"
    exit 1
    ;;
esac
