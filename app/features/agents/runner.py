from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import threading
from datetime import datetime, timezone
import re

from sqlalchemy import select

from .executor import execute_task_automation
from features.tasks.domain import (
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_REQUESTED,
    EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_STARTED,
    EVENT_COMMENT_ADDED,
    EVENT_SCHEDULE_COMPLETED,
    EVENT_SCHEDULE_FAILED,
    EVENT_SCHEDULE_QUEUED,
    EVENT_SCHEDULE_STARTED,
)
from shared.contracts import ConcurrencyConflictError
from shared.eventing import append_event, rebuild_state
from shared.models import ProjectMember, ProjectSkill, SessionLocal, Task, User as UserModel
from shared.serializers import to_iso_utc
from shared.typed_notifications import append_notification_created_event
from shared.settings import (
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
    AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS,
    AGENT_RUNNER_INTERVAL_SECONDS,
    AGENT_RUNNER_MAX_CONCURRENCY,
    AGENT_SYSTEM_USER_ID,
    logger,
)
from shared.task_automation import (
    first_enabled_schedule_trigger,
    parse_schedule_due_at,
    rearm_first_schedule_trigger,
    schedule_trigger_matches_status,
)

_runner_stop_event = threading.Event()
_runner_wakeup_event = threading.Event()
_runner_thread: threading.Thread | None = None
_TEAM_MODE_AGENT_PROJECT_ROLES = {"TeamLeadAgent", "DeveloperAgent", "QAAgent"}
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)


@dataclass(frozen=True, slots=True)
class QueuedAutomationRun:
    task_id: str
    workspace_id: str
    project_id: str | None
    title: str
    description: str
    status: str
    instruction: str
    request_source: str
    is_scheduled_run: bool
    trigger_task_id: str | None
    trigger_from_status: str | None
    trigger_to_status: str | None
    triggered_at: str | None
    actor_user_id: str


def _normalize_nonnegative_int(value) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(0, parsed)


def _project_has_team_mode_skill(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectSkill.id).where(
            ProjectSkill.workspace_id == workspace_id,
            ProjectSkill.project_id == normalized_project_id,
            ProjectSkill.skill_key == "team_mode",
            ProjectSkill.enabled == True,  # noqa: E712
            ProjectSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


def _resolve_task_actor_user_id(
    *,
    db,
    task_id: str,
    state: dict | None = None,
    fallback_actor_user_id: str | None = None,
) -> str:
    source_state = dict(state or {})
    assignee_id = str(source_state.get("assignee_id") or "").strip()
    workspace_id = str(source_state.get("workspace_id") or "").strip()
    project_id = str(source_state.get("project_id") or "").strip()
    if not assignee_id:
        task_row = db.get(Task, task_id)
        if task_row is not None:
            assignee_id = str(task_row.assignee_id or "").strip()
            if not workspace_id:
                workspace_id = str(task_row.workspace_id or "").strip()
            if not project_id:
                project_id = str(task_row.project_id or "").strip()
    if not assignee_id:
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID

    user_row = db.get(UserModel, assignee_id)
    if user_row is None or not bool(user_row.is_active):
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
    if str(user_row.user_type or "").strip().lower() != "agent":
        return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID

    if project_id:
        membership = db.execute(
            select(ProjectMember).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == assignee_id,
            )
        ).scalar_one_or_none()
        if membership is None:
            return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
        project_role = str(membership.role or "").strip()
        if project_role not in _TEAM_MODE_AGENT_PROJECT_ROLES:
            return str(fallback_actor_user_id or "").strip() or AGENT_SYSTEM_USER_ID
    return assignee_id


def _resolve_assignee_project_role(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    assignee_id: str,
) -> str:
    normalized_project_id = str(project_id or "").strip()
    normalized_assignee_id = str(assignee_id or "").strip()
    if not workspace_id or not normalized_project_id or not normalized_assignee_id:
        return ""
    role = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            ProjectMember.user_id == normalized_assignee_id,
        )
    ).scalar_one_or_none()
    return str(role or "").strip()


def _is_team_mode_kickoff_instruction(instruction: str) -> bool:
    return str(instruction or "").strip().casefold().startswith("team mode kickoff for project ")


