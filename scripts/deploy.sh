#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEPLOY_LICENSE_CONTROL_PLANE="${DEPLOY_LICENSE_CONTROL_PLANE:-false}"

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

if [[ "${DEPLOY_LICENSE_CONTROL_PLANE,,}" == "true" || "${DEPLOY_LICENSE_CONTROL_PLANE}" == "1" ]]; then
  export DEPLOY_EXTRA_COMPOSE_FILES="docker-compose.license-control-plane.yml"
  export DEPLOY_EXTRA_UP_SERVICES="license-control-plane"
  LCP_API_TOKEN_VALUE="$(resolve_compose_env_value "LCP_API_TOKEN" || true)"
  if [[ -n "$LCP_API_TOKEN_VALUE" ]]; then
    export LCP_API_TOKEN="$LCP_API_TOKEN_VALUE"
  fi
fi

export DEPLOY_LABEL="internal"
exec ./scripts/deploy-core.sh "$@"
