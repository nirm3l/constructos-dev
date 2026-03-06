from __future__ import annotations

import re
from typing import Any


_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)


def _is_team_mode_developer_role(role: str | None) -> bool:
    return str(role or "").strip().lower() == "developeragent"


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


def _extract_commit_shas_from_text(text: str | None) -> set[str]:
    raw = str(text or "")
    return {str(match).lower() for match in _COMMIT_SHA_EXPLICIT_RE.findall(raw)}


def _is_noop_ack_comment(comment: str | None) -> bool:
    normalized = str(comment or "").strip().casefold()
    if not normalized:
        return False
    return normalized.startswith("codex runner: request accepted, leaving progress note.")


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
        del db, workspace_id, project_id, task_id, action
        if not has_git_delivery_skill:
            return None
        if not _is_team_mode_developer_role(assignee_role):
            return None
        state = dict(task_state or {})
        if str(state.get("status") or "").strip() != "Dev":
            return None
        ref_commit_shas = _extract_commit_shas_from_refs(state.get("external_refs"))
        comment_commit_shas = _extract_commit_shas_from_text(comment) | _extract_commit_shas_from_text(summary)
        has_commit_evidence = bool(ref_commit_shas or comment_commit_shas)
        if has_commit_evidence:
            return None
        if _is_noop_ack_comment(comment):
            return "Developer automation produced acknowledgement only and no commit evidence (git_delivery)."
        return "Developer automation completed without commit evidence (git_delivery)."
