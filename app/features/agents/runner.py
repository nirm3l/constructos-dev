from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
import re

from sqlalchemy import select

from plugins.runner_policy import (
    blocker_escalation_notification,
    is_agent_project_role,
    is_blocker_source_role,
    is_developer_role,
    is_kickoff_instruction,
    is_qa_role,
    is_recurring_oversight_task,
    lead_role_for_escalation,
    normalize_success_outcome,
    success_validation_error,
    preflight_error as plugin_preflight_error,
)
from .executor import AutomationOutcome, build_automation_usage_metadata, execute_task_automation_stream
from .service import AgentTaskService
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
from shared.models import Note, Project, ProjectMember, ProjectRule, ProjectSkill, SessionLocal, Task, User as UserModel
from shared.serializers import to_iso_utc
from shared.typed_notifications import append_notification_created_event
from shared.settings import (
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
    AGENT_RUNNER_ENABLED,
    AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS,
    AGENT_RUNNER_INTERVAL_SECONDS,
    AGENT_RUNNER_MAX_CONCURRENCY,
    AGENT_SYSTEM_USER_ID,
    MCP_AUTH_TOKEN,
    logger,
)
from shared.task_automation import (
    STATUS_MATCH_ALL,
    STATUS_SCOPE_EXTERNAL,
    TRIGGER_KIND_STATUS_CHANGE,
    first_enabled_schedule_trigger,
    normalize_execution_triggers,
    parse_schedule_due_at,
    rearm_first_schedule_trigger,
    selector_matches_task,
    schedule_trigger_matches_status,
)

_runner_stop_event = threading.Event()
_runner_wakeup_event = threading.Event()
_runner_thread: threading.Thread | None = None
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)
_TASK_BRANCH_RE = re.compile(r"\btask/[a-z0-9][a-z0-9._/-]*\b", re.IGNORECASE)
_TRANSIENT_INTERRUPT_RE = re.compile(r"(?:exit=-15|sigterm|terminated by signal 15)", re.IGNORECASE)
_RECOVERABLE_FAILURE_RE = re.compile(
    r"(?:exit=-15|sigterm|terminated by signal 15|timeout|timed out|429|rate limit|502|503|504|bad gateway|gateway timeout|temporarily unavailable|connection reset)",
    re.IGNORECASE,
)
_MAX_RECOVERABLE_RETRIES = 3
_KICKOFF_EXECUTION_HOLDOFF_SECONDS = 20
_AUTOMATION_STREAM_PROGRESS_MAX_CHARS = 24000
_AUTOMATION_STREAM_FLUSH_INTERVAL_SECONDS = 0.35
_AUTOMATION_STREAM_NOISY_STATUS_MESSAGES = {
    "Codex started processing the request.",
    "Reasoning step completed.",
}
_STATUS_CHANGE_AUTOMATION_ACTIONS = {
    "automation",
    "execute_instruction",
    "queue",
    "queue_automation",
    "queue_instruction",
    "request_automation",
    "request_instruction",
    "run",
    "run_automation",
    "run_instruction",
    "run_task_instruction",
    "start_automation",
    "start_instruction",
    "trigger_automation",
    "trigger_instruction",
}


def execute_task_automation(**kwargs):
    return execute_task_automation_stream(**kwargs)


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


def _parse_iso_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        candidate = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _normalize_nonnegative_int(value) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(0, parsed)


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


