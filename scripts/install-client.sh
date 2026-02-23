#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://app.constructos.dev}"
BUNDLE_PATH="${BUNDLE_PATH:-client}"
VERSION="${VERSION:-}"
INSTALL_DIR="${INSTALL_DIR:-./constructos-client}"

BUNDLE_URL="${BASE_URL%/}/${BUNDLE_PATH#/}"

if [[ -z "$VERSION" ]]; then
  VERSION="$(curl -fsSL "${BUNDLE_URL}/latest.txt" | tr -d '\r' | tr -d '\n' || true)"
fi
if [[ -z "$VERSION" ]]; then
  echo "VERSION is required (example: VERSION=v0.1.230) when latest.txt is unavailable"
  exit 1
fi

ASSET_NAME="${ASSET_NAME:-constructos-client-bundle-${VERSION}.tar.gz}"
ASSET_URL="${BUNDLE_URL}/${ASSET_NAME}"
TMP_ARCHIVE="$(mktemp -t constructos-client.XXXXXX.tar.gz)"
trap 'rm -f "$TMP_ARCHIVE"' EXIT

curl -fsSL --retry 3 "$ASSET_URL" -o "$TMP_ARCHIVE"

mkdir -p "$INSTALL_DIR"
tar -xzf "$TMP_ARCHIVE" -C "$INSTALL_DIR" --strip-components=1

echo "Client bundle installed to: ${INSTALL_DIR}"
echo "Source URL: ${ASSET_URL}"
echo "Next steps:"
echo "1) cd ${INSTALL_DIR}"
echo "2) cp .env.example .env"
echo "3) edit .env values"
echo "4) DEPLOY_SOURCE=ghcr IMAGE_TAG=${VERSION} ./scripts/deploy-client.sh"
