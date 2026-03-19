#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
FRONTEND_PACKAGE_FILE = ROOT / "app" / "frontend" / "package.json"
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump_patch(version: str) -> str:
    match = SEMVER_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Unsupported VERSION format: {version!r}. Expected x.y.z")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def read_version() -> str:
    if not VERSION_FILE.exists():
        return "1.0.0"
    return VERSION_FILE.read_text(encoding="utf-8").strip() or "1.0.0"


def write_version(version: str) -> None:
    VERSION_FILE.write_text(f"{version}\n", encoding="utf-8")


def write_frontend_package_version(version: str) -> None:
    package = json.loads(FRONTEND_PACKAGE_FILE.read_text(encoding="utf-8"))
    package["version"] = version
    FRONTEND_PACKAGE_FILE.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump VERSION patch segment.")
    parser.add_argument(
        "--update-frontend-package",
        action="store_true",
        help="Also update app/frontend/package.json version to match VERSION.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print next version without writing files.",
    )
    args = parser.parse_args()

    current = read_version()
    nxt = bump_patch(current)
    if args.dry_run:
        print(nxt)
        return
    write_version(nxt)
    if args.update_frontend_package:
        write_frontend_package_version(nxt)
    print(nxt)


if __name__ == "__main__":
    main()