def _is_team_lead_recurring_oversight_task(state: dict | None) -> bool:
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


def _extract_commit_shas_from_refs(refs: object) -> set[str]:
    out: set[str] = set()
    if not isinstance(refs, list):
        return out
    for item in refs:
        if isinstance(item, dict):
            text = f"{item.get('url') or ''} {item.get('label') or ''}"
        else:
            text = str(item or "")
        for match in _COMMIT_SHA_EXPLICIT_RE.findall(text):
            out.add(str(match).lower())
    return out


def _resolve_project_human_member_user_ids(*, db, workspace_id: str, project_id: str | None) -> list[str]:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return []
    rows = db.execute(
        select(ProjectMember.user_id)
        .join(UserModel, UserModel.id == ProjectMember.user_id)
        .where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == normalized_project_id,
            UserModel.is_active == True,  # noqa: E712
            UserModel.user_type != "agent",
        )
    ).scalars().all()
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        user_id = str(item or "").strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        out.append(user_id)
    return out


def _enqueue_team_lead_blocker_escalation(
    *,
    db,
    workspace_id: str,
    project_id: str | None,
    blocked_task_id: str,
    blocked_title: str,
    blocked_role: str,
    blocked_status: str,
    blocked_error: str | None,
) -> int:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return 0
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
            ProjectMember.role == "TeamLeadAgent",
        )
        .order_by(Task.created_at.asc())
    ).scalars().all()
    queued = 0
    for lead_task in lead_tasks:
        lead_state, _ = rebuild_state(db, "Task", lead_task.id)
        if str(lead_state.get("automation_state") or "").strip() in {"queued", "running"}:
            continue
        instruction = (
            str(lead_state.get("instruction") or "").strip()
            or str(lead_state.get("scheduled_instruction") or "").strip()
            or "Handle blocker escalation and coordinate next actions."
        )
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=lead_task.id,
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": requested_at,
                "instruction": instruction,
                "source": "blocker_escalation",
                "trigger_task_id": blocked_task_id,
                "to_status": blocked_status or "Blocked",
                "from_status": None,
                "triggered_at": requested_at,
            },
            metadata={
                "actor_id": str(lead_task.assignee_id or AGENT_SYSTEM_USER_ID),
                "workspace_id": workspace_id,
                "project_id": normalized_project_id,
                "task_id": lead_task.id,
            },
        )
        queued += 1

    lead_assignee = str(lead_tasks[0].assignee_id or "").strip() if lead_tasks else AGENT_SYSTEM_USER_ID
    if not lead_assignee:
        lead_assignee = AGENT_SYSTEM_USER_ID
    blocked_summary = str(blocked_error or "").strip()[:300]
    dedupe_hash = hashlib.sha1(blocked_summary.encode("utf-8")).hexdigest()[:12] if blocked_summary else "none"
    human_ids = _resolve_project_human_member_user_ids(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
    )
    for human_id in human_ids:
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=(
                f"Team Mode blocker detected: {blocked_title or blocked_task_id} "
                f"({blocked_role or 'agent'}, status={blocked_status or 'Blocked'}). "
                "Team Lead escalation run was queued."
            ),
            actor_id=lead_assignee,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=blocked_task_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=f"team-mode-blocker:{blocked_task_id}:{blocked_status or 'Blocked'}:{dedupe_hash}",
            payload={
                "kind": "team_mode_blocker_escalation",
                "blocked_task_id": blocked_task_id,
                "blocked_role": blocked_role,
                "blocked_status": blocked_status,
                "queued_lead_tasks": queued,
                "error": blocked_summary,
            },
            source_event="agents.runner.blocker_escalation",
        )
    return queued


def _append_schedule_rearm_update(
    *,
    db,
    task_id: str,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    execution_triggers,
    now_utc: datetime,
) -> None:
    updated_triggers, next_due = rearm_first_schedule_trigger(
        execution_triggers=execution_triggers,
        now_utc=now_utc,
    )
    if not next_due:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "execution_triggers": updated_triggers,
            "scheduled_at_utc": next_due,
            "schedule_state": "idle",
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
    )


