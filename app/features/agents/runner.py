from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import threading
from datetime import datetime, timezone

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
from shared.models import SessionLocal, Task
from shared.serializers import to_iso_utc
from shared.settings import (
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
    AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS,
    AGENT_RUNNER_INTERVAL_SECONDS,
    AGENT_RUNNER_MAX_CONCURRENCY,
    AGENT_SYSTEM_USER_ID,
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


def _normalize_nonnegative_int(value) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(0, parsed)


def _append_schedule_rearm_update(
    *,
    db,
    task_id: str,
    workspace_id: str,
    project_id: str | None,
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
            "actor_id": AGENT_SYSTEM_USER_ID,
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
            "actor_id": AGENT_SYSTEM_USER_ID,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
        },
    )
    instruction = run.instruction or str(state.get("instruction") or state.get("scheduled_instruction") or "").strip()
    if not instruction:
        return
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=run.task_id,
        event_type=EVENT_AUTOMATION_REQUESTED,
        payload={
            "requested_at": requested_at_iso,
            "instruction": instruction,
            "source": "status_change",
        },
        metadata={
            "actor_id": AGENT_SYSTEM_USER_ID,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": run.task_id,
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
        is_scheduled_run = request_source == "schedule"
        schedule_state = str(state.get("schedule_state", "idle")).strip().lower()
        now_iso = to_iso_utc(datetime.now(timezone.utc))
        try:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_STARTED,
                payload={"started_at": now_iso},
                metadata={
                    "actor_id": AGENT_SYSTEM_USER_ID,
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
                        "actor_id": AGENT_SYSTEM_USER_ID,
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

        if AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS:
            if action == "complete" and state.get("status") != "Done":
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=TASK_EVENT_COMPLETED,
                    payload={"completed_at": completed_at},
                    metadata={
                        "actor_id": AGENT_SYSTEM_USER_ID,
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
                    payload={"task_id": run.task_id, "user_id": AGENT_SYSTEM_USER_ID, "body": comment},
                    metadata={
                        "actor_id": AGENT_SYSTEM_USER_ID,
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
                "actor_id": AGENT_SYSTEM_USER_ID,
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
                    "actor_id": AGENT_SYSTEM_USER_ID,
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
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            requested_at_iso=completed_at,
        )
        db.commit()


def _record_automation_failure(run: QueuedAutomationRun, error: Exception) -> None:
    failed_at = to_iso_utc(datetime.now(timezone.utc))
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=EVENT_AUTOMATION_FAILED,
            payload={"failed_at": failed_at, "error": str(error), "summary": "Automation runner failed."},
            metadata={
                "actor_id": AGENT_SYSTEM_USER_ID,
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
                    "actor_id": AGENT_SYSTEM_USER_ID,
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
                execution_triggers=state.get("execution_triggers"),
                now_utc=now_utc,
            )
        _requeue_pending_status_change_request(
            db=db,
            run=run,
            state=state,
            workspace_id=workspace_id,
            project_id=project_id,
            requested_at_iso=failed_at,
        )
        db.commit()


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
    with SessionLocal() as db:
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.desc()).limit(scan_limit)
        ).scalars().all()

    claimed_runs: list[QueuedAutomationRun] = []
    for task_id in candidate_ids:
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
            # Keep worker alive; failures are reflected on the next cycle.
            pass
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
            failed_at = to_iso_utc(now)
            error = f"Automation run exceeded stale threshold ({int(stale_after_seconds)}s) and was recovered."
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=task_id,
                event_type=EVENT_AUTOMATION_FAILED,
                payload={"failed_at": failed_at, "error": error, "summary": "Automation runner recovered stale running task."},
                metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
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
                        metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
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
                            "actor_id": AGENT_SYSTEM_USER_ID,
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
                    "actor_id": AGENT_SYSTEM_USER_ID,
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
                    "actor_id": AGENT_SYSTEM_USER_ID,
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
