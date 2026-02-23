#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${VERSION:-$(git describe --tags --always 2>/dev/null || date -u +"%Y%m%d%H%M%S")}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/dist}"
BUNDLE_ROOT="constructos-client-bundle-${VERSION}"
STAGING_DIR="${OUTPUT_DIR}/${BUNDLE_ROOT}"
ARCHIVE_PATH="${OUTPUT_DIR}/${BUNDLE_ROOT}.tar.gz"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/scripts"

cp docker-compose.client.yml "$STAGING_DIR/docker-compose.client.yml"
cp docker-compose.ubuntu-gpu.yml "$STAGING_DIR/docker-compose.ubuntu-gpu.yml"
cp docker-compose.macos-m4.yml "$STAGING_DIR/docker-compose.macos-m4.yml"
cp .env.client.example "$STAGING_DIR/.env.example"
cp scripts/deploy-core.sh "$STAGING_DIR/scripts/deploy-core.sh"
cp scripts/deploy-client.sh "$STAGING_DIR/scripts/deploy-client.sh"

chmod +x "$STAGING_DIR/scripts/deploy-core.sh" "$STAGING_DIR/scripts/deploy-client.sh"

cat > "$STAGING_DIR/README.txt" <<'EOF'
Constructos Client Deployment Bundle
===================================

1) Copy env template and edit values:
   cp .env.example .env

2) Deploy:
   DEPLOY_SOURCE=ghcr IMAGE_TAG=vX.Y.Z ./scripts/deploy-client.sh

Notes:
- This bundle excludes marketing-site and license-control-plane services.
- Main compose file: docker-compose.client.yml
- Default image names:
  ghcr.io/nirm3l/constructos-task-app:<tag>
  ghcr.io/nirm3l/constructos-mcp-tools:<tag>
EOF

mkdir -p "$OUTPUT_DIR"
tar -czf "$ARCHIVE_PATH" -C "$OUTPUT_DIR" "$BUNDLE_ROOT"

echo "Client bundle prepared:"
echo "- Folder:  $STAGING_DIR"
echo "- Archive: $ARCHIVE_PATH"
