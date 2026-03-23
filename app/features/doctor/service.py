from __future__ import annotations

import asyncio
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.attachments.api import AttachmentDeletePayload, delete_attachment, download_attachment, upload_attachment
from features.agents.gateway import build_ui_gateway
from features.tasks.command_handlers import CommandContext as TaskCommandContext, RequestAutomationRunInternalHandler
from features.tasks.domain import EVENT_UPDATED as TASK_EVENT_UPDATED
from features.tasks.api import list_comments as list_task_comments
from features.tasks.application import TaskApplicationService
from shared.core import CommentCreate, TaskCreate, User, append_event, ensure_role, load_note_view, load_specification_view, load_task_view
from shared.models import DoctorRun, Note, Project, ProjectPluginConfig, SessionLocal, Specification, Task, TaskComment, WorkspaceDoctorConfig
from shared.project_repository import ensure_project_repository_initialized
from shared.settings import AGENT_ENABLED_PLUGINS, AGENT_RUNNER_ENABLED, AGENT_SYSTEM_USER_ID

DOCTOR_PLUGIN_KEY = "doctor"
DOCTOR_FIXTURE_VERSION = "2"
DOCTOR_PROJECT_NAME = "ConstructOS Doctor"
DOCTOR_PROJECT_DESCRIPTION = (
    "Workspace validation project used by ConstructOS Doctor to exercise seeded Team Mode and task automation flows."
)
DOCTOR_SPEC_TITLE = "Doctor surface validation specification"
DOCTOR_SPEC_TASK_TITLE = "Doctor specification linked task"
DOCTOR_SPEC_NOTE_TITLE = "Doctor specification note"
DOCTOR_TASK_NOTE_TITLE = "Doctor task note"
DOCTOR_TASK_COMMENT_BODY = "Doctor fixture task comment validates task comment persistence."
DOCTOR_TEAM_TASK_CODES = ("dev-a", "dev-b", "qa-a", "lead-a")
DOCTOR_TASK_BLUEPRINTS = (
    {
        "code": "dev-a",
        "title": "Doctor developer slice A",
        "status": "To Do",
        "instruction": "Implement the assigned ConstructOS Doctor validation slice and report progress through task updates.",
    },
    {
        "code": "dev-b",
        "title": "Doctor developer slice B",
        "status": "To Do",
        "instruction": "Implement the second ConstructOS Doctor validation slice and keep artifacts attached to the task.",
    },
    {
        "code": "qa-a",
        "title": "Doctor QA verification",
        "status": "To Do",
        "instruction": "Validate the Doctor project flow, capture evidence, and report any regressions.",
    },
    {
        "code": "lead-a",
        "title": "Doctor lead orchestration",
        "status": "To Do",
        "instruction": "Coordinate the Doctor validation cycle, review progress, and drive the seeded workflow forward.",
    },
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _enabled_plugins() -> set[str]:
    return {
        str(item or "").strip().lower()
        for item in (AGENT_ENABLED_PLUGINS or [])
        if str(item or "").strip()
    }


def doctor_supported() -> bool:
    enabled = _enabled_plugins()
    if not enabled:
        return True
    if enabled.intersection({"none", "off", "disabled"}):
        return False
    return DOCTOR_PLUGIN_KEY in enabled


def _repo_context_refs(*, project_id: str) -> list[dict[str, str]]:
    return [
        {
            "url": f"https://github.com/constructos/doctor-{project_id[:8]}",
            "title": "Doctor fixture repository",
            "source": "doctor_fixture",
        },
    ]


def _doctor_project_name_candidates(workspace_id: str) -> list[str]:
    suffix = str(workspace_id or "").strip()[:8] or "workspace"
    return [
        DOCTOR_PROJECT_NAME,
        f"{DOCTOR_PROJECT_NAME} {suffix}",
    ]


def _doctor_command_id(kind: str, scope_id: str, suffix: str | None = None) -> str:
    scope = str(scope_id or "").strip()[:8] or "scope"
    base = f"dr:{kind}:{scope}"
    extra = str(suffix or "").strip()
    if not extra:
        return base
    compact = extra.replace("_", "-").replace(":", "-")
    compact = "-".join(part for part in compact.split("-") if part)[:32]
    return f"{base}:{compact}"


def _merge_external_refs(existing: object, desired: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in existing if isinstance(existing, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        key = (url, title)
        if key in seen:
            continue
        payload: dict[str, str] = {"url": url}
        if title:
            payload["title"] = title
        if source:
            payload["source"] = source
        merged.append(payload)
        seen.add(key)
    for item in desired:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        key = (url, title)
        if key in seen:
            continue
        payload: dict[str, str] = {"url": url}
        if title:
            payload["title"] = title
        if source:
            payload["source"] = source
        merged.append(payload)
        seen.add(key)
    return merged


def _write_doctor_compose_manifest(*, project: Project) -> str:
    repo_root = ensure_project_repository_initialized(project_name=project.name, project_id=project.id)
    repo_root.mkdir(parents=True, exist_ok=True)
    manifest_path = repo_root / "docker-compose.yml"
    manifest_path.write_text(
        "services:\n"
        "  web:\n"
        "    image: nginx:alpine\n"
        "    ports:\n"
        "      - \"6768:80\"\n",
        encoding="utf-8",
    )
    return str(Path("docker-compose.yml"))


def _task_event_metadata(*, user: User, workspace_id: str, project_id: str, task_id: str) -> dict[str, str]:
    return {
        "actor_id": str(user.id or "").strip() or AGENT_SYSTEM_USER_ID,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "task_id": task_id,
    }


def _upload_fixture_attachment(
    db: Session,
    *,
    user: User,
    workspace_id: str,
    project_id: str,
    filename: str,
    content: str,
    task_id: str | None = None,
    note_id: str | None = None,
) -> dict[str, Any]:
    upload = UploadFile(
        filename=filename,
        file=io.BytesIO(content.encode("utf-8")),
        headers={"content-type": "text/plain"},
    )
    return asyncio.run(
        upload_attachment(
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            note_id=note_id,
            file=upload,
            db=db,
            user=user,
        )
    )


def _find_specification_by_title(db: Session, *, project_id: str, title: str) -> Specification | None:
    return db.execute(
        select(Specification).where(
            Specification.project_id == project_id,
            Specification.title == title,
            Specification.is_deleted == False,  # noqa: E712
            Specification.archived == False,  # noqa: E712
        ).order_by(Specification.created_at.asc())
    ).scalar_one_or_none()


def _find_note_by_title(db: Session, *, project_id: str, title: str) -> Note | None:
    return db.execute(
        select(Note).where(
            Note.project_id == project_id,
            Note.title == title,
            Note.is_deleted == False,  # noqa: E712
            Note.archived == False,  # noqa: E712
        ).order_by(Note.created_at.asc())
    ).scalar_one_or_none()


def _find_task_by_title(db: Session, *, project_id: str, title: str) -> Task | None:
    return db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.title == title,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        ).order_by(Task.created_at.asc())
    ).scalar_one_or_none()


def _find_project_by_name(
    db: Session,
    *,
    workspace_id: str,
    name: str,
    include_deleted: bool = False,
) -> Project | None:
    filters = [
        Project.workspace_id == workspace_id,
        Project.name == name,
    ]
    if not include_deleted:
        filters.append(Project.is_deleted == False)  # noqa: E712
    return db.execute(
        select(Project).where(*filters).order_by(Project.created_at.asc())
    ).scalars().first()


def _extract_setup_project_id(setup: object) -> str:
    if not isinstance(setup, dict):
        return ""
    project = setup.get("project") if isinstance(setup.get("project"), dict) else {}
    project_id = str(project.get("id") or "").strip()
    if project_id:
        return project_id
    summary = setup.get("user_facing_summary") if isinstance(setup.get("user_facing_summary"), dict) else {}
    project_link = str(summary.get("project_link") or "").strip()
    if "project=" in project_link:
        return project_link.rsplit("project=", 1)[-1].strip()
    return ""


def _setup_error_messages(setup: object) -> list[str]:
    if not isinstance(setup, dict):
        return []
    out: list[str] = []
    for item in setup.get("errors") or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get("detail") or item.get("message") or "").strip()
        if detail:
            out.append(detail)
    for item in setup.get("steps") or []:
        if not isinstance(item, dict):
            continue
        error = item.get("error") if isinstance(item.get("error"), dict) else {}
        detail = str(error.get("detail") or error.get("message") or "").strip()
        if detail:
            out.append(detail)
    return out


