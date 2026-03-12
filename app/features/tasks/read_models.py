from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from features.agents.gates import run_runtime_deploy_health_check
from plugins.team_mode.task_roles import derive_task_role, normalize_team_agents
from plugins.context_policy import classify_project_delivery_context
from shared.delivery_evidence import (
    derive_deploy_execution_snapshot,
    extract_task_branches_from_refs,
    has_merge_to_main_ref,
    is_strict_deploy_success_snapshot,
)
from shared.core import (
    Note,
    Task,
    ensure_project_access,
    ensure_role,
    get_user_zoneinfo,
    load_task_command_state,
    normalize_datetime_to_utc,
    rebuild_state,
    serialize_task,
)
from shared.serializers import load_created_by_map
from shared.project_repository import branch_is_merged_to_main, find_project_compose_manifest
from shared.models import Project, ProjectMember, ProjectPluginConfig, ProjectRule
from shared.task_automation import (
    build_legacy_schedule_trigger,
    derive_legacy_schedule_fields,
    normalize_execution_triggers,
)

_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\\b(?:commit|sha|changeset|hash)\\s*[:=#]?\\s*|/commit/)([0-9a-f]{7,40})\\b"
)
_TASK_BRANCH_RE = re.compile(r"\\btask/[a-z0-9][a-z0-9._/-]*\\b", re.IGNORECASE)
_MERGE_TO_MAIN_REF_PREFIX = "merge:main:"


def _parse_json_list(raw: object) -> list[dict[str, object]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _extract_commit_shas_from_refs(refs: object) -> set[str]:
    out: set[str] = set()
    for item in _parse_json_list(refs):
        text = f"{item.get('url') or ''} {item.get('label') or ''} {item.get('title') or ''}"
        for match in _COMMIT_SHA_EXPLICIT_RE.findall(text):
            out.add(str(match).lower())
    return out


def _has_task_branch_evidence(*, refs: object, task_id: str) -> bool:
    expected = f"task/{str(task_id or '').strip().lower()[:8]}"
    if not expected or expected == "task/":
        return False
    corpus_parts: list[str] = []
    for item in _parse_json_list(refs):
        corpus_parts.append(str(item.get("url") or ""))
        corpus_parts.append(str(item.get("label") or ""))
        corpus_parts.append(str(item.get("title") or ""))
    corpus = "\n".join(corpus_parts).lower()
    for match in _TASK_BRANCH_RE.findall(corpus):
        candidate = str(match or "").strip().lower()
        if candidate.startswith(expected):
            return True
    return False


def _task_has_main_merge_marker(refs: object) -> bool:
    for item in _parse_json_list(refs):
        url = str(item.get("url") or "").strip().casefold()
        if url.startswith(_MERGE_TO_MAIN_REF_PREFIX):
            return True
    return False


def _read_plugin_payload(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
    plugin_key: str,
) -> tuple[bool, dict[str, object], dict[str, object]]:
    row = db.execute(
        select(ProjectPluginConfig.enabled, ProjectPluginConfig.config_json, ProjectPluginConfig.compiled_policy_json).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == plugin_key,
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).first()
    if row is None:
        return False, {}, {}
    enabled = bool(row[0])
    def _parse_obj(raw: object) -> dict[str, object]:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return enabled, _parse_obj(row[1]), _parse_obj(row[2])


def _task_has_http_artifact(*, refs: object, notes: list[Note]) -> bool:
    def _has_http(items: list[dict[str, object]]) -> bool:
        for item in items:
            url = str(item.get("url") or "").strip().lower()
            if url.startswith("http://") or url.startswith("https://"):
                return True
        return False
    if _has_http(_parse_json_list(refs)):
        return True
    for note in notes:
        if _has_http(_parse_json_list(getattr(note, "external_refs", "[]"))):
            return True
    return False


def _resolve_task_role(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
    assignee_id: str,
    assigned_agent_code: str,
    labels: object,
    status: str,
) -> str:
    member_role_by_user_id = {
        str(user_id): str(role or "").strip()
        for user_id, role in db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
            )
        ).all()
    }
    _enabled, team_config, _team_compiled = _read_plugin_payload(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
        plugin_key="team_mode",
    )
    team_agents = normalize_team_agents(team_config.get("team"))
    agent_role_by_code = {
        str(agent.get("id") or "").strip(): str(agent.get("authority_role") or "").strip()
        for agent in team_agents
        if str(agent.get("id") or "").strip()
    }
    role = derive_task_role(
        task_like={
            "assignee_id": assignee_id,
            "assigned_agent_code": assigned_agent_code,
            "labels": labels,
            "status": status,
        },
        member_role_by_user_id=member_role_by_user_id,
        agent_role_by_code=agent_role_by_code,
    )
    return str(role or "").strip()