def _requeue_pending_status_change_request(
    *,
    db,
    run: QueuedAutomationRun,
    state: dict,
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str,
    requested_at_iso: str,
) -> None:
    pending_requests = _normalize_nonnegative_int(state.get("automation_pending_requests"))
    if pending_requests <= 0:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=run.task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={"automation_pending_requests": pending_requests - 1},
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
        },
    )
    instruction = run.instruction or str(state.get("instruction") or state.get("scheduled_instruction") or "").strip()
    if not instruction:
        return
    trigger_task_id = str(state.get("last_requested_trigger_task_id") or run.trigger_task_id or "").strip() or None
    trigger_from_status = str(state.get("last_requested_from_status") or run.trigger_from_status or "").strip() or None
    trigger_to_status = str(state.get("last_requested_to_status") or run.trigger_to_status or "").strip() or None
    triggered_at = str(state.get("last_requested_triggered_at") or run.triggered_at or "").strip() or requested_at_iso
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=run.task_id,
        event_type=EVENT_AUTOMATION_REQUESTED,
        payload={
            "requested_at": requested_at_iso,
            "instruction": instruction,
            "source": "status_change",
            "trigger_task_id": trigger_task_id,
            "from_status": trigger_from_status,
            "to_status": trigger_to_status,
            "triggered_at": triggered_at,
        },
        metadata={
            "actor_id": actor_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
            "trigger_task_id": trigger_task_id,
            "trigger_from_status": trigger_from_status,
            "trigger_to_status": trigger_to_status,
            "triggered_at": triggered_at,
        },
    )


def _claim_queued_task(task_id: str) -> QueuedAutomationRun | None:
    with SessionLocal() as db:
        state, version = rebuild_state(db, "Task", task_id)
        if state.get("automation_state", "idle") != "queued":
            return None
        workspace_id = str(state.get("workspace_id") or "").strip()
        if not workspace_id:
            return None
        project_id = str(state.get("project_id") or "").strip() or None
        request_source = str(state.get("last_requested_source") or "").strip().lower()
        trigger_task_id = str(state.get("last_requested_trigger_task_id") or "").strip() or None
        trigger_from_status = str(state.get("last_requested_from_status") or "").strip() or None
        trigger_to_status = str(state.get("last_requested_to_status") or "").strip() or None
        triggered_at = str(state.get("last_requested_triggered_at") or "").strip() or None
        is_scheduled_run = request_source == "schedule"
        schedule_state = str(state.get("schedule_state", "idle")).strip().lower()
        actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        try:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_STARTED,
                payload={"started_at": now_iso},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task_id,
                },
                expected_version=version,
            )
            if is_scheduled_run and schedule_state in {"queued", "idle"}:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_SCHEDULE_STARTED,
                    payload={"started_at": now_iso},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                    },
                )
            db.commit()
        except ConcurrencyConflictError:
            db.rollback()
            return None
    instruction = (
        str(state.get("last_requested_instruction") or "").strip()
        or str(state.get("instruction") or "").strip()
        or str(state.get("scheduled_instruction") or "").strip()
    )
    return QueuedAutomationRun(
        task_id=task_id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=str(state.get("title") or ""),
        description=str(state.get("description") or ""),
        status=str(state.get("status") or "To do"),
        instruction=instruction,
        request_source=request_source,
        is_scheduled_run=is_scheduled_run,
        trigger_task_id=trigger_task_id,
        trigger_from_status=trigger_from_status,
        trigger_to_status=trigger_to_status,
        triggered_at=triggered_at,
        actor_user_id=actor_user_id,
    )


