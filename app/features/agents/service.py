from __future__ import annotations

import hmac
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from features.projects.application import ProjectApplicationService
from features.tasks.application import TaskApplicationService
from features.tasks.read_models import TaskListQuery, get_task_automation_status_read_model, list_tasks_read_model
from shared.core import CommentCreate, Project, ProjectCreate, SessionLocal, TaskAutomationRun, TaskCreate, TaskPatch, User, load_task_command_state, load_task_view
from shared.deps import ensure_role
from shared.models import User as UserModel
from shared.settings import (
    MCP_ACTOR_USER_ID,
    MCP_DEFAULT_WORKSPACE_ID,
    MCP_ALLOWED_PROJECT_IDS,
    MCP_ALLOWED_WORKSPACE_IDS,
    MCP_AUTH_TOKEN,
)


class AgentTaskService:
    """Service used by MCP tools to safely operate on tasks."""

    def _require_token(self, auth_token: str | None):
        if not MCP_AUTH_TOKEN:
            return
        if not auth_token or not hmac.compare_digest(auth_token, MCP_AUTH_TOKEN):
            raise HTTPException(status_code=401, detail="Invalid MCP token")

    def _assert_workspace_allowed(self, workspace_id: str):
        if MCP_ALLOWED_WORKSPACE_IDS and workspace_id not in MCP_ALLOWED_WORKSPACE_IDS:
            raise HTTPException(status_code=403, detail="Workspace is outside MCP allowlist")

    def _assert_project_allowed(self, project_id: str | None):
        if not project_id:
            return
        if MCP_ALLOWED_PROJECT_IDS and project_id not in MCP_ALLOWED_PROJECT_IDS:
            raise HTTPException(status_code=403, detail="Project is outside MCP allowlist")

    def _resolve_actor_user(self) -> UserModel:
        with SessionLocal() as db:
            user = db.get(User, MCP_ACTOR_USER_ID)
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            return user

    def _resolve_workspace_for_create(self, *, db, explicit_workspace_id: str | None, project_id: str | None) -> tuple[str, str | None]:
        if project_id:
            project = db.execute(select(Project).where(Project.id == project_id, Project.is_deleted == False)).scalar_one_or_none()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            self._assert_project_allowed(project_id)
            if explicit_workspace_id and explicit_workspace_id != project.workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            workspace_id = project.workspace_id
            self._assert_workspace_allowed(workspace_id)
            return workspace_id, project_id

        if explicit_workspace_id:
            self._assert_workspace_allowed(explicit_workspace_id)
            return explicit_workspace_id, None

        if MCP_DEFAULT_WORKSPACE_ID:
            self._assert_workspace_allowed(MCP_DEFAULT_WORKSPACE_ID)
            return MCP_DEFAULT_WORKSPACE_ID, None

        if len(MCP_ALLOWED_WORKSPACE_IDS) == 1:
            only_workspace = next(iter(MCP_ALLOWED_WORKSPACE_IDS))
            return only_workspace, None

        raise HTTPException(
            status_code=400,
            detail="workspace_id is required when no project_id is provided and MCP default workspace is not configured",
        )

    def _resolve_workspace_for_project_create(self, *, explicit_workspace_id: str | None) -> str:
        if explicit_workspace_id:
            self._assert_workspace_allowed(explicit_workspace_id)
            return explicit_workspace_id
        if MCP_DEFAULT_WORKSPACE_ID:
            self._assert_workspace_allowed(MCP_DEFAULT_WORKSPACE_ID)
            return MCP_DEFAULT_WORKSPACE_ID
        if len(MCP_ALLOWED_WORKSPACE_IDS) == 1:
            return next(iter(MCP_ALLOWED_WORKSPACE_IDS))
        raise HTTPException(
            status_code=400,
            detail="workspace_id is required for project creation when MCP default workspace is not configured",
        )

    def list_tasks(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        view: str | None = None,
        q: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        label: str | None = None,
        assignee_id: str | None = None,
        priority: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=workspace_id,
                    view=view,
                    q=q,
                    status=status,
                    project_id=project_id,
                    label=label,
                    assignee_id=assignee_id,
                    priority=priority,
                    archived=archived,
                    limit=limit,
                    offset=offset,
                ),
            )

    def get_task(self, *, task_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            task = load_task_view(db, task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            return task

    def get_task_automation_status(self, *, task_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            return get_task_automation_status_read_model(db, user, task_id)

    def create_task(
        self,
        *,
        workspace_id: str | None = None,
        title: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        description: str = "",
        priority: str = "Med",
        due_date: str | None = None,
        task_type: str = "manual",
        scheduled_instruction: str | None = None,
        scheduled_at_utc: str | None = None,
        schedule_timezone: str | None = None,
        assignee_id: str | None = None,
        labels: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_create(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            payload = TaskCreate(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
                task_type=task_type,
                scheduled_instruction=scheduled_instruction,
                scheduled_at_utc=scheduled_at_utc,
                schedule_timezone=schedule_timezone,
                assignee_id=assignee_id,
                labels=labels or [],
            )
            return TaskApplicationService(db, user, command_id=command_id or f"mcp-create-{uuid.uuid4()}").create_task(payload)

    def create_project(
        self,
        *,
        name: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        description: str = "",
        custom_statuses: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            payload = ProjectCreate(
                workspace_id=resolved_workspace_id,
                name=name,
                description=description,
                custom_statuses=custom_statuses,
            )
            return ProjectApplicationService(db, user, command_id=command_id or f"mcp-project-create-{uuid.uuid4()}").create_project(payload)

    def update_task(self, *, task_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            payload = TaskPatch(**patch)
            return TaskApplicationService(db, user, command_id=command_id or f"mcp-patch-{uuid.uuid4()}").patch_task(task_id, payload)

    def complete_task(self, *, task_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            return TaskApplicationService(db, user, command_id=command_id or f"mcp-complete-{uuid.uuid4()}").complete_task(task_id)

    def add_task_comment(
        self,
        *,
        task_id: str,
        body: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            payload = CommentCreate(body=body)
            return TaskApplicationService(db, user, command_id=command_id or f"mcp-comment-{uuid.uuid4()}").add_comment(task_id, payload)

    def request_task_automation_run(
        self,
        *,
        task_id: str,
        instruction: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            payload = TaskAutomationRun(instruction=instruction)
            return TaskApplicationService(db, user, command_id=command_id or f"mcp-run-{uuid.uuid4()}").request_automation_run(task_id, payload)
