#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
APP_COMPOSE_PROJECT_NAME="${APP_COMPOSE_PROJECT_NAME:-constructos-app}"

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

echo "Using compose project: ${APP_COMPOSE_PROJECT_NAME}"

echo "[1/5] Stopping app stack and removing app volumes..."
docker compose -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" down -v || true

echo "[2/5] Cleaning local projection DB and uploaded files..."
rm -f data/*.db
rm -f app/*.db
rm -rf data/uploads
rm -rf app/uploads
mkdir -p data

echo "[3/5] Running fresh deploy..."
./scripts/deploy.sh

echo "[4/5] Waiting for API health..."
for i in {1..60}; do
  if curl -sS "http://localhost:8080/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[5/5] Current stack status:"
docker compose -p "${APP_COMPOSE_PROJECT_NAME}" "${COMPOSE_ARGS[@]}" ps
echo "---"
echo "Health:"
curl -sS "http://localhost:8080/api/health"
echo
echo "---"
echo "Version:"
curl -sS "http://localhost:8080/api/version"
echo
