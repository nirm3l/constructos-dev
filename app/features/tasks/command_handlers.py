from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.core import (
    AggregateEventRepository,
    BulkAction,
    CommentCreate,
    DEFAULT_STATUSES,
    Project,
    Specification,
    ReorderPayload,
    Task,
    TaskComment,
    TaskGroup,
    TaskCreate,
    TaskPatch,
    TaskWatcher,
    User,
    allocate_id,
    coerce_originator_id,
    ensure_project_access,
    ensure_role,
    get_kurrent_client,
    get_user_zoneinfo,
    load_task_command_state,
    load_task_view,
    normalize_datetime_to_utc,
    rebuild_state,
    to_iso_utc,
)
from features.notifications.domain import NotificationAggregate
from .domain import TaskAggregate

MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_\-]+)")


def _normalize_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        tag = str(raw).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _normalize_external_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url:
            continue
        item = {"url": url}
        title = str(raw.get("title") or "").strip()
        source = str(raw.get("source") or "").strip()
        if title:
            item["title"] = title
        if source:
            item["source"] = source
        out.append(item)
    return out


def _normalize_attachment_refs(values: list[dict] | None) -> list[dict]:
    if not values:
        return []
    out: list[dict] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "").strip()
        if not path:
            continue
        item = {"path": path}
        name = str(raw.get("name") or "").strip()
        mime_type = str(raw.get("mime_type") or "").strip()
        size_bytes = raw.get("size_bytes")
        if name:
            item["name"] = name
        if mime_type:
            item["mime_type"] = mime_type
        if isinstance(size_bytes, int) and size_bytes >= 0:
            item["size_bytes"] = size_bytes
        out.append(item)
    return out


def _normalize_task_title(value: str) -> str:
    return " ".join(str(value or "").split())


def _task_title_key(value: str) -> str:
    return _normalize_task_title(value).casefold()


def _task_aggregate_id(project_id: str, title: str) -> str:
    key = _task_title_key(title)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"task:{project_id}:{key}"))


def _extract_unique_mentioned_usernames(body: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for username in MENTION_PATTERN.findall(body or ""):
        normalized = username.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(username)
    return out


def _emit_mention_notifications(
    db: Session,
    *,
    actor: User,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    body: str,
) -> None:
    usernames = _extract_unique_mentioned_usernames(body)
    if not usernames:
        return

    mentioned_users = db.execute(select(User).where(User.username.in_(usernames))).scalars().all()
    by_username = {str(user.username or "").casefold(): user for user in mentioned_users}
    actor_username = str(actor.username or "Someone")
    repo = AggregateEventRepository(db)
    for username in usernames:
        target = by_username.get(username.casefold())
        if target is None:
            continue
        if not bool(getattr(target, "notifications_enabled", True)):
            continue
        notification_id = allocate_id(db)
        aggregate = NotificationAggregate(
            id=coerce_originator_id(notification_id),
            user_id=target.id,
            message=f"{actor_username} mentioned you on task #{task_id}",
        )
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": actor.id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "task_id": task_id,
            },
            expected_version=0,
        )


