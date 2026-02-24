#!/usr/bin/env bash
set -euo pipefail

is_truthy() {
  case "$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_bundle_passphrase() {
  if [ -n "${APP_BUNDLE_PASSWORD_OVERRIDE:-}" ]; then
    printf '%s' "${APP_BUNDLE_PASSWORD_OVERRIDE}"
    return 0
  fi

  local license_token="${LICENSE_SERVER_TOKEN:-}"
  if [ -z "${license_token}" ]; then
    echo "Encrypted bundle mode requires LICENSE_SERVER_TOKEN." >&2
    return 1
  fi

  local segment_index="${APP_BUNDLE_TOKEN_SEGMENT_INDEX:-}"
  if [ -z "${segment_index}" ]; then
    printf '%s' "${license_token}"
    return 0
  fi

  if ! [[ "${segment_index}" =~ ^-?[0-9]+$ ]]; then
    echo "APP_BUNDLE_TOKEN_SEGMENT_INDEX must be an integer." >&2
    return 1
  fi

  local delimiter="${APP_BUNDLE_TOKEN_DELIMITER:-.}"
  if [ -z "${delimiter}" ]; then
    delimiter="."
  fi

  local segments=()
  local old_ifs="${IFS}"
  IFS="${delimiter}" read -r -a segments <<< "${license_token}"
  IFS="${old_ifs}"

  local idx="${segment_index}"
  local count="${#segments[@]}"
  if (( idx < 0 )); then
    idx=$((count + idx))
  fi

  if (( idx < 0 || idx >= count )); then
    echo "APP_BUNDLE_TOKEN_SEGMENT_INDEX is outside token segment range." >&2
    return 1
  fi

  local passphrase="${segments[$idx]}"
  if [ -z "${passphrase}" ]; then
    echo "Derived bundle passphrase segment is empty." >&2
    return 1
  fi
  printf '%s' "${passphrase}"
}

main() {
  local app_dir="${APP_RUNTIME_APP_DIR:-/app}"
  local encrypted_enabled="${APP_ENCRYPTED_BUNDLE_ENABLED:-false}"
  local encrypted_bundle_path="${APP_ENCRYPTED_BUNDLE_PATH:-/opt/constructos/app.tar.gz.enc}"
  local decrypted_app_dir="${APP_DECRYPTED_APP_DIR:-/tmp/constructos-app}"
  local decrypted_archive_path="/tmp/constructos-app-bundle.tar.gz"
  local kdf_iterations="${APP_BUNDLE_KDF_ITERATIONS:-200000}"

  if [ "$#" -eq 0 ]; then
    set -- uvicorn main:app --host 0.0.0.0 --port 8000
  fi

  if ! is_truthy "${encrypted_enabled}"; then
    cd "${app_dir}"
    exec "$@"
  fi

  if [ ! -f "${encrypted_bundle_path}" ]; then
    echo "Encrypted bundle is enabled but file is missing: ${encrypted_bundle_path}" >&2
    exit 1
  fi

  local passphrase
  passphrase="$(resolve_bundle_passphrase)"

  rm -rf "${decrypted_app_dir}"
  mkdir -p "${decrypted_app_dir}"

  openssl enc \
    -d \
    -aes-256-cbc \
    -pbkdf2 \
    -iter "${kdf_iterations}" \
    -in "${encrypted_bundle_path}" \
    -out "${decrypted_archive_path}" \
    -pass "pass:${passphrase}"

  tar -xzf "${decrypted_archive_path}" -C "${decrypted_app_dir}"
  rm -f "${decrypted_archive_path}"

  export PYTHONPATH="${decrypted_app_dir}${PYTHONPATH:+:${PYTHONPATH}}"
  cd "${decrypted_app_dir}"
  exec "$@"
}

main "$@"
