from __future__ import annotations

from plugins.team_mode.task_roles import (
    derive_task_role,
    ensure_team_mode_labels,
    normalize_team_agents,
    pick_agent_for_task,
)


def test_derive_task_role_accepts_lowercase_tm_role_label() -> None:
    role = derive_task_role(
        task_like={"labels": ["tm.role:developer"], "status": "To do", "assignee_id": "u1"},
        member_role_by_user_id={},
        allow_status_fallback=False,
    )
    assert role == "Developer"


def test_derive_task_role_prefers_assigned_agent_code_mapping() -> None:
    role = derive_task_role(
        task_like={
            "labels": [],
            "status": "Blocked",
            "assignee_id": "u-owner",
            "assigned_agent_code": "dev-a",
        },
        member_role_by_user_id={"u-owner": "Owner"},
        agent_role_by_code={"dev-a": "Developer", "qa-a": "QA"},
        allow_status_fallback=True,
    )
    assert role == "Developer"


def test_pick_agent_for_task_selects_matching_slot() -> None:
    agents = normalize_team_agents(
        {
            "agents": [
                {"id": "dev-a", "name": "Developer A", "authority_role": "Developer", "executor_user_id": "u-dev"},
                {"id": "qa-a", "name": "QA A", "authority_role": "QA", "executor_user_id": "u-qa"},
            ]
        }
    )
    selected = pick_agent_for_task(
        agents=agents,
        task_like={"id": "t1", "assigned_agent_code": "qa-a", "status": "QA", "assignee_id": "u-any"},
        member_role_by_user_id={},
    )
    assert selected is not None
    assert selected["id"] == "qa-a"


def test_ensure_team_mode_labels_replaces_old_role_and_strips_slot_labels() -> None:
    labels = ensure_team_mode_labels(
        labels=["bug", "tm.role:qaagent", "tm.agent:qa-a"],
        role="Developer",
        agent_slot="dev-a",
    )
    assert "bug" in labels
    assert "tm.role:Developer" in labels
    assert all(not str(label).startswith("tm.agent:") for label in labels)
    assert all(label != "tm.role:qaagent" for label in labels)
