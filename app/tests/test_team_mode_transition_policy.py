from __future__ import annotations

from plugins.team_mode.state_machine import evaluate_team_mode_transition
from plugins.team_mode.semantics import REQUIRED_SEMANTIC_STATUSES


def test_transition_allows_developer_to_request_review() -> None:
    allowed, reason = evaluate_team_mode_transition(
        status_semantics=REQUIRED_SEMANTIC_STATUSES,
        from_status="In Progress",
        to_status="In Review",
        actor_role="Developer",
    )
    assert allowed is True
    assert reason == "allowed"


def test_transition_denies_qa_to_request_review() -> None:
    allowed, reason = evaluate_team_mode_transition(
        status_semantics=REQUIRED_SEMANTIC_STATUSES,
        from_status="In Progress",
        to_status="In Review",
        actor_role="QA",
    )
    assert allowed is False
    assert reason == "actor_role_not_permitted"


def test_transition_allows_lead_to_move_task_back_to_todo() -> None:
    allowed, reason = evaluate_team_mode_transition(
        status_semantics=REQUIRED_SEMANTIC_STATUSES,
        from_status="Blocked",
        to_status="To do",
        actor_role="Lead",
    )
    assert allowed is True
    assert reason == "allowed"


def test_transition_allows_qa_to_complete() -> None:
    allowed, reason = evaluate_team_mode_transition(
        status_semantics=REQUIRED_SEMANTIC_STATUSES,
        from_status="In Progress",
        to_status="Completed",
        actor_role="QA",
    )
    assert allowed is True
    assert reason == "allowed"
