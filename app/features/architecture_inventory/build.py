from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from features.agents.capability_registry import build_capability_registry

_INDEX_LINE_RE = re.compile(r"^\d+\.\s+`([^`]+\.md)`")
_BACKTICKED_DOC_RE = re.compile(r"`([^`]+\.md)`")


def _repo_root() -> Path:
    module_path = Path(__file__).resolve()
    # Support both repository checkout layout (`.../task-management/app/features/...`)
    # and container image layout where the app is copied into `/app`.
    for candidate in [*module_path.parents]:
        docs_index = candidate / "docs" / "internal" / "00-index.md"
        if docs_index.exists():
            return candidate
    # Safe fallback for environments where docs are intentionally omitted.
    return module_path.parents[2]


def _docs_internal_root() -> Path:
    return _repo_root() / "docs" / "internal"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _empty_internal_docs_inventory(*, docs_root: Path, index_path: Path, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "root": str(docs_root),
        "index_path": str(index_path),
        "reading_order": [],
        "referenced_docs": [],
        "existing_docs": [],
        "missing_from_reading_order": [],
        "unreferenced_docs": [],
    }


def build_internal_docs_inventory() -> dict[str, Any]:
    docs_root = _docs_internal_root()
    index_path = docs_root / "00-index.md"
    if not docs_root.exists():
        return _empty_internal_docs_inventory(
            docs_root=docs_root,
            index_path=index_path,
            reason="internal_docs_directory_missing",
        )
    if not index_path.exists():
        return _empty_internal_docs_inventory(
            docs_root=docs_root,
            index_path=index_path,
            reason="internal_docs_index_missing",
        )
    index_text = _read_text(index_path)
    reading_order: list[str] = []
    for line in index_text.splitlines():
        match = _INDEX_LINE_RE.match(line.strip())
        if match:
            reading_order.append(match.group(1))
    existing_docs = sorted(path.name for path in docs_root.glob("*.md"))
    referenced_docs = sorted({match.group(1) for match in _BACKTICKED_DOC_RE.finditer(index_text)})
    missing_from_reading_order = [name for name in reading_order if not (docs_root / name).exists()]
    unreferenced_docs = [name for name in existing_docs if name not in referenced_docs]
    return {
        "available": True,
        "reason": "",
        "root": str(docs_root),
        "index_path": str(index_path),
        "reading_order": reading_order,
        "referenced_docs": referenced_docs,
        "existing_docs": existing_docs,
        "missing_from_reading_order": missing_from_reading_order,
        "unreferenced_docs": unreferenced_docs,
    }


def build_architecture_inventory() -> dict[str, Any]:
    capabilities = build_capability_registry()
    internal_docs = build_internal_docs_inventory()
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo_root": str(_repo_root()),
        "capabilities": capabilities,
        "internal_docs": internal_docs,
        "counts": {
            **dict(capabilities.get("counts") or {}),
            "internal_docs": len(internal_docs.get("existing_docs") or []),
            "internal_docs_reading_order": len(internal_docs.get("reading_order") or []),
        },
    }