def _resolve_doctor_project(db: Session, *, workspace_id: str, project_id: str | None) -> Project | None:
    active = _load_project(db, project_id=project_id)
    if active is not None:
        return active
    for candidate in _doctor_project_name_candidates(workspace_id):
        active = _find_project_by_name(db, workspace_id=workspace_id, name=candidate, include_deleted=False)
        if active is not None:
            return active
    return None


def _safe_get_task(gateway: Any, *, task_id: str) -> dict[str, Any] | None:
    normalized = str(task_id or "").strip()
    if not normalized:
        return None
    try:
        task = gateway.get_task(task_id=normalized)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    return task if isinstance(task, dict) else None


def _wait_for_task_visibility(
    db: Session,
    *,
    gateway: Any,
    task_id: str,
    timeout_seconds: float = 15.0,
    interval_seconds: float = 0.1,
) -> dict[str, Any]:
    normalized = str(task_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=500, detail="Doctor task visibility wait received an empty task id")
    deadline = time.monotonic() + max(timeout_seconds, interval_seconds)
    while time.monotonic() <= deadline:
        db.expire_all()
        with SessionLocal() as read_db:
            task_row = read_db.get(Task, normalized)
            if task_row is not None and not bool(getattr(task_row, "is_deleted", False)):
                return {
                    "id": str(task_row.id),
                    "project_id": str(getattr(task_row, "project_id", "") or "").strip() or None,
                    "title": str(getattr(task_row, "title", "") or "").strip(),
                }
            task_state = load_task_view(read_db, normalized)
            if task_state:
                return task_state
            task_view = _safe_get_task(gateway, task_id=normalized)
            if task_view:
                return task_view
        time.sleep(interval_seconds)
    raise HTTPException(status_code=404, detail="Doctor task did not become visible after creation")


def _create_doctor_spec_task(
    task_service: TaskApplicationService,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    command_id: str | None = None,
) -> dict[str, Any]:
    service = task_service
    if command_id:
        service = TaskApplicationService(task_service.db, task_service.user, command_id=command_id)
    return service.create_task(
        TaskCreate(
            workspace_id=workspace_id,
            project_id=project_id,
            title=DOCTOR_SPEC_TASK_TITLE,
            description="Doctor validates spec-linked task persistence and read filters.",
            priority="Med",
            status="To Do",
            assignee_id=user_id,
            assigned_agent_code=None,
            external_refs=[
                {
                    "url": "https://example.com/doctor/spec-task",
                    "title": "Doctor spec task reference",
                    "source": "doctor_fixture",
                },
            ],
        )
    )


