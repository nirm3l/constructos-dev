from __future__ import annotations

import re
from pathlib import Path


def test_frontend_bootstrap_consumers_do_not_use_legacy_config_mirror():
    repo_root = Path(__file__).resolve().parents[5]
    frontend_src = repo_root / "app" / "frontend" / "src"
    assert frontend_src.exists()

    legacy_patterns = (
        re.compile(r"bootstrap\.data\?\.\s*config\b"),
        re.compile(r"bootstrap\.data\.\s*config\b"),
        re.compile(r"bootstrap\.data\?\.\s*\[\s*['\"]config['\"]\s*\]"),
        re.compile(r"bootstrap\.data\.\s*\[\s*['\"]config['\"]\s*\]"),
    )

    offenders: list[str] = []
    for path in frontend_src.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in legacy_patterns:
            if pattern.search(text):
                offenders.append(str(path.relative_to(repo_root)))
                break

    assert not offenders, (
        "Legacy bootstrap.config mirror consumers detected in frontend. "
        "Use root bootstrap fields instead: "
        + ", ".join(sorted(offenders))
    )
