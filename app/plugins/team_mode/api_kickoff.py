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
    should_dispatch_kickoff = kickoff_intent
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

    promote_gate_policy_to_execution_mode_if_needed(
        db=db,
        user=user,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        command_id=command_id,
    )

    rows = db.execute(
        select(Task, ProjectMember.role)
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
            ProjectMember.role.in_(["DeveloperAgent", "TeamLeadAgent", "QAAgent"]),
        )
        .order_by(Task.created_at.asc())
    ).all()

    def _task_instruction(task: Task) -> str:
        return str(task.instruction or "").strip() or str(task.scheduled_instruction or "").strip()

    candidates_dev: list[tuple[Task, str]] = []
    candidates_lead: list[tuple[Task, str]] = []
    candidates_qa: list[tuple[Task, str]] = []
    for task, role in rows:
        normalized_role = str(role or "").strip()
        normalized_status = str(task.status or "").strip()
        if normalized_role == "DeveloperAgent" and normalized_status == "Dev" and _task_instruction(task):
            candidates_dev.append((task, normalized_role))
        elif normalized_role == "TeamLeadAgent" and normalized_status == "Lead" and _task_instruction(task):
            candidates_lead.append((task, normalized_role))
        elif normalized_role == "QAAgent" and normalized_status in {"QA", "Blocked"} and _task_instruction(task):
            candidates_qa.append((task, normalized_role))

    kickoff_targets: list[tuple[Task, str]] = [*candidates_dev, *candidates_lead]
    if not kickoff_targets:
        kickoff_targets = list(candidates_qa)

    kickoff_instruction = build_team_lead_kickoff_instruction(
        project_id=normalized_project_id,
        requester_user_id=str(user.id),
    )
    from features.tasks.application import TaskApplicationService
    from shared.core import TaskAutomationRun

    queued_task_ids: list[str] = []
    queued_by_role: dict[str, int] = {"DeveloperAgent": 0, "TeamLeadAgent": 0, "QAAgent": 0}
    failed: list[dict[str, str]] = []
    for task, role in kickoff_targets:
        task_id = str(task.id or "").strip()
        if not task_id:
            continue
        task_command_id = command_id_with_suffix(command_id, f"kickoff-{task_id[:8]}")
        instruction = kickoff_instruction if str(role or "").strip() == "TeamLeadAgent" else _task_instruction(task)
        if not instruction:
            continue
        try:
            TaskApplicationService(db, user, command_id=task_command_id).request_automation_run(
                task_id,
                TaskAutomationRun(instruction=instruction),
                wake_runner=False,
            )
            queued_task_ids.append(task_id)
            queued_by_role[str(role or "").strip()] = int(queued_by_role.get(str(role or "").strip(), 0)) + 1
        except HTTPException as exc:
            failed.append({"task_id": task_id, "error": str(exc.detail or "").strip() or f"HTTP {exc.status_code}"})
        except Exception as exc:  # pragma: no cover
            failed.append({"task_id": task_id, "error": str(exc)[:200]})

    kickoff_ok = len(queued_task_ids) > 0 and not failed
    queued_dev = int(queued_by_role.get("DeveloperAgent", 0))
    queued_lead = int(queued_by_role.get("TeamLeadAgent", 0))
    queued_qa = int(queued_by_role.get("QAAgent", 0))
    if kickoff_ok:
        message = (
            f"Team Mode kickoff dispatched for project {normalized_project_id}: "
            f"{len(queued_task_ids)} task(s) queued "
            f"(Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa})."
        )
    else:
        message = (
            f"Team Mode kickoff failed for project {normalized_project_id}: "
            f"{len(queued_task_ids)} task(s) queued (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}), "
            f"{len(failed)} queue attempt(s) failed."
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
            "queued_by_role": queued_by_role,
            "failed": failed,
        },
        source_event="agents.chat.kickoff_dispatch",
    )
    db.commit()

    if not kickoff_targets:
        return {
            "ok": False,
            "action": "comment",
            "summary": "Team Mode kickoff blocked: no runnable Team Mode tasks found.",
            "comment": "Ensure Dev/Lead/QA tasks are in active workflow statuses with automation instructions, then retry kickoff.",
            "kickoff_dispatched": False,
            "queued_task_ids": [],
            "queued_by_role": queued_by_role,
            "failed": [],
        }
    if kickoff_ok:
        summary = "Team Mode kickoff dispatched to task automation."
        comment = f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa})."
    else:
        summary = "Team Mode kickoff partially failed."
        comment = (
            f"Queued tasks: {len(queued_task_ids)} (Dev={queued_dev}, Lead={queued_lead}, QA={queued_qa}). "
            f"Failed queues: {len(failed)}."
        )
    return {
        "ok": kickoff_ok,
        "action": "comment",
        "summary": summary,
        "comment": comment,
        "kickoff_dispatched": kickoff_ok,
        "queued_task_ids": queued_task_ids,
        "queued_by_role": queued_by_role,
        "failed": failed,
    }