def _seed_doctor_delivery_fixture(
    db: Session,
    *,
    gateway: Any,
    workspace_id: str,
    project: Project,
    user: User,
    command_id: str | None = None,
) -> dict[str, Any]:
    task_service = TaskApplicationService(db, user, command_id=command_id)
    existing_project_refs: list[dict[str, str]] = []
    raw_project_refs = str(getattr(project, "external_refs", "") or "").strip()
    if raw_project_refs:
        try:
            parsed_project_refs = json.loads(raw_project_refs)
            if isinstance(parsed_project_refs, list):
                existing_project_refs = [item for item in parsed_project_refs if isinstance(item, dict)]
        except Exception:
            existing_project_refs = []
    project_payload = gateway.update_project(
        project_id=project.id,
        patch={"external_refs": _merge_external_refs(existing_project_refs, _repo_context_refs(project_id=project.id))},
        command_id=(f"{command_id}:project-refs" if command_id else _doctor_command_id("fx", project.id, "project-refs")),
    )
    manifest_path = _write_doctor_compose_manifest(project=project)

    listed = gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project.id,
        archived=False,
        limit=100,
    )
    items = listed.get("items") if isinstance(listed, dict) else []
    task_by_code = {
        str((item or {}).get("assigned_agent_code") or "").strip().lower(): item
        for item in items
        if isinstance(item, dict) and str((item or {}).get("assigned_agent_code") or "").strip()
    }
    required_codes = set(DOCTOR_TEAM_TASK_CODES)
    if not required_codes.issubset(task_by_code.keys()):
        missing = sorted(required_codes.difference(task_by_code.keys()))
        raise HTTPException(status_code=500, detail=f"Doctor fixture tasks are missing codes: {', '.join(missing)}")

    timestamp = _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")
    deploy_snapshot = {
        "executed_at": timestamp,
        "stack": f"constructos-doctor-{project.id[:8]}",
        "port": 6768,
        "health_path": "/health",
        "command": f"docker compose -p constructos-doctor-{project.id[:8]} up -d",
        "manifest_path": manifest_path,
        "runtime_type": "static_assets",
        "runtime_ok": True,
        "http_url": "http://gateway:6768/health",
        "http_status": 200,
    }

    dev_codes = ("dev-a", "dev-b")
    for idx, code in enumerate(dev_codes, start=1):
        task = task_by_code[code]
        task_id = str(task.get("id") or "").strip()
        commit_sha = f"deadbeef{idx:04x}"
        refs = [
            {"url": f"commit:{commit_sha}", "title": f"Doctor fixture commit {idx}", "source": "doctor_fixture"},
            {"url": f"branch:task/{task_id[:8]}-doctor-slice-{idx}", "title": "Doctor task branch", "source": "doctor_fixture"},
        ]
        append_event(
            db,
            aggregate_type="Task",
            aggregate_id=task_id,
            event_type=TASK_EVENT_UPDATED,
            payload={
                "status": "Completed",
                "external_refs": refs,
            },
            metadata=_task_event_metadata(user=user, workspace_id=workspace_id, project_id=project.id, task_id=task_id),
        )
        task_service.mark_automation_completed(
            task_id,
            completed_at=timestamp,
            summary="Doctor fixture automation completed.",
        )

    lead_task = task_by_code["lead-a"]
    lead_task_id = str(lead_task.get("id") or "").strip()
    lead_refs = [
        {"url": "merge:main:deadbeef0001", "title": "Doctor merged output", "source": "doctor_fixture"},
        {"url": f"deploy:stack:{deploy_snapshot['stack']}", "title": "Doctor deploy stack", "source": "doctor_fixture"},
        {"url": f"deploy:command:{deploy_snapshot['command']}", "title": "Doctor deploy command", "source": "doctor_fixture"},
        {"url": f"deploy:compose:{manifest_path}", "title": "Doctor compose manifest", "source": "doctor_fixture"},
        {"url": f"deploy:runtime:{deploy_snapshot['runtime_type']}", "title": "Doctor runtime decision", "source": "doctor_fixture"},
        {"url": f"deploy:health:{deploy_snapshot['http_url']}:http_200:{timestamp}", "title": "Doctor deploy health", "source": "doctor_fixture"},
    ]
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=lead_task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "status": "Completed",
            "external_refs": lead_refs,
            "last_deploy_execution": deploy_snapshot,
        },
        metadata=_task_event_metadata(user=user, workspace_id=workspace_id, project_id=project.id, task_id=lead_task_id),
    )
    task_service.mark_automation_completed(
        lead_task_id,
        completed_at=timestamp,
        summary="Doctor fixture automation completed.",
    )

    qa_task = task_by_code["qa-a"]
    qa_task_id = str(qa_task.get("id") or "").strip()
    qa_refs = [
        {
            "url": f"https://example.com/doctor/qa-report/{project.id[:8]}",
            "title": "Doctor QA report",
            "source": "doctor_fixture",
        },
    ]
    qa_handoff_token = f"lead:{lead_task_id}:{timestamp}"
    append_event(
        db,
        aggregate_type="Task",
        aggregate_id=qa_task_id,
        event_type=TASK_EVENT_UPDATED,
        payload={
            "status": "Completed",
            "external_refs": qa_refs,
            "team_mode_phase": "qa_validation",
        },
        metadata=_task_event_metadata(user=user, workspace_id=workspace_id, project_id=project.id, task_id=qa_task_id),
    )
    RequestAutomationRunInternalHandler(
        TaskCommandContext(db=db, user=user),
        task_id=qa_task_id,
        requested_at=timestamp,
        instruction="Validate the Doctor fixture deployment evidence.",
        source="lead_handoff",
        source_task_id=lead_task_id,
        reason="lead_handoff",
        workflow_scope="team_mode",
        trigger_link=f"{lead_task_id}->{qa_task_id}:QA",
        correlation_id=qa_handoff_token,
        trigger_task_id=lead_task_id,
        from_status="Completed",
        to_status="Completed",
        triggered_at=timestamp,
        lead_handoff_token=qa_handoff_token,
        lead_handoff_at=timestamp,
        lead_handoff_refs=lead_refs,
        lead_handoff_deploy_execution=deploy_snapshot,
        commit=False,
    )()
    task_service.mark_automation_completed(
        qa_task_id,
        completed_at=timestamp,
        summary="Doctor fixture automation completed.",
    )

    db.commit()
    return {
        "project": project_payload,
        "manifest_path": manifest_path,
        "task_ids": {code: str((task_by_code.get(code) or {}).get("id") or "") for code in sorted(required_codes)},
        "deploy_snapshot": deploy_snapshot,
    }


