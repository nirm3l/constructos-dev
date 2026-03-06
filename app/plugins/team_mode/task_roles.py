from __future__ import annotations

import json
from typing import Any

TEAM_MODE_ROLE_LABEL_PREFIX = "tm.role:"
TEAM_MODE_ROLES = {"Developer", "QA", "Lead"}
_CANONICAL_ROLE_BY_CASEFOLD = {role.casefold(): role for role in TEAM_MODE_ROLES}
_LEGACY_ROLE_ALIASES = {
    "developeragent": "Developer",
    "qaagent": "QA",
    "teamleadagent": "Lead",
    "developer": "Developer",
    "qa": "QA",
    "lead": "Lead",
}
_STATUS_ROLE_FALLBACK = {
    "dev": "Developer",
    "qa": "QA",
    "lead": "Lead",
}


def parse_labels(raw_labels: Any) -> list[str]:
    if isinstance(raw_labels, list):
        return [str(item or "").strip() for item in raw_labels if str(item or "").strip()]
    text = str(raw_labels or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item or "").strip() for item in parsed if str(item or "").strip()]


def extract_role_from_labels(raw_labels: Any) -> str | None:
    for label in parse_labels(raw_labels):
        normalized = str(label).strip()
        if not normalized:
            continue
        lowered = normalized.casefold()
        if not lowered.startswith(TEAM_MODE_ROLE_LABEL_PREFIX):
            continue
        role = normalized[len(TEAM_MODE_ROLE_LABEL_PREFIX) :].strip()
        canonical = _CANONICAL_ROLE_BY_CASEFOLD.get(role.casefold()) or _LEGACY_ROLE_ALIASES.get(role.casefold())
        if canonical:
            return canonical
    return None


def canonicalize_role(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _LEGACY_ROLE_ALIASES.get(text.casefold(), text)


def derive_task_role(
    *,
    task_like: dict[str, Any],
    member_role_by_user_id: dict[str, str] | None = None,
    allow_status_fallback: bool = True,
) -> str:
    labels_role = extract_role_from_labels(task_like.get("labels"))
    if labels_role:
        return labels_role
    assignee_id = str(task_like.get("assignee_id") or "").strip()
    if assignee_id and isinstance(member_role_by_user_id, dict):
        member_role = str(member_role_by_user_id.get(assignee_id) or "").strip()
        member_role_canonical = _LEGACY_ROLE_ALIASES.get(member_role.casefold()) or member_role
        if member_role_canonical in TEAM_MODE_ROLES:
            return member_role_canonical
    if allow_status_fallback:
        status_key = str(task_like.get("status") or "").strip().casefold()
        return _STATUS_ROLE_FALLBACK.get(status_key, "")
    return ""


def ensure_team_mode_labels(
    *,
    labels: list[str] | None,
    role: str | None,
    agent_slot: str | None = None,
) -> list[str]:
    normalized_labels = [str(item or "").strip() for item in (labels or []) if str(item or "").strip()]
    stripped = [
        label
        for label in normalized_labels
        if not label.casefold().startswith(TEAM_MODE_ROLE_LABEL_PREFIX)
        and not label.casefold().startswith("tm.agent:")
    ]
    normalized_role = str(role or "").strip()
    if normalized_role in TEAM_MODE_ROLES:
        stripped.append(f"{TEAM_MODE_ROLE_LABEL_PREFIX}{normalized_role}")
    _ = agent_slot
    out: list[str] = []
    seen: set[str] = set()
    for label in stripped:
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def normalize_team_agents(raw_team: Any) -> list[dict[str, str]]:
    if not isinstance(raw_team, dict):
        return []
    raw_agents = raw_team.get("agents")
    if not isinstance(raw_agents, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw_agents:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        authority_role = str(item.get("authority_role") or "").strip()
        authority_role = _LEGACY_ROLE_ALIASES.get(authority_role.casefold()) or authority_role
        executor_user_id = str(item.get("executor_user_id") or "").strip()
        if not agent_id or authority_role not in TEAM_MODE_ROLES:
            continue
        out.append(
            {
                "id": agent_id,
                "name": name,
                "authority_role": authority_role,
                "executor_user_id": executor_user_id,
            }
        )
    return out


def pick_agent_for_task(
    *,
    agents: list[dict[str, str]],
    task_like: dict[str, Any],
    member_role_by_user_id: dict[str, str] | None = None,
) -> dict[str, str] | None:
    if not agents:
        return None
    explicit_code = str(task_like.get("assigned_agent_code") or "").strip()
    if explicit_code:
        for agent in agents:
            if str(agent.get("id") or "").strip() == explicit_code:
                return agent
    role = derive_task_role(
        task_like=task_like,
        member_role_by_user_id=member_role_by_user_id,
        allow_status_fallback=True,
    )
    if not role:
        return None
    candidates = [agent for agent in agents if str(agent.get("authority_role") or "").strip() == role]
    if not candidates:
        return None
    # Deterministic spread by task id when multiple slots share the same role.
    task_id = str(task_like.get("id") or "").strip()
    if task_id and len(candidates) > 1:
        idx = sum(ord(ch) for ch in task_id) % len(candidates)
        return candidates[idx]
    return candidates[0]
