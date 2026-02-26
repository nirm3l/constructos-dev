#!/usr/bin/env bash
set -euo pipefail

MODE="user"
METHOD="pipx"
PACKAGE_NAME="constructos-cli"

usage() {
  cat <<'EOF'
Uninstall COS CLI (Ubuntu/macOS).

Usage:
  ./tools/cos/scripts/uninstall.sh [--user|--system] [--method pipx|link]

Options:
  --user               User-level uninstall (default).
  --system             System-level uninstall (only with --method link).
  --method pipx        Remove pipx-installed package.
  --method link        Remove symlink install.
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

if [[ "${METHOD}" == "pipx" ]]; then
  if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx not found; nothing to uninstall with --method pipx." >&2
    exit 1
  fi
  if pipx list --short 2>/dev/null | grep -qx "${PACKAGE_NAME}"; then
    pipx uninstall "${PACKAGE_NAME}"
    echo "Uninstalled ${PACKAGE_NAME}."
  else
    echo "${PACKAGE_NAME} is not installed via pipx."
  fi
  exit 0
fi

if [[ "${MODE}" == "user" ]]; then
  TARGET="${HOME}/.local/bin/cos"
  if [[ -L "${TARGET}" || -f "${TARGET}" ]]; then
    rm -f "${TARGET}"
    echo "Removed ${TARGET}."
  else
    echo "${TARGET} does not exist."
  fi
  exit 0
fi

TARGET="/usr/local/bin/cos"
if [[ "$(id -u)" -eq 0 ]]; then
  rm -f "${TARGET}"
else
  sudo rm -f "${TARGET}"
fi
echo "Removed ${TARGET}."