def _record_automation_success(run: QueuedAutomationRun, *, summary: str, action: str, comment: str | None) -> None:
    completed_at = to_iso_utc(datetime.now(timezone.utc))
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        actor_user_id = _resolve_task_actor_user_id(
            db=db,
            task_id=run.task_id,
            state=state,
            fallback_actor_user_id=run.actor_user_id,
        )
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
        )
        queued_blocker_escalations = 0
        kickoff_instruction = str(run.instruction or "").strip()
        if (
            action == "complete"
            and assignee_role == "TeamLeadAgent"
            and _is_team_mode_kickoff_instruction(kickoff_instruction)
        ):
            action = "comment"
            summary = "Kickoff dispatch completed; Lead oversight task remains active."
            if not str(comment or "").strip():
                comment = "Kickoff completed in dispatch-only mode. Lead oversight task kept active for recurring coordination."
        if (
            action == "complete"
            and assignee_role == "TeamLeadAgent"
            and _is_team_lead_recurring_oversight_task(state)
        ):
            action = "comment"
            summary = "Recurring lead oversight cycle completed; task remains active in Lead."
            if not str(comment or "").strip():
                comment = "Recurring Team Lead oversight task cannot be auto-completed by automation run."

        if AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS:
            if action == "complete" and state.get("status") != "Done":
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_COMPLETED,
                    payload={"completed_at": completed_at},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
            if comment:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_COMMENT_ADDED,
                    payload={"task_id": run.task_id, "user_id": actor_user_id, "body": comment},
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )

        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_COMPLETED,
            payload={"completed_at": completed_at, "summary": summary, "source_event": EVENT_AUTOMATION_REQUESTED},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        if run.is_scheduled_run:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=EVENT_SCHEDULE_COMPLETED,
                payload={"completed_at": completed_at, "summary": summary},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            _append_schedule_rearm_update(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        # Smooth execution: for kickoff-dispatched Dev/QA tasks, auto-requeue once if no concrete progress evidence is present.
        current_status = str(state.get("status") or "").strip()
        commit_shas = _extract_commit_shas_from_refs(state.get("external_refs"))
        should_auto_retry = (
            run.request_source == "manual"
            and action == "comment"
            and (
                (assignee_role == "DeveloperAgent" and current_status == "Dev" and not commit_shas)
                or (
                    assignee_role == "QAAgent"
                    and current_status == "QA"
                    and not bool(state.get("external_refs"))
                )
            )
        )
        if should_auto_retry:
            retry_instruction = str(run.instruction or "").strip()
            if retry_instruction:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": completed_at,
                        "instruction": retry_instruction,
                        "source": "auto_retry",
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
                )
        if assignee_role in {"DeveloperAgent", "QAAgent"} and str(state.get("status") or "").strip() == "Blocked":
            queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                blocked_task_id=run.task_id,
                blocked_title=str(state.get("title") or ""),
                blocked_role=assignee_role,
                blocked_status="Blocked",
                blocked_error=str(comment or summary or "").strip() or None,
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            requested_at_iso=completed_at,
        )
        db.commit()
    if queued_blocker_escalations > 0:
        wake_automation_runner()


def _record_automation_failure(run: QueuedAutomationRun, error: Exception) -> None:
    failed_at = to_iso_utc(datetime.now(timezone.utc))
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        actor_user_id = _resolve_task_actor_user_id(
            db=db,
            task_id=run.task_id,
            state=state,
            fallback_actor_user_id=run.actor_user_id,
        )
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
        )
        queued_blocker_escalations = 0
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_FAILED,
            payload={"failed_at": failed_at, "error": str(error), "summary": "Automation runner failed."},
            metadata={
                "actor_id": actor_user_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": run.task_id,
            },
        )
        schedule_state = str(state.get("schedule_state") or "").strip().lower()
        if run.is_scheduled_run or schedule_state in {"queued", "running"}:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=EVENT_SCHEDULE_FAILED,
                payload={"failed_at": failed_at, "error": str(error)},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            _append_schedule_rearm_update(
                db=db,
                task_id=run.task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            requested_at_iso=failed_at,
        )
        if assignee_role in {"DeveloperAgent", "QAAgent"}:
            queued_blocker_escalations = _enqueue_team_lead_blocker_escalation(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                blocked_task_id=run.task_id,
                blocked_title=str(state.get("title") or ""),
                blocked_role=assignee_role,
                blocked_status=str(state.get("status") or "").strip() or "Blocked",
                blocked_error=str(error),
            )
        db.commit()
    if queued_blocker_escalations > 0:
        wake_automation_runner()


