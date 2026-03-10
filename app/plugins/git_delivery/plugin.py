from __future__ import annotations

import re
from typing import Any


_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)
_TASK_BRANCH_RE = re.compile(r"\btask/[a-z0-9][a-z0-9._/-]*\b", re.IGNORECASE)


def _is_team_mode_developer_role(role: str | None) -> bool:
    return str(role or "").strip().casefold() == "developer"


def _extract_commit_shas_from_refs(refs: object) -> set[str]:
    out: set[str] = set()
    if not isinstance(refs, list):
        return out
    for item in refs:
        if isinstance(item, dict):
            text = f"{item.get('url') or ''} {item.get('label') or ''}"
        else:
            text = str(item or "")
        for match in _COMMIT_SHA_EXPLICIT_RE.findall(text):
            out.add(str(match).lower())
    return out


def _extract_task_branch_evidence_from_refs(refs: object) -> set[str]:
    out: set[str] = set()
    if not isinstance(refs, list):
        return out
    for item in refs:
        if isinstance(item, dict):
            text = f"{item.get('url') or ''} {item.get('label') or ''}"
        else:
            text = str(item or "")
        for match in _TASK_BRANCH_RE.findall(text):
            out.add(str(match).lower())
    return out

class GitDeliveryPlugin:
    key = "git_delivery"

    def check_scope(self) -> str | None:
        return None

    def default_required_checks(self) -> list[str]:
        return []

    def check_descriptions(self) -> dict[str, str]:
        return {}

    def default_plugin_policy_patch(self) -> dict[str, Any]:
        return {}

    def evaluate_checks(self, _ctx, **_kwargs: Any) -> dict[str, Any]:
        return {"scope": "git_delivery", "checks": [], "required_failed": []}

    def service_is_delivery_active(self, *, skill_keys: set[str]) -> bool:
        normalized = {str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()}
        return self.key in normalized

    def runner_preflight_error(
        self,
        *,
        db: Any,
        workspace_id: str,
        project_id: str | None,
        task_status: str | None,
        assignee_role: str | None,
        has_git_delivery_skill: bool,
        has_repo_context: bool,
    ) -> str | None:
        del db, workspace_id, project_id
        if not has_git_delivery_skill:
            return None
        if not _is_team_mode_developer_role(assignee_role):
            return None
        if str(task_status or "").strip() != "Dev":
            return None
        if has_repo_context:
            return None
        return "Repository context missing for git_delivery Developer task; cannot execute delivery automation."

    def runner_success_validation_error(
        self,
        *,
        db: Any,
        workspace_id: str,
        project_id: str | None,
        task_id: str,
        task_state: dict | None,
        assignee_role: str | None,
        action: str,
        summary: str,
        comment: str | None,
        has_git_delivery_skill: bool,
    ) -> str | None:
        del db, workspace_id, project_id, task_id, action, summary, comment
        if not has_git_delivery_skill:
            return None
        if not _is_team_mode_developer_role(assignee_role):
            return None
        state = dict(task_state or {})
        if str(state.get("status") or "").strip() != "Dev":
            return None
        refs = state.get("external_refs")
        has_commit_evidence = bool(_extract_commit_shas_from_refs(refs))
        has_branch_evidence = bool(_extract_task_branch_evidence_from_refs(refs))
        if has_commit_evidence and has_branch_evidence:
            return None
        missing_parts: list[str] = []
        if not has_commit_evidence:
            missing_parts.append("commit")
        if not has_branch_evidence:
            missing_parts.append("task branch")
        missing_label = " + ".join(missing_parts) if missing_parts else "required"
        return (
            "Developer automation completed without required git_delivery evidence in external_refs "
            f"({missing_label})."
        )
