import json
import queue
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.agents.intent_classifier import (
    AUTOMATION_REQUEST_INTENT_FIELDS,
    classify_instruction_intent,
    resolve_instruction_intent,
)
from features.agents.executor import build_automation_usage_metadata, execute_task_automation_stream
from features.agents.gateway import build_ui_gateway
from shared.core import (
    ActivityLog,
    BulkAction,
    CommentCreate,
    ReorderPayload,
    Task,
    TaskAutomationRun,
    TaskComment,
    TaskCreate,
    TaskPatch,
    TaskWatcher,
    User,
    ensure_project_access,
    ensure_role,
    export_tasks_response,
    get_command_id,
    get_current_user,
    get_current_user_detached,
    get_db,
    get_user_zoneinfo,
    load_task_view,
    serialize_task,
    to_iso_utc,
)
from shared.eventing import append_event, rebuild_state
from shared.in_memory_stream_broker import InMemoryStreamBroker
from shared.models import CommandExecution, SessionLocal
from .application import TaskApplicationService
from .domain import (
    EVENT_AUTOMATION_COMPLETED,
    EVENT_AUTOMATION_FAILED,
    EVENT_AUTOMATION_REQUESTED,
    EVENT_AUTOMATION_STARTED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
)
from .read_models import TaskListQuery, list_tasks_read_model

router = APIRouter()


class TaskReviewDecisionPayload(BaseModel):
    action: str
    comment: str | None = None

_STREAM_BROKER = InMemoryStreamBroker(max_events=1500)


def _create_stream_run(task_id: str) -> str:
    return _STREAM_BROKER.create_run(key=task_id)


