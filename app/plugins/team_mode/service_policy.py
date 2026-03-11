from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select

from shared.models import ProjectMember, ProjectPluginConfig, Task
from .task_roles import canonicalize_role, derive_task_role


def project_has_team_mode_enabled(*, db: Any, workspace_id: str, project_id: str) -> bool:
    row = db.execute(
        select(ProjectPluginConfig.id).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == "team_mode",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def open_developer_tasks(*, db: Any, project_id: str) -> list[dict[str, str]]:
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(ProjectMember.project_id == project_id)
        ).all()
    }
    rows = db.execute(
        select(Task.id, Task.title, Task.status, Task.assignee_id, Task.labels)
        .where(
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
        .order_by(Task.created_at.asc())
    ).all()
    blocking_statuses = {"Dev", "Blocked", "To do"}
    return [
        {
            "task_id": str(task_id or "").strip(),
            "title": str(title or "").strip(),
            "status": str(status or "").strip(),
        }
        for task_id, title, status, assignee_id, labels in rows
        if derive_task_role(
            task_like={
                "assignee_id": str(assignee_id or "").strip(),
                "labels": labels,
                "status": str(status or "").strip(),
            },
            member_role_by_user_id=member_role_by_user_id,
        )
        == "Developer"
        if str(task_id or "").strip() and str(status or "").strip() in blocking_statuses
    ]


def enforce_done_transition(
    *,
    db: Any,
    state: Any,
    assignee_role: str,
    verify_delivery_workflow_fn: Callable[..., dict],
    auth_token: str | None,
) -> None:
    project_id = str(state.project_id or "").strip()
    workspace_id = str(state.workspace_id or "").strip()
    if not project_id or not workspace_id:
        return
    if not project_has_team_mode_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
        return

    open_dev = open_developer_tasks(db=db, project_id=project_id)

    if canonicalize_role(assignee_role) == "QA":
        delivery = verify_delivery_workflow_fn(
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        required_checks = [
            "repo_context_present",
            "git_contract_ok",
            "compose_manifest_present",
            "lead_deploy_decision_evidence_present",
            "deploy_execution_evidence_present",
            "qa_handoff_current_cycle_ok",
            "deploy_serves_application_root",
            "qa_has_verifiable_artifacts",
        ]
        failing = [check for check in required_checks if not bool((delivery.get("checks") or {}).get(check))]
        if open_dev:
            failing.append("dev_tasks_all_done")
        if failing:
            raise HTTPException(
                status_code=409,
                detail=(
                    "QA Done transition blocked by Team Mode closeout guards. "
                    f"failed_checks={failing}; "
                    f"open_dev_tasks={[item['task_id'] for item in open_dev]}"
                ),
            )
        return

    if canonicalize_role(assignee_role) == "Lead":
        if open_dev:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Lead Done transition blocked: open Dev tasks remain. "
                    f"open_dev_tasks={[item['task_id'] for item in open_dev]}"
                ),
            )

        delivery = verify_delivery_workflow_fn(
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        required_checks = [
            "repo_context_present",
            "git_contract_ok",
            "compose_manifest_present",
            "lead_deploy_decision_evidence_present",
            "qa_handoff_current_cycle_ok",
            "deploy_serves_application_root",
            "qa_has_verifiable_artifacts",
            "deploy_execution_evidence_present",
        ]
        failing = [check for check in required_checks if not bool((delivery.get("checks") or {}).get(check))]
        if failing:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Lead Done transition blocked by Team Mode delivery closeout guards. "
                    f"failed_checks={failing}"
                ),
            )
