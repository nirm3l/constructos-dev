from __future__ import annotations

from features.tasks.command_handlers import _is_team_mode_transition_allowed


def test_transition_allowed_when_declared_and_role_matches() -> None:
    allowed, reason = _is_team_mode_transition_allowed(
        workflow={
            "statuses": ["To do", "Dev", "QA", "Done"],
            "transitions": [
                {"from": "Dev", "to": "QA", "allowed_roles": ["DeveloperAgent"]},
            ],
        },
        from_status="Dev",
        to_status="QA",
        actor_role="DeveloperAgent",
    )
    assert allowed is True
    assert reason == "allowed"


def test_transition_denied_when_no_transitions_declared() -> None:
    allowed, reason = _is_team_mode_transition_allowed(
        workflow={"statuses": ["To do", "Dev", "QA"], "transitions": []},
        from_status="Dev",
        to_status="QA",
        actor_role="DeveloperAgent",
    )
    assert allowed is False
    assert reason == "no_transitions_declared"


def test_transition_denied_when_target_status_not_allowed() -> None:
    allowed, reason = _is_team_mode_transition_allowed(
        workflow={
            "statuses": ["To do", "Dev", "QA"],
            "transitions": [
                {"from": "Dev", "to": "Done", "allowed_roles": ["DeveloperAgent"]},
            ],
        },
        from_status="Dev",
        to_status="Done",
        actor_role="DeveloperAgent",
    )
    assert allowed is False
    assert reason == "target_status_not_allowed"


def test_transition_denied_when_role_not_permitted() -> None:
    allowed, reason = _is_team_mode_transition_allowed(
        workflow={
            "statuses": ["To do", "Dev", "QA", "Done"],
            "transitions": [
                {"from": "Dev", "to": "QA", "allowed_roles": ["DeveloperAgent"]},
            ],
        },
        from_status="Dev",
        to_status="QA",
        actor_role="QAAgent",
    )
    assert allowed is False
    assert reason == "actor_role_not_permitted"
