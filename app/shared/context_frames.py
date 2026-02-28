from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from .knowledge_graph import build_graph_context_pack
from .models import (
    ContextSessionState,
    Note,
    Project,
    ProjectRule,
    ProjectSkill,
    SessionLocal,
    Specification,
    Task,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat()


def _project_context_revision(db, *, project_id: str) -> str:
    project = db.get(Project, project_id)
    if project is None or bool(project.is_deleted):
        return "missing"
    rows = [
        ("project", project.updated_at, 1),
        (
            "task",
            db.execute(
                select(func.max(Task.updated_at), func.count(Task.id)).where(
                    Task.project_id == project_id, Task.is_deleted == False  # noqa: E712
                )
            ).one_or_none(),
            None,
        ),
        (
            "note",
            db.execute(
                select(func.max(Note.updated_at), func.count(Note.id)).where(
                    Note.project_id == project_id, Note.is_deleted == False  # noqa: E712
                )
            ).one_or_none(),
            None,
        ),
        (
            "specification",
            db.execute(
                select(func.max(Specification.updated_at), func.count(Specification.id)).where(
                    Specification.project_id == project_id, Specification.is_deleted == False  # noqa: E712
                )
            ).one_or_none(),
            None,
        ),
        (
            "rule",
            db.execute(
                select(func.max(ProjectRule.updated_at), func.count(ProjectRule.id)).where(
                    ProjectRule.project_id == project_id, ProjectRule.is_deleted == False  # noqa: E712
                )
            ).one_or_none(),
            None,
        ),
        (
            "skill",
            db.execute(
                select(func.max(ProjectSkill.updated_at), func.count(ProjectSkill.id)).where(
                    ProjectSkill.project_id == project_id, ProjectSkill.is_deleted == False  # noqa: E712
                )
            ).one_or_none(),
            None,
        ),
    ]
    payload: dict[str, Any] = {"project_id": project_id}
    for label, raw, fallback_count in rows:
        max_updated_at: datetime | None = None
        count = int(fallback_count or 0)
        if hasattr(raw, "_mapping"):
            values = list(raw._mapping.values())  # type: ignore[attr-defined]
            if len(values) >= 1 and isinstance(values[0], datetime):
                max_updated_at = values[0]
            if len(values) >= 2:
                try:
                    count = int(values[1] or 0)
                except Exception:
                    count = int(fallback_count or 0)
        elif isinstance(raw, tuple):
            if len(raw) >= 1 and isinstance(raw[0], datetime):
                max_updated_at = raw[0]
            if len(raw) >= 2:
                try:
                    count = int(raw[1] or 0)
                except Exception:
                    count = int(fallback_count or 0)
        elif isinstance(raw, datetime):
            max_updated_at = raw
            count = max(1, int(fallback_count or 1))
        payload[f"{label}_max_updated_at"] = _as_iso(max_updated_at if isinstance(max_updated_at, datetime) else None)
        payload[f"{label}_count"] = count
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _collect_delta_lines(db, *, project_id: str, since: datetime | None, max_items: int = 6) -> tuple[str, dict[str, int]]:
    if since is None:
        return "_(no prior frame timestamp)_", {"tasks": 0, "notes": 0, "specifications": 0, "rules": 0, "skills": 0}
    counts = {"tasks": 0, "notes": 0, "specifications": 0, "rules": 0, "skills": 0}

    def _top_changes(model, label: str, title_col, deleted_col):
        rows = db.execute(
            select(title_col, model.updated_at)
            .where(model.project_id == project_id, deleted_col == False, model.updated_at >= since)  # noqa: E712
            .order_by(model.updated_at.desc())
            .limit(max_items)
        ).all()
        counts[label] = len(rows)
        return [f"- {str(row[0] or '').strip() or '(untitled)'}" for row in rows if str(row[0] or "").strip() or True]

    parts: list[str] = []
    task_lines = _top_changes(Task, "tasks", Task.title, Task.is_deleted)
    if task_lines:
        parts.append("Updated tasks:\n" + "\n".join(task_lines))
    note_lines = _top_changes(Note, "notes", Note.title, Note.is_deleted)
    if note_lines:
        parts.append("Updated notes:\n" + "\n".join(note_lines))
    spec_lines = _top_changes(Specification, "specifications", Specification.title, Specification.is_deleted)
    if spec_lines:
        parts.append("Updated specifications:\n" + "\n".join(spec_lines))
    rule_lines = _top_changes(ProjectRule, "rules", ProjectRule.title, ProjectRule.is_deleted)
    if rule_lines:
        parts.append("Updated rules:\n" + "\n".join(rule_lines))
    skill_lines = _top_changes(ProjectSkill, "skills", ProjectSkill.name, ProjectSkill.is_deleted)
    if skill_lines:
        parts.append("Updated skills:\n" + "\n".join(skill_lines))
    if not parts:
        return "_(no project deltas since last frame)_", counts
    return "\n\n".join(parts), counts


def build_project_context_frame(
    *,
    workspace_id: str | None,
    project_id: str | None,
    scope_type: str,
    scope_id: str,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    project_key = str(project_id or "").strip()
    scope_type_key = str(scope_type or "").strip().lower() or "generic"
    scope_id_key = str(scope_id or "").strip() or "default"
    if not project_key:
        return {
            "mode": "full",
            "revision": "",
            "markdown": "_(project context unavailable)_",
            "evidence": [],
            "summary_markdown": "_(summary unavailable)_",
            "delta_counts": {},
        }

    with SessionLocal() as db:
        revision = _project_context_revision(db, project_id=project_key)
        state = db.execute(
            select(ContextSessionState).where(
                ContextSessionState.scope_type == scope_type_key,
                ContextSessionState.scope_id == scope_id_key,
            )
        ).scalar_one_or_none()
        now = _utc_now()
        is_full = state is None or str(state.context_revision or "").strip() != revision

        if is_full:
            pack = build_graph_context_pack(
                project_id=project_key,
                focus_entity_type=focus_entity_type,
                focus_entity_id=focus_entity_id,
                limit=max(1, int(limit)),
            ) or {}
            markdown = str(pack.get("markdown") or "").strip() or "_(knowledge graph unavailable)_"
            evidence = pack.get("evidence") or []
            summary = str((pack.get("summary") or {}).get("executive") or "").strip()
            summary_markdown = summary or "_(summary unavailable)_"
            delta_counts = {}
            mode = "full"
        else:
            markdown, delta_counts = _collect_delta_lines(
                db,
                project_id=project_key,
                since=state.last_frame_at,
                max_items=6,
            )
            evidence = []
            summary_markdown = "Delta frame over prior project context."
            mode = "delta"

        snapshot = {
            "mode": mode,
            "revision": revision,
            "focus_entity_type": str(focus_entity_type or ""),
            "focus_entity_id": str(focus_entity_id or ""),
            "delta_counts": delta_counts,
        }
        if state is None:
            state = ContextSessionState(
                workspace_id=str(workspace_id or "").strip() or None,
                project_id=project_key,
                scope_type=scope_type_key,
                scope_id=scope_id_key,
                context_revision=revision,
                last_frame_mode=mode,
                last_frame_at=now,
                snapshot_json=json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            )
            db.add(state)
        else:
            state.workspace_id = str(workspace_id or state.workspace_id or "").strip() or None
            state.project_id = project_key
            state.context_revision = revision
            state.last_frame_mode = mode
            state.last_frame_at = now
            state.snapshot_json = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        db.commit()
        return {
            "mode": mode,
            "revision": revision,
            "markdown": markdown,
            "evidence": evidence,
            "summary_markdown": summary_markdown,
            "delta_counts": delta_counts,
        }
