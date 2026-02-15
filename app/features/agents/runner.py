from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .executor import execute_task_automation
from features.tasks.domain import (
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
from shared.eventing import append_event, rebuild_state
from shared.models import SessionLocal, Task
from shared.schedule import next_scheduled_at_utc, parse_recurring_rule
from shared.serializers import to_iso_utc
from shared.settings import AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS, AGENT_RUNNER_INTERVAL_SECONDS, AGENT_SYSTEM_USER_ID
from shared.settings import AGENT_EXECUTOR_TIMEOUT_SECONDS

_runner_stop_event = threading.Event()
_runner_thread: threading.Thread | None = None


def run_queued_automation_once(limit: int = 10) -> int:
    processed = 0
    with SessionLocal() as db:
        candidate_ids = db.execute(
            select(Task.id).where(Task.is_deleted == False).order_by(Task.updated_at.asc()).limit(max(limit * 10, limit))
        ).scalars().all()

        for task_id in candidate_ids:
            state, _ = rebuild_state(db, "Task", task_id)
            if state.get("automation_state", "idle") != "queued":
                continue
            if state.get("status") == "Done":
                continue
            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue

            project_id = state.get("project_id")
            now_iso = to_iso_utc(datetime.now(timezone.utc))
            instruction = (state.get("last_requested_instruction") or "").strip()
            is_scheduled = state.get("task_type") == "scheduled_instruction"
            schedule_state = state.get("schedule_state", "idle")
            recurring_rule_raw = (state.get("recurring_rule") or "").strip() or None
            scheduled_at_raw = state.get("scheduled_at_utc")

            try:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_AUTOMATION_STARTED,
                    payload={"started_at": now_iso},
                    metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                )
                if is_scheduled and schedule_state in {"queued", "idle"}:
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

                outcome = execute_task_automation(
                    task_id=task_id,
                    title=str(state.get("title", "")),
                    description=str(state.get("description", "")),
                    status=str(state.get("status", "To do")),
                    instruction=instruction,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    allow_mutations=True,
                )

                if AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS:
                    latest_state, _ = rebuild_state(db, "Task", task_id)
                    if outcome.action == "complete" and latest_state.get("status") != "Done":
                        append_event(
                            db,
                            aggregate_type="Task",
                            aggregate_id=task_id,
                            event_type=TASK_EVENT_COMPLETED,
                            payload={"completed_at": now_iso},
                            metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                        )
                    if outcome.comment:
                        comment = outcome.comment
                        append_event(
                            db,
                            aggregate_type="Task",
                            aggregate_id=task_id,
                            event_type=EVENT_COMMENT_ADDED,
                            payload={"task_id": task_id, "user_id": AGENT_SYSTEM_USER_ID, "body": comment},
                            metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                        )

                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_AUTOMATION_COMPLETED,
                    payload={"completed_at": now_iso, "summary": outcome.summary, "source_event": EVENT_AUTOMATION_REQUESTED},
                    metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                )
                if is_scheduled:
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=EVENT_SCHEDULE_COMPLETED,
                        payload={"completed_at": now_iso, "summary": outcome.summary},
                        metadata={
                            "actor_id": AGENT_SYSTEM_USER_ID,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
                    # Recurring schedules: re-arm the task for the next run.
                    interval = parse_recurring_rule(recurring_rule_raw)
                    if interval and scheduled_at_raw:
                        try:
                            base_scheduled_at = datetime.fromisoformat(str(scheduled_at_raw))
                            next_at = next_scheduled_at_utc(
                                base_scheduled_at_utc=base_scheduled_at,
                                now_utc=datetime.now(timezone.utc),
                                interval=interval,
                            )
                            append_event(
                                db,
                                aggregate_type="Task",
                                aggregate_id=task_id,
                                event_type="TaskUpdated",
                                payload={"scheduled_at_utc": to_iso_utc(next_at), "schedule_state": "idle"},
                                metadata={
                                    "actor_id": AGENT_SYSTEM_USER_ID,
                                    "workspace_id": workspace_id,
                                    "project_id": project_id,
                                    "task_id": task_id,
                                },
                            )
                        except Exception:
                            # If the rule/time is malformed, keep the schedule as-is (one-shot behavior).
                            pass
                db.commit()
            except Exception as exc:
                db.rollback()
                failed_at = to_iso_utc(datetime.now(timezone.utc))
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_AUTOMATION_FAILED,
                    payload={"failed_at": failed_at, "error": str(exc), "summary": "Automation runner failed."},
                    metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
                )
                if is_scheduled:
                    append_event(
                        db,
                        aggregate_type="Task",
                        aggregate_id=task_id,
                        event_type=EVENT_SCHEDULE_FAILED,
                        payload={"failed_at": failed_at, "error": str(exc)},
                        metadata={
                            "actor_id": AGENT_SYSTEM_USER_ID,
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "task_id": task_id,
                        },
                    )
                    # If it's recurring, keep the cadence going even after failures.
                    interval = parse_recurring_rule(recurring_rule_raw)
                    if interval and scheduled_at_raw:
                        try:
                            base_scheduled_at = datetime.fromisoformat(str(scheduled_at_raw))
                            next_at = next_scheduled_at_utc(
                                base_scheduled_at_utc=base_scheduled_at,
                                now_utc=datetime.now(timezone.utc),
                                interval=interval,
                            )
                            append_event(
                                db,
                                aggregate_type="Task",
                                aggregate_id=task_id,
                                event_type="TaskUpdated",
                                payload={"scheduled_at_utc": to_iso_utc(next_at), "schedule_state": "idle"},
                                metadata={
                                    "actor_id": AGENT_SYSTEM_USER_ID,
                                    "workspace_id": workspace_id,
                                    "project_id": project_id,
                                    "task_id": task_id,
                                },
                            )
                        except Exception:
                            pass
                db.commit()
            processed += 1
            if processed >= limit:
                break

    return processed


