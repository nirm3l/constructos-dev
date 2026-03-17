from plugins.team_mode.state_machine import evaluate_team_mode_transition


def _workflow() -> dict:
    return {
        "statuses": ["To do", "Dev", "Lead", "QA", "Done", "Blocked"],
        "transitions": [
            {"from": "To do", "to": "Dev", "allowed_roles": ["Developer", "Lead"]},
            {"from": "Dev", "to": "Lead", "allowed_roles": ["Developer"]},
            {"from": "Lead", "to": "QA", "allowed_roles": ["Lead"]},
            {"from": "QA", "to": "Done", "allowed_roles": ["QA"]},
            {"from": "Dev", "to": "Blocked", "allowed_roles": ["Developer", "Lead"]},
        ],
    }


def test_team_mode_transition_allows_declared_role() -> None:
    allowed, reason = evaluate_team_mode_transition(
        workflow=_workflow(),
        from_status="Dev",
        to_status="Lead",
        actor_role="Developer",
    )
    assert allowed is True
    assert reason == "allowed"


def test_team_mode_transition_denies_wrong_role() -> None:
    allowed, reason = evaluate_team_mode_transition(
        workflow=_workflow(),
        from_status="Dev",
        to_status="Lead",
        actor_role="QA",
    )
    assert allowed is False
    assert reason == "actor_role_not_permitted"


def test_team_mode_transition_denies_undeclared_edge() -> None:
    allowed, reason = evaluate_team_mode_transition(
        workflow=_workflow(),
        from_status="Dev",
        to_status="QA",
        actor_role="Developer",
    )
    assert allowed is False
    assert reason == "transition_not_declared"

