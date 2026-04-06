#!/usr/bin/env bash
set -euo pipefail

setup_git_runtime() {
  local app_dir="${1:-}"
  local workspace_dir="${2:-}"
  if ! command -v git >/dev/null 2>&1; then
    return 0
  fi

  if [ -n "${app_dir}" ]; then
    git config --global --add safe.directory "${app_dir}" >/dev/null 2>&1 || true
  fi
  if [ -n "${workspace_dir}" ]; then
    git config --global --add safe.directory "${workspace_dir}" >/dev/null 2>&1 || true
  fi

  if [ -z "${GITHUB_PAT:-}" ]; then
    return 0
  fi

  local askpass_path="${HOME:-/home/app}/.codex/git-askpass.sh"
  mkdir -p "$(dirname "${askpass_path}")"
  cat > "${askpass_path}" <<'EOF'
#!/usr/bin/env sh
case "$1" in
  *Username*) printf '%s\n' "x-access-token" ;;
  *Password*) printf '%s\n' "${GITHUB_PAT:-}" ;;
  *) printf '\n' ;;
esac
EOF
  chmod 0700 "${askpass_path}"

  export GIT_ASKPASS="${askpass_path}"
  export GIT_ASKPASS_REQUIRE=force
  export GIT_TERMINAL_PROMPT=0
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    export GITHUB_TOKEN="${GITHUB_PAT}"
  fi

  git config --global credential.helper "" >/dev/null 2>&1 || true
  git config --global credential.useHttpPath true >/dev/null 2>&1 || true
}

resolve_writable_workspace_dir() {
  local requested_dir="${1:-}"
  local fallback_dir="${2:-/tmp/constructos-workspace}"
  local candidate="${requested_dir:-/home/app/workspace}"

  if mkdir -p "${candidate}" >/dev/null 2>&1 && touch "${candidate}/.write-test" >/dev/null 2>&1; then
    rm -f "${candidate}/.write-test" >/dev/null 2>&1 || true
    printf '%s' "${candidate}"
    return 0
  fi

  echo "Workspace directory is not writable (${candidate}); falling back to ${fallback_dir}." >&2
  mkdir -p "${fallback_dir}"
  touch "${fallback_dir}/.write-test"
  rm -f "${fallback_dir}/.write-test" >/dev/null 2>&1 || true
  printf '%s' "${fallback_dir}"
}

resolve_writable_codex_home_dir() {
  local requested_dir="${1:-}"
  local fallback_dir="${2:-/home/app/agent-home/codex-home}"
  local candidate="${requested_dir:-/home/app/codex-home}"

  if mkdir -p "${candidate}" >/dev/null 2>&1 && touch "${candidate}/.write-test" >/dev/null 2>&1; then
    rm -f "${candidate}/.write-test" >/dev/null 2>&1 || true
    printf '%s' "${candidate}"
    return 0
  fi

  echo "Codex home directory is not writable (${candidate}); falling back to ${fallback_dir}." >&2
  mkdir -p "${fallback_dir}"
  touch "${fallback_dir}/.write-test"
  rm -f "${fallback_dir}/.write-test" >/dev/null 2>&1 || true
  printf '%s' "${fallback_dir}"
}

main() {
  local app_dir="${APP_RUNTIME_APP_DIR:-/app}"
  local requested_workspace_dir="${AGENT_WORKDIR:-${AGENT_CODEX_WORKDIR:-/home/app/workspace}}"
  local requested_codex_home_dir="${AGENT_HOME_ROOT:-${AGENT_CODEX_HOME_ROOT:-/home/app/codex-home}}"
  local app_workspace_dir
  local app_codex_home_dir

  if [ "$#" -eq 0 ]; then
    set -- uvicorn main:app --host 0.0.0.0 --port 8000
  fi

  app_workspace_dir="$(resolve_writable_workspace_dir "${requested_workspace_dir}")"
  app_codex_home_dir="$(resolve_writable_codex_home_dir "${requested_codex_home_dir}")"
  export AGENT_WORKDIR="${app_workspace_dir}"
  export AGENT_CODEX_WORKDIR="${app_workspace_dir}"
  export AGENT_HOME_ROOT="${app_codex_home_dir}"
  export AGENT_CODEX_HOME_ROOT="${app_codex_home_dir}"

  setup_git_runtime "${app_dir}" "${app_workspace_dir}"
  cd "${app_dir}"
  exec "$@"
}

main "$@"