def _require_project_scope(db: Session, *, workspace_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    return project


def _require_specification_scope(db: Session, *, workspace_id: str, project_id: str, specification_id: str) -> Specification:
    specification = db.get(Specification, specification_id)
    if not specification or specification.is_deleted:
        raise HTTPException(status_code=404, detail="Specification not found")
    if specification.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to workspace")
    if specification.project_id != project_id:
        raise HTTPException(status_code=400, detail="Specification does not belong to project")
    if specification.archived:
        raise HTTPException(status_code=409, detail="Specification is archived")
    return specification


def _require_task_group_scope(db: Session, *, workspace_id: str, project_id: str, task_group_id: str) -> TaskGroup:
    task_group = db.get(TaskGroup, task_group_id)
    if not task_group or task_group.is_deleted:
        raise HTTPException(status_code=404, detail="Task group not found")
    if task_group.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Task group does not belong to workspace")
    if task_group.project_id != project_id:
        raise HTTPException(status_code=400, detail="Task group does not belong to project")
    return task_group


def _validate_schedule_fields(
    *,
    task_type: str,
    scheduled_instruction: str | None,
    scheduled_at_utc: str | None,
) -> None:
    if task_type not in {"manual", "scheduled_instruction"}:
        raise HTTPException(status_code=422, detail='task_type must be "manual" or "scheduled_instruction"')
    if task_type == "scheduled_instruction":
        if not (scheduled_instruction or "").strip():
            raise HTTPException(status_code=422, detail="scheduled_instruction is required for scheduled_instruction tasks")
        if not scheduled_at_utc:
            raise HTTPException(status_code=422, detail="scheduled_at_utc is required for scheduled_instruction tasks")


def require_task_command_state(db: Session, user: User, task_id: str, *, allowed: set[str]) -> tuple[str, str | None, str, bool]:
    state = load_task_command_state(db, task_id)
    if not state or state.is_deleted:
        raise HTTPException(status_code=404, detail="Task not found")
    if state.project_id:
        ensure_project_access(db, state.workspace_id, state.project_id, user.id, allowed)
    else:
        ensure_role(db, state.workspace_id, user.id, allowed)
    return state.workspace_id, state.project_id, state.status, state.archived


def _load_task_aggregate(repo: AggregateEventRepository, task_id: str) -> TaskAggregate:
    return repo.load_with_class(
        aggregate_type="Task",
        aggregate_id=task_id,
        aggregate_cls=TaskAggregate,
    )


def _persist_task_aggregate(
    repo: AggregateEventRepository,
    aggregate: TaskAggregate,
    *,
    actor_id: str,
    workspace_id: str,
    project_id: str | None,
    task_id: str,
    expected_version: int | None = None,
) -> None:
    repo.persist(
        aggregate,
        base_metadata={
            "actor_id": actor_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "task_id": task_id,
        },
        expected_version=expected_version,
    )


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class CreateTaskHandler:
    ctx: CommandContext
    payload: TaskCreate

    def __call__(self) -> dict:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member"})
        project = _require_project_scope(self.ctx.db, workspace_id=self.payload.workspace_id, project_id=self.payload.project_id)
        ensure_project_access(
            self.ctx.db,
            self.payload.workspace_id,
            self.payload.project_id,
            self.ctx.user.id,
            {"Owner", "Admin", "Member"},
        )
        title = _normalize_task_title(self.payload.title)
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        tid = _task_aggregate_id(self.payload.project_id, title)
        existing_task_state = load_task_command_state(self.ctx.db, tid)
        if existing_task_state and not existing_task_state.is_deleted:
            task_view = load_task_view(self.ctx.db, tid)
            if task_view is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return task_view
        if existing_task_state and existing_task_state.is_deleted:
            raise HTTPException(
                status_code=409,
                detail="Task with this title already exists in deleted state; restore is not supported",
            )

        specification_id = (self.payload.specification_id or "").strip() or None
        task_group_id = (self.payload.task_group_id or "").strip() or None
        assignee_id = (self.payload.assignee_id or "").strip() or None

        if specification_id:
            _require_specification_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                specification_id=specification_id,
            )
        if task_group_id:
            _require_task_group_scope(
                self.ctx.db,
                workspace_id=self.payload.workspace_id,
                project_id=self.payload.project_id,
                task_group_id=task_group_id,
            )
        try:
            statuses = json.loads(project.custom_statuses or "[]")
        except Exception:
            statuses = DEFAULT_STATUSES
        initial_status = (statuses[0] if statuses else DEFAULT_STATUSES[0]) or DEFAULT_STATUSES[0]
        user_tz = get_user_zoneinfo(self.ctx.user)
        task_type = (self.payload.task_type or "manual").strip() or "manual"
        scheduled_at = normalize_datetime_to_utc(self.payload.scheduled_at_utc, user_tz)
        scheduled_instruction = (self.payload.scheduled_instruction or "").strip() or None
        external_refs = _normalize_external_refs([r.model_dump() for r in self.payload.external_refs])
        attachment_refs = _normalize_attachment_refs([r.model_dump() for r in self.payload.attachment_refs])
        if not attachment_refs and self.payload.attachments:
            attachment_refs = _normalize_attachment_refs(self.payload.attachments)
        _validate_schedule_fields(
            task_type=task_type,
            scheduled_instruction=scheduled_instruction,
            scheduled_at_utc=to_iso_utc(scheduled_at),
        )
        max_order = self.ctx.db.execute(
            select(func.max(Task.order_index)).where(Task.workspace_id == self.payload.workspace_id, Task.project_id == self.payload.project_id)
        ).scalar() or 0
        aggregate = TaskAggregate(
            id=coerce_originator_id(tid),
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            task_group_id=task_group_id,
            specification_id=specification_id,
            title=title,
            description=self.payload.description,
            status=initial_status,
            priority=self.payload.priority,
            due_date=to_iso_utc(normalize_datetime_to_utc(self.payload.due_date, user_tz)),
            assignee_id=assignee_id,
            labels=_normalize_tags(self.payload.labels),
            subtasks=self.payload.subtasks,
            attachments=attachment_refs,
            external_refs=external_refs,
            attachment_refs=attachment_refs,
            recurring_rule=self.payload.recurring_rule,
            task_type=task_type,
            scheduled_instruction=scheduled_instruction if task_type == "scheduled_instruction" else None,
            scheduled_at_utc=to_iso_utc(scheduled_at) if task_type == "scheduled_instruction" else None,
            schedule_timezone=self.payload.schedule_timezone if task_type == "scheduled_instruction" else None,
            schedule_state="idle",
            order_index=max_order + 1,
        )
        if task_type == "scheduled_instruction":
            aggregate.configure_schedule(
                scheduled_instruction=scheduled_instruction,
                scheduled_at_utc=to_iso_utc(scheduled_at),
                schedule_timezone=self.payload.schedule_timezone,
                schedule_state="idle",
            )
        _persist_task_aggregate(
            AggregateEventRepository(self.ctx.db),
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
            task_id=tid,
            expected_version=0,
        )
        try:
            self.ctx.db.commit()
        except IntegrityError as exc:
            self.ctx.db.rollback()
            message = str(exc).lower()
            if "unique constraint failed" not in message or "tasks.id" not in message:
                raise
        task_view = load_task_view(self.ctx.db, tid)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found after create")
        return task_view


