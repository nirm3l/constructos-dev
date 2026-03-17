from __future__ import annotations

from plugins.team_mode.semantics import (
    REQUIRED_SEMANTIC_STATUSES,
    default_team_mode_config,
    derive_phase_from_status_and_role,
    semantic_status_key,
)
from shared.team_mode_lifecycle import developer_success_transition
from shared.settings import DEFAULT_USER_ID


def test_default_team_mode_config_has_resolved_human_owner() -> None:
    config = default_team_mode_config()

    assert config["oversight"]["human_owner_user_id"] == DEFAULT_USER_ID


def test_semantic_status_key_maps_required_statuses() -> None:
    assert semantic_status_key(status="To do") == "todo"
    assert semantic_status_key(status="In Progress") == "active"
    assert semantic_status_key(status="Completed") == "completed"


def test_phase_derivation_matches_single_task_lifecycle() -> None:
    assert derive_phase_from_status_and_role(status="To do", assignee_role="Developer") == "implementation"
    assert derive_phase_from_status_and_role(status="In Review", assignee_role="Developer") == "in_review"
    assert derive_phase_from_status_and_role(status="In Progress", assignee_role="Lead") == "deployment"
    assert derive_phase_from_status_and_role(status="In Progress", assignee_role="QA") == "qa_validation"
    assert derive_phase_from_status_and_role(status=REQUIRED_SEMANTIC_STATUSES["completed"], assignee_role="QA") == "completed"


def test_developer_success_transition_keeps_deployable_slice_active_for_lead() -> None:
    transition = developer_success_transition(
        review_required=False,
        requires_deploy=True,
        completed_status=REQUIRED_SEMANTIC_STATUSES["completed"],
    )

    assert transition["status"] == REQUIRED_SEMANTIC_STATUSES["active"]
    assert transition["phase"] == "deploy_ready"
    assert transition["next_role"] == "Lead"
    assert transition["terminal"] is False
