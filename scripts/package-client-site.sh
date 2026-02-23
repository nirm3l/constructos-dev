#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${VERSION:-$(git describe --tags --always 2>/dev/null || date -u +"%Y%m%d%H%M%S")}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/dist}"
SITE_DIR="${SITE_DIR:-${OUTPUT_DIR}/client-site}"
CLIENT_DIR="${SITE_DIR}/client"
BUNDLE_ARCHIVE="${OUTPUT_DIR}/constructos-client-bundle-${VERSION}.tar.gz"

VERSION="$VERSION" OUTPUT_DIR="$OUTPUT_DIR" ./scripts/package-client-bundle.sh

mkdir -p "$CLIENT_DIR"
cp scripts/install-client.sh "${SITE_DIR}/install.sh"
cp "$BUNDLE_ARCHIVE" "$CLIENT_DIR/"
printf '%s\n' "$VERSION" > "${CLIENT_DIR}/latest.txt"

(cd "$CLIENT_DIR" && sha256sum "constructos-client-bundle-${VERSION}.tar.gz" > "constructos-client-bundle-${VERSION}.tar.gz.sha256")

echo "Client site bundle prepared:"
echo "- Installer: ${SITE_DIR}/install.sh"
echo "- Bundle: ${CLIENT_DIR}/constructos-client-bundle-${VERSION}.tar.gz"
echo "- Latest marker: ${CLIENT_DIR}/latest.txt"
echo "- Checksum: ${CLIENT_DIR}/constructos-client-bundle-${VERSION}.tar.gz.sha256"