def _runner_loop():
    while not _runner_stop_event.is_set():
        try:
            recover_stale_running_automation_once(limit=20)
            queue_due_scheduled_tasks_once(limit=20)
            run_queued_automation_once(limit=20)
        except Exception:
            # Keep worker alive; failures are reflected on the next cycle.
            pass
        _runner_stop_event.wait(AGENT_RUNNER_INTERVAL_SECONDS)


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
            if state.get("task_type") == "scheduled_instruction":
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_SCHEDULE_FAILED,
                    payload={"failed_at": failed_at, "error": error},
                    metadata={"actor_id": AGENT_SYSTEM_USER_ID, "workspace_id": workspace_id, "project_id": project_id, "task_id": task_id},
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
        tasks = db.execute(
            select(Task)
            .where(
                Task.is_deleted == False,
                Task.task_type == "scheduled_instruction",
                Task.schedule_state == "idle",
                Task.status != "Done",
                Task.scheduled_at_utc.is_not(None),
                Task.scheduled_at_utc <= now,
            )
            .order_by(Task.scheduled_at_utc.asc())
            .limit(limit)
        ).scalars().all()

        for task in tasks:
            state, _ = rebuild_state(db, "Task", task.id)
            if state.get("task_type") != "scheduled_instruction":
                continue
            if state.get("schedule_state", "idle") != "idle":
                continue
            if state.get("automation_state", "idle") in {"queued", "running"}:
                continue
            workspace_id = state.get("workspace_id")
            if not workspace_id:
                continue
            project_id = state.get("project_id")
            instruction = (state.get("scheduled_instruction") or "").strip()
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
    return queued


def start_automation_runner():
    global _runner_thread
    if _runner_thread and _runner_thread.is_alive():
        return
    _runner_stop_event.clear()
    _runner_thread = threading.Thread(target=_runner_loop, name="automation-runner", daemon=True)
    _runner_thread.start()


def stop_automation_runner():
    global _runner_thread
    _runner_stop_event.set()
    if _runner_thread and _runner_thread.is_alive():
        _runner_thread.join(timeout=3)
    _runner_thread = None
