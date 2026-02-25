#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
CLEAN=1
RUN_TWINE_CHECK=1

usage() {
  cat <<'EOF'
Build COS CLI distribution artifacts (wheel + sdist).

Usage:
  ./tools/cos/scripts/build.sh [--no-clean] [--skip-check] [--python python3.12]

Options:
  --no-clean           Keep existing dist/ and build/ directories.
  --skip-check         Skip `twine check` metadata validation.
  --python <binary>    Python interpreter to use (default: python3 or PYTHON_BIN env).
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-clean)
      CLEAN=0
      shift
      ;;
    --skip-check)
      RUN_TWINE_CHECK=0
      shift
      ;;
    --python)
      PYTHON_BIN="${2:-}"
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python interpreter not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
  echo "Selected Python cannot run pip: ${PYTHON_BIN}" >&2
  echo "Choose another interpreter with --python, for example: --python /usr/bin/python3" >&2
  exit 1
fi

if ! "${PYTHON_BIN}" -m build --version >/dev/null 2>&1; then
  echo "Missing Python package 'build' for ${PYTHON_BIN}." >&2
  echo "Install it with: ${PYTHON_BIN} -m pip install --user build" >&2
  exit 1
fi

if [[ "${RUN_TWINE_CHECK}" == "1" ]] && ! "${PYTHON_BIN}" -m twine --version >/dev/null 2>&1; then
  echo "Missing Python package 'twine' for ${PYTHON_BIN}." >&2
  echo "Install it with: ${PYTHON_BIN} -m pip install --user twine" >&2
  exit 1
fi

if [[ "${CLEAN}" == "1" ]]; then
  rm -rf "${COS_DIR}/dist" "${COS_DIR}/build"
fi

"${PYTHON_BIN}" -m build --sdist --wheel "${COS_DIR}"

if [[ "${RUN_TWINE_CHECK}" == "1" ]]; then
  "${PYTHON_BIN}" -m twine check "${COS_DIR}"/dist/*
fi

echo ""
echo "Build completed. Artifacts:"
ls -1 "${COS_DIR}"/dist/*
