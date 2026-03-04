from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select

from shared.models import ProjectMember, ProjectSkill, Task


def project_has_team_mode_enabled(*, db: Any, workspace_id: str, project_id: str) -> bool:
    row = db.execute(
        select(ProjectSkill.id).where(
            ProjectSkill.workspace_id == workspace_id,
            ProjectSkill.project_id == project_id,
            ProjectSkill.skill_key == "team_mode",
            ProjectSkill.enabled == True,  # noqa: E712
            ProjectSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def open_developer_tasks(*, db: Any, project_id: str) -> list[dict[str, str]]:
    rows = db.execute(
        select(Task.id, Task.title, Task.status)
        .join(
            ProjectMember,
            (ProjectMember.workspace_id == Task.workspace_id)
            & (ProjectMember.project_id == Task.project_id)
            & (ProjectMember.user_id == Task.assignee_id),
        )
        .where(
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            ProjectMember.role == "DeveloperAgent",
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
        for task_id, title, status in rows
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

    if str(assignee_role or "").strip() == "QAAgent":
        delivery = verify_delivery_workflow_fn(
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        required_checks = [
            "repo_context_present",
            "git_contract_ok",
            "dev_tasks_have_commit_evidence",
            "dev_tasks_have_unique_commit_evidence",
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

    if str(assignee_role or "").strip() == "TeamLeadAgent":
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
            "dev_tasks_have_commit_evidence",
            "dev_tasks_have_task_branch_evidence",
            "dev_tasks_have_unique_commit_evidence",
            "dev_tasks_have_automation_run_evidence",
            "qa_tasks_have_automation_run_evidence",
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
