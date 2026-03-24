from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from features.notes.application import NoteApplicationService
from features.tasks.application import TaskApplicationService
from shared.commanding import execute_command
from shared.core import (
    NotePatch,
    SpecificationCreate,
    SpecificationPatch,
    TaskPatch,
    User,
    ensure_project_access,
    ensure_role,
    load_note_command_state,
    load_note_view,
    load_task_command_state,
    load_task_view,
)

from .command_handlers import (
    ArchiveSpecificationHandler,
    CommandContext,
    CreateNoteFromSpecificationHandler,
    CreateTaskFromSpecificationHandler,
    CreateTasksFromSpecificationBatchHandler,
    CreateSpecificationHandler,
    DeleteSpecificationHandler,
    PatchSpecificationHandler,
    RestoreSpecificationHandler,
    require_specification_command_state,
)


MUTATION_ROLES = {"Owner", "Admin", "Member"}


class SpecificationApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def _require_specification_scope(self, specification_id: str, *, require_active: bool) -> tuple[str, str]:
        workspace_id, project_id, _, archived = require_specification_command_state(
            self.db,
            self.user,
            specification_id,
            allowed=MUTATION_ROLES,
        )
        if require_active and archived:
            raise HTTPException(status_code=409, detail="Specification is archived")
        return workspace_id, project_id

    def create_specification(self, payload: SpecificationCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateSpecificationHandler(self.ctx, payload),
        )

    def patch_specification(self, specification_id: str, payload: SpecificationPatch) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchSpecificationHandler(self.ctx, specification_id, payload),
        )

    def archive_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveSpecificationHandler(self.ctx, specification_id),
        )

    def restore_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Restore",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RestoreSpecificationHandler(self.ctx, specification_id),
        )

    def delete_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteSpecificationHandler(self.ctx, specification_id),
        )

    def create_task_from_specification(
        self,
        specification_id: str,
        *,
        title: str,
        description: str = "",
        priority: str = "Med",
        due_date: datetime | None = None,
        assignee_id: str | None = None,
        labels: list[str] | None = None,
        external_refs: list[dict] | None = None,
        attachment_refs: list[dict] | None = None,
        recurring_rule: str | None = None,
        task_type: str = "manual",
        scheduled_instruction: str | None = None,
        scheduled_at_utc: datetime | None = None,
        schedule_timezone: str | None = None,
    ) -> dict:
        workspace_id, project_id = self._require_specification_scope(specification_id, require_active=True)
        normalized_title = str(title or "").strip()
        if not normalized_title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        return execute_command(
            self.db,
            command_name="Specification.TaskCreate",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateTaskFromSpecificationHandler(
                self.ctx,
                workspace_id=workspace_id,
                project_id=project_id,
                specification_id=specification_id,
                title=normalized_title,
                description=description or "",
                priority=priority or "Med",
                due_date=due_date,
                assignee_id=assignee_id,
                labels=labels or [],
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
                recurring_rule=recurring_rule,
                task_type=task_type,
                scheduled_instruction=scheduled_instruction,
                scheduled_at_utc=scheduled_at_utc,
                schedule_timezone=schedule_timezone,
            ),
        )

    def create_tasks_from_specification(
        self,
        specification_id: str,
        *,
        titles: list[str],
        description: str = "",
        priority: str = "Med",
        due_date: datetime | None = None,
        assignee_id: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        workspace_id, project_id = self._require_specification_scope(specification_id, require_active=True)
        normalized_titles = [str(title).strip() for title in titles if str(title).strip()]
        if not normalized_titles:
            raise HTTPException(status_code=422, detail="titles must contain at least one non-empty item")

        return execute_command(
            self.db,
            command_name="Specification.TaskCreateBatch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateTasksFromSpecificationBatchHandler(
                self.ctx,
                workspace_id=workspace_id,
                project_id=project_id,
                specification_id=specification_id,
                titles=normalized_titles,
                description=description or "",
                priority=priority or "Med",
                due_date=due_date,
                assignee_id=assignee_id,
                labels=labels or [],
            ),
        )

    def create_note_from_specification(
        self,
        specification_id: str,
        *,
        title: str,
        body: str = "",
        tags: list[str] | None = None,
        pinned: bool = False,
        external_refs: list[dict] | None = None,
        attachment_refs: list[dict] | None = None,
    ) -> dict:
        workspace_id, project_id = self._require_specification_scope(specification_id, require_active=True)
        normalized_title = str(title or "").strip()
        if not normalized_title:
            raise HTTPException(status_code=422, detail="title cannot be empty")
        return execute_command(
            self.db,
            command_name="Specification.NoteCreate",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateNoteFromSpecificationHandler(
                self.ctx,
                workspace_id=workspace_id,
                project_id=project_id,
                specification_id=specification_id,
                title=normalized_title,
                body=body or "",
                tags=tags or [],
                pinned=bool(pinned),
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
            ),
        )

    def link_task_to_specification(self, specification_id: str, task_id: str) -> dict:
        self._require_specification_scope(specification_id, require_active=True)
        return TaskApplicationService(self.db, self.user, command_id=self.command_id).patch_task(
            task_id,
            TaskPatch(specification_id=specification_id),
        )

    def unlink_task_from_specification(self, specification_id: str, task_id: str) -> dict:
        workspace_id, project_id = self._require_specification_scope(specification_id, require_active=False)
        task_state = load_task_command_state(self.db, task_id)
        if not task_state or task_state.is_deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        if task_state.project_id:
            ensure_project_access(self.db, task_state.workspace_id, task_state.project_id, self.user.id, MUTATION_ROLES)
        else:
            ensure_role(self.db, task_state.workspace_id, self.user.id, MUTATION_ROLES)
        if task_state.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Task does not belong to specification workspace")
        if task_state.project_id != project_id:
            raise HTTPException(status_code=400, detail="Task does not belong to specification project")
        if task_state.specification_id and task_state.specification_id != specification_id:
            raise HTTPException(status_code=409, detail="Task is linked to a different specification")
        if not task_state.specification_id:
            existing = load_task_view(self.db, task_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Task not found")
            return existing
        return TaskApplicationService(self.db, self.user, command_id=self.command_id).patch_task(
            task_id,
            TaskPatch(specification_id=None),
        )

    def link_note_to_specification(self, specification_id: str, note_id: str) -> dict:
        self._require_specification_scope(specification_id, require_active=True)
        return NoteApplicationService(self.db, self.user, command_id=self.command_id).patch_note(
            note_id,
            NotePatch(specification_id=specification_id),
        )

    def unlink_note_from_specification(self, specification_id: str, note_id: str) -> dict:
        workspace_id, project_id = self._require_specification_scope(specification_id, require_active=False)
        note_state = load_note_command_state(self.db, note_id)
        if not note_state or note_state.is_deleted:
            raise HTTPException(status_code=404, detail="Note not found")
        if note_state.project_id:
            ensure_project_access(self.db, note_state.workspace_id, note_state.project_id, self.user.id, MUTATION_ROLES)
        else:
            ensure_role(self.db, note_state.workspace_id, self.user.id, MUTATION_ROLES)
        if note_state.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Note does not belong to specification workspace")
        if note_state.project_id != project_id:
            raise HTTPException(status_code=400, detail="Note does not belong to specification project")
        if note_state.specification_id and note_state.specification_id != specification_id:
            raise HTTPException(status_code=409, detail="Note is linked to a different specification")
        if not note_state.specification_id:
            existing = load_note_view(self.db, note_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Note not found")
            return existing
        return NoteApplicationService(self.db, self.user, command_id=self.command_id).patch_note(
            note_id,
            NotePatch(specification_id=None),
        )