def _build_execution_gates(
    *,
    db: Session,
    task_id: str,
    state: dict,
    workspace_id: str,
    project_id: str | None,
) -> list[dict[str, object]]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return []
    task_row = db.get(Task, task_id)
    if task_row is None:
        return []
    project = db.get(Project, normalized_project_id)
    if project is None:
        return []
    status = str(state.get("status") or task_row.status or "").strip()
    assignee_id = str(state.get("assignee_id") or task_row.assignee_id or "").strip()
    assigned_agent_code = str(state.get("assigned_agent_code") or task_row.assigned_agent_code or "").strip()
    role = _resolve_task_role(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        assignee_id=assignee_id,
        assigned_agent_code=assigned_agent_code,
        labels=state.get("labels", task_row.labels),
        status=status,
    )
    task_notes = db.execute(
        select(Note).where(
            Note.task_id == task_id,
            Note.is_deleted == False,  # noqa: E712
            Note.archived == False,  # noqa: E712
        )
    ).scalars().all()
    git_enabled, git_config, git_compiled = _read_plugin_payload(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        plugin_key="git_delivery",
    )
    docker_enabled, docker_config, docker_compiled = _read_plugin_payload(
        db=db,
        workspace_id=workspace_id,
        project_id=normalized_project_id,
        plugin_key="docker_compose",
    )
    runtime_cfg = docker_compiled.get("runtime_deploy_health")
    if not isinstance(runtime_cfg, dict):
        runtime_cfg = docker_config.get("runtime_deploy_health") if isinstance(docker_config.get("runtime_deploy_health"), dict) else {}
    runtime_required = bool((runtime_cfg or {}).get("required")) if docker_enabled else False
    runtime_stack = str((runtime_cfg or {}).get("stack") or "constructos-ws-default")
    runtime_port_raw = (runtime_cfg or {}).get("port")
    try:
        runtime_port = int(runtime_port_raw) if runtime_port_raw is not None else None
    except Exception:
        runtime_port = None
    runtime_health_path = str((runtime_cfg or {}).get("health_path") or "/health")
    runtime_require_http_200 = bool((runtime_cfg or {}).get("require_http_200", True))
    execution_cfg = git_compiled.get("execution")
    if not isinstance(execution_cfg, dict):
        execution_cfg = git_config.get("execution") if isinstance(git_config.get("execution"), dict) else {}
    require_dev_tests = bool((execution_cfg or {}).get("require_dev_tests", False))
    external_refs = state.get("external_refs", task_row.external_refs)
    automation_state = str(state.get("automation_state") or "idle").strip().lower()
    last_error = str(state.get("last_agent_error") or "").strip()
    gates: list[dict[str, object]] = []

    if git_enabled and role == "Developer" and status == "Dev":
        project_rules = db.execute(
            select(ProjectRule).where(
                ProjectRule.workspace_id == workspace_id,
                ProjectRule.project_id == normalized_project_id,
                ProjectRule.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        has_repo_context = bool(
            classify_project_delivery_context(
                project_description=str(getattr(project, "description", "") or ""),
                project_external_refs=getattr(project, "external_refs", "[]"),
                project_rules=project_rules,
                parse_json_list=_parse_json_list,
                allow_llm=False,
            ).get("has_repo_context")
        )
        gates.append(
            {
                "id": "repo_context",
                "label": "Repository context",
                "status": "pass" if has_repo_context else "fail",
                "blocking": True,
                "message": "Project repository context is linked." if has_repo_context else "Link project repository context before Developer execution.",
            }
        )
        has_commit = bool(_extract_commit_shas_from_refs(external_refs))
        gates.append(
            {
                "id": "dev_commit_evidence",
                "label": "Commit evidence",
                "status": "pass" if has_commit else "waiting",
                "blocking": True,
                "message": "Commit evidence exists in external refs." if has_commit else "Expected external ref like commit:<sha> after implementation run.",
            }
        )
        has_branch = _has_task_branch_evidence(refs=external_refs, task_id=task_id)
        gates.append(
            {
                "id": "dev_task_branch_evidence",
                "label": "Task branch evidence",
                "status": "pass" if has_branch else "waiting",
                "blocking": True,
                "message": "Task branch evidence is present." if has_branch else "Expected external ref with task/<task-id-prefix>-... evidence.",
            }
        )
        if require_dev_tests:
            tests_gate_status = "waiting"
            tests_gate_message = "Tests must run and pass before Developer handoff."
            if "tests_run=true and tests_passed=true" in last_error:
                tests_gate_status = "fail"
                tests_gate_message = "Latest run failed test requirement."
            elif automation_state == "completed" and "tests_run=true and tests_passed=true" not in last_error and last_error == "":
                tests_gate_status = "pass"
                tests_gate_message = "Runner did not report test requirement failure."
            gates.append(
                {
                    "id": "dev_tests_required",
                    "label": "Developer tests",
                    "status": tests_gate_status,
                    "blocking": True,
                    "message": tests_gate_message,
                }
            )
        else:
            gates.append(
                {
                    "id": "dev_tests_required",
                    "label": "Developer tests",
                    "status": "not_applicable",
                    "blocking": False,
                    "message": "Tests are optional for this project (git_delivery.execution.require_dev_tests=false).",
                }
            )

    if role == "Lead" and status == "Lead" and docker_enabled and runtime_required:
        has_merge_to_main = False
        project_task_ids = [
            str(item or "").strip()
            for item in db.execute(
                select(Task.id).where(
                    Task.workspace_id == workspace_id,
                    Task.project_id == normalized_project_id,
                    Task.is_deleted == False,  # noqa: E712
                    Task.archived == False,  # noqa: E712
                )
            ).scalars().all()
            if str(item or "").strip()
        ]
        for project_task_id in project_task_ids:
            project_task_state, _ = rebuild_state(db, "Task", project_task_id)
            if has_merge_to_main_ref(project_task_state.get("external_refs")):
                has_merge_to_main = True
                break
            for branch_name in extract_task_branches_from_refs(project_task_state.get("external_refs")):
                if branch_is_merged_to_main(
                    project_name=str(getattr(project, "name", "") or ""),
                    project_id=normalized_project_id,
                    branch_name=branch_name,
                ):
                    has_merge_to_main = True
                    break
            if has_merge_to_main:
                break
        manifest = find_project_compose_manifest(
            project_name=str(getattr(project, "name", "") or ""),
            project_id=normalized_project_id,
        )
        has_manifest = manifest is not None
        gates.append(
            {
                "id": "compose_manifest",
                "label": "Compose manifest",
                "status": "pass" if has_manifest else ("waiting" if not has_merge_to_main else "fail"),
                "blocking": True,
                "message": (
                    str(manifest)
                    if has_manifest
                    else (
                        "Waiting for a committed Developer handoff before compose/deploy evaluation."
                        if not has_merge_to_main
                        else "Project repository is missing docker-compose.yml/compose.yml."
                    )
                ),
            }
        )
        if has_manifest:
            runtime = run_runtime_deploy_health_check(
                stack=runtime_stack,
                port=runtime_port,
                health_path=runtime_health_path,
                require_http_200=runtime_require_http_200,
                host=None,
            )
            gates.append(
                {
                    "id": "runtime_deploy_health",
                    "label": "Runtime deploy health",
                    "status": "pass" if bool(runtime.get("ok")) else "fail",
                    "blocking": True,
                    "message": (
                        f"Health check passed at {str(runtime.get('http_url') or f'http://gateway:{runtime_port}{runtime_health_path}')}"
                        if bool(runtime.get("ok"))
                        else str(runtime.get("http_error") or "Deploy stack is not running/healthy.")
                    ),
                }
            )

    if role == "QA" and status == "QA":
        structured_lead_handoff = bool(
            str(state.get("last_requested_workflow_scope") or "").strip() == "team_mode"
            and str(state.get("last_requested_source_task_id") or "").strip()
            and (
                str(state.get("last_requested_source") or "").strip() == "lead_handoff"
                or str(state.get("last_requested_reason") or "").strip() == "lead_handoff"
            )
        )
        has_lead_handoff_token = bool(str(state.get("last_lead_handoff_token") or "").strip()) or structured_lead_handoff
        qa_handoff_deploy = (
            state.get("last_lead_handoff_deploy_execution")
            if isinstance(state.get("last_lead_handoff_deploy_execution"), dict)
            else {}
        )
        if not qa_handoff_deploy and structured_lead_handoff:
            source_task_id = str(state.get("last_requested_source_task_id") or "").strip()
            if source_task_id:
                lead_source_state, _ = rebuild_state(db, "Task", source_task_id)
                qa_handoff_deploy = derive_deploy_execution_snapshot(
                    refs=lead_source_state.get("external_refs"),
                    current_snapshot=(
                        lead_source_state.get("last_deploy_execution")
                        if isinstance(lead_source_state.get("last_deploy_execution"), dict)
                        else {}
                    ),
                )
        qa_handoff_deploy_at = (
            str(qa_handoff_deploy.get("executed_at") or "").strip()
            if is_strict_deploy_success_snapshot(qa_handoff_deploy)
            else ""
        )
        lead_rows = db.execute(
            select(Task.id, Task.status).where(
                Task.workspace_id == workspace_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
                Task.archived == False,  # noqa: E712
            )
        ).all()
        lead_in_progress = False
        latest_lead_deploy_at = None
        for lead_task_id, lead_status in lead_rows:
            lead_state, _ = rebuild_state(db, "Task", str(lead_task_id or "").strip())
            lead_role = _resolve_task_role(
                db=db,
                workspace_id=workspace_id,
                project_id=normalized_project_id,
                assignee_id=str(lead_state.get("assignee_id") or ""),
                assigned_agent_code=str(lead_state.get("assigned_agent_code") or ""),
                labels=lead_state.get("labels"),
                status=str(lead_status or ""),
            )
            if lead_role == "Lead" and str(lead_status or "").strip() == "Lead":
                lead_in_progress = True
            lead_deploy_execution = derive_deploy_execution_snapshot(
                refs=lead_state.get("external_refs"),
                current_snapshot=(
                    lead_state.get("last_deploy_execution")
                    if isinstance(lead_state.get("last_deploy_execution"), dict)
                    else {}
                ),
            )
            executed_at = str(lead_deploy_execution.get("executed_at") or "").strip()
            if executed_at and is_strict_deploy_success_snapshot(lead_deploy_execution) and (latest_lead_deploy_at is None or executed_at > latest_lead_deploy_at):
                latest_lead_deploy_at = executed_at
        qa_handoff_current_cycle = bool(
            has_lead_handoff_token
            and (
                not latest_lead_deploy_at
                or qa_handoff_deploy_at == latest_lead_deploy_at
            )
        )
        gates.append(
            {
                "id": "qa_handoff_ready",
                "label": "Lead handoff",
                "status": "waiting" if ((lead_in_progress and not has_lead_handoff_token) or (has_lead_handoff_token and latest_lead_deploy_at and not qa_handoff_current_cycle)) else "pass",
                "blocking": bool((lead_in_progress and not has_lead_handoff_token) or (has_lead_handoff_token and latest_lead_deploy_at and not qa_handoff_current_cycle)),
                "message": (
                    "Waiting for Lead handoff to QA."
                    if (lead_in_progress and not has_lead_handoff_token)
                    else (
                        "Waiting for Lead handoff for the current deploy cycle."
                        if (has_lead_handoff_token and latest_lead_deploy_at and not qa_handoff_current_cycle)
                        else "Lead handoff is complete; QA can execute."
                    )
                ),
            }
        )
        has_qa_artifacts = _task_has_http_artifact(refs=external_refs, notes=task_notes)
        qa_status = "pass" if has_qa_artifacts else ("fail" if automation_state == "completed" else "waiting")
        gates.append(
            {
                "id": "qa_verifiable_artifacts",
                "label": "QA artifacts",
                "status": qa_status,
                "blocking": False,
                "message": "QA artifacts are present in external refs/linked notes." if has_qa_artifacts else "Add verifiable QA artifacts (links/logs) after QA validation.",
            }
        )
    return gates


@dataclass(frozen=True, slots=True)
class TaskListQuery:
    workspace_id: str
    project_id: str
    task_group_id: str | None = None
    specification_id: str | None = None
    view: str | None = None
    q: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    label: str | None = None
    assignee_id: str | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    priority: str | None = None
    archived: bool = False
    limit: int = 30
    offset: int = 0


def list_tasks_read_model(db: Session, user, query: TaskListQuery) -> dict:
    ensure_project_access(db, query.workspace_id, query.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stmt = select(Task).where(
        Task.workspace_id == query.workspace_id,
        Task.project_id == query.project_id,
        Task.is_deleted == False,
        Task.archived == query.archived,
    )
    now = datetime.now(timezone.utc)
    user_tz = get_user_zoneinfo(user)

    if query.q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{query.q}%"), Task.description.ilike(f"%{query.q}%"), Task.labels.ilike(f"%{query.q}%")))
    if query.status:
        stmt = stmt.where(Task.status == query.status)
    if query.label:
        stmt = stmt.where(Task.labels.ilike(f"%{query.label}%"))
    if query.tags:
        tag_filters = [Task.labels.ilike(f'%"{tag}"%') for tag in query.tags]
        if tag_filters:
            stmt = stmt.where(or_(*tag_filters))
    if query.assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == query.assignee_id)
    if query.task_group_id is not None:
        stmt = stmt.where(Task.task_group_id == query.task_group_id)
    if query.specification_id is not None:
        stmt = stmt.where(Task.specification_id == query.specification_id)
    if query.due_from:
        stmt = stmt.where(Task.due_date >= normalize_datetime_to_utc(query.due_from, user_tz))
    if query.due_to:
        stmt = stmt.where(Task.due_date <= normalize_datetime_to_utc(query.due_to, user_tz))
    if query.priority:
        stmt = stmt.where(Task.priority == query.priority)

    if query.view == "inbox":
        # Inbox focuses on actionable items for the current user:
        # - open tasks only
        # - assigned to current user or unassigned
        # - no due date or due within today/tomorrow (local timezone)
        local_now = now.astimezone(user_tz)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_day_after_tomorrow_start = local_start + timedelta(days=2)
        inbox_due_cutoff_utc = local_day_after_tomorrow_start.astimezone(timezone.utc)
        stmt = stmt.where(
            Task.completed_at.is_(None),
            or_(Task.assignee_id.is_(None), Task.assignee_id == user.id),
            or_(Task.due_date.is_(None), Task.due_date < inbox_due_cutoff_utc),
        )
    elif query.view == "today":
        local_now = now.astimezone(user_tz)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_start + timedelta(days=1)
        stmt = stmt.where(Task.due_date >= local_start.astimezone(timezone.utc), Task.due_date < local_end.astimezone(timezone.utc), Task.completed_at.is_(None))
    elif query.view == "upcoming":
        local_now = now.astimezone(user_tz)
        local_tomorrow_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        stmt = stmt.where(Task.due_date >= local_tomorrow_start.astimezone(timezone.utc), Task.completed_at.is_(None))
    elif query.view == "overdue":
        stmt = stmt.where(Task.due_date < now, Task.completed_at.is_(None))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    tasks = db.execute(stmt.order_by(Task.order_index.asc(), Task.created_at.desc()).limit(query.limit).offset(query.offset)).scalars().all()
    task_ids = [t.id for t in tasks]
    automation_state_by_task_id: dict[str, str] = {}
    for task in tasks:
        has_automation = bool(
            str(task.instruction or task.scheduled_instruction or "").strip()
            or normalize_execution_triggers(task.execution_triggers)
        )
        if not has_automation:
            continue
        try:
            state, _ = rebuild_state(db, "Task", task.id)
            automation_state_by_task_id[task.id] = str(state.get("automation_state") or "idle")
        except Exception:
            automation_state_by_task_id[task.id] = "idle"
    linked_note_count_by_task_id: dict[str, int] = {}
    if task_ids:
        note_counts = db.execute(
            select(Note.task_id, func.count())
            .where(
                Note.workspace_id == query.workspace_id,
                Note.project_id == query.project_id,
                Note.is_deleted == False,
                Note.archived == False,
                Note.task_id.is_not(None),
                Note.task_id.in_(task_ids),
            )
            .group_by(Note.task_id)
        ).all()
        linked_note_count_by_task_id = {
            str(task_id): int(count or 0)
            for task_id, count in note_counts
            if task_id
        }
    created_by_map = load_created_by_map(db, "Task", [t.id for t in tasks])
    return {
        "items": [
            serialize_task(
                t,
                created_by=created_by_map.get(t.id, ""),
                linked_note_count=linked_note_count_by_task_id.get(t.id, 0),
                automation_state=automation_state_by_task_id.get(t.id, "idle"),
            )
            for t in tasks
        ],
        "total": total,
        "limit": query.limit,
        "offset": query.offset,
    }


def get_task_automation_status_read_model(db: Session, user, task_id: str) -> dict:
    command_state = load_task_command_state(db, task_id)
    if not command_state or command_state.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")

    if command_state.project_id:
        ensure_project_access(
            db,
            command_state.workspace_id,
            command_state.project_id,
            user.id,
            {"Owner", "Admin", "Member", "Guest"},
        )
    else:
        ensure_role(db, command_state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    state, _ = rebuild_state(db, "Task", task_id)
    execution_gates = _build_execution_gates(
        db=db,
        task_id=task_id,
        state=state,
        workspace_id=str(command_state.workspace_id or ""),
        project_id=str(command_state.project_id or "") or None,
    )
    instruction = str(state.get("instruction") or state.get("scheduled_instruction") or "").strip() or None
    execution_triggers = normalize_execution_triggers(state.get("execution_triggers"))
    if not execution_triggers:
        legacy_trigger = build_legacy_schedule_trigger(
            scheduled_at_utc=state.get("scheduled_at_utc"),
            schedule_timezone=state.get("schedule_timezone"),
            recurring_rule=state.get("recurring_rule"),
        )
        if legacy_trigger is not None:
            execution_triggers = [legacy_trigger]
    legacy_schedule = derive_legacy_schedule_fields(
        instruction=instruction,
        execution_triggers=execution_triggers,
    )
    derived_deploy_execution = derive_deploy_execution_snapshot(
        refs=state.get("external_refs"),
        current_snapshot=state.get("last_deploy_execution") if isinstance(state.get("last_deploy_execution"), dict) else {},
    )
    structured_lead_handoff = bool(
        str(state.get("last_requested_workflow_scope") or "").strip() == "team_mode"
        and str(state.get("last_requested_source_task_id") or "").strip()
        and (
            str(state.get("last_requested_source") or "").strip() == "lead_handoff"
            or str(state.get("last_requested_reason") or "").strip() == "lead_handoff"
        )
    )
    derived_handoff_deploy_execution = (
        state.get("last_lead_handoff_deploy_execution")
        if isinstance(state.get("last_lead_handoff_deploy_execution"), dict)
        else {}
    )
    if not derived_handoff_deploy_execution and structured_lead_handoff:
        source_task_id = str(state.get("last_requested_source_task_id") or "").strip()
        if source_task_id:
            lead_source_state, _ = rebuild_state(db, "Task", source_task_id)
            derived_handoff_deploy_execution = derive_deploy_execution_snapshot(
                refs=lead_source_state.get("external_refs"),
                current_snapshot=(
                    lead_source_state.get("last_deploy_execution")
                    if isinstance(lead_source_state.get("last_deploy_execution"), dict)
                    else {}
                ),
            )
    return {
        "task_id": task_id,
        "automation_state": state.get("automation_state", "idle"),
        "automation_pending_requests": int(state.get("automation_pending_requests") or 0),
        "last_agent_run_at": state.get("last_agent_run_at"),
        "last_agent_progress": state.get("last_agent_progress"),
        "last_agent_stream_status": state.get("last_agent_stream_status"),
        "last_agent_stream_updated_at": state.get("last_agent_stream_updated_at"),
        "last_agent_run_id": state.get("last_agent_run_id"),
        "last_agent_error": state.get("last_agent_error"),
        "last_agent_comment": state.get("last_agent_comment"),
        "last_agent_usage": state.get("last_agent_usage"),
        "last_agent_prompt_mode": state.get("last_agent_prompt_mode"),
        "last_agent_prompt_segment_chars": state.get("last_agent_prompt_segment_chars"),
        "last_agent_codex_session_id": state.get("last_agent_codex_session_id"),
        "last_agent_codex_resume_attempted": state.get("last_agent_codex_resume_attempted"),
        "last_agent_codex_resume_succeeded": state.get("last_agent_codex_resume_succeeded"),
        "last_agent_codex_resume_fallback_used": state.get("last_agent_codex_resume_fallback_used"),
        "last_requested_instruction": state.get("last_requested_instruction"),
        "last_requested_source": state.get("last_requested_source"),
        "last_requested_source_task_id": state.get("last_requested_source_task_id"),
        "last_requested_chat_session_id": state.get("last_requested_chat_session_id"),
        "last_requested_reason": state.get("last_requested_reason"),
        "last_requested_trigger_link": state.get("last_requested_trigger_link"),
        "last_requested_correlation_id": state.get("last_requested_correlation_id"),
        "last_requested_trigger_task_id": state.get("last_requested_trigger_task_id"),
        "last_requested_from_status": state.get("last_requested_from_status"),
        "last_requested_to_status": state.get("last_requested_to_status"),
        "last_requested_triggered_at": state.get("last_requested_triggered_at"),
        "last_requested_execution_intent": state.get("last_requested_execution_intent"),
        "last_requested_execution_kickoff_intent": state.get("last_requested_execution_kickoff_intent"),
        "last_requested_project_creation_intent": state.get("last_requested_project_creation_intent"),
        "last_requested_workflow_scope": state.get("last_requested_workflow_scope"),
        "last_requested_execution_mode": state.get("last_requested_execution_mode"),
        "last_requested_task_completion_requested": state.get("last_requested_task_completion_requested"),
        "last_requested_classifier_reason": state.get("last_requested_classifier_reason"),
        "last_dispatch_decision": state.get("last_dispatch_decision"),
        "last_ignored_request_source": state.get("last_ignored_request_source"),
        "last_ignored_request_source_task_id": state.get("last_ignored_request_source_task_id"),
        "last_ignored_request_reason": state.get("last_ignored_request_reason"),
        "last_ignored_request_trigger_link": state.get("last_ignored_request_trigger_link"),
        "last_ignored_request_correlation_id": state.get("last_ignored_request_correlation_id"),
        "last_ignored_request_trigger_task_id": state.get("last_ignored_request_trigger_task_id"),
        "last_ignored_request_from_status": state.get("last_ignored_request_from_status"),
        "last_ignored_request_to_status": state.get("last_ignored_request_to_status"),
        "last_ignored_request_triggered_at": state.get("last_ignored_request_triggered_at"),
        "last_lead_handoff_token": state.get("last_lead_handoff_token") or (state.get("last_requested_correlation_id") if structured_lead_handoff else None),
        "last_lead_handoff_at": state.get("last_lead_handoff_at"),
        "last_lead_handoff_refs": state.get("last_lead_handoff_refs_json"),
        "last_lead_handoff_deploy_execution": derived_handoff_deploy_execution or None,
        "last_deploy_execution": derived_deploy_execution or None,
        "team_mode_phase": state.get("team_mode_phase"),
        "team_mode_blocking_gate": state.get("team_mode_blocking_gate"),
        "team_mode_blocked_reason": state.get("team_mode_blocked_reason"),
        "team_mode_blocked_at": state.get("team_mode_blocked_at"),
        "instruction": instruction,
        "execution_triggers": execution_triggers,
        "task_type": str(legacy_schedule.get("task_type") or state.get("task_type") or "manual"),
        "schedule_state": state.get("schedule_state", "idle"),
        "scheduled_at_utc": legacy_schedule.get("scheduled_at_utc"),
        "scheduled_instruction": legacy_schedule.get("scheduled_instruction"),
        "last_schedule_run_at": state.get("last_schedule_run_at"),
        "last_schedule_error": state.get("last_schedule_error"),
        "execution_gates": execution_gates,
    }