@dataclass(frozen=True, slots=True)
class PatchTaskHandler:
    ctx: CommandContext
    task_id: str
    payload: TaskPatch

    def __call__(self) -> dict:
        user_tz = get_user_zoneinfo(self.ctx.user)
        data = self.payload.model_dump(exclude_unset=True)
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if "project_id" in data:
            if not data["project_id"]:
                raise HTTPException(status_code=422, detail="project_id cannot be null")
            _require_project_scope(self.ctx.db, workspace_id=workspace_id, project_id=str(data["project_id"]))
            ensure_project_access(
                self.ctx.db,
                workspace_id,
                str(data["project_id"]),
                self.ctx.user.id,
                {"Owner", "Admin", "Member"},
            )
        if "labels" in data and data["labels"] is not None:
            data["labels"] = _normalize_tags(data["labels"])
        if "external_refs" in data and data["external_refs"] is not None:
            data["external_refs"] = _normalize_external_refs(data["external_refs"])
        if "attachment_refs" in data and data["attachment_refs"] is not None:
            data["attachment_refs"] = _normalize_attachment_refs(data["attachment_refs"])
            data["attachments"] = data["attachment_refs"]
        elif "attachments" in data and data["attachments"] is not None:
            data["attachments"] = _normalize_attachment_refs(data["attachments"])
            data["attachment_refs"] = data["attachments"]
        current_row = self.ctx.db.get(Task, self.task_id)
        current_state = None
        if current_row is None and get_kurrent_client() is not None:
            current_state, _ = rebuild_state(self.ctx.db, "Task", self.task_id)
        if current_row is None and not current_state:
            raise HTTPException(status_code=404, detail="Task not found")

        current_task_type = (
            (current_row.task_type if current_row is not None else None)
            or (str(current_state.get("task_type")) if current_state else None)
            or "manual"
        )
        current_scheduled_instruction = (
            current_row.scheduled_instruction if current_row is not None else (current_state.get("scheduled_instruction") if current_state else None)
        )
        current_scheduled_at_utc = (
            to_iso_utc(current_row.scheduled_at_utc)
            if current_row is not None
            else (current_state.get("scheduled_at_utc") if current_state else None)
        )
        current_schedule_timezone = (
            current_row.schedule_timezone if current_row is not None else (current_state.get("schedule_timezone") if current_state else None)
        )
        current_specification_id = (
            current_row.specification_id if current_row is not None else (current_state.get("specification_id") if current_state else None)
        )
        current_task_group_id = (
            current_row.task_group_id if current_row is not None else (current_state.get("task_group_id") if current_state else None)
        )
        effective_project_id = str(data.get("project_id", project_id) or "")
        if not effective_project_id:
            raise HTTPException(status_code=422, detail="project_id is required")
        project_id_changed = "project_id" in data and str(data.get("project_id") or "") != str(project_id or "")
        if project_id_changed and current_specification_id and "specification_id" not in data:
            raise HTTPException(status_code=409, detail="Cannot change project while task is linked to specification")
        if project_id_changed and current_task_group_id and "task_group_id" not in data:
            raise HTTPException(status_code=409, detail="Cannot change project while task is linked to task group")
        if "task_group_id" in data:
            if data.get("task_group_id"):
                _require_task_group_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    task_group_id=str(data["task_group_id"]),
                )
            else:
                data["task_group_id"] = None
        if "specification_id" in data:
            specification_id = data.get("specification_id")
            if specification_id:
                _require_specification_scope(
                    self.ctx.db,
                    workspace_id=workspace_id,
                    project_id=effective_project_id,
                    specification_id=str(specification_id),
                )
            else:
                data["specification_id"] = None
        event_payload = dict(data)
        if "due_date" in event_payload:
            event_payload["due_date"] = to_iso_utc(normalize_datetime_to_utc(event_payload["due_date"], user_tz))
        if "scheduled_at_utc" in event_payload:
            event_payload["scheduled_at_utc"] = to_iso_utc(normalize_datetime_to_utc(event_payload["scheduled_at_utc"], user_tz))
        if "scheduled_instruction" in event_payload and event_payload["scheduled_instruction"] is not None:
            event_payload["scheduled_instruction"] = str(event_payload["scheduled_instruction"]).strip() or None

        effective_task_type = str(event_payload.get("task_type", current_task_type))
        effective_scheduled_instruction = event_payload.get("scheduled_instruction", current_scheduled_instruction)
        effective_scheduled_at_utc = event_payload.get("scheduled_at_utc", current_scheduled_at_utc)
        _validate_schedule_fields(
            task_type=effective_task_type,
            scheduled_instruction=effective_scheduled_instruction,
            scheduled_at_utc=effective_scheduled_at_utc,
        )
        if effective_task_type == "manual":
            event_payload["scheduled_instruction"] = None
            event_payload["scheduled_at_utc"] = None
            event_payload["schedule_timezone"] = None
            event_payload["schedule_state"] = "idle"
            event_payload["last_schedule_error"] = None
            event_payload["recurring_rule"] = None
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.update(changes=event_payload)
        if effective_task_type == "scheduled_instruction":
            aggregate.configure_schedule(
                scheduled_instruction=effective_scheduled_instruction,
                scheduled_at_utc=effective_scheduled_at_utc,
                schedule_timezone=event_payload.get("schedule_timezone", current_schedule_timezone),
                schedule_state=event_payload.get("schedule_state", "idle"),
            )
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=event_payload.get("project_id", project_id),
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class CompleteTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if status == "Done":
            raise HTTPException(status_code=409, detail="Task already completed")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.complete(completed_at=to_iso_utc(datetime.now(timezone.utc)))
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ReopenTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, status, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if status != "Done":
            raise HTTPException(status_code=409, detail="Task is not completed")
        reopen_status = "To do"
        if project_id:
            project = self.ctx.db.get(Project, project_id)
            if project and not project.is_deleted:
                try:
                    statuses = json.loads(project.custom_statuses or "[]")
                except Exception:
                    statuses = DEFAULT_STATUSES
                reopen_status = (statuses[0] if statuses else DEFAULT_STATUSES[0]) or DEFAULT_STATUSES[0]
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.reopen(status=reopen_status)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        task_view = load_task_view(self.ctx.db, self.task_id)
        if task_view is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task_view


