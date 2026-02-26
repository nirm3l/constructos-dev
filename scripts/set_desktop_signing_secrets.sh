#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-nirm3l/m4tr1x}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required. Install GitHub CLI first." >&2
  exit 1
fi

declare -a SECRET_NAMES=(
  "DESKTOP_CSC_LINK"
  "DESKTOP_CSC_KEY_PASSWORD"
  "DESKTOP_CSC_NAME"
  "DESKTOP_WIN_CSC_LINK"
  "DESKTOP_WIN_CSC_KEY_PASSWORD"
  "DESKTOP_APPLE_ID"
  "DESKTOP_APPLE_APP_SPECIFIC_PASSWORD"
  "DESKTOP_APPLE_TEAM_ID"
  "DESKTOP_APPLE_API_KEY"
  "DESKTOP_APPLE_API_KEY_ID"
  "DESKTOP_APPLE_API_ISSUER"
)

updated=0
skipped=0

for name in "${SECRET_NAMES[@]}"; do
  value="${!name:-}"
  if [[ -z "$value" ]]; then
    echo "[SKIP] ${name} is not set in environment."
    skipped=$((skipped + 1))
    continue
  fi
  printf '%s' "$value" | gh secret set "$name" -R "$REPO" --body -
  echo "[OK] Updated ${name} in ${REPO}"
  updated=$((updated + 1))
done

echo ""
echo "Secrets updated: ${updated}"
echo "Secrets skipped: ${skipped}"
echo "Repository: ${REPO}"
