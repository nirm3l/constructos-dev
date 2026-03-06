from __future__ import annotations

from .task_roles import canonicalize_role

TEAM_MODE_AGENT_PROJECT_ROLES = {"Lead", "Developer", "QA"}


def is_team_mode_agent_project_role(role: str | None) -> bool:
    return canonicalize_role(role) in TEAM_MODE_AGENT_PROJECT_ROLES


def is_team_mode_developer_role(role: str | None) -> bool:
    return canonicalize_role(role) == "Developer"


def is_team_mode_qa_role(role: str | None) -> bool:
    return canonicalize_role(role) == "QA"


def is_team_mode_lead_role(role: str | None) -> bool:
    return canonicalize_role(role) == "Lead"


def is_team_mode_kickoff_instruction(instruction: str) -> bool:
    return str(instruction or "").strip().casefold().startswith("team mode kickoff for project ")


def is_team_lead_recurring_oversight_task(state: dict | None) -> bool:
    source = dict(state or {})
    if str(source.get("task_type") or "").strip() != "scheduled_instruction":
        return False
    triggers = source.get("execution_triggers") or []
    if not isinstance(triggers, list):
        return False
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        if str(trigger.get("kind") or "").strip() != "schedule":
            continue
        recurring_rule = str(trigger.get("recurring_rule") or "").strip()
        run_on_statuses = [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
        if recurring_rule and "Lead" in run_on_statuses:
            return True
    return False
