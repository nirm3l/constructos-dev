#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_ARGS=(-f docker-compose.license-control-plane.yml)
SERVICES=(
  license-control-plane
  license-control-plane-backup
)
ACTION="${1:-up}"

case "$ACTION" in
  up)
    docker compose "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  down)
    # Intentionally no `-v` so control-plane data is preserved.
    docker compose "${COMPOSE_ARGS[@]}" down
    ;;
  restart)
    docker compose "${COMPOSE_ARGS[@]}" up -d --build "${SERVICES[@]}"
    ;;
  status)
    docker compose "${COMPOSE_ARGS[@]}" ps
    ;;
  logs)
    docker compose "${COMPOSE_ARGS[@]}" logs -f "${SERVICES[@]}"
    ;;
  *)
    echo "Usage: ./scripts/deploy-control-plane.sh [up|down|restart|status|logs]"
    exit 1
    ;;
esac
