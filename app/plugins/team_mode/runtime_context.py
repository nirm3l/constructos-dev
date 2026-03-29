from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.eventing import rebuild_state
from shared.models import ProjectMember, ProjectPluginConfig, Task

from .semantics import REQUIRED_SEMANTIC_STATUSES, normalize_review_policy, normalize_status_semantics
from .task_roles import build_active_agent_load_by_code, canonicalize_role, derive_task_role, normalize_team_agents


@dataclass(frozen=True, slots=True)
class TeamModeTaskRuntimeEntry:
    task: Task
    state: dict[str, Any]
    task_like: dict[str, Any]
    workflow_role: str


@dataclass(slots=True)
class TeamModeProjectRuntimeContext:
    db: Session
    workspace_id: str
    project_id: str
    _plugin_loaded: bool = field(default=False, init=False, repr=False)
    _enabled: bool = field(default=False, init=False, repr=False)
    _config: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _team_agents: list[dict[str, str]] | None = field(default=None, init=False, repr=False)
    _member_role_by_user_id: dict[str, str] | None = field(default=None, init=False, repr=False)
    _tasks: list[Task] | None = field(default=None, init=False, repr=False)
    _task_by_id: dict[str, Task] | None = field(default=None, init=False, repr=False)
    _task_state_by_id: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _task_like_by_id: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _task_entry_by_id: dict[str, TeamModeTaskRuntimeEntry] = field(default_factory=dict, init=False, repr=False)
    _status_semantics: dict[str, str] | None = field(default=None, init=False, repr=False)
    _review_policy: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def _load_plugin_payload(self) -> None:
        if self._plugin_loaded:
            return
        self._plugin_loaded = True
        row = self.db.execute(
            select(ProjectPluginConfig.enabled, ProjectPluginConfig.config_json).where(
                ProjectPluginConfig.workspace_id == self.workspace_id,
                ProjectPluginConfig.project_id == self.project_id,
                ProjectPluginConfig.plugin_key == "team_mode",
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).first()
        if row is None:
            self._enabled = False
            self._config = {}
            return
        self._enabled = bool(row[0])
        try:
            parsed = json.loads(str(row[1] or "").strip() or "{}")
        except Exception:
            parsed = {}
        self._config = dict(parsed) if isinstance(parsed, dict) else {}

    @property
    def enabled(self) -> bool:
        self._load_plugin_payload()
        return bool(self._enabled)

    @property
    def config(self) -> dict[str, Any]:
        self._load_plugin_payload()
        return dict(self._config)

    @property
    def team_agents(self) -> list[dict[str, str]]:
        if self._team_agents is None:
            self._team_agents = normalize_team_agents(self.config.get("team"))
        return [dict(agent) for agent in self._team_agents]

    @property
    def agent_role_by_code(self) -> dict[str, str]:
        return {
            str(agent.get("id") or "").strip(): canonicalize_role(agent.get("authority_role"))
            for agent in self.team_agents
            if str(agent.get("id") or "").strip()
        }

    @property
    def member_role_by_user_id(self) -> dict[str, str]:
        if self._member_role_by_user_id is None:
            self._member_role_by_user_id = {
                str(user_id): canonicalize_role(role)
                for user_id, role in self.db.execute(
                    select(ProjectMember.user_id, ProjectMember.role).where(
                        ProjectMember.workspace_id == self.workspace_id,
                        ProjectMember.project_id == self.project_id,
                    )
                ).all()
            }
        return dict(self._member_role_by_user_id)

    @property
    def tasks(self) -> list[Task]:
        if self._tasks is None:
            self._tasks = list(
                self.db.execute(
                    select(Task).where(
                        Task.workspace_id == self.workspace_id,
                        Task.project_id == self.project_id,
                        Task.is_deleted == False,  # noqa: E712
                        Task.archived == False,  # noqa: E712
                    ).order_by(Task.created_at.asc())
                ).scalars().all()
            )
        return list(self._tasks)

    @property
    def task_by_id(self) -> dict[str, Task]:
        if self._task_by_id is None:
            self._task_by_id = {
                str(getattr(task, "id", "") or "").strip(): task
                for task in self.tasks
                if str(getattr(task, "id", "") or "").strip()
            }
        return dict(self._task_by_id)

    def task_state(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return {}
        cached = self._task_state_by_id.get(normalized_task_id)
        if cached is not None:
            return dict(cached)
        state, _ = rebuild_state(self.db, "Task", normalized_task_id)
        normalized_state = dict(state or {})
        self._task_state_by_id[normalized_task_id] = normalized_state
        return dict(normalized_state)

    def task_like(self, task: Task) -> dict[str, Any]:
        task_id = str(getattr(task, "id", "") or "").strip()
        if not task_id:
            return {}
        cached = self._task_like_by_id.get(task_id)
        if cached is not None:
            return dict(cached)
        state = self.task_state(task_id)
        task_like = {
            "id": task_id,
            "assignee_id": str(state.get("assignee_id") or getattr(task, "assignee_id", "") or "").strip(),
            "assigned_agent_code": str(state.get("assigned_agent_code") or getattr(task, "assigned_agent_code", "") or "").strip(),
            "dispatch_slot": str(state.get("dispatch_slot") or "").strip(),
            "labels": state.get("labels") if state.get("labels") is not None else getattr(task, "labels", None),
            "status": str(state.get("status") or getattr(task, "status", "") or "").strip(),
            "automation_state": str(state.get("automation_state") or "idle").strip().lower(),
            "instruction": str(state.get("instruction") or getattr(task, "instruction", "") or "").strip(),
            "scheduled_instruction": str(state.get("scheduled_instruction") or getattr(task, "scheduled_instruction", "") or "").strip(),
        }
        self._task_like_by_id[task_id] = task_like
        return dict(task_like)

    def task_likes(self) -> list[dict[str, Any]]:
        return [self.task_like(task) for task in self.tasks if str(getattr(task, "id", "") or "").strip()]

    @staticmethod
    def _clone_task_entry(entry: TeamModeTaskRuntimeEntry | None) -> TeamModeTaskRuntimeEntry | None:
        if entry is None:
            return None
        return TeamModeTaskRuntimeEntry(
            task=entry.task,
            state=dict(entry.state),
            task_like=dict(entry.task_like),
            workflow_role=str(entry.workflow_role or "").strip(),
        )

    def task_entry(self, task_id: str) -> TeamModeTaskRuntimeEntry | None:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return None
        cached = self._task_entry_by_id.get(normalized_task_id)
        if cached is not None:
            return self._clone_task_entry(cached)
        task = self.task_by_id.get(normalized_task_id)
        if task is None:
            return None
        task_like = self.task_like(task)
        cached = TeamModeTaskRuntimeEntry(
            task=task,
            state=self.task_state(normalized_task_id),
            task_like=task_like,
            workflow_role=self.derive_workflow_role(task_like=task_like),
        )
        self._task_entry_by_id[normalized_task_id] = cached
        return self._clone_task_entry(cached)

    def task_entries(self) -> list[TeamModeTaskRuntimeEntry]:
        entries: list[TeamModeTaskRuntimeEntry] = []
        for task_id in self.task_by_id:
            entry = self.task_entry(task_id)
            if entry is not None:
                entries.append(entry)
        return entries

    def source_task_entries(
        self,
        source_task_ids: list[str] | tuple[str, ...] | set[str],
        *,
        exclude_task_id: str | None = None,
    ) -> list[TeamModeTaskRuntimeEntry]:
        normalized_exclude_task_id = str(exclude_task_id or "").strip()
        entries: list[TeamModeTaskRuntimeEntry] = []
        for source_task_id in source_task_ids:
            normalized_source_task_id = str(source_task_id or "").strip()
            if not normalized_source_task_id or normalized_source_task_id == normalized_exclude_task_id:
                continue
            entry = self.task_entry(normalized_source_task_id)
            if entry is not None:
                entries.append(entry)
        return entries

    def project_has_runtime_activity(self, *, exclude_task_id: str | None = None) -> bool:
        normalized_exclude_task_id = str(exclude_task_id or "").strip()
        for entry in self.task_entries():
            task_id = str(getattr(entry.task, "id", "") or "").strip()
            if task_id and task_id == normalized_exclude_task_id:
                continue
            state = entry.state
            if str(state.get("last_requested_source") or "").strip():
                return True
            if str(state.get("last_lead_handoff_token") or "").strip():
                return True
            if isinstance(state.get("last_deploy_execution"), dict) and state.get("last_deploy_execution"):
                return True
            refs = state.get("external_refs")
            if isinstance(refs, list) and any(isinstance(item, dict) and str(item.get("url") or "").strip() for item in refs):
                return True
        return False

    @property
    def status_semantics(self) -> dict[str, str]:
        if self._status_semantics is None:
            self._status_semantics = normalize_status_semantics(self.config.get("status_semantics"))
        return dict(self._status_semantics)

    @property
    def review_policy(self) -> dict[str, Any]:
        if self._review_policy is None:
            self._review_policy = normalize_review_policy(self.config.get("review_policy"))
        return dict(self._review_policy)

    @property
    def completed_status(self) -> str:
        return str(self.status_semantics.get("completed") or REQUIRED_SEMANTIC_STATUSES["completed"]).strip()

    @property
    def blocked_status(self) -> str:
        return str(self.status_semantics.get("blocked") or REQUIRED_SEMANTIC_STATUSES["blocked"]).strip()

    @property
    def human_owner_user_id(self) -> str | None:
        oversight = self.config.get("oversight") if isinstance(self.config.get("oversight"), dict) else {}
        user_id = str(oversight.get("human_owner_user_id") or "").strip()
        return user_id or None

    @property
    def reviewer_user_id(self) -> str | None:
        reviewer_user_id = str(self.review_policy.get("reviewer_user_id") or "").strip()
        if reviewer_user_id:
            return reviewer_user_id
        return self.human_owner_user_id

    @property
    def review_required(self) -> bool:
        return bool(self.review_policy.get("require_code_review"))

    def derive_workflow_role(
        self,
        *,
        task: Task | None = None,
        task_like: dict[str, Any] | None = None,
    ) -> str:
        source_task_like = dict(task_like or {})
        if task is not None:
            source_task_like = self.task_like(task)
        if not source_task_like:
            return ""
        return str(
            derive_task_role(
                task_like=source_task_like,
                member_role_by_user_id=self.member_role_by_user_id,
                agent_role_by_code=self.agent_role_by_code,
            )
            or ""
        ).strip()

    def active_agent_load_by_code(
        self,
        *,
        agents: list[dict[str, str]] | None = None,
    ) -> dict[str, int]:
        effective_agents = list(agents or self.team_agents)
        if not effective_agents:
            return {}
        return build_active_agent_load_by_code(
            agents=effective_agents,
            task_likes=self.task_likes(),
            member_role_by_user_id=self.member_role_by_user_id,
            agent_role_by_code=self.agent_role_by_code,
        )