def _publish_stream_event(task_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
    return _STREAM_BROKER.publish_event(key=task_id, event=event)


def _finish_stream_run(task_id: str) -> None:
    _STREAM_BROKER.finish_run(key=task_id)


def _subscribe_stream_run(task_id: str, run_id: str, since_seq: int) -> tuple[queue.Queue, list[dict[str, Any]], bool]:
    return _STREAM_BROKER.subscribe_run(key=task_id, run_id=run_id, since_seq=since_seq)


def _unsubscribe_stream_run(task_id: str, subscriber_queue: queue.Queue) -> None:
    _STREAM_BROKER.unsubscribe_run(key=task_id, subscriber_queue=subscriber_queue)


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


@router.get("/api/tasks")
def list_tasks(
    workspace_id: str,
    project_id: str,
    task_group_id: str | None = None,
    specification_id: str | None = None,
    view: str | None = None,
    q: str | None = None,
    status: str | None = None,
    tags: str | None = None,
    label: str | None = None,
    assignee_id: str | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    priority: str | None = None,
    archived: bool = False,
    limit: int = Query(default=30, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user_detached),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project_id,
        task_group_id=task_group_id,
        specification_id=specification_id,
        view=view,
        q=q,
        status=status,
        tags=[t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None,
        label=label,
        assignee_id=assignee_id,
        due_from=due_from,
        due_to=due_to,
        priority=priority,
        archived=archived,
        limit=limit,
        offset=offset,
    )


@router.get("/api/tasks/{task_id}")
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = load_task_view(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    workspace_id = str(task.get("workspace_id") or "").strip()
    project_id = str(task.get("project_id") or "").strip()
    if project_id:
        ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    else:
        ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return task


@router.post("/api/tasks")
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    provided_fields = payload.model_fields_set
    return gateway.create_task(
        workspace_id=payload.workspace_id,
        title=payload.title,
        project_id=payload.project_id,
        description=payload.description,
        status=payload.status if "status" in provided_fields else None,
        priority=payload.priority,
        due_date=payload.due_date.isoformat() if payload.due_date else None,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        instruction=payload.instruction if "instruction" in provided_fields else None,
        execution_triggers=payload.execution_triggers if "execution_triggers" in provided_fields else None,
        task_relationships=payload.task_relationships if "task_relationships" in provided_fields else None,
        delivery_mode=payload.delivery_mode if "delivery_mode" in provided_fields else None,
        recurring_rule=payload.recurring_rule if "recurring_rule" in provided_fields else None,
        specification_id=payload.specification_id,
        task_group_id=payload.task_group_id,
        task_type=payload.task_type if "task_type" in provided_fields else None,
        scheduled_instruction=payload.scheduled_instruction if "scheduled_instruction" in provided_fields else None,
        scheduled_at_utc=(
            payload.scheduled_at_utc.isoformat()
            if "scheduled_at_utc" in provided_fields and payload.scheduled_at_utc
            else None
        ),
        schedule_timezone=payload.schedule_timezone if "schedule_timezone" in provided_fields else None,
        assignee_id=payload.assignee_id,
        assigned_agent_code=payload.assigned_agent_code if "assigned_agent_code" in provided_fields else None,
        labels=payload.labels,
        command_id=command_id,
    )


@router.patch("/api/tasks/{task_id}")
def patch_task(
    task_id: str,
    payload: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.update_task(
        task_id=task_id,
        patch=payload.model_dump(exclude_unset=True),
        command_id=command_id,
    )


@router.post("/api/tasks/{task_id}/complete")
def complete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.complete_task(task_id=task_id, command_id=command_id)


@router.post("/api/tasks/{task_id}/review")
def review_task(
    task_id: str,
    payload: TaskReviewDecisionPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).review_task(
        task_id,
        action=payload.action,
        comment=payload.comment,
    )


@router.post("/api/tasks/{task_id}/reopen")
def reopen_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).reopen_task(task_id)


@router.post("/api/tasks/{task_id}/archive")
def archive_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).archive_task(task_id)


@router.post("/api/tasks/{task_id}/restore")
def restore_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).restore_task(task_id)


@router.post("/api/tasks/bulk")
def bulk_action(
    payload: BulkAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.bulk_task_action(
        task_ids=payload.task_ids,
        action=payload.action,
        payload=payload.payload,
        command_id=command_id,
    )


@router.post("/api/tasks/reorder")
def reorder_tasks(
    payload: ReorderPayload,
    workspace_id: str,
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).reorder_tasks(workspace_id, project_id, payload)


@router.get("/api/calendar")
def calendar_view(
    workspace_id: str,
    project_id: str,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    user_tz = get_user_zoneinfo(user)
    start = datetime.combine(from_date, datetime.min.time(), tzinfo=user_tz).astimezone(timezone.utc)
    end = datetime.combine(to_date, datetime.max.time(), tzinfo=user_tz).astimezone(timezone.utc)
    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.due_date >= start,
            Task.due_date <= end,
            Task.is_deleted == False,
        )
    ).scalars().all()
    return {"items": [serialize_task(t) for t in tasks]}


@router.post("/api/tasks/{task_id}/comments")
def add_comment(
    task_id: str,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.add_task_comment(task_id=task_id, body=payload.body, command_id=command_id)


@router.get("/api/tasks/{task_id}/comments")
def list_comments(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_project_access(db, task.workspace_id, task.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    comments = db.execute(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at.desc())).scalars().all()
    return [{"id": c.id, "task_id": c.task_id, "user_id": c.user_id, "body": c.body, "created_at": to_iso_utc(c.created_at)} for c in comments]


@router.post("/api/tasks/{task_id}/comments/{comment_id}/delete")
def delete_comment(
    task_id: str,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).delete_comment(task_id, comment_id)


@router.post("/api/tasks/{task_id}/watch")
def toggle_watch(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return TaskApplicationService(db, user, command_id=command_id).toggle_watch(task_id)


@router.get("/api/tasks/{task_id}/activity")
def task_activity(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    ensure_project_access(db, task.workspace_id, task.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    logs = db.execute(select(ActivityLog).where(ActivityLog.task_id == task_id).order_by(ActivityLog.created_at.desc()).limit(200)).scalars().all()
    out = []
    seen_activity_keys: set[str] = set()
    for l in logs:
        details = json.loads(l.details or "{}")
        details_map = details if isinstance(details, dict) else {}
        event_key = str(details_map.get("_event_key") or "").strip()
        created_at_iso = to_iso_utc(l.created_at)
        dedupe_key = event_key or (
            f"{l.action}|{json.dumps(details_map, sort_keys=True, ensure_ascii=True)}|{created_at_iso}"
        )
        if dedupe_key in seen_activity_keys:
            continue
        seen_activity_keys.add(dedupe_key)
        if isinstance(details, dict):
            details.pop("_event_key", None)
        out.append({"id": l.id, "action": l.action, "actor_id": l.actor_id, "details": details, "created_at": created_at_iso})
    return out


@router.get("/api/export")
def export_tasks(
    workspace_id: str,
    project_id: str,
    format: str = "json",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member"})
    return export_tasks_response(db, workspace_id, project_id, format)


@router.post("/api/tasks/{task_id}/automation/run")
def request_automation_run(
    task_id: str,
    payload: TaskAutomationRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.request_task_automation_run(
        task_id=task_id,
        instruction=payload.instruction,
        source=payload.source,
        source_task_id=payload.source_task_id,
        chat_session_id=payload.chat_session_id,
        execution_intent=payload.execution_intent,
        execution_kickoff_intent=payload.execution_kickoff_intent,
        project_creation_intent=payload.project_creation_intent,
        workflow_scope=payload.workflow_scope,
        execution_mode=payload.execution_mode,
        task_completion_requested=payload.task_completion_requested,
        classifier_reason=payload.classifier_reason,
        command_id=command_id,
    )


@router.post("/api/tasks/{task_id}/automation/stream")
def run_automation_stream(
    task_id: str,
    payload: TaskAutomationRun,
    user: User = Depends(get_current_user_detached),
    command_id: str | None = Depends(get_command_id),
):
    def _single_final_stream(response: dict[str, Any]) -> StreamingResponse:
        body = json.dumps({"type": "final", "response": response}, ensure_ascii=True) + "\n"
        return StreamingResponse(iter([body]), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    normalized_command_id = str(command_id or "").strip() or None
    with SessionLocal() as db:
        if normalized_command_id:
            existing = db.execute(
                select(CommandExecution).where(CommandExecution.command_id == normalized_command_id)
            ).scalar_one_or_none()
            if existing is not None:
                try:
                    replay_payload = json.loads(existing.response_json or "{}")
                except Exception:
                    replay_payload = {}
                if not isinstance(replay_payload, dict):
                    replay_payload = {}
                replay_response = {
                    "ok": bool(replay_payload.get("ok", True)),
                    "task_id": str(replay_payload.get("task_id") or task_id),
                    "automation_state": str(replay_payload.get("automation_state") or "completed"),
                    "summary": str(replay_payload.get("summary") or "Automation run replayed from command idempotency."),
                    "comment": str(replay_payload.get("comment") or ""),
                }
                return _single_final_stream(replay_response)

        task_row = db.get(Task, task_id)
        if not task_row or task_row.is_deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        workspace_id = str(task_row.workspace_id or "").strip()
        project_id = str(task_row.project_id or "").strip() or None
        if project_id:
            ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        else:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})

        state, _ = rebuild_state(db, "Task", task_id)
    current_automation_state = str(state.get("automation_state") or "").strip().lower()
    if current_automation_state in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail="Automation is already in progress for this task.",
        )
    title = str(state.get("title") or "")
    description = str(state.get("description") or "")
    status = str(state.get("status") or "To Do")
    instruction = str(payload.instruction or "").strip() or str(state.get("instruction") or state.get("scheduled_instruction") or "").strip()
    if not instruction:
        raise HTTPException(status_code=422, detail="instruction is required")
    classification = resolve_instruction_intent(
        instruction=instruction,
        workspace_id=workspace_id,
        project_id=project_id,
        session_id=None,
        current={
            "execution_intent": payload.execution_intent,
            "execution_kickoff_intent": payload.execution_kickoff_intent,
            "project_creation_intent": payload.project_creation_intent,
            "workflow_scope": payload.workflow_scope,
            "execution_mode": payload.execution_mode,
            "task_completion_requested": payload.task_completion_requested,
            "reason": payload.classifier_reason,
        },
        classify_fn=classify_instruction_intent,
        required_fields=AUTOMATION_REQUEST_INTENT_FIELDS,
    )
    existing_codex_session_id = str(state.get("last_agent_codex_session_id") or "").strip()
    resume_attempted = _coerce_bool(state.get("last_agent_codex_resume_attempted"))
    resume_last_succeeded = _coerce_bool(state.get("last_agent_codex_resume_succeeded"))
    resume_blocked = resume_attempted is True and resume_last_succeeded is False
    resume_codex_session_id = (
        existing_codex_session_id
        if existing_codex_session_id and not resume_blocked
        else None
    )
    run_id = _create_stream_run(task_id)

    now_iso = to_iso_utc(datetime.now(timezone.utc))
    with SessionLocal() as db:
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=EVENT_AUTOMATION_REQUESTED,
            payload={
                "requested_at": now_iso,
                "instruction": instruction,
                "source": "manual_stream",
                "execution_intent": bool(classification.get("execution_intent")),
                "execution_kickoff_intent": bool(classification.get("execution_kickoff_intent")),
                "project_creation_intent": bool(classification.get("project_creation_intent")),
                "workflow_scope": str(classification.get("workflow_scope") or "").strip() or None,
                "execution_mode": str(classification.get("execution_mode") or "").strip() or None,
                "task_completion_requested": bool(classification.get("task_completion_requested")),
                "classifier_reason": str(classification.get("reason") or "").strip() or None,
            },
            metadata={
                "actor_id": user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
            },
        )
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=EVENT_AUTOMATION_STARTED,
            payload={
                "started_at": now_iso,
                "last_agent_progress": "",
                "last_agent_stream_status": "Automation run started.",
                "last_agent_stream_updated_at": now_iso,
                "last_agent_run_id": run_id,
            },
            metadata={
                "actor_id": user.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
            },
        )
        db.commit()
        _publish_stream_event(task_id, {"type": "status", "message": "Automation run started."})
        if normalized_command_id:
            try:
                db.add(
                    CommandExecution(
                        command_id=normalized_command_id,
                        command_name="Task.AutomationStream",
                        user_id=user.id,
                        response_json=json.dumps(
                            {
                                "ok": True,
                                "task_id": task_id,
                                "automation_state": "running",
                                "summary": "Automation stream run accepted.",
                                "comment": "",
                            },
                            ensure_ascii=True,
                        ),
                    )
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.execute(
                    select(CommandExecution).where(CommandExecution.command_id == normalized_command_id)
                ).scalar_one_or_none()
                if existing is not None:
                    try:
                        replay_payload = json.loads(existing.response_json or "{}")
                    except Exception:
                        replay_payload = {}
                    if not isinstance(replay_payload, dict):
                        replay_payload = {}
                    replay_response = {
                        "ok": bool(replay_payload.get("ok", True)),
                        "task_id": str(replay_payload.get("task_id") or task_id),
                        "automation_state": str(replay_payload.get("automation_state") or "completed"),
                        "summary": str(replay_payload.get("summary") or "Automation run replayed from command idempotency."),
                        "comment": str(replay_payload.get("comment") or ""),
                    }
                    return _single_final_stream(replay_response)
                raise

    stream_headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }

    def _stream():
        event_queue: queue.Queue[dict[str, object]] = queue.Queue()
        outcome_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}
        done_event = threading.Event()
        stream_text = ""
        stream_status = ""
        last_flush_at = 0.0
        stream_max_chars = 24000
        stream_flush_interval_seconds = 0.35
        finalize_lock = threading.Lock()
        finalized_response: dict[str, Any] = {}
        stream_lock = threading.Lock()

        def _persist_stream_progress(*, force: bool = False) -> None:
            nonlocal last_flush_at, stream_text, stream_status
            now_monotonic = time.monotonic()
            if not force and (now_monotonic - last_flush_at) < stream_flush_interval_seconds:
                return
            last_flush_at = now_monotonic
            with stream_lock:
                progress_text = stream_text[-stream_max_chars:]
                status_text = stream_status or None
            now_iso = to_iso_utc(datetime.now(timezone.utc))
            with SessionLocal() as local_db:
                append_event(
                    local_db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=TASK_EVENT_UPDATED,
                    payload={
                        "last_agent_progress": progress_text,
                        "last_agent_stream_status": status_text,
                        "last_agent_stream_updated_at": now_iso,
                        "last_agent_run_id": run_id,
                    },
                    metadata={
                        "actor_id": user.id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                    },
                )
                local_db.commit()

        def _on_event(event: dict[str, object]) -> None:
            nonlocal stream_text, stream_status
            event_type = str(event.get("type") or "").strip()
            if event_type == "assistant_text":
                delta = str(event.get("delta") or "")
                if delta:
                    with stream_lock:
                        stream_text = (stream_text + delta)[-stream_max_chars:]
                    _persist_stream_progress(force=False)
            elif event_type == "status":
                message = str(event.get("message") or "").strip()
                if message:
                    with stream_lock:
                        stream_status = message
                        stream_text = (f"{stream_text}\n\n{message}".strip())[-stream_max_chars:]
                    _persist_stream_progress(force=True)
            published = _publish_stream_event(task_id, dict(event))
            if published:
                event_queue.put(published)
            else:
                event_queue.put(event)

        def _worker() -> None:
            try:
                outcome_holder["value"] = execute_task_automation_stream(
                    task_id=task_id,
                    title=title,
                    description=description,
                    status=status,
                    instruction=instruction,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    execution_kickoff_intent=bool(classification.get("execution_kickoff_intent")),
                    workflow_scope=str(classification.get("workflow_scope") or "").strip() or None,
                    execution_mode=str(classification.get("execution_mode") or "").strip() or None,
                    task_completion_requested=bool(classification.get("task_completion_requested")),
                    codex_session_id=resume_codex_session_id,
                    actor_user_id=user.id,
                    allow_mutations=True,
                    prompt_instruction_segments={"user_instruction": len(instruction)},
                    on_event=_on_event,
                    stream_plain_text=True,
                )
            except Exception as exc:  # pragma: no cover - surfaced to stream consumer
                error_holder["value"] = exc
            finally:
                done_event.set()

        def _finalize_once() -> dict[str, Any]:
            with finalize_lock:
                existing = finalized_response.get("value")
                if isinstance(existing, dict):
                    return existing
                _persist_stream_progress(force=True)

                if "value" in error_holder:
                    failed_at = to_iso_utc(datetime.now(timezone.utc))
                    error_text = str(error_holder["value"])
                    with SessionLocal() as local_db:
                        append_event(
                            local_db,
                            aggregate_type="Task",
                            aggregate_id=task_id,
                            event_type=EVENT_AUTOMATION_FAILED,
                            payload={"failed_at": failed_at, "error": error_text, "summary": "Automation runner failed."},
                            metadata={
                                "actor_id": user.id,
                                "workspace_id": workspace_id,
                                "project_id": project_id,
                                "task_id": task_id,
                            },
                        )
                        append_event(
                            local_db,
                            aggregate_type="Task",
                            aggregate_id=task_id,
                            event_type=TASK_EVENT_UPDATED,
                            payload={
                                "last_agent_stream_status": "Automation run failed.",
                                "last_agent_stream_updated_at": failed_at,
                                "last_agent_run_id": run_id,
                            },
                            metadata={
                                "actor_id": user.id,
                                "workspace_id": workspace_id,
                                "project_id": project_id,
                                "task_id": task_id,
                            },
                        )
                        local_db.commit()
                        if normalized_command_id:
                            command_row = local_db.execute(
                                select(CommandExecution).where(CommandExecution.command_id == normalized_command_id)
                            ).scalar_one_or_none()
                            if command_row is not None:
                                command_row.response_json = json.dumps(
                                    {
                                        "ok": False,
                                        "task_id": task_id,
                                        "automation_state": "failed",
                                        "summary": "Automation runner failed.",
                                        "comment": error_text,
                                    },
                                    ensure_ascii=True,
                                )
                                local_db.commit()
                    response = {
                        "ok": False,
                        "task_id": task_id,
                        "automation_state": "failed",
                        "summary": "Automation runner failed.",
                        "comment": error_text,
                    }
                    _publish_stream_event(task_id, {"type": "final", "response": response})
                    _finish_stream_run(task_id)
                    finalized_response["value"] = response
                    return response

                outcome = outcome_holder.get("value")
                if outcome is None:
                    response = {
                        "ok": False,
                        "task_id": task_id,
                        "automation_state": "failed",
                        "summary": "Automation runner failed.",
                        "comment": "Missing automation outcome.",
                    }
                    _publish_stream_event(task_id, {"type": "final", "response": response})
                    _finish_stream_run(task_id)
                    finalized_response["value"] = response
                    return response

                completed_at = to_iso_utc(datetime.now(timezone.utc))
                outcome_comment = str(outcome.comment or "").strip()
                usage_metadata = build_automation_usage_metadata(outcome)
                usage_payload = usage_metadata.get("last_agent_usage")
                with SessionLocal() as local_db:
                    append_event(
                        local_db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=EVENT_AUTOMATION_COMPLETED,
                        payload={
                            "completed_at": completed_at,
                            "summary": str(outcome.summary or "Automation run finished."),
                            "comment": outcome_comment,
                            "usage": usage_payload if isinstance(usage_payload, dict) else None,
                            "prompt_mode": usage_metadata.get("last_agent_prompt_mode"),
                            "prompt_segment_chars": usage_metadata.get("last_agent_prompt_segment_chars"),
                            "codex_session_id": usage_metadata.get("last_agent_codex_session_id"),
                            "resume_attempted": usage_metadata.get("last_agent_codex_resume_attempted"),
                            "resume_succeeded": usage_metadata.get("last_agent_codex_resume_succeeded"),
                            "resume_fallback_used": usage_metadata.get("last_agent_codex_resume_fallback_used"),
                        },
                        metadata={
                            "actor_id": user.id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
                    append_event(
                        local_db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=TASK_EVENT_UPDATED,
                        payload={
                            "last_agent_stream_status": "Automation run completed.",
                            "last_agent_stream_updated_at": completed_at,
                            "last_agent_progress": outcome_comment or str(outcome.summary or ""),
                            "last_agent_comment": outcome_comment or None,
                            "last_agent_run_id": run_id,
                            **usage_metadata,
                        },
                        metadata={
                            "actor_id": user.id,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
                    local_db.commit()
                    if normalized_command_id:
                        command_row = local_db.execute(
                            select(CommandExecution).where(CommandExecution.command_id == normalized_command_id)
                        ).scalar_one_or_none()
                        if command_row is not None:
                            command_row.response_json = json.dumps(
                                {
                                    "ok": True,
                                    "task_id": task_id,
                                    "automation_state": "completed",
                                    "summary": str(outcome.summary or "Automation run finished."),
                                    "comment": outcome_comment,
                                },
                                ensure_ascii=True,
                            )
                            local_db.commit()
                response = {
                    "ok": True,
                    "task_id": task_id,
                    "automation_state": "completed",
                    "summary": str(outcome.summary or "Automation run finished."),
                    "comment": str(outcome.comment or ""),
                }
                _publish_stream_event(task_id, {"type": "final", "response": response})
                _finish_stream_run(task_id)
                finalized_response["value"] = response
                return response

        def _background_finalize() -> None:
            done_event.wait()
            _finalize_once()

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        finalizer = threading.Thread(target=_background_finalize, daemon=True)
        finalizer.start()

        while True:
            try:
                event = event_queue.get(timeout=0.15)
            except queue.Empty:
                if done_event.is_set():
                    break
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "").strip()
            if event_type in {"assistant_text", "status", "usage"}:
                yield json.dumps(event, ensure_ascii=True) + "\n"

        response = _finalize_once()
        yield json.dumps({"type": "final", "response": response}, ensure_ascii=True) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers=stream_headers)


@router.get("/api/tasks/{task_id}/automation")
def task_automation_status(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_task_automation_status(task_id=task_id)


@router.get("/api/tasks/{task_id}/automation/stream")
def resume_automation_stream(
    task_id: str,
    run_id: str,
    since_seq: int = 0,
    user: User = Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        task_row = db.get(Task, task_id)
        if not task_row or task_row.is_deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        workspace_id = str(task_row.workspace_id or "").strip()
        project_id = str(task_row.project_id or "").strip() or None
        if project_id:
            ensure_project_access(db, workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        else:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    subscriber_queue, replay_events, done = _subscribe_stream_run(task_id, run_id, since_seq)
    if not replay_events and done:
        raise HTTPException(status_code=404, detail="Automation stream run is not available")

    headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }

    def _stream():
        try:
            for event in replay_events:
                yield json.dumps(event, ensure_ascii=True) + "\n"
            if done:
                return
            while True:
                try:
                    event = subscriber_queue.get(timeout=0.5)
                except queue.Empty:
                    broker = _STREAM_BROKER.current_state(key=task_id)
                    if not isinstance(broker, dict):
                        break
                    if str(broker.get("run_id") or "").strip() != str(run_id).strip():
                        break
                    if bool(broker.get("done")):
                        break
                    continue
                if not isinstance(event, dict):
                    continue
                yield json.dumps(event, ensure_ascii=True) + "\n"
                if str(event.get("type") or "").strip() == "final":
                    break
        finally:
            _unsubscribe_stream_run(task_id, subscriber_queue)

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers=headers)