@dataclass(frozen=True, slots=True)
class ArchiveTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if archived:
            raise HTTPException(status_code=409, detail="Task already archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.archive()
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class RestoreTaskHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, archived = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        if not archived:
            raise HTTPException(status_code=409, detail="Task is not archived")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.restore()
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class BulkTaskActionHandler:
    ctx: CommandContext
    payload: BulkAction

    def __call__(self, task_id: str) -> bool:
        workspace_id, project_id, status, archived = require_task_command_state(self.ctx.db, self.ctx.user, task_id, allowed={"Owner", "Admin", "Member"})
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, task_id)
        if self.payload.action == "complete":
            if status == "Done":
                return False
            aggregate.complete(completed_at=to_iso_utc(datetime.now(timezone.utc)))
        elif self.payload.action == "archive":
            if archived:
                return False
            aggregate.archive()
        elif self.payload.action == "delete":
            aggregate.delete()
        elif self.payload.action == "set_status":
            aggregate.update(changes={"status": self.payload.payload.get("status", status)})
        elif self.payload.action == "reopen":
            if status != "Done":
                return False
            aggregate.reopen(status=self.payload.payload.get("status", "To do"))
        else:
            return False
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
        )
        self.ctx.db.commit()
        return True


@dataclass(frozen=True, slots=True)
class ReorderTasksHandler:
    ctx: CommandContext
    workspace_id: str
    project_id: str
    payload: ReorderPayload

    def __call__(self, task_id: str, order_index: int) -> bool:
        state = load_task_command_state(self.ctx.db, task_id)
        if (
            not state
            or state.is_deleted
            or state.workspace_id != self.workspace_id
            or state.project_id != self.project_id
        ):
            return False
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, task_id)
        aggregate.reorder(order_index=order_index, status=self.payload.status)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.workspace_id,
            project_id=state.project_id,
            task_id=task_id,
        )
        self.ctx.db.commit()
        return True


