#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_ROOT = REPO_ROOT / "app" / "features"
TARGET_FILE_NAMES = {"api.py", "application.py", "command_handlers.py"}
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "scripts" / "cqrs_guardrails_allowlist.json"


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    pattern: re.Pattern[str]
    description: str


@dataclass(frozen=True, slots=True)
class AllowlistEntry:
    path: str
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    line: int
    source: str
    rule_key: str
    rule_description: str


RULES: tuple[Rule, ...] = (
    Rule(
        key="append_event_direct",
        pattern=re.compile(r"\bappend_event\("),
        description="Direct append_event() bypasses aggregate class usage in command/API/application layers.",
    ),
    Rule(
        key="db_add",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.add\("),
        description="Direct row insert/update via Session.add().",
    ),
    Rule(
        key="db_delete",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.delete\("),
        description="Direct row delete via Session.delete().",
    ),
    Rule(
        key="db_execute_insert",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.execute\(\s*insert\("),
        description="Direct SQL insert via Session.execute(insert(...)).",
    ),
    Rule(
        key="db_execute_update",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.execute\(\s*update\("),
        description="Direct SQL update via Session.execute(update(...)).",
    ),
    Rule(
        key="db_execute_delete",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.execute\(\s*delete\("),
        description="Direct SQL delete via Session.execute(delete(...)).",
    ),
    Rule(
        key="query_delete",
        pattern=re.compile(r"\b(?:self\.)?(?:ctx\.)?db\.query\(.*\)\.delete\("),
        description="Direct SQL delete via Query.delete().",
    ),
)


def iter_target_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if path.name in TARGET_FILE_NAMES:
            yield path


def load_allowlist(path: Path) -> list[AllowlistEntry]:
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError(f"{path} must contain a top-level 'entries' list.")

    parsed: list[AllowlistEntry] = []
    for idx, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: entries[{idx}] must be an object.")
        rel_path = str(raw.get("path") or "").strip()
        regex_text = str(raw.get("regex") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if not rel_path:
            raise ValueError(f"{path}: entries[{idx}] is missing 'path'.")
        if not regex_text:
            raise ValueError(f"{path}: entries[{idx}] is missing 'regex'.")
        if not reason:
            raise ValueError(f"{path}: entries[{idx}] is missing 'reason'.")
        try:
            compiled = re.compile(regex_text)
        except re.error as exc:
            raise ValueError(f"{path}: entries[{idx}] has invalid regex '{regex_text}': {exc}") from exc
        parsed.append(AllowlistEntry(path=rel_path, pattern=compiled, reason=reason))
    return parsed


def is_allowlisted(*, allowlist: list[AllowlistEntry], rel_path: str, source_line: str) -> bool:
    for entry in allowlist:
        if entry.path != rel_path:
            continue
        if entry.pattern.search(source_line):
            return True
    return False


def scan_file(path: Path, *, allowlist: list[AllowlistEntry]) -> list[Violation]:
    rel_path = path.relative_to(REPO_ROOT).as_posix()
    violations: list[Violation] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        source = raw_line.rstrip()
        stripped = source.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for rule in RULES:
            if not rule.pattern.search(source):
                continue
            if is_allowlisted(allowlist=allowlist, rel_path=rel_path, source_line=source):
                continue
            violations.append(
                Violation(
                    path=rel_path,
                    line=line_no,
                    source=source,
                    rule_key=rule.key,
                    rule_description=rule.description,
                )
            )
            break
    return violations


def scan_repository(*, allowlist: list[AllowlistEntry]) -> list[Violation]:
    violations: list[Violation] = []
    for target_file in iter_target_files(TARGET_ROOT):
        violations.extend(scan_file(target_file, allowlist=allowlist))
    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce CQRS write-side guardrails: command/API/application layers should not "
            "write read-model rows directly."
        )
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="Path to JSON allowlist file (default: scripts/cqrs_guardrails_allowlist.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    allowlist = load_allowlist(args.allowlist.resolve())
    violations = scan_repository(allowlist=allowlist)
    if not violations:
        print("CQRS guardrails: OK")
        return 0

    print("CQRS guardrails: violations found")
    for item in violations:
        print(
            f"- {item.path}:{item.line} [{item.rule_key}] {item.rule_description}\n"
            f"  {item.source}"
        )
    allowlist_path = args.allowlist.resolve()
    try:
        allowlist_rel = allowlist_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        allowlist_rel = allowlist_path.as_posix()
    print(
        f"\nIf an exception is intentional, add a scoped regex entry to `{allowlist_rel}` "
        "with a clear reason."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
