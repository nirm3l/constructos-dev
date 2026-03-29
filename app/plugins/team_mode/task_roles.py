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
    agent_role_by_code: dict[str, str] | None = None,
) -> str:
    assigned_agent_code = str(task_like.get("assigned_agent_code") or "").strip()
    if assigned_agent_code and isinstance(agent_role_by_code, dict):
        assigned_agent_role = str(agent_role_by_code.get(assigned_agent_code) or "").strip()
        assigned_agent_role_canonical = _LEGACY_ROLE_ALIASES.get(assigned_agent_role.casefold()) or assigned_agent_role
        if assigned_agent_role_canonical in TEAM_MODE_ROLES:
            return assigned_agent_role_canonical
    labels_role = extract_role_from_labels(task_like.get("labels"))
    if labels_role:
        return labels_role
    assignee_id = str(task_like.get("assignee_id") or "").strip()
    if assignee_id and isinstance(member_role_by_user_id, dict):
        member_role = str(member_role_by_user_id.get(assignee_id) or "").strip()
        member_role_canonical = _LEGACY_ROLE_ALIASES.get(member_role.casefold()) or member_role
        if member_role_canonical in TEAM_MODE_ROLES:
            return member_role_canonical
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
    _ = role
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


def pick_agent_for_role(
    *,
    agents: list[dict[str, str]],
    authority_role: str | None,
    current_load_by_agent_code: dict[str, int] | None = None,
) -> dict[str, str] | None:
    normalized_role = canonicalize_role(authority_role)
    if not agents or normalized_role not in TEAM_MODE_ROLES:
        return None
    normalized_loads = {
        str(agent.get("id") or "").strip(): 0
        for agent in agents
        if str(agent.get("id") or "").strip()
    }
    for agent_code, raw_load in dict(current_load_by_agent_code or {}).items():
        normalized_agent_code = str(agent_code or "").strip()
        if not normalized_agent_code or normalized_agent_code not in normalized_loads:
            continue
        try:
            normalized_loads[normalized_agent_code] = max(0, int(raw_load))
        except Exception:
            normalized_loads[normalized_agent_code] = 0
    candidates: list[tuple[int, int, dict[str, str]]] = []
    for index, agent in enumerate(agents):
        agent_id = str(agent.get("id") or "").strip()
        agent_role = canonicalize_role(agent.get("authority_role"))
        if not agent_id or agent_role != normalized_role:
            continue
        candidates.append((int(normalized_loads.get(agent_id) or 0), index, agent))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def build_active_agent_load_by_code(
    *,
    agents: list[dict[str, str]],
    task_likes: list[dict[str, Any]],
    member_role_by_user_id: dict[str, str] | None = None,
    agent_role_by_code: dict[str, str] | None = None,
) -> dict[str, int]:
    load_by_agent_code = {
        str(agent.get("id") or "").strip(): 0
        for agent in agents
        if str(agent.get("id") or "").strip()
    }
    if not load_by_agent_code:
        return {}
    for task_like in task_likes:
        if not isinstance(task_like, dict):
            continue
        automation_state = str(task_like.get("automation_state") or "idle").strip().lower()
        if automation_state not in {"queued", "running"}:
            continue
        assigned_agent_code = str(task_like.get("assigned_agent_code") or "").strip()
        dispatch_slot = str(task_like.get("dispatch_slot") or "").strip()
        if assigned_agent_code in load_by_agent_code:
            load_by_agent_code[assigned_agent_code] = int(load_by_agent_code.get(assigned_agent_code) or 0) + 1
            continue
        if dispatch_slot in load_by_agent_code:
            load_by_agent_code[dispatch_slot] = int(load_by_agent_code.get(dispatch_slot) or 0) + 1
            continue
        role = derive_task_role(
            task_like=task_like,
            member_role_by_user_id=member_role_by_user_id,
            agent_role_by_code=agent_role_by_code,
        )
        selected_agent = pick_agent_for_role(
            agents=agents,
            authority_role=role,
            current_load_by_agent_code=load_by_agent_code,
        )
        selected_agent_code = str((selected_agent or {}).get("id") or "").strip()
        if not selected_agent_code:
            continue
        load_by_agent_code[selected_agent_code] = int(load_by_agent_code.get(selected_agent_code) or 0) + 1
    return load_by_agent_code


def pick_agent_for_task(
    *,
    agents: list[dict[str, str]],
    task_like: dict[str, Any],
    member_role_by_user_id: dict[str, str] | None = None,
    agent_role_by_code: dict[str, str] | None = None,
    current_load_by_agent_code: dict[str, int] | None = None,
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
        agent_role_by_code=agent_role_by_code,
    )
    if not role:
        return None
    return pick_agent_for_role(
        agents=agents,
        authority_role=role,
        current_load_by_agent_code=current_load_by_agent_code,
    )
