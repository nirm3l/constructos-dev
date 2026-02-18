#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/5] Stopping Docker Compose stack and removing volumes..."
docker compose down -v --remove-orphans || true

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
docker compose ps
echo "---"
echo "Health:"
curl -sS "http://localhost:8080/api/health"
echo
echo "---"
echo "Version:"
curl -sS "http://localhost:8080/api/version"
echo
