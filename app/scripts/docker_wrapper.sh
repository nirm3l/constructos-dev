#!/usr/bin/env sh
set -eu

REAL_DOCKER_BIN="${REAL_DOCKER_BIN:-/usr/bin/docker}"
REAL_DOCKER_COMPOSE_BIN="${REAL_DOCKER_COMPOSE_BIN:-/usr/bin/docker-compose}"

is_truthy() {
  case "$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if ! is_truthy "${AGENT_DOCKER_SOFT_ISOLATION:-true}"; then
  exec "${REAL_DOCKER_BIN}" "$@"
fi

project_name="$(echo "${AGENT_DOCKER_PROJECT_NAME:-constructos-ws-default}" | tr -d '\r' | xargs)"
allowed_prefix="$(echo "${AGENT_DOCKER_ALLOWED_PROJECT_PREFIX:-constructos-ws-}" | tr -d '\r' | xargs)"

if [ -z "${project_name}" ] || [ -z "${allowed_prefix}" ]; then
  echo "Docker soft isolation is enabled but project/prefix is not configured." >&2
  exit 126
fi

case "${project_name}" in
  "${allowed_prefix}"*)
    ;;
  *)
    echo "Docker project '${project_name}' must start with '${allowed_prefix}'." >&2
    exit 126
    ;;
esac

if [ "$#" -eq 0 ]; then
  exec "${REAL_DOCKER_BIN}"
fi

command="$1"
shift

case "${command}" in
  version|info|context)
    exec "${REAL_DOCKER_BIN}" "${command}" "$@"
    ;;
  ps)
    exec "${REAL_DOCKER_BIN}" ps --filter "label=com.docker.compose.project=${project_name}" "$@"
    ;;
  container)
    subcommand="${1:-}"
    if [ -z "${subcommand}" ]; then
      echo "Blocked by Docker soft isolation. Use 'docker container ls'." >&2
      exit 126
    fi
    shift
    case "${subcommand}" in
      ls)
        exec "${REAL_DOCKER_BIN}" container ls --filter "label=com.docker.compose.project=${project_name}" "$@"
        ;;
      *)
        echo "Blocked by Docker soft isolation. Use 'docker compose -p ${project_name} ...'." >&2
        exit 126
        ;;
    esac
    ;;
  compose)
    saw_project_flag=0
    project_arg=""
    expecting_project_value=0
    for arg in "$@"; do
      if [ "${expecting_project_value}" = "1" ]; then
        saw_project_flag=1
        project_arg="${arg}"
        expecting_project_value=0
        continue
      fi
      case "${arg}" in
        --project-name|-p)
          expecting_project_value=1
          ;;
        --project-name=*)
          saw_project_flag=1
          project_arg="${arg#--project-name=}"
          ;;
        -p*)
          saw_project_flag=1
          project_arg="${arg#-p}"
          ;;
      esac
    done

    if [ "${saw_project_flag}" = "1" ] && [ "${project_arg}" != "${project_name}" ]; then
      echo "Blocked by Docker soft isolation. Project must be '${project_name}'." >&2
      exit 126
    fi

    if [ -x "${REAL_DOCKER_COMPOSE_BIN}" ]; then
      if [ "${saw_project_flag}" = "0" ]; then
        exec "${REAL_DOCKER_COMPOSE_BIN}" -p "${project_name}" "$@"
      fi
      exec "${REAL_DOCKER_COMPOSE_BIN}" "$@"
    fi

    if [ "${saw_project_flag}" = "0" ]; then
      exec "${REAL_DOCKER_BIN}" compose -p "${project_name}" "$@"
    fi
    exec "${REAL_DOCKER_BIN}" compose "$@"
    ;;
  *)
    echo "Blocked by Docker soft isolation. Allowed: compose, ps, container ls, info, version, context." >&2
    exit 126
    ;;
esac
