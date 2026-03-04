from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import select

from shared.core import User, append_event
from shared.models import ProjectMember, ProjectSkill, Task
from shared.typed_notifications import append_notification_created_event


def maybe_dispatch_execution_kickoff(
    *,
    db: Any,
    user: User,
    workspace_id: str,
    project_id: str | None,
    intent_flags: dict[str, bool] | None,
    allow_mutations: bool,
    command_id: str | None,
    promote_gate_policy_to_execution_mode_if_needed: Callable[..., None] | None = None,
    build_team_lead_kickoff_instruction: Callable[..., str] | None = None,
    command_id_with_suffix: Callable[[str | None, str], str | None] | None = None,
) -> dict[str, object] | None:
    normalized_project_id = str(project_id or "").strip()
    if not allow_mutations or not normalized_project_id:
        return None
    if not callable(promote_gate_policy_to_execution_mode_if_needed):
        return None
    if not callable(build_team_lead_kickoff_instruction):
        return None
    if not callable(command_id_with_suffix):
        return None

    flags = intent_flags or {}
    kickoff_intent = bool(flags.get("execution_kickoff_intent"))
    execution_intent = bool(flags.get("execution_intent"))
    project_creation_intent = bool(flags.get("project_creation_intent"))
    should_dispatch_kickoff = kickoff_intent or (execution_intent and not project_creation_intent)
    if not should_dispatch_kickoff:
        return None

    team_mode_skill = db.execute(
        select(ProjectSkill.id).where(
            ProjectSkill.workspace_id == workspace_id,
            ProjectSkill.project_id == normalized_project_id,
            ProjectSkill.skill_key == "team_mode",
            ProjectSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if team_mode_skill is None:
        return None

    lead_project_role = "TeamLeadAgent"
    if not lead_project_role:
        return None

    promote_gate_policy_to_execution_mode_if_needed(
        db=db,
        user=user,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        command_id=command_id,
    )

    lead_tasks = db.execute(
        select(Task)
        .join(
            ProjectMember,
            (ProjectMember.workspace_id == Task.workspace_id)
            & (ProjectMember.project_id == Task.project_id)
            & (ProjectMember.user_id == Task.assignee_id),
        )
        .where(
            Task.workspace_id == workspace_id,
            Task.project_id == normalized_project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
            Task.status != "Done",
            ProjectMember.role == lead_project_role,
        )
        .order_by(Task.created_at.asc())
    ).scalars().all()

    kickoff_instruction = build_team_lead_kickoff_instruction(
        project_id=normalized_project_id,
        requester_user_id=str(user.id),
    )
    from features.tasks.application import TaskApplicationService
    from shared.core import TaskAutomationRun

    queued_task_ids: list[str] = []
    failed: list[dict[str, str]] = []
    for task in lead_tasks:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        task_command_id = command_id_with_suffix(command_id, f"kickoff-{task_id[:8]}")
        try:
            TaskApplicationService(db, user, command_id=task_command_id).request_automation_run(
                task_id,
                TaskAutomationRun(instruction=kickoff_instruction),
                wake_runner=False,
            )
            queued_task_ids.append(task_id)
        except HTTPException as exc:
            failed.append({"task_id": task_id, "error": str(exc.detail or "").strip() or f"HTTP {exc.status_code}"})
        except Exception as exc:  # pragma: no cover
            failed.append({"task_id": task_id, "error": str(exc)[:200]})

    kickoff_ok = len(queued_task_ids) > 0 and not failed
    if kickoff_ok:
        message = (
            f"Team Mode kickoff dispatched for project {normalized_project_id}: "
            f"{len(queued_task_ids)} lead task(s) queued."
        )
    else:
        message = (
            f"Team Mode kickoff failed for project {normalized_project_id}: "
            f"{len(queued_task_ids)} lead task(s) queued, {len(failed)} queue attempt(s) failed."
        )
    dedupe_key = command_id_with_suffix(command_id, "team-mode-kickoff-notify")
    append_notification_created_event(
        db,
        append_event_fn=append_event,
        user_id=str(user.id),
        message=message,
        actor_id=str(user.id),
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        notification_type="ManualMessage",
        severity="warning" if not kickoff_ok else "info",
        dedupe_key=dedupe_key,
        payload={
            "kind": "team_mode_kickoff",
            "queued_task_ids": queued_task_ids,
            "failed": failed,
        },
        source_event="agents.chat.kickoff_dispatch",
    )
    db.commit()

    if not lead_tasks:
        return {
            "ok": False,
            "action": "comment",
            "summary": "Team Mode kickoff blocked: no active Team Lead tasks found.",
            "comment": "Create/assign at least one active Lead task and retry kickoff.",
            "kickoff_dispatched": False,
            "queued_task_ids": [],
            "failed": [],
        }
    if kickoff_ok:
        summary = "Team Mode kickoff dispatched to Team Lead automation."
        comment = f"Queued lead tasks: {len(queued_task_ids)}."
    else:
        summary = "Team Mode kickoff failed to queue Team Lead automation."
        comment = f"Queued lead tasks: {len(queued_task_ids)}. Failed queues: {len(failed)}."
    return {
        "ok": kickoff_ok,
        "action": "comment",
        "summary": summary,
        "comment": comment,
        "kickoff_dispatched": kickoff_ok,
        "queued_task_ids": queued_task_ids,
        "failed": failed,
    }