def _seed_doctor_product_surface_fixture(
    db: Session,
    *,
    gateway: Any,
    workspace_id: str,
    project: Project,
    user: User,
    command_id: str | None = None,
) -> dict[str, Any]:
    task_service = TaskApplicationService(db, user, command_id=command_id)

    project_attachment = _upload_fixture_attachment(
        db,
        user=user,
        workspace_id=workspace_id,
        project_id=project.id,
        filename="doctor-spec.txt",
        content="Doctor specification attachment validates project-scoped attachment upload.",
    )
    temp_attachment = _upload_fixture_attachment(
        db,
        user=user,
        workspace_id=workspace_id,
        project_id=project.id,
        filename="doctor-temp.txt",
        content="Doctor temporary attachment validates deletion.",
    )
    note_attachment = _upload_fixture_attachment(
        db,
        user=user,
        workspace_id=workspace_id,
        project_id=project.id,
        filename="doctor-note.txt",
        content="Doctor note attachment validates attachment refs on notes.",
    )

    specification = _find_specification_by_title(db, project_id=project.id, title=DOCTOR_SPEC_TITLE)
    specification_patch = {
        "title": DOCTOR_SPEC_TITLE,
        "body": "Doctor validates specification CRUD, linked tasks, linked notes, attachments, and external refs.",
        "status": "Ready",
        "tags": ["doctor-fixture"],
        "external_refs": [
            {"url": "https://example.com/doctor/specification", "title": "Doctor specification reference", "source": "doctor_fixture"},
        ],
        "attachment_refs": [project_attachment],
    }
    if specification is None:
        specification_view = gateway.create_specification(
            workspace_id=workspace_id,
            project_id=project.id,
            title=specification_patch["title"],
            body=specification_patch["body"],
            status=specification_patch["status"],
            tags=specification_patch["tags"],
            external_refs=specification_patch["external_refs"],
            attachment_refs=specification_patch["attachment_refs"],
            force_new=False,
            command_id=(f"{command_id}:spec-create" if command_id else _doctor_command_id("fx", project.id, "spec-create")),
        )
    else:
        specification_view = gateway.update_specification(
            specification_id=str(specification.id),
            patch=specification_patch,
            command_id=(f"{command_id}:spec-update" if command_id else _doctor_command_id("fx", project.id, "spec-update")),
        )
    specification_id = str(specification_view.get("id") or "").strip()
    if not specification_id:
        raise HTTPException(status_code=500, detail="Doctor surface specification was not created")

    spec_task = _find_task_by_title(db, project_id=project.id, title=DOCTOR_SPEC_TASK_TITLE)
    if spec_task is not None and _safe_get_task(gateway, task_id=str(spec_task.id)) is None:
        spec_task = None
    if spec_task is None:
        spec_task_view = _create_doctor_spec_task(
            task_service,
            workspace_id=workspace_id,
            project_id=project.id,
            user_id=str(user.id),
            command_id=(f"{command_id}:spec-task-create" if command_id else _doctor_command_id("fx", project.id, "spec-task-create")),
        )
    else:
        try:
            spec_task_view = gateway.update_task(
                task_id=str(spec_task.id),
                patch={
                    "title": DOCTOR_SPEC_TASK_TITLE,
                    "description": "Doctor validates spec-linked task persistence and read filters.",
                    "specification_id": specification_id,
                    "assignee_id": str(user.id),
                    "assigned_agent_code": None,
                    "external_refs": [
                        {"url": "https://example.com/doctor/spec-task", "title": "Doctor spec task reference", "source": "doctor_fixture"},
                    ],
                },
                command_id=(f"{command_id}:spec-task-update" if command_id else _doctor_command_id("fx", project.id, "spec-task-update")),
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            spec_task_view = _create_doctor_spec_task(
                task_service,
                workspace_id=workspace_id,
                project_id=project.id,
                user_id=str(user.id),
                command_id=(f"{command_id}:spec-task-create-recover" if command_id else _doctor_command_id("fx", project.id, "spec-task-create-recover")),
            )
    spec_task_id = str(spec_task_view.get("id") or "").strip()
    if not spec_task_id:
        raise HTTPException(status_code=500, detail="Doctor specification task was not created")
    spec_task_view = _wait_for_task_visibility(
        db,
        gateway=gateway,
        task_id=spec_task_id,
    )

    task_attachment = _upload_fixture_attachment(
        db,
        user=user,
        workspace_id=workspace_id,
        project_id=project.id,
        task_id=spec_task_id,
        filename="doctor-task.txt",
        content="Doctor task attachment validates task-scoped attachment upload.",
    )
    try:
        spec_task_view = gateway.update_task(
            task_id=spec_task_id,
            patch={
                "attachment_refs": [task_attachment],
                "assignee_id": str(user.id),
                "assigned_agent_code": None,
                "external_refs": [
                    {"url": "https://example.com/doctor/spec-task", "title": "Doctor spec task reference", "source": "doctor_fixture"},
                    {"url": "https://example.com/doctor/spec-task/evidence", "title": "Doctor task evidence", "source": "doctor_fixture"},
                ],
                "specification_id": specification_id,
            },
            command_id=(f"{command_id}:spec-task-attach" if command_id else _doctor_command_id("fx", project.id, "spec-task-attach")),
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        spec_task_view = _create_doctor_spec_task(
            task_service,
            workspace_id=workspace_id,
            project_id=project.id,
            user_id=str(user.id),
            command_id=(f"{command_id}:spec-task-create-retry" if command_id else _doctor_command_id("fx", project.id, "spec-task-create-retry")),
        )
        spec_task_id = str(spec_task_view.get("id") or "").strip()
        spec_task_view = _wait_for_task_visibility(
            db,
            gateway=gateway,
            task_id=spec_task_id,
        )
        task_attachment = _upload_fixture_attachment(
            db,
            user=user,
            workspace_id=workspace_id,
            project_id=project.id,
            task_id=spec_task_id,
            filename="doctor-task.txt",
            content="Doctor task attachment validates task-scoped attachment upload.",
        )
        spec_task_view = gateway.update_task(
            task_id=spec_task_id,
            patch={
                "attachment_refs": [task_attachment],
                "assignee_id": str(user.id),
                "assigned_agent_code": None,
                "external_refs": [
                    {"url": "https://example.com/doctor/spec-task", "title": "Doctor spec task reference", "source": "doctor_fixture"},
                    {"url": "https://example.com/doctor/spec-task/evidence", "title": "Doctor task evidence", "source": "doctor_fixture"},
                ],
                "specification_id": specification_id,
            },
            command_id=(f"{command_id}:spec-task-attach-retry" if command_id else _doctor_command_id("fx", project.id, "spec-task-attach-retry")),
        )

    spec_note = _find_note_by_title(db, project_id=project.id, title=DOCTOR_SPEC_NOTE_TITLE)
    if spec_note is None:
        spec_note_view = gateway.create_note(
            workspace_id=workspace_id,
            project_id=project.id,
            title=DOCTOR_SPEC_NOTE_TITLE,
            body="Doctor validates specification note persistence and spec note filters.",
            specification_id=specification_id,
            tags=["doctor-fixture"],
            external_refs=[
                {"url": "https://example.com/doctor/spec-note", "title": "Doctor specification note reference", "source": "doctor_fixture"},
                {"url": "https://example.com/doctor/spec-note/evidence", "title": "Doctor note evidence", "source": "doctor_fixture"},
            ],
            attachment_refs=[note_attachment],
            pinned=True,
            force_new=False,
            command_id=(f"{command_id}:spec-note-create" if command_id else _doctor_command_id("fx", project.id, "spec-note-create")),
        )
    else:
        spec_note_view = gateway.update_note(
            note_id=str(spec_note.id),
            patch={
                "title": DOCTOR_SPEC_NOTE_TITLE,
                "body": "Doctor validates specification note persistence and spec note filters.",
                "tags": ["doctor-fixture"],
                "pinned": True,
                "specification_id": specification_id,
                "attachment_refs": [note_attachment],
                "external_refs": [
                    {"url": "https://example.com/doctor/spec-note", "title": "Doctor specification note reference", "source": "doctor_fixture"},
                    {"url": "https://example.com/doctor/spec-note/evidence", "title": "Doctor note evidence", "source": "doctor_fixture"},
                ],
            },
            command_id=(f"{command_id}:spec-note-update" if command_id else _doctor_command_id("fx", project.id, "spec-note-update")),
        )
    spec_note_id = str(spec_note_view.get("id") or "").strip()
    if not spec_note_id:
        raise HTTPException(status_code=500, detail="Doctor specification note was not created")

    task_note = _find_note_by_title(db, project_id=project.id, title=DOCTOR_TASK_NOTE_TITLE)
    task_note_patch = {
        "title": DOCTOR_TASK_NOTE_TITLE,
        "body": "Doctor validates task note persistence, task note filtering, and specification linking.",
        "tags": ["doctor-fixture"],
        "task_id": spec_task_id,
        "specification_id": specification_id,
        "external_refs": [
            {"url": "https://example.com/doctor/task-note", "title": "Doctor task note reference", "source": "doctor_fixture"},
        ],
    }
    if task_note is None:
        task_note_view = gateway.create_note(
            workspace_id=workspace_id,
            project_id=project.id,
            title=task_note_patch["title"],
            body=task_note_patch["body"],
            task_id=spec_task_id,
            specification_id=specification_id,
            tags=task_note_patch["tags"],
            external_refs=task_note_patch["external_refs"],
            attachment_refs=[],
            pinned=False,
            force_new=False,
            command_id=(f"{command_id}:task-note-create" if command_id else _doctor_command_id("fx", project.id, "task-note-create")),
        )
    else:
        task_note_view = gateway.update_note(
            note_id=str(task_note.id),
            patch=task_note_patch,
            command_id=(f"{command_id}:task-note-update" if command_id else _doctor_command_id("fx", project.id, "task-note-update")),
        )
    task_note_id = str(task_note_view.get("id") or "").strip()
    if not task_note_id:
        raise HTTPException(status_code=500, detail="Doctor task note was not created")

    existing_comment = db.execute(
        select(TaskComment).where(
            TaskComment.task_id == spec_task_id,
            TaskComment.body == DOCTOR_TASK_COMMENT_BODY,
        )
    ).scalar_one_or_none()
    comment_result: dict[str, Any] | None = None
    if existing_comment is None:
        comment_result = TaskApplicationService(
            db,
            user,
            command_id=(f"{command_id}:task-comment-add" if command_id else _doctor_command_id("fx", project.id, "task-comment-add")),
        ).add_comment(spec_task_id, CommentCreate(body=DOCTOR_TASK_COMMENT_BODY))
        db.commit()
        db.expire_all()
    else:
        comment_result = {
            "id": int(existing_comment.id),
            "task_id": spec_task_id,
            "body": existing_comment.body,
        }

    downloaded = download_attachment(workspace_id=workspace_id, path=str(task_attachment.get("path") or ""), db=db, user=user)
    deleted = delete_attachment(
        payload=AttachmentDeletePayload(workspace_id=workspace_id, path=str(temp_attachment.get("path") or "")),
        db=db,
        user=user,
    )

    specification_view = load_specification_view(db, specification_id)
    spec_task_state = load_task_view(db, spec_task_id)
    spec_note_state = load_note_view(db, spec_note_id)
    task_note_state = load_note_view(db, task_note_id)
    spec_tasks = gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project.id,
        specification_id=specification_id,
        archived=False,
        limit=100,
    )
    spec_notes = gateway.list_notes(
        workspace_id=workspace_id,
        project_id=project.id,
        specification_id=specification_id,
        archived=False,
        limit=100,
    )
    task_notes = gateway.list_notes(
        workspace_id=workspace_id,
        project_id=project.id,
        task_id=spec_task_id,
        archived=False,
        limit=100,
    )
    task_comments = list_task_comments(task_id=spec_task_id, db=db, user=user)
    comment_row = db.execute(
        select(TaskComment).where(
            TaskComment.task_id == spec_task_id,
            TaskComment.body == DOCTOR_TASK_COMMENT_BODY,
        )
    ).scalar_one_or_none()
    product_checks = [
        {
            "id": "specification_created",
            "label": "Specification CRUD and read model",
            "status": "passed" if specification_view and str(specification_view.get("id") or "").strip() == specification_id else "failed",
            "details": specification_view or {},
        },
        {
            "id": "specification_task_link",
            "label": "Specification linked task",
            "status": "passed" if spec_task_state and str(spec_task_state.get("specification_id") or "").strip() == specification_id else "failed",
            "details": spec_task_state or {},
        },
        {
            "id": "specification_note_link",
            "label": "Specification linked note",
            "status": "passed" if spec_note_state and str(spec_note_state.get("specification_id") or "").strip() == specification_id else "failed",
            "details": spec_note_state or {},
        },
        {
            "id": "task_note_link",
            "label": "Task note persisted and linked to specification",
            "status": "passed" if task_note_state and str(task_note_state.get("task_id") or "").strip() == spec_task_id and str(task_note_state.get("specification_id") or "").strip() == specification_id else "failed",
            "details": task_note_state or {},
        },
        {
            "id": "task_comment_persisted",
            "label": "Task comment persistence",
            "status": "passed"
            if str((comment_result or {}).get("body") or "").strip() == DOCTOR_TASK_COMMENT_BODY and comment_row is not None
            else "failed",
            "details": {"comment_result": comment_result or {}, "comments": task_comments},
        },
        {
            "id": "attachment_upload_download_delete",
            "label": "Attachment upload, read, and delete",
            "status": "passed" if bool(getattr(downloaded, "path", "")) and bool((deleted or {}).get("ok")) else "failed",
            "details": {
                "project_attachment": project_attachment,
                "task_attachment": task_attachment,
                "note_attachment": note_attachment,
                "temporary_deleted": deleted,
                "download_path": getattr(downloaded, "path", None),
                "download_filename": getattr(downloaded, "filename", None),
            },
        },
        {
            "id": "specification_filters",
            "label": "Specification and task note filters",
            "status": "passed"
            if any(str((item or {}).get("id") or "").strip() == spec_task_id for item in (spec_tasks.get("items") or []) if isinstance(item, dict))
            and any(str((item or {}).get("id") or "").strip() == spec_note_id for item in (spec_notes.get("items") or []) if isinstance(item, dict))
            and any(str((item or {}).get("id") or "").strip() == task_note_id for item in (task_notes.get("items") or []) if isinstance(item, dict))
            else "failed",
            "details": {
                "spec_tasks": spec_tasks,
                "spec_notes": spec_notes,
                "task_notes": task_notes,
            },
        },
        {
            "id": "attachment_refs_persisted",
            "label": "Attachment refs persisted on task, note, and specification",
            "status": "passed"
            if bool((specification_view or {}).get("attachment_refs"))
            and bool((spec_task_state or {}).get("attachment_refs"))
            and bool((spec_note_state or {}).get("attachment_refs"))
            else "failed",
            "details": {
                "specification_attachment_refs": (specification_view or {}).get("attachment_refs") or [],
                "task_attachment_refs": (spec_task_state or {}).get("attachment_refs") or [],
                "note_attachment_refs": (spec_note_state or {}).get("attachment_refs") or [],
            },
        },
    ]

    return {
        "specification_id": specification_id,
        "specification_task_id": spec_task_id,
        "specification_note_id": spec_note_id,
        "task_note_id": task_note_id,
        "product_checks": product_checks,
    }


def _clean_setup_summary(
    setup: dict[str, Any] | Any,
    *,
    team_verify: dict[str, Any],
    delivery_verify: dict[str, Any],
) -> dict[str, Any] | Any:
    if not isinstance(setup, dict):
        return setup
    cleaned = dict(setup)
    verification = cleaned.get("verification")
    if isinstance(verification, dict):
        verification_clean = dict(verification)
        verification_clean["team_mode"] = team_verify
        verification_clean["delivery"] = delivery_verify
        cleaned["verification"] = verification_clean
    user_facing_summary = cleaned.get("user_facing_summary")
    if isinstance(user_facing_summary, dict):
        summary_clean = dict(user_facing_summary)
        verification_summary = summary_clean.get("verification")
        if isinstance(verification_summary, dict):
            verification_summary_clean = dict(verification_summary)
            verification_summary_clean["team_mode_ok"] = bool(team_verify.get("ok"))
            verification_summary_clean["team_mode_failed_requirements"] = list(team_verify.get("required_failed_checks") or [])
            verification_summary_clean["delivery_ok"] = bool(delivery_verify.get("ok"))
            verification_summary_clean["delivery_failed_requirements"] = [
                {
                    "id": str(check_id or "").strip(),
                    "description": str(
                        ((delivery_verify.get("check_descriptions") or {}) if isinstance(delivery_verify, dict) else {}).get(check_id, "")
                    ).strip(),
                }
                for check_id in list(delivery_verify.get("required_failed_checks") or [])
                if str(check_id or "").strip()
            ]
            summary_clean["verification"] = verification_summary_clean
        cleaned["user_facing_summary"] = summary_clean
    return cleaned


def _require_workspace_admin(db: Session, *, workspace_id: str, user_id: str) -> None:
    ensure_role(db, workspace_id, user_id, {"Owner", "Admin"})


def _load_doctor_config(db: Session, *, workspace_id: str) -> WorkspaceDoctorConfig | None:
    return db.execute(
        select(WorkspaceDoctorConfig).where(
            WorkspaceDoctorConfig.workspace_id == workspace_id,
            WorkspaceDoctorConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()


def _load_project(db: Session, *, project_id: str | None) -> Project | None:
    normalized = str(project_id or "").strip()
    if not normalized:
        return None
    project = db.get(Project, normalized)
    if project is None or bool(getattr(project, "is_deleted", False)):
        return None
    return project


def _plugin_enabled(db: Session, *, workspace_id: str, project_id: str, plugin_key: str) -> bool:
    row = db.execute(
        select(ProjectPluginConfig.enabled).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == plugin_key,
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    return bool(row)


def _task_rows(db: Session, *, workspace_id: str, project_id: str) -> list[Task]:
    return db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
    ).scalars().all()


def _serialize_run(row: DoctorRun) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    raw_summary = str(getattr(row, "summary_json", "") or "").strip()
    if raw_summary:
        try:
            parsed = json.loads(raw_summary)
            if isinstance(parsed, dict):
                summary = parsed
        except Exception:
            summary = {}
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "project_id": str(getattr(row, "project_id", "") or "").strip() or None,
        "fixture_version": str(getattr(row, "fixture_version", "") or "").strip() or DOCTOR_FIXTURE_VERSION,
        "status": str(getattr(row, "status", "") or "").strip() or "unknown",
        "summary": summary,
        "started_at": getattr(row, "started_at", None).isoformat() if getattr(row, "started_at", None) else None,
        "finished_at": getattr(row, "finished_at", None).isoformat() if getattr(row, "finished_at", None) else None,
        "triggered_by": str(getattr(row, "triggered_by", "") or "").strip() or None,
        "created_at": getattr(row, "created_at", None).isoformat() if getattr(row, "created_at", None) else None,
        "updated_at": getattr(row, "updated_at", None).isoformat() if getattr(row, "updated_at", None) else None,
    }


def _ensure_doctor_team_tasks(*, gateway: Any, workspace_id: str, project_id: str, command_id: str | None = None) -> dict[str, Any]:
    listed = gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project_id,
        archived=False,
        limit=100,
    )
    items = listed.get("items") if isinstance(listed, dict) else []
    if not isinstance(items, list):
        items = []
    existing_by_code = {
        str((item or {}).get("assigned_agent_code") or "").strip().lower(): item
        for item in items
        if isinstance(item, dict) and str((item or {}).get("assigned_agent_code") or "").strip()
    }
    created_task_ids: dict[str, str] = {}
    for idx, blueprint in enumerate(DOCTOR_TASK_BLUEPRINTS):
        code = str(blueprint["code"]).strip().lower()
        if code in existing_by_code:
            continue
        created = gateway.create_task(
            workspace_id=workspace_id,
            project_id=project_id,
            title=str(blueprint["title"]),
            status=str(blueprint["status"]),
            instruction=str(blueprint["instruction"]),
            assigned_agent_code=code,
            command_id=(f"{command_id}:task:{idx}" if command_id else _doctor_command_id("task", project_id, code)),
        )
        created_task_ids[code] = str(created.get("id") or "").strip()
    refreshed = gateway.list_tasks(
        workspace_id=workspace_id,
        project_id=project_id,
        archived=False,
        limit=100,
    )
    return {
        "created_task_ids": created_task_ids,
        "items": refreshed.get("items") if isinstance(refreshed, dict) else [],
    }


def get_doctor_status(db: Session, *, workspace_id: str, user: User) -> dict[str, Any]:
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    supported = doctor_supported()
    config = _load_doctor_config(db, workspace_id=workspace_id)
    project = _load_project(db, project_id=getattr(config, "doctor_project_id", None) if config is not None else None)
    seeded = project is not None
    team_mode_enabled = _plugin_enabled(db, workspace_id=workspace_id, project_id=project.id, plugin_key="team_mode") if project else False
    git_delivery_enabled = _plugin_enabled(db, workspace_id=workspace_id, project_id=project.id, plugin_key="git_delivery") if project else False
    tasks = _task_rows(db, workspace_id=workspace_id, project_id=project.id) if project else []
    seeded_team_tasks = [
        task for task in tasks
        if str(getattr(task, "assigned_agent_code", "") or "").strip().lower() in DOCTOR_TEAM_TASK_CODES
    ]
    latest_runs = db.execute(
        select(DoctorRun).where(
            DoctorRun.workspace_id == workspace_id,
            DoctorRun.is_deleted == False,  # noqa: E712
        ).order_by(DoctorRun.started_at.desc().nullslast(), DoctorRun.created_at.desc()).limit(10)
    ).scalars().all()
    latest_run = latest_runs[0] if latest_runs else None
    return {
        "workspace_id": workspace_id,
        "plugin_key": DOCTOR_PLUGIN_KEY,
        "supported": supported,
        "enabled": bool(getattr(config, "enabled", True)) if config is not None else False,
        "fixture_version": str(getattr(config, "fixture_version", "") or "").strip() or DOCTOR_FIXTURE_VERSION,
        "project": (
            {
                "id": str(project.id),
                "name": str(project.name or ""),
                "status": str(project.status or ""),
                "link": f"?tab=projects&project={project.id}",
            }
            if project is not None
            else None
        ),
        "seeded": seeded,
        "runner_enabled": bool(AGENT_RUNNER_ENABLED),
        "checks": {
            "team_mode_enabled": team_mode_enabled,
            "git_delivery_enabled": git_delivery_enabled,
            "seeded_team_task_count": len(seeded_team_tasks),
            "task_count": len(tasks),
        },
        "last_seeded_at": getattr(config, "last_seeded_at", None).isoformat() if getattr(config, "last_seeded_at", None) else None,
        "last_run_at": getattr(config, "last_run_at", None).isoformat() if getattr(config, "last_run_at", None) else None,
        "last_run_status": str(getattr(config, "last_run_status", "") or "").strip() or None,
        "last_run": _serialize_run(latest_run) if latest_run is not None else None,
        "recent_runs": [_serialize_run(item) for item in latest_runs],
    }


def seed_doctor_workspace(db: Session, *, workspace_id: str, user: User, command_id: str | None = None) -> dict[str, Any]:
    _require_workspace_admin(db, workspace_id=workspace_id, user_id=user.id)
    if not doctor_supported():
        raise HTTPException(status_code=400, detail="Doctor plugin is not supported by AGENT_ENABLED_PLUGINS")

    config = _load_doctor_config(db, workspace_id=workspace_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    existing_project = _resolve_doctor_project(
        db,
        workspace_id=workspace_id,
        project_id=getattr(config, "doctor_project_id", None) if config is not None else None,
    )
    setup: dict[str, Any] = {}
    setup_attempts: list[dict[str, Any]] = []
    candidate_names = _doctor_project_name_candidates(workspace_id)
    if existing_project is not None:
        setup = gateway.setup_project_orchestration(
            project_id=str(existing_project.id),
            short_description=DOCTOR_PROJECT_DESCRIPTION,
            workspace_id=workspace_id,
            enable_team_mode=True,
            enable_git_delivery=True,
            enable_docker_compose=False,
            seed_team_tasks=True,
            kickoff_after_setup=False,
            command_id=command_id or _doctor_command_id("seed", workspace_id),
        )
        setup_attempts.append({"project_id": str(existing_project.id), "name": existing_project.name, "result": setup})
    else:
        for index, candidate_name in enumerate(candidate_names):
            setup = gateway.setup_project_orchestration(
                name=candidate_name,
                short_description=DOCTOR_PROJECT_DESCRIPTION,
                primary_starter_key="blank",
                workspace_id=workspace_id,
                enable_team_mode=True,
                enable_git_delivery=True,
                enable_docker_compose=False,
                seed_team_tasks=True,
                kickoff_after_setup=False,
                command_id=command_id or _doctor_command_id("seed", workspace_id),
            )
            setup_attempts.append({"project_id": None, "name": candidate_name, "result": setup})
            if _extract_setup_project_id(setup):
                break
            active_project = _find_project_by_name(db, workspace_id=workspace_id, name=candidate_name, include_deleted=False)
            if active_project is not None:
                existing_project = active_project
                break
            errors = " ".join(_setup_error_messages(setup)).lower()
            if "deleted state" not in errors or index == len(candidate_names) - 1:
                break
        if existing_project is not None:
            setup = gateway.setup_project_orchestration(
                project_id=str(existing_project.id),
                short_description=DOCTOR_PROJECT_DESCRIPTION,
                workspace_id=workspace_id,
                enable_team_mode=True,
                enable_git_delivery=True,
                enable_docker_compose=False,
                seed_team_tasks=True,
                kickoff_after_setup=False,
                command_id=command_id or _doctor_command_id("seed", workspace_id),
            )
            setup_attempts.append({"project_id": str(existing_project.id), "name": existing_project.name, "result": setup})

    project_id = _extract_setup_project_id(setup)
    if not project_id:
        fallback_project = _resolve_doctor_project(
            db,
            workspace_id=workspace_id,
            project_id=getattr(existing_project, "id", None),
        )
        project_id = str(getattr(fallback_project, "id", "") or "").strip()
    if not project_id:
        errors = _setup_error_messages(setup)
        detail = "Doctor project setup did not return a project id"
        if errors:
            detail = f"{detail}: {' | '.join(errors)}"
        raise HTTPException(status_code=500, detail=detail)
    _ensure_doctor_team_tasks(
        gateway=gateway,
        workspace_id=workspace_id,
        project_id=project_id,
        command_id=command_id or _doctor_command_id("seed", workspace_id),
    )

    now = _now_utc()
    if config is None:
        config = WorkspaceDoctorConfig(
            workspace_id=workspace_id,
            enabled=True,
            doctor_project_id=project_id,
            fixture_version=DOCTOR_FIXTURE_VERSION,
            last_seeded_at=now,
            created_by=str(user.id),
            updated_by=str(user.id),
        )
    else:
        config.enabled = True
        config.doctor_project_id = project_id
        config.fixture_version = DOCTOR_FIXTURE_VERSION
        config.last_seeded_at = now
        config.updated_by = str(user.id)
    db.add(config)
    db.commit()
    db.refresh(config)
    payload = get_doctor_status(db, workspace_id=workspace_id, user=user)
    payload["setup"] = setup
    payload["setup_attempts"] = setup_attempts
    return payload


def run_doctor_workspace(db: Session, *, workspace_id: str, user: User, command_id: str | None = None) -> dict[str, Any]:
    _require_workspace_admin(db, workspace_id=workspace_id, user_id=user.id)
    if not doctor_supported():
        raise HTTPException(status_code=400, detail="Doctor plugin is not supported by AGENT_ENABLED_PLUGINS")

    config = _load_doctor_config(db, workspace_id=workspace_id)
    if config is None or _load_project(db, project_id=config.doctor_project_id) is None:
        seed_doctor_workspace(db, workspace_id=workspace_id, user=user, command_id=command_id)
        config = _load_doctor_config(db, workspace_id=workspace_id)
    assert config is not None
    project = _load_project(db, project_id=config.doctor_project_id)
    if project is None:
        raise HTTPException(status_code=500, detail="Doctor project is missing after seed")

    gateway = build_ui_gateway(actor_user_id=user.id)
    run = DoctorRun(
        workspace_id=workspace_id,
        project_id=project.id,
        fixture_version=DOCTOR_FIXTURE_VERSION,
        status="running",
        summary_json="{}",
        started_at=_now_utc(),
        triggered_by=str(user.id),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    checks: list[dict[str, Any]] = []
    try:
        setup = gateway.setup_project_orchestration(
            project_id=project.id,
            workspace_id=workspace_id,
            enable_team_mode=True,
            enable_git_delivery=True,
            enable_docker_compose=False,
            seed_team_tasks=True,
            kickoff_after_setup=False,
            command_id=command_id or _doctor_command_id("run", workspace_id),
        )
        ensured_tasks = _ensure_doctor_team_tasks(
            gateway=gateway,
            workspace_id=workspace_id,
            project_id=project.id,
            command_id=command_id or _doctor_command_id("run", workspace_id),
        )
        fixture = _seed_doctor_delivery_fixture(
            db,
            gateway=gateway,
            workspace_id=workspace_id,
            project=project,
            user=user,
            command_id=command_id or _doctor_command_id("run", workspace_id),
        )
        surface_fixture = _seed_doctor_product_surface_fixture(
            db,
            gateway=gateway,
            workspace_id=workspace_id,
            project=project,
            user=user,
            command_id=command_id or _doctor_command_id("run", workspace_id),
        )
        capabilities = gateway.get_project_capabilities(project_id=project.id, workspace_id=workspace_id)
        team_verify = gateway.verify_team_mode_workflow(project_id=project.id, workspace_id=workspace_id)
        delivery_verify = gateway.verify_delivery_workflow(project_id=project.id, workspace_id=workspace_id)
        tasks = gateway.list_tasks(workspace_id=workspace_id, project_id=project.id, archived=False, limit=100)
        items = tasks.get("items") if isinstance(tasks, dict) else []
        if not isinstance(items, list):
            items = []
        seeded_team_tasks = [
            item for item in items
            if str((item or {}).get("assigned_agent_code") or "").strip().lower() in DOCTOR_TEAM_TASK_CODES
        ]

        capability_map = capabilities.get("capabilities") if isinstance(capabilities, dict) else {}
        delivery_checks = delivery_verify.get("checks") if isinstance(delivery_verify, dict) else {}
        checks.extend([
            {
                "id": "project_present",
                "label": "Doctor project exists",
                "status": "passed",
                "details": {"project_id": project.id, "project_name": project.name},
            },
            {
                "id": "team_mode_enabled",
                "label": "Team Mode enabled",
                "status": "passed" if bool((capability_map or {}).get("team_mode")) else "failed",
                "details": capability_map,
            },
            {
                "id": "git_delivery_enabled",
                "label": "Git Delivery enabled",
                "status": "passed" if bool((capability_map or {}).get("git_delivery")) else "failed",
                "details": capability_map,
            },
            {
                "id": "seeded_team_tasks",
                "label": "Seeded team tasks present",
                "status": "passed" if len(seeded_team_tasks) >= 4 else "failed",
                "details": {
                    "task_count": len(seeded_team_tasks),
                    "task_ids": [str(item.get("id") or "") for item in seeded_team_tasks if isinstance(item, dict)],
                },
            },
            {
                "id": "team_mode_workflow",
                "label": "Team Mode workflow verification",
                "status": "passed" if bool(team_verify.get("ok")) else "failed",
                "details": team_verify,
            },
            {
                "id": "delivery_workflow",
                "label": "Delivery workflow verification",
                "status": "passed" if bool(delivery_verify.get("ok")) else "failed",
                "details": delivery_verify,
            },
        ])
        for check_id in (
            "repo_context_present",
            "git_contract_ok",
            "compose_manifest_present",
            "lead_deploy_decision_evidence_present",
            "deploy_execution_evidence_present",
            "qa_handoff_current_cycle_ok",
            "qa_has_verifiable_artifacts",
        ):
            checks.append({
                "id": check_id,
                "label": check_id.replace("_", " "),
                "status": "passed" if bool((delivery_checks or {}).get(check_id)) else "failed",
                "details": {"value": bool((delivery_checks or {}).get(check_id))},
            })
        checks.extend(surface_fixture.get("product_checks") or [])
        failed = [item for item in checks if item.get("status") == "failed"]
        warning = [item for item in checks if item.get("status") == "warning"]
        summary = {
            "project_id": project.id,
            "project_link": f"?tab=projects&project={project.id}",
            "setup": _clean_setup_summary(
                setup,
                team_verify=team_verify,
                delivery_verify=delivery_verify,
            ),
            "ensured_tasks": ensured_tasks,
            "fixture": fixture,
            "surface_fixture": surface_fixture,
            "capabilities": capabilities,
            "verification": team_verify,
            "delivery_verification": delivery_verify,
            "checks": checks,
            "counts": {
                "passed": sum(1 for item in checks if item.get("status") == "passed"),
                "warning": len(warning),
                "failed": len(failed),
            },
        }
        run.summary_json = json.dumps(summary, ensure_ascii=False)
        run.status = "failed" if failed else ("warning" if warning else "passed")
    except Exception as exc:
        run.summary_json = json.dumps({"checks": checks, "error": str(exc)}, ensure_ascii=False)
        run.status = "failed"
        raise
    finally:
        finished = _now_utc()
        run.finished_at = finished
        db.add(run)
        config.last_run_at = finished
        config.last_run_status = run.status
        config.updated_by = str(user.id)
        db.add(config)
        db.commit()

    return {
        "workspace_id": workspace_id,
        "run": _serialize_run(run),
        "status": get_doctor_status(db, workspace_id=workspace_id, user=user),
    }


def reset_doctor_workspace(db: Session, *, workspace_id: str, user: User, command_id: str | None = None) -> dict[str, Any]:
    _require_workspace_admin(db, workspace_id=workspace_id, user_id=user.id)
    config = _load_doctor_config(db, workspace_id=workspace_id)
    if config is None:
        return get_doctor_status(db, workspace_id=workspace_id, user=user)

    project = _resolve_doctor_project(db, workspace_id=workspace_id, project_id=config.doctor_project_id)
    if project is None:
        config.doctor_project_id = None
        config.last_seeded_at = None
    else:
        config.doctor_project_id = project.id
    config.last_run_at = None
    config.last_run_status = "reset"
    config.updated_by = str(user.id)
    db.add(config)
    db.commit()
    return get_doctor_status(db, workspace_id=workspace_id, user=user)