def _parse_iso_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _project_has_git_delivery_skill(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    row = db.execute(
        select(ProjectSkill.id).where(
            ProjectSkill.workspace_id == workspace_id,
            ProjectSkill.project_id == normalized_project_id,
            ProjectSkill.skill_key == "git_delivery",
            ProjectSkill.enabled == True,  # noqa: E712
            ProjectSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return row is not None


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


def _extract_json_body(raw: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate.startswith("```"):
        return candidate
    lines = candidate.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    if lines and lines[0].strip().lower() == "json":
        lines = lines[1:]
    return "\n".join(lines).strip()


def _project_team_mode_execution_enabled(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not workspace_id or not normalized_project_id:
        return False
    gate_rules = db.execute(
        select(ProjectRule)
        .where(
            ProjectRule.workspace_id == workspace_id,
            ProjectRule.project_id == normalized_project_id,
            ProjectRule.is_deleted == False,  # noqa: E712
            ProjectRule.title.ilike("Gate Policy"),
        )
        .order_by(ProjectRule.updated_at.desc())
    ).scalars().all()
    if not gate_rules:
        return True
    for rule in gate_rules:
        parsed = None
        body = _extract_json_body(str(rule.body or ""))
        if body:
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = None
        if not isinstance(parsed, dict):
            continue
        mode = str(parsed.get("mode") or "").strip().lower()
        if not mode:
            return True
        return mode == "execution"
    return True


def _project_has_repo_context(*, db, workspace_id: str, project_id: str | None) -> bool:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False
    project = db.get(Project, normalized_project_id)
    if project is None or bool(getattr(project, "is_deleted", False)):
        return False
    project_rules = db.execute(
        select(ProjectRule).where(
            ProjectRule.workspace_id == workspace_id,
            ProjectRule.project_id == normalized_project_id,
            ProjectRule.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()
    return AgentTaskService._project_has_repo_context(
        project_description=str(getattr(project, "description", "") or ""),
        project_external_refs=getattr(project, "external_refs", "[]"),
        project_rules=project_rules,
    )


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
        if not is_agent_project_role(project_role):
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


def _extract_commit_shas_from_text(text: str | None) -> set[str]:
    raw = str(text or "")
    return {str(match).lower() for match in _COMMIT_SHA_EXPLICIT_RE.findall(raw)}


def _task_has_git_delivery_completion_evidence(
    *,
    state: dict | None,
    summary: str,
    comment: str | None,
) -> bool:
    source = dict(state or {})
    title = str(source.get("title") or "").strip()
    description = str(source.get("description") or "").strip()
    instruction = str(source.get("instruction") or "").strip()
    scheduled_instruction = str(source.get("scheduled_instruction") or "").strip()
    refs = source.get("external_refs")
    corpus = "\n".join(
        [
            title,
            description,
            instruction,
            scheduled_instruction,
            str(summary or ""),
            str(comment or ""),
        ]
    )
    commit_refs = _extract_commit_shas_from_refs(refs)
    commit_text = _extract_commit_shas_from_text(corpus)
    has_commit_evidence = bool(commit_refs or commit_text)
    has_branch_evidence = bool(_TASK_BRANCH_RE.search(corpus))
    if not (has_commit_evidence and has_branch_evidence):
        return False
    is_deploy_task = "deploy" in title.lower() or "docker compose" in title.lower()
    if not is_deploy_task:
        return True
    deploy_markers = ("docker compose", "/health", "http 200", "up (healthy)", "healthcheck")
    deploy_corpus = corpus.lower()
    return any(marker in deploy_corpus for marker in deploy_markers)


def _normalize_string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _parse_task_labels(raw_labels: str | None) -> list[str]:
    if not raw_labels:
        return []
    try:
        parsed = json.loads(raw_labels)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item or "").strip() for item in parsed if str(item or "").strip()]


def _task_state_for_selector(task: Task) -> dict[str, object]:
    return {
        "id": str(task.id or "").strip(),
        "workspace_id": str(task.workspace_id or "").strip(),
        "project_id": str(task.project_id or "").strip(),
        "specification_id": str(task.specification_id or "").strip(),
        "assignee_id": str(task.assignee_id or "").strip(),
        "labels": _parse_task_labels(task.labels),
        "status": str(task.status or "").strip(),
        "updated_at": to_iso_utc(task.updated_at) if getattr(task, "updated_at", None) else None,
    }


def _normalize_status_change_action(raw: object) -> str | None:
    if isinstance(raw, dict):
        return str(raw.get("type") or raw.get("action") or "").strip().lower() or None
    return str(raw or "").strip().lower() or None


def _is_cross_task_automation_action(action: str | None) -> bool:
    if not action:
        return True
    return action in _STATUS_CHANGE_AUTOMATION_ACTIONS


def _task_has_execution_evidence(*, db, task_id: str, state: dict | None) -> bool:
    source = dict(state or {})
    external_refs = source.get("external_refs")
    if isinstance(external_refs, list):
        for item in external_refs:
            if isinstance(item, dict) and str(item.get("url") or "").strip():
                return True
            if isinstance(item, str) and str(item).strip():
                return True
    attachment_refs = source.get("attachment_refs")
    if isinstance(attachment_refs, list):
        for item in attachment_refs:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                return True
    note_row = db.execute(
        select(Note.id).where(
            Note.task_id == task_id,
            Note.is_deleted == False,  # noqa: E712
        ).limit(1)
    ).scalar_one_or_none()
    return note_row is not None


def _is_noop_ack_comment(comment: str | None) -> bool:
    normalized = str(comment or "").strip().casefold()
    if not normalized:
        return False
    return normalized.startswith("codex runner: request accepted, leaving progress note.")


def _is_transient_runner_interruption(error: Exception | str | None) -> bool:
    text = str(error or "").strip()
    if not text:
        return False
    return bool(_TRANSIENT_INTERRUPT_RE.search(text))


def _is_recoverable_failure(error: Exception | str | None) -> bool:
    text = str(error or "").strip()
    if not text:
        return False
    return bool(_RECOVERABLE_FAILURE_RE.search(text))


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
    lead_role = lead_role_for_escalation(db=db, workspace_id=workspace_id, project_id=normalized_project_id)
    if not str(lead_role or "").strip():
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
            ProjectMember.role == str(lead_role),
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
        notification_cfg = blocker_escalation_notification(
            blocked_task_id=blocked_task_id,
            blocked_title=blocked_title,
            blocked_role=blocked_role,
            blocked_status=blocked_status,
            blocked_error=blocked_error,
            queued_lead_tasks=queued,
        )
        message = str(notification_cfg.get("message") or "").strip() or (
            f"Workflow blocker detected: {blocked_title or blocked_task_id} "
            f"({blocked_role or 'agent'}, status={blocked_status or 'Blocked'}). "
            "Lead escalation run was queued."
        )
        kind = str(notification_cfg.get("kind") or "").strip() or "workflow_blocker_escalation"
        dedupe_prefix = str(notification_cfg.get("dedupe_prefix") or "").strip() or "workflow-blocker"
        source_event = str(notification_cfg.get("source_event") or "").strip() or "agents.runner.blocker_escalation"
        append_notification_created_event(
            db,
            append_event_fn=append_event,
            user_id=human_id,
            message=message,
            actor_id=lead_assignee,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
            task_id=blocked_task_id,
            notification_type="ManualMessage",
            severity="warning",
            dedupe_key=f"{dedupe_prefix}:{blocked_task_id}:{blocked_status or 'Blocked'}:{dedupe_hash}",
            payload={
                "kind": kind,
                "blocked_task_id": blocked_task_id,
                "blocked_role": blocked_role,
                "blocked_status": blocked_status,
                "queued_lead_tasks": queued,
                "error": blocked_summary,
            },
            source_event=source_event,
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
        requested_instruction = str(state.get("last_requested_instruction") or "").strip()
        if is_kickoff_instruction(requested_instruction):
            requested_at_dt = _parse_iso_utc(str(state.get("last_requested_at") or "").strip())
            if requested_at_dt is not None:
                age_seconds = (datetime.now(timezone.utc) - requested_at_dt).total_seconds()
                if age_seconds < float(_KICKOFF_EXECUTION_HOLDOFF_SECONDS):
                    return None
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
                payload={
                    "started_at": now_iso,
                    "last_agent_progress": "Automation run started.",
                    "last_agent_stream_status": "Automation run started.",
                    "last_agent_stream_updated_at": now_iso,
                },
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


def _record_automation_success(run: QueuedAutomationRun, *, outcome: AutomationOutcome) -> None:
    action = str(outcome.action or "").strip()
    summary = str(outcome.summary or "").strip()
    comment = str(outcome.comment or "").strip() or None
    usage_metadata = build_automation_usage_metadata(outcome)
    usage_payload = usage_metadata.get("last_agent_usage")
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
        git_delivery_enabled = _project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id)
        team_mode_enabled = _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id)

        validation_error = success_validation_error(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=run.task_id,
            task_state=state,
            assignee_role=assignee_role,
            action=action,
            summary=summary,
            comment=comment,
            has_git_delivery_skill=git_delivery_enabled,
        )
        if validation_error:
            raise RuntimeError(validation_error)

        queued_blocker_escalations = 0
        action, summary, comment = normalize_success_outcome(
            action=action,
            summary=summary,
            comment=comment,
            instruction=str(run.instruction or "").strip(),
            assignee_role=assignee_role,
            task_state=state,
        )
        if (
            action != "complete"
            and git_delivery_enabled
            and not team_mode_enabled
            and str(state.get("status") or "").strip() != "Done"
            and _task_has_git_delivery_completion_evidence(state=state, summary=summary, comment=comment)
        ):
            action = "complete"

        if _normalize_nonnegative_int(state.get("runner_recover_retry_count")) > 0:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={"runner_recover_retry_count": 0},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )

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
            payload={
                "completed_at": completed_at,
                "summary": summary,
                "source_event": EVENT_AUTOMATION_REQUESTED,
                "comment": comment,
                "usage": usage_payload if isinstance(usage_payload, dict) else None,
                "prompt_mode": usage_metadata.get("last_agent_prompt_mode"),
                "prompt_segment_chars": usage_metadata.get("last_agent_prompt_segment_chars"),
                "codex_session_id": usage_metadata.get("last_agent_codex_session_id"),
                "resume_attempted": usage_metadata.get("last_agent_codex_resume_attempted"),
                "resume_succeeded": usage_metadata.get("last_agent_codex_resume_succeeded"),
                "resume_fallback_used": usage_metadata.get("last_agent_codex_resume_fallback_used"),
            },
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
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_agent_stream_status": "Automation run completed.",
                "last_agent_stream_updated_at": completed_at,
                **usage_metadata,
            },
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
            and not _is_noop_ack_comment(comment)
            and (
                (is_developer_role(assignee_role) and current_status == "Dev" and not commit_shas)
                or (
                    is_qa_role(assignee_role)
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
        if is_blocker_source_role(assignee_role) and str(
            state.get("status") or ""
        ).strip() == "Blocked":
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
    transient_interruption = _is_transient_runner_interruption(error)
    recoverable_failure = _is_recoverable_failure(error)
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
        retry_count = _normalize_nonnegative_int(state.get("runner_recover_retry_count"))
        should_retry = transient_interruption or (recoverable_failure and retry_count < _MAX_RECOVERABLE_RETRIES)
        if (
            AGENT_RUNNER_APPLY_OUTCOME_MUTATIONS
            and is_blocker_source_role(assignee_role)
            and str(state.get("status") or "").strip() != "Blocked"
            and not should_retry
        ):
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={"status": "Blocked"},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
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
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=run.task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "last_agent_stream_status": "Automation run failed.",
                "last_agent_stream_updated_at": failed_at,
            },
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
        if should_retry:
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={"runner_recover_retry_count": retry_count + 1},
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            retry_instruction = (
                str(run.instruction or "").strip()
                or str(state.get("instruction") or "").strip()
                or str(state.get("scheduled_instruction") or "").strip()
            )
            if retry_instruction:
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=run.task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": failed_at,
                        "instruction": retry_instruction,
                        "source": (
                            "runner_recover_after_interrupt"
                            if transient_interruption
                            else "runner_recover_after_failure"
                        ),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": run.task_id,
                    },
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
        if is_blocker_source_role(assignee_role):
            if not should_retry:
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


def _preflight_automation_error(run: QueuedAutomationRun) -> str | None:
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        workspace_id = str(state.get("workspace_id") or run.workspace_id or "").strip()
        if not workspace_id:
            return None
        project_id = str(state.get("project_id") or run.project_id or "").strip() or None
        assignee_role = _resolve_assignee_project_role(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            assignee_id=str(state.get("assignee_id") or ""),
        )
        return plugin_preflight_error(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            task_status=str(state.get("status") or "").strip() or None,
            assignee_role=assignee_role,
            has_git_delivery_skill=_project_has_git_delivery_skill(db=db, workspace_id=workspace_id, project_id=project_id),
            has_repo_context=_project_has_repo_context(db=db, workspace_id=workspace_id, project_id=project_id),
        )


def _execute_claimed_automation(run: QueuedAutomationRun) -> None:
    preflight_error = _preflight_automation_error(run)
    if preflight_error:
        _record_automation_failure(run, RuntimeError(preflight_error))
        return
    resume_codex_session_id: str | None = None
    with SessionLocal() as db:
        state, _ = rebuild_state(db, "Task", run.task_id)
        existing_codex_session_id = str(state.get("last_agent_codex_session_id") or "").strip()
        resume_attempted = _coerce_bool(state.get("last_agent_codex_resume_attempted"))
        resume_last_succeeded = _coerce_bool(state.get("last_agent_codex_resume_succeeded"))
        resume_blocked = resume_attempted is True and resume_last_succeeded is False
        if existing_codex_session_id and not resume_blocked:
            resume_codex_session_id = existing_codex_session_id
    stream_lock = threading.Lock()
    stream_text = ""
    stream_status = ""
    last_flush_at = 0.0

    def _persist_stream_progress(*, force: bool = False) -> None:
        nonlocal last_flush_at, stream_text, stream_status
        now_monotonic = time.monotonic()
        if not force and (now_monotonic - last_flush_at) < _AUTOMATION_STREAM_FLUSH_INTERVAL_SECONDS:
            return
        last_flush_at = now_monotonic
        with stream_lock:
            progress = stream_text[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            status_text = stream_status
        now_iso = to_iso_utc(datetime.now(timezone.utc))
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
            append_event(
                db,
                aggregate_type="Task",
                aggregate_id=run.task_id,
                event_type=TASK_EVENT_UPDATED,
                payload={
                    "last_agent_progress": progress,
                    "last_agent_stream_status": status_text or None,
                    "last_agent_stream_updated_at": now_iso,
                },
                metadata={
                    "actor_id": actor_user_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "task_id": run.task_id,
                },
            )
            db.commit()

    def _on_stream_event(event: dict[str, object]) -> None:
        nonlocal stream_text, stream_status
        event_type = str(event.get("type") or "").strip()
        if event_type == "assistant_text":
            delta = str(event.get("delta") or "")
            if not delta:
                return
            with stream_lock:
                stream_text = (stream_text + delta)[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            _persist_stream_progress(force=False)
            return
        if event_type == "status":
            message = str(event.get("message") or "").strip()
            if not message:
                return
            if message in _AUTOMATION_STREAM_NOISY_STATUS_MESSAGES:
                return
            with stream_lock:
                stream_status = message
                stream_text = (f"{stream_text}\n\n{message}".strip())[-_AUTOMATION_STREAM_PROGRESS_MAX_CHARS:]
            _persist_stream_progress(force=True)

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
            codex_session_id=resume_codex_session_id,
            allow_mutations=True,
            prompt_instruction_segments={"user_instruction": len(run.instruction)},
            on_event=_on_stream_event,
        )
        _persist_stream_progress(force=True)
    except Exception as exc:
        _persist_stream_progress(force=True)
        _record_automation_failure(run, exc)
        return

    try:
        _record_automation_success(
            run,
            outcome=outcome,
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


def queue_satisfied_external_status_triggers_once(limit: int = 20) -> int:
    queued = 0
    now_iso = to_iso_utc(datetime.now(timezone.utc))
    with SessionLocal() as db:
        candidate_tasks = db.execute(
            select(Task)
            .where(
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
                Task.execution_triggers.ilike("%status_change%"),
            )
            .order_by(Task.updated_at.asc())
            .limit(max(limit * 20, limit))
        ).scalars().all()
        workspace_cache: dict[str, list[dict[str, object]]] = {}

        def _workspace_states(workspace_id: str) -> list[dict[str, object]]:
            if workspace_id not in workspace_cache:
                rows = db.execute(
                    select(Task).where(
                        Task.workspace_id == workspace_id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.archived == False,  # noqa: E712
                    )
                ).scalars().all()
                workspace_cache[workspace_id] = [_task_state_for_selector(row) for row in rows]
            return workspace_cache[workspace_id]

        for task in candidate_tasks:
            if queued >= limit:
                break
            task_id = str(task.id or "").strip()
            if not task_id:
                continue
            workspace_id = str(task.workspace_id or "").strip()
            project_id = str(task.project_id or "").strip() or None
            if not workspace_id or not project_id:
                continue
            if not _project_has_team_mode_skill(db=db, workspace_id=workspace_id, project_id=project_id):
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

            state, _ = rebuild_state(db, "Task", task_id)
            if str(state.get("automation_state") or "idle").strip() in {"queued", "running"}:
                continue
            instruction = (
                str(state.get("instruction") or "").strip()
                or str(state.get("scheduled_instruction") or "").strip()
            )
            if not instruction:
                continue

            triggers = normalize_execution_triggers(state.get("execution_triggers"))
            if not triggers:
                continue
            task_states = _workspace_states(workspace_id)
            for trigger in triggers:
                if str(trigger.get("kind") or "") != TRIGGER_KIND_STATUS_CHANGE:
                    continue
                if not bool(trigger.get("enabled", True)):
                    continue
                if str(trigger.get("scope") or "").strip().lower() != STATUS_SCOPE_EXTERNAL:
                    continue
                action = _normalize_status_change_action(trigger.get("action"))
                if not _is_cross_task_automation_action(action):
                    continue
                # Reconcile only triggers defined by destination status. Transition-source constraints
                # cannot be safely inferred without a concrete status-change event.
                if _normalize_string_list(trigger.get("from_statuses")):
                    continue
                to_statuses = _normalize_string_list(trigger.get("to_statuses"))
                if not to_statuses:
                    continue
                allowed_statuses = {value.casefold() for value in to_statuses}

                selector = trigger.get("selector")
                selected_sources = [
                    item
                    for item in task_states
                    if str(item.get("id") or "").strip() != task_id and selector_matches_task(task_state=item, selector=selector)
                ]
                if not selected_sources:
                    continue
                satisfied_sources = [
                    item
                    for item in selected_sources
                    if str(item.get("status") or "").strip().casefold() in allowed_statuses
                ]
                match_mode = str(trigger.get("match_mode") or "").strip().lower()
                if match_mode == STATUS_MATCH_ALL:
                    if len(satisfied_sources) != len(selected_sources):
                        continue
                    trigger_source = satisfied_sources[0]
                else:
                    if not satisfied_sources:
                        continue
                    trigger_source = satisfied_sources[0]

                trigger_task_id = str(trigger_source.get("id") or "").strip() or None
                trigger_to_status = str(trigger_source.get("status") or "").strip() or None
                last_source = str(state.get("last_requested_source") or "").strip().lower()
                last_trigger_task_id = str(state.get("last_requested_trigger_task_id") or "").strip()
                last_to_status = str(state.get("last_requested_to_status") or "").strip()
                if (
                    last_source in {"status_change", "trigger_reconcile"}
                    and last_trigger_task_id
                    and trigger_task_id
                    and last_trigger_task_id == trigger_task_id
                    and (not trigger_to_status or last_to_status.casefold() == trigger_to_status.casefold())
                ):
                    continue

                actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
                append_event(
                    db,
                    aggregate_type="Task",
                    aggregate_id=task_id,
                    event_type=EVENT_AUTOMATION_REQUESTED,
                    payload={
                        "requested_at": now_iso,
                        "instruction": instruction,
                        "source": "trigger_reconcile",
                        "trigger_task_id": trigger_task_id,
                        "from_status": None,
                        "to_status": trigger_to_status,
                        "triggered_at": str(trigger_source.get("updated_at") or now_iso),
                    },
                    metadata={
                        "actor_id": actor_user_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "task_id": task_id,
                        "trigger_task_id": trigger_task_id,
                        "trigger_to_status": trigger_to_status,
                    },
                )
                db.commit()
                queued += 1
                break
    return queued


def _eligible_for_team_mode_auto_queue(state: dict[str, object], *, now_utc: datetime, cooldown_seconds: int = 45) -> bool:
    automation_state = str(state.get("automation_state") or "idle").strip().lower()
    if automation_state in {"queued", "running"}:
        return False
    if automation_state not in {"idle", "failed", "completed"}:
        return False
    last_requested = _parse_iso_timestamp(state.get("last_requested_at"))
    if last_requested is None:
        return True
    return (now_utc - last_requested).total_seconds() >= float(max(5, cooldown_seconds))


def queue_team_mode_happy_path_once(limit: int = 20) -> int:
    queued = 0
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        team_mode_projects = db.execute(
            select(ProjectSkill.project_id)
            .where(
                ProjectSkill.skill_key == "team_mode",
                ProjectSkill.enabled == True,  # noqa: E712
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
            .distinct()
        ).scalars().all()
        for project_id in [str(item or "").strip() for item in team_mode_projects if str(item or "").strip()]:
            if queued >= limit:
                break
            project = db.get(Project, project_id)
            if project is None or bool(getattr(project, "is_deleted", False)):
                continue
            workspace_id = str(project.workspace_id or "").strip()
            if not workspace_id:
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

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
                    Task.project_id == project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                    Task.status != "Done",
                    ProjectMember.role.in_(["DeveloperAgent", "TeamLeadAgent", "QAAgent"]),
                )
                .order_by(Task.created_at.asc())
            ).all()
            if not rows:
                continue

            dev_candidates: list[tuple[Task, dict[str, object]]] = []
            lead_candidates: list[tuple[Task, dict[str, object]]] = []
            qa_candidates: list[tuple[Task, dict[str, object]]] = []
            lead_tasks_in_lead_status = 0

            for task, role in rows:
                state, _ = rebuild_state(db, "Task", str(task.id))
                normalized_role = str(role or "").strip()
                normalized_status = str(state.get("status") or task.status or "").strip()
                if normalized_role == "TeamLeadAgent" and normalized_status == "Lead":
                    lead_tasks_in_lead_status += 1

                if not _eligible_for_team_mode_auto_queue(state, now_utc=now_utc):
                    continue
                instruction = (
                    str(state.get("instruction") or "").strip()
                    or str(state.get("scheduled_instruction") or "").strip()
                )
                if not instruction:
                    continue
                if normalized_role == "DeveloperAgent" and normalized_status == "Dev":
                    dev_candidates.append((task, state))
                elif normalized_role == "TeamLeadAgent" and normalized_status == "Lead":
                    lead_candidates.append((task, state))
                elif normalized_role == "QAAgent" and normalized_status == "QA":
                    qa_candidates.append((task, state))

            to_queue: list[tuple[Task, dict[str, object]]] = []
            if dev_candidates:
                to_queue.extend([(task, state) for task, state in dev_candidates])
            else:
                # Mainline Team Mode progression: Dev -> Lead -> QA.
                # QA runs only after Lead handoff has happened (no Lead task remains in Lead status).
                if lead_tasks_in_lead_status > 0:
                    to_queue.extend([(task, state) for task, state in lead_candidates])
                else:
                    to_queue.extend([(task, state) for task, state in qa_candidates])

            from features.tasks.application import TaskApplicationService
            from shared.core import TaskAutomationRun

            for task, state in to_queue:
                if queued >= limit:
                    break
                task_id = str(task.id or "").strip()
                if not task_id:
                    continue
                actor_user_id = _resolve_task_actor_user_id(db=db, task_id=task_id, state=state)
                actor = db.get(UserModel, actor_user_id)
                if actor is None or not bool(getattr(actor, "is_active", False)):
                    continue
                instruction = (
                    str(state.get("instruction") or "").strip()
                    or str(state.get("scheduled_instruction") or "").strip()
                )
                if not instruction:
                    continue
                command_id = f"tm-orch-{project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
                try:
                    TaskApplicationService(db, actor, command_id=command_id).request_automation_run(
                        task_id,
                        TaskAutomationRun(instruction=instruction),
                        wake_runner=False,
                    )
                except Exception:
                    continue
                queued += 1
            db.commit()
    return queued


def closeout_team_mode_tasks_once(limit: int = 20) -> int:
    completed = 0
    now_utc = datetime.now(timezone.utc)
    with SessionLocal() as db:
        team_mode_projects = db.execute(
            select(ProjectSkill.project_id)
            .where(
                ProjectSkill.skill_key == "team_mode",
                ProjectSkill.enabled == True,  # noqa: E712
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
            .distinct()
        ).scalars().all()
        from features.agents.service import AgentTaskService
        from features.tasks.application import TaskApplicationService

        for project_id in [str(item or "").strip() for item in team_mode_projects if str(item or "").strip()]:
            if completed >= limit:
                break
            project = db.get(Project, project_id)
            if project is None or bool(getattr(project, "is_deleted", False)):
                continue
            workspace_id = str(project.workspace_id or "").strip()
            if not workspace_id:
                continue
            if not _project_team_mode_execution_enabled(db=db, workspace_id=workspace_id, project_id=project_id):
                continue

            try:
                verification = AgentTaskService(
                    require_token=False,
                    actor_user_id=AGENT_SYSTEM_USER_ID,
                ).verify_delivery_workflow(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    auth_token=MCP_AUTH_TOKEN or None,
                )
            except Exception:
                continue
            if not bool((verification or {}).get("ok")):
                continue

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
                    Task.project_id == project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                    Task.status != "Done",
                    ProjectMember.role.in_(["DeveloperAgent", "TeamLeadAgent", "QAAgent"]),
                )
                .order_by(Task.created_at.asc())
            ).all()
            if not rows:
                continue

            lead_rows_count = sum(1 for _, role in rows if str(role or "").strip() == "TeamLeadAgent")
            ordered_candidates: list[tuple[Task, str, dict[str, object]]] = []
            priority = {"DeveloperAgent": 0, "QAAgent": 1, "TeamLeadAgent": 2}
            for task, role in rows:
                normalized_role = str(role or "").strip()
                state, _ = rebuild_state(db, "Task", str(task.id))
                ordered_candidates.append((task, normalized_role, state))
            ordered_candidates.sort(key=lambda item: priority.get(item[1], 99))

            for task, role, state in ordered_candidates:
                if completed >= limit:
                    break
                task_id = str(task.id or "").strip()
                if not task_id:
                    continue
                if role == "TeamLeadAgent" and lead_rows_count > 1 and is_recurring_oversight_task(state):
                    # Keep long-running oversight tasks active when there is a dedicated deploy Lead task.
                    continue
                actor_user_id = _resolve_task_actor_user_id(
                    db=db,
                    task_id=task_id,
                    state=state,
                    fallback_actor_user_id=AGENT_SYSTEM_USER_ID,
                )
                actor = db.get(UserModel, actor_user_id)
                if actor is None or not bool(getattr(actor, "is_active", False)):
                    continue
                command_id = f"tm-close-{project_id[:8]}-{task_id[:8]}-{int(now_utc.timestamp())}"
                try:
                    TaskApplicationService(db, actor, command_id=command_id).complete_task(task_id)
                except Exception:
                    continue
                completed += 1
            db.commit()
    return completed


def _runner_loop():
    while not _runner_stop_event.is_set():
        try:
            recover_stale_running_automation_once(limit=20)
            queue_team_mode_happy_path_once(limit=20)
            queue_satisfied_external_status_triggers_once(limit=20)
            queue_due_scheduled_tasks_once(limit=20)
            run_queued_automation_once(limit=20)
            closeout_team_mode_tasks_once(limit=20)
        except Exception:
            # Keep worker alive, but do not swallow diagnostics.
            logger.exception("Automation runner tick failed.")
        woke = _runner_wakeup_event.wait(AGENT_RUNNER_INTERVAL_SECONDS)
        if woke:
            _runner_wakeup_event.clear()


def recover_stale_running_automation_once(limit: int = 20, stale_after_seconds_override: float | None = None) -> int:
    recovered = 0
    now = datetime.now(timezone.utc)
    stale_after_seconds = (
        max(float(stale_after_seconds_override), 0.0)
        if stale_after_seconds_override is not None
        else max(min(float(AGENT_EXECUTOR_TIMEOUT_SECONDS) * 2.0, 300.0), 90.0)
    )
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
            # Kickoff guard applies only to recurring oversight schedules.
            # Generic scheduled tasks should run normally.
            if is_recurring_oversight_task(state):
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
    if not AGENT_RUNNER_ENABLED:
        return
    if _runner_thread and _runner_thread.is_alive():
        return
    _runner_stop_event.clear()
    _runner_wakeup_event.clear()
    try:
        # On process restart/deploy, immediately recover orphaned "running" tasks.
        recovered = recover_stale_running_automation_once(limit=200, stale_after_seconds_override=0.0)
        if recovered > 0:
            logger.info("Automation runner startup recovered %s stale running task(s).", recovered)
    except Exception:
        logger.exception("Automation runner startup recovery failed.")
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