def _execute_claimed_automation(run: QueuedAutomationRun) -> None:
    try:
        if not run.instruction:
            raise RuntimeError("instruction is empty")
        outcome = execute_task_automation(
            task_id=run.task_id,
            title=run.title,
            description=run.description,
            status=run.status,
            instruction=run.instruction,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            actor_user_id=run.actor_user_id,
            trigger_task_id=run.trigger_task_id,
            trigger_from_status=run.trigger_from_status,
            trigger_to_status=run.trigger_to_status,
            trigger_timestamp=run.triggered_at,
            allow_mutations=True,
        )
    except Exception as exc:
        _record_automation_failure(run, exc)
        return

    try:
        _record_automation_success(
            run,
            summary=outcome.summary,
            action=outcome.action,
            comment=outcome.comment,
        )
    except Exception as exc:
        _record_automation_failure(run, exc)


def run_queued_automation_once(limit: int = 10) -> int:
    normalized_limit = max(1, int(limit))
    scan_limit = max(normalized_limit * 50, normalized_limit, AGENT_RUNNER_MAX_CONCURRENCY * 20)
    queued_event_task_ids: list[str] = []
    with SessionLocal() as db:
        try:
            from shared.models import StoredEvent

            queued_event_task_ids = db.execute(
                select(StoredEvent.aggregate_id)
                .where(
                    StoredEvent.aggregate_type == "Task",
                    StoredEvent.event_type == EVENT_AUTOMATION_REQUESTED,
                )
                .order_by(StoredEvent.occurred_at.desc())
                .limit(scan_limit)
            ).scalars().all()
        except Exception:
            queued_event_task_ids = []
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.desc()).limit(scan_limit)
        ).scalars().all()
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for task_id in [*queued_event_task_ids, *candidate_ids]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id or normalized_task_id in seen_ids:
            continue
        seen_ids.add(normalized_task_id)
        ordered_ids.append(normalized_task_id)

    claimed_runs: list[QueuedAutomationRun] = []
    for task_id in ordered_ids:
        claimed = _claim_queued_task(task_id)
        if claimed is None:
            continue
        claimed_runs.append(claimed)
        if len(claimed_runs) >= normalized_limit:
            break
    if not claimed_runs:
        return 0

    max_workers = max(1, min(int(AGENT_RUNNER_MAX_CONCURRENCY), normalized_limit, len(claimed_runs)))
    if max_workers == 1:
        for run in claimed_runs:
            _execute_claimed_automation(run)
        return len(claimed_runs)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="automation-runner") as pool:
        futures = [pool.submit(_execute_claimed_automation, run) for run in claimed_runs]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                # Individual worker errors are handled inside _execute_claimed_automation.
                continue
    return len(claimed_runs)


def _runner_loop():
    while not _runner_stop_event.is_set():
        try:
            recover_stale_running_automation_once(limit=20)
            queue_due_scheduled_tasks_once(limit=20)
            run_queued_automation_once(limit=20)
        except Exception:
            # Keep worker alive, but do not swallow diagnostics.
            logger.exception("Automation runner tick failed.")
        woke = _runner_wakeup_event.wait(AGENT_RUNNER_INTERVAL_SECONDS)
        if woke:
            _runner_wakeup_event.clear()


