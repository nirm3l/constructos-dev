#!/usr/bin/env bash
set -euo pipefail

MODE="user"
METHOD="pipx"
PACKAGE_NAME="constructos-cos"

usage() {
  cat <<'EOF'
Install COS CLI (Ubuntu/macOS).

Usage:
  ./tools/cos/scripts/install.sh [--user|--system] [--method pipx|link]

Options:
  --user               User-level install (default).
  --system             System-level install (only with --method link).
  --method pipx        Install via pipx (recommended, isolated env).
  --method link        Install by linking repo launcher script.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      MODE="user"
      shift
      ;;
    --system)
      MODE="system"
      shift
      ;;
    --method)
      METHOD="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "${METHOD}" != "pipx" && "${METHOD}" != "link" ]]; then
  echo "Invalid --method value: ${METHOD}" >&2
  exit 2
fi

if [[ "${MODE}" == "system" && "${METHOD}" != "link" ]]; then
  echo "--system is currently supported only with --method link." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCHER_PATH="${COS_DIR}/cos"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH." >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI is required but was not found in PATH." >&2
  echo "Install Codex first, then run this installer again." >&2
  exit 1
fi

if [[ "${METHOD}" == "pipx" ]]; then
  if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx is required for --method pipx." >&2
    echo "Ubuntu: sudo apt-get install pipx (or python3 -m pip install --user pipx)" >&2
    echo "macOS:  brew install pipx" >&2
    exit 1
  fi
  pipx install --force "${COS_DIR}"
  pipx ensurepath >/dev/null 2>&1 || true
  echo "Installed ${PACKAGE_NAME} via pipx."
  echo "Run: cos --help"
  exit 0
fi

if [[ "${MODE}" == "user" ]]; then
  TARGET_DIR="${HOME}/.local/bin"
  mkdir -p "${TARGET_DIR}"
  ln -sf "${LAUNCHER_PATH}" "${TARGET_DIR}/cos"
  echo "Linked cos -> ${TARGET_DIR}/cos"
  echo "Ensure ${TARGET_DIR} is in PATH."
  exit 0
fi

TARGET_DIR="/usr/local/bin"
if [[ "$(id -u)" -eq 0 ]]; then
  mkdir -p "${TARGET_DIR}"
  ln -sf "${LAUNCHER_PATH}" "${TARGET_DIR}/cos"
else
  sudo mkdir -p "${TARGET_DIR}"
  sudo ln -sf "${LAUNCHER_PATH}" "${TARGET_DIR}/cos"
fi
echo "Linked cos -> ${TARGET_DIR}/cos"