@dataclass(frozen=True, slots=True)
class AddCommentHandler:
    ctx: CommandContext
    task_id: str
    payload: CommentCreate

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.add_comment(task_id=self.task_id, user_id=self.ctx.user.id, body=self.payload.body)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        _emit_mention_notifications(
            self.ctx.db,
            actor=self.ctx.user,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
            body=self.payload.body,
        )
        self.ctx.db.commit()
        last = self.ctx.db.execute(select(TaskComment).where(TaskComment.task_id == self.task_id).order_by(TaskComment.id.desc()).limit(1)).scalar_one_or_none()
        if last:
            return {"id": last.id, "task_id": self.task_id, "body": last.body, "created_at": to_iso_utc(last.created_at)}
        return {"id": None, "task_id": self.task_id, "body": self.payload.body, "created_at": None}


@dataclass(frozen=True, slots=True)
class DeleteCommentHandler:
    ctx: CommandContext
    task_id: str
    comment_id: int

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        comment = self.ctx.db.get(TaskComment, self.comment_id)
        if not comment or comment.task_id != self.task_id:
            raise HTTPException(status_code=404, detail="Comment not found")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.delete_comment(task_id=self.task_id, comment_id=self.comment_id)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class ToggleWatchHandler:
    ctx: CommandContext
    task_id: str

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member", "Guest"})
        currently_watched = (
            self.ctx.db.execute(
                select(func.count()).select_from(TaskWatcher).where(
                    TaskWatcher.task_id == self.task_id,
                    TaskWatcher.user_id == self.ctx.user.id,
                )
            ).scalar_one()
            or 0
        ) > 0
        next_watched = not currently_watched
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.toggle_watch(task_id=self.task_id, user_id=self.ctx.user.id, watched=next_watched)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"watched": next_watched}


@dataclass(frozen=True, slots=True)
class RequestAutomationRunHandler:
    ctx: CommandContext
    task_id: str
    instruction: str | None = None

    def __call__(self) -> dict:
        workspace_id, project_id, _, _ = require_task_command_state(self.ctx.db, self.ctx.user, self.task_id, allowed={"Owner", "Admin", "Member"})
        requested_at = to_iso_utc(datetime.now(timezone.utc))
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = _load_task_aggregate(repo, self.task_id)
        aggregate.request_automation(requested_at=requested_at, instruction=self.instruction)
        _persist_task_aggregate(
            repo,
            aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=self.task_id,
        )
        self.ctx.db.commit()
        return {"ok": True, "task_id": self.task_id, "automation_state": "queued", "requested_at": requested_at}