def recover_stale_running_automation_once(limit: int = 20) -> int:
    recovered = 0
    now = datetime.now(timezone.utc)
    stale_after_seconds = max(float(AGENT_EXECUTOR_TIMEOUT_SECONDS) * 2.0, 90.0)
    with SessionLocal() as db:
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.asc()).limit(max(limit * 10, limit))
        ).scalars().all()

        for task_id in candidate_ids:
            state, _ = rebuild_state(db, "Task", task_id)
            if state.get("automation_state") != "running":
                continue
            last_run_raw = state.get("last_agent_run_at")
            if not last_run_raw:
                continue
            try:
                last_run = datetime.fromisoformat(str(last_run_raw))
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age_seconds = (now - last_run.astimezone(timezone.utc)).total_seconds()
            if age_seconds < stale_after_seconds:
                continue

            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue
            project_id = state.get("project_id")
            actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
            failed_at = to_iso_utc(now)
            error = f"Automation run exceeded stale threshold ({int(stale_after_seconds)}s) and was recovered."
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_FAILED,
                payload={"failed_at": failed_at, "error": error, "summary": "Automation runner recovered stale running task."},
                metadata={"actor_id": actor_user_id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
            )
            request_source = str(state.get("last_requested_source") or "").strip().lower()
            schedule_state = str(state.get("schedule_state") or "").strip().lower()
            if request_source == "schedule" or schedule_state in {"queued", "running"}:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_SCHEDULE_FAILED,
                    payload={"failed_at": failed_at, "error": error},
                        metadata={"actor_id": actor_user_id, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                )
                updated_triggers, next_due = rearm_first_schedule_trigger(
                    execution_triggers=state.get("execution_triggers"),
                    now_utc=now,
                )
                if next_due:
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=TASK_EVENT_UPDATED,
                        payload={
                            "execution_triggers": updated_triggers,
                            "scheduled_at_utc": next_due,
                            "schedule_state": "idle",
                        },
                        metadata={
                            "actor_id": actor_user_id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
            db.commit()
            recovered += 1
            if recovered >= limit:
                break
    return recovered


def queue_due_scheduled_tasks_once(limit: int = 20) -> int:
    queued = 0
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        candidate_tasks = db.execute(
            select(Task)
            .where(
                Task.is_deleted == False,
                Task.task_type == "scheduled_instruction",
                Task.schedule_state == "idle",
            )
            .order_by(Task.scheduled_at_utc.asc())
            .limit(max(limit * 10, limit))
        ).scalars().all()

        for task in candidate_tasks:
            state, _ = rebuild_state(db, "Task", task.id)
            if state.get("schedule_state", "idle") != "idle":
                continue
            if state.get("automation_state", "idle") in {"queued", "running"}:
                continue
            _idx, schedule_trigger = first_enabled_schedule_trigger(state.get("execution_triggers"))
            if schedule_trigger is None:
                continue
            if not schedule_trigger_matches_status(trigger=schedule_trigger, status=state.get("status")):
                continue
            due_at = parse_schedule_due_at(schedule_trigger)
            if due_at is None or due_at > now:
                continue
            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue
            project_id = state.get("project_id")
            # Team Mode oversight schedules should not auto-start before explicit kickoff.
            # First run must come from manual/status-triggered request; schedule is fallback cadence afterwards.
            if _project_has_team_mode_skill(
                db=db,
                workspace_id=str(workspace_id),
                project_id=str(project_id or ""),
            ):
                last_requested_source = str(state.get("last_requested_source") or "").strip()
                last_agent_run_at = str(state.get("last_agent_run_at") or "").strip()
                if not last_requested_source and not last_agent_run_at:
                    continue
            actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task.id, state=state)
            instruction = (
                (state.get("instruction") or "").strip()
                or (state.get("scheduled_instruction") or "").strip()
            )
            if not instruction:
                continue
            now_iso = to_iso_utc(datetime.now(timezone.utc))
            # Guard in-memory record so the same task is not re-queued while handling this batch.
            task.schedule_state = "queued"
            db.flush()
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task.id,
                event_type=EVENT_SCHEDULE_QUEUED,
                payload={"queued_at": now_iso},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task.id,
                },
            )
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task.id,
                event_type=EVENT_AUTOMATION_REQUESTED,
                payload={"requested_at": now_iso, "instruction": instruction, "source": "schedule"},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": task.id,
                },
            )
            db.commit()
            queued += 1
            if queued >= limit:
                break
    return queued


def start_automation_runner():
    global _runner_thread
    if _runner_thread and _runner_thread.is_alive():
        return
    _runner_stop_event.clear()
    _runner_wakeup_event.clear()
    _runner_thread = threading.Thread(target=_runner_loop, name="automation-runner", daemon=True)
    _runner_thread.start()


def stop_automation_runner():
    global _runner_thread
    _runner_stop_event.set()
    _runner_wakeup_event.set()
    if _runner_thread and _runner_thread.is_alive():
        _runner_thread.join(timeout=3)
    _runner_thread = None


def wake_automation_runner():
    _runner_wakeup_event.set()
