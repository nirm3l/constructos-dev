from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select

from features.projects.application import ProjectApplicationService
from features.project_templates.application import ProjectTemplateApplicationService
from features.project_skills.application import ProjectSkillApplicationService
from features.project_skills.read_models import (
    ProjectSkillListQuery,
    WorkspaceSkillListQuery,
    list_project_skills_read_model,
    list_workspace_skills_read_model,
    load_project_skill_view,
    load_workspace_skill_view,
)
from features.rules.application import ProjectRuleApplicationService
from features.rules.read_models import ProjectRuleListQuery, list_project_rules_read_model
from features.specifications.application import SpecificationApplicationService
from features.specifications.read_models import SpecificationListQuery, list_specifications_read_model
from features.users.application import UserApplicationService
from features.users.gateway import UserOperationGateway
from features.tasks.application import TaskApplicationService
from features.tasks.read_models import TaskListQuery, get_task_automation_status_read_model, list_tasks_read_model
from features.notes.application import NoteApplicationService
from features.notes.read_models import NoteListQuery, list_notes_read_model
from features.note_groups.application import NoteGroupApplicationService
from features.note_groups.read_models import NoteGroupListQuery, list_note_groups_read_model
from features.task_groups.application import TaskGroupApplicationService
from features.task_groups.read_models import TaskGroupListQuery, list_task_groups_read_model
from shared.core import (
    BulkAction,
    CommentCreate,
    NoteCreate,
    NoteGroupCreate,
    NoteGroupPatch,
    NotePatch,
    Project,
    ProjectCreate,
    ProjectPatch,
    ProjectRule,
    ProjectRuleCreate,
    ProjectRulePatch,
    ReorderPayload,
    SessionLocal,
    TaskAutomationRun,
    TaskCreate,
    TaskGroupCreate,
    TaskGroupPatch,
    TaskPatch,
    User,
    UserPreferencesPatch,
    ensure_project_access,
    load_note_command_state,
    load_note_group_command_state,
    load_note_view,
    load_task_command_state,
    load_task_group_command_state,
    load_task_view,
)
from shared.core import load_project_rule_command_state, load_project_rule_view
from shared.core import (
    SpecificationCreate,
    SpecificationPatch,
    load_specification_command_state,
    load_specification_view,
)
from features.project_templates.schemas import ProjectFromTemplateCreate, ProjectFromTemplatePreview
from shared.deps import ensure_role
from shared.knowledge_graph import (
    build_graph_context_pack,
    graph_context_pack as graph_context_pack_query,
    graph_find_related_resources as graph_find_related_resources_query,
    graph_get_dependency_path as graph_get_dependency_path_query,
    graph_get_neighbors as graph_get_neighbors_query,
    graph_get_project_overview as graph_get_project_overview_query,
    require_graph_available,
    search_project_knowledge as search_project_knowledge_query,
)
from shared.models import (
    Note,
    ProjectMember,
    ProjectRule as ProjectRuleModel,
    ProjectSkill,
    Task,
    TaskComment,
    WorkspaceSkill,
    User as UserModel,
)
from shared.settings import (
    DEFAULT_USER_ID,
    MCP_ACTOR_USER_ID,
    MCP_DEFAULT_WORKSPACE_ID,
    MCP_ALLOWED_PROJECT_IDS,
    MCP_ALLOWED_WORKSPACE_IDS,
    MCP_AUTH_TOKEN,
)

_READ_ONLY_MCP_METHODS = frozenset(
    {
        "list_tasks",
        "list_notes",
        "list_task_groups",
        "list_note_groups",
        "list_project_rules",
        "list_project_members",
        "list_project_skills",
        "list_workspace_skills",
        "list_specifications",
        "list_spec_tasks",
        "list_spec_notes",
        "get_note",
        "get_task",
        "get_project_rule",
        "get_project_skill",
        "get_workspace_skill",
        "get_specification",
        "get_task_automation_status",
        "get_my_preferences",
        "get_project_chat_context",
        "graph_get_project_overview",
        "graph_get_neighbors",
        "graph_find_related_resources",
        "graph_get_dependency_path",
        "graph_context_pack",
        "search_project_knowledge",
        "verify_team_mode_workflow",
        "verify_delivery_workflow",
        "list_project_templates",
        "get_project_template",
        "preview_project_from_template",
    }
)
_LICENSE_WRITE_BLOCKED_MESSAGE = "License expired. Write access is disabled until subscription is reactivated."
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_GITHUB_HOST_TOKENS = ("github.com", "www.github.com")


def _graph_summary_to_markdown(summary: dict[str, object] | None) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    lines: list[str] = []
    executive = str(summary.get("executive") or "").strip()
    if executive:
        lines.append("# Grounded Summary")
        lines.append("")
        lines.append(executive)
    key_points = summary.get("key_points")
    if isinstance(key_points, list) and key_points:
        if lines:
            lines.append("")
        lines.append("## Key Points")
        for item in key_points:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            evidence_ids = [str(raw).strip() for raw in (item.get("evidence_ids") or []) if str(raw).strip()]
            if not claim:
                continue
            suffix = f" [{', '.join(evidence_ids)}]" if evidence_ids else ""
            lines.append(f"- {claim}{suffix}")
    gaps = summary.get("gaps")
    if isinstance(gaps, list) and gaps:
        if lines:
            lines.append("")
        lines.append("## Gaps")
        for gap in gaps:
            text = str(gap or "").strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines).strip()


def _render_project_rules_markdown(rows: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for title, body in rows:
        clean_title = str(title or "").strip()
        clean_body = str(body or "").strip()
        if not clean_title and not clean_body:
            continue
        label = clean_title or "Untitled rule"
        if clean_body:
            lines.append(f"- {label}: {clean_body}")
        else:
            lines.append(f"- {label}")
    return "\n".join(lines) if lines else "_(no project rules)_"


def _render_project_skills_markdown(rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        skill_key = str(row.get("skill_key") or "").strip()
        summary = str(row.get("summary") or "").strip()
        mode = str(row.get("mode") or "").strip().lower() or "advisory"
        trust_level = str(row.get("trust_level") or "").strip().lower() or "reviewed"
        source_locator = str(row.get("source_locator") or "").strip()
        if not name and not skill_key:
            continue
        label = name or skill_key
        key_text = f" ({skill_key})" if skill_key else ""
        source_text = f" source={source_locator}" if source_locator else ""
        suffix_parts = [f"mode={mode}", f"trust={trust_level}"]
        if summary:
            suffix_parts.append(summary)
        suffix_text = "; ".join(suffix_parts)
        lines.append(f"- {label}{key_text}: {suffix_text}{source_text}")
    return "\n".join(lines) if lines else "_(no project skills)_"


def _render_project_chat_context_markdown(
    *,
    soul_md: str,
    rules_md: str,
    skills_md: str,
    graph_md: str,
    graph_evidence_json: str,
    graph_summary_md: str,
) -> str:
    return (
        "Context Pack:\n"
        "File: Soul.md (source: project.description)\n"
        f"{soul_md}\n\n"
        "File: ProjectRules.md (source: project_rules)\n"
        f"{rules_md}\n\n"
        "File: ProjectSkills.md (source: project_skills)\n"
        f"{skills_md}\n\n"
        "File: GraphContext.md (source: knowledge_graph)\n"
        f"{graph_md}\n\n"
        "File: GraphEvidence.json (source: knowledge_graph.evidence)\n"
        f"{graph_evidence_json}\n\n"
        "File: GraphSummary.md (source: knowledge_graph.summary)\n"
        f"{graph_summary_md}\n\n"
        "Refresh Policy:\n"
        "- If required project details are missing, stale, or uncertain, call `get_project_chat_context` again before continuing.\n"
        "- If project rules/skills or graph relations may have changed, refresh this context before making decisions.\n"
        "- If claims are not backed by GraphEvidence IDs, refresh context and verify evidence before acting.\n"
    ).strip()


class AgentTaskService:
    """Service used by MCP tools to safely operate on tasks."""

    def __init__(
        self,
        *,
        user_gateway: UserOperationGateway | None = None,
        require_token: bool = True,
        actor_user_id: str | None = None,
        allowed_workspace_ids: set[str] | None = None,
        allowed_project_ids: set[str] | None = None,
        default_workspace_id: str | None = None,
    ):
        self._user_gateway = user_gateway or UserOperationGateway()
        self._require_mcp_token = bool(require_token)
        self._actor_user_id = str(actor_user_id or "").strip() or None
        self._allowed_workspace_ids = (
            set(MCP_ALLOWED_WORKSPACE_IDS) if allowed_workspace_ids is None else set(allowed_workspace_ids)
        )
        self._allowed_project_ids = (
            set(MCP_ALLOWED_PROJECT_IDS) if allowed_project_ids is None else set(allowed_project_ids)
        )
        self._default_workspace_id = (
            str(MCP_DEFAULT_WORKSPACE_ID or "").strip()
            if default_workspace_id is None
            else str(default_workspace_id or "").strip()
        )

    def _calling_method_name(self) -> str:
        frame = inspect.currentframe()
        if frame is None:
            return ""
        caller = frame.f_back
        if caller is None:
            return ""
        service_method_frame = caller.f_back
        if service_method_frame is None:
            return ""
        return str(service_method_frame.f_code.co_name or "")

    def _is_write_operation_call(self, method_name: str) -> bool:
        if not method_name or method_name.startswith("_"):
            return False
        return method_name not in _READ_ONLY_MCP_METHODS

    def _enforce_license_write_access(self) -> None:
        from features.licensing.read_models import license_status_read_model

        with SessionLocal() as db:
            payload = license_status_read_model(db)
        if bool(payload.get("write_access")):
            return
        raise HTTPException(status_code=402, detail=_LICENSE_WRITE_BLOCKED_MESSAGE)

    def _require_token(self, auth_token: str | None):
        if self._require_mcp_token and MCP_AUTH_TOKEN:
            if not auth_token or not hmac.compare_digest(auth_token, MCP_AUTH_TOKEN):
                raise HTTPException(status_code=401, detail="Invalid MCP token")

        if self._is_write_operation_call(self._calling_method_name()):
            self._enforce_license_write_access()

    def _assert_workspace_allowed(self, workspace_id: str):
        if self._allowed_workspace_ids and workspace_id not in self._allowed_workspace_ids:
            raise HTTPException(status_code=403, detail="Workspace is outside MCP allowlist")

    def _assert_project_allowed(self, project_id: str | None):
        if not project_id:
            return
        if self._allowed_project_ids and project_id not in self._allowed_project_ids:
            raise HTTPException(status_code=403, detail="Project is outside MCP allowlist")

    @staticmethod
    def _parse_json_string(value: str, *, field_name: str) -> Any:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"{field_name} must be valid JSON") from exc

    @classmethod
    def _normalize_execution_triggers_input(
        cls,
        value: Any,
        *,
        field_name: str = "execution_triggers",
    ) -> list[dict[str, Any]] | None:
        if value is None:
            return None

        def _expand_mapping(raw: dict[str, Any]) -> list[dict[str, Any]] | None:
            if "kind" in raw:
                return [dict(raw)]
            expanded: list[dict[str, Any]] = []
            for kind in ("manual", "schedule", "status_change"):
                if kind not in raw:
                    continue
                candidate = raw.get(kind)
                if candidate is None:
                    continue
                if isinstance(candidate, list):
                    for item in candidate:
                        if isinstance(item, dict):
                            merged = dict(item)
                            merged["kind"] = str(merged.get("kind") or kind)
                            expanded.append(merged)
                        elif isinstance(item, bool):
                            expanded.append({"kind": kind, "enabled": item})
                    continue
                if isinstance(candidate, dict):
                    merged = dict(candidate)
                    merged["kind"] = str(merged.get("kind") or kind)
                    expanded.append(merged)
                    continue
                if isinstance(candidate, bool):
                    expanded.append({"kind": kind, "enabled": candidate})
            return expanded or None

        parsed = value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            parsed = cls._parse_json_string(raw, field_name=field_name)
        if isinstance(parsed, dict):
            parsed = _expand_mapping(parsed) or [parsed]
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail=f"{field_name} must be a JSON array or object")
        normalized: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail=f"{field_name} items must be JSON objects")
            normalized.extend(_expand_mapping(item) or [dict(item)])
        return normalized

    @classmethod
    def _normalize_string_list_input(
        cls,
        value: Any,
        *,
        field_name: str,
    ) -> list[str] | None:
        if value is None:
            return None
        parsed = value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                parsed = cls._parse_json_string(raw, field_name=field_name)
            else:
                parsed = [segment.strip() for segment in raw.split(",") if segment.strip()]
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422, detail=f"{field_name} must be a list or comma-separated string")
        out: list[str] = []
        for item in parsed:
            clean = str(item or "").strip()
            if clean:
                out.append(clean)
        return out

    @classmethod
    def _normalize_task_patch_input(cls, patch: Any) -> dict[str, Any]:
        if isinstance(patch, str):
            parsed = cls._parse_json_string(patch, field_name="patch")
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=422, detail="patch must be a JSON object")
            normalized_patch: dict[str, Any] = dict(parsed)
        elif isinstance(patch, dict):
            normalized_patch = dict(patch)
        else:
            raise HTTPException(status_code=422, detail="patch must be an object")

        if "execution_triggers" in normalized_patch:
            normalized_patch["execution_triggers"] = cls._normalize_execution_triggers_input(
                normalized_patch.get("execution_triggers"),
                field_name="patch.execution_triggers",
            )
        if "labels" in normalized_patch:
            normalized_patch["labels"] = cls._normalize_string_list_input(
                normalized_patch.get("labels"),
                field_name="patch.labels",
            )
        recurring_rule = str(normalized_patch.get("recurring_rule") or "").strip()
        if recurring_rule and "task_type" not in normalized_patch and "scheduled_at_utc" in normalized_patch:
            normalized_patch["task_type"] = "scheduled_instruction"
            if "scheduled_instruction" not in normalized_patch and "instruction" in normalized_patch:
                normalized_patch["scheduled_instruction"] = normalized_patch.get("instruction")
        return normalized_patch

    def _assert_task_allowed(self, *, db, task_id: str | None):
        if not task_id:
            return None
        state = load_task_command_state(db, task_id)
        if not state or state.is_deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        self._assert_workspace_allowed(state.workspace_id)
        self._assert_project_allowed(state.project_id)
        return state

    def _assert_task_group_allowed(self, *, db, task_group_id: str | None):
        if not task_group_id:
            return None
        state = load_task_group_command_state(db, task_group_id)
        if not state or state.is_deleted:
            raise HTTPException(status_code=404, detail="Task group not found")
        self._assert_workspace_allowed(state.workspace_id)
        self._assert_project_allowed(state.project_id)
        return state

    def _assert_note_group_allowed(self, *, db, note_group_id: str | None):
        if not note_group_id:
            return None
        state = load_note_group_command_state(db, note_group_id)
        if not state or state.is_deleted:
            raise HTTPException(status_code=404, detail="Note group not found")
        self._assert_workspace_allowed(state.workspace_id)
        self._assert_project_allowed(state.project_id)
        return state

    def _assert_project_rule_allowed(self, *, db, rule_id: str | None):
        if not rule_id:
            return None
        state = load_project_rule_command_state(db, rule_id)
        if not state or state.is_deleted:
            raise HTTPException(status_code=404, detail="Project rule not found")
        self._assert_workspace_allowed(state.workspace_id)
        self._assert_project_allowed(state.project_id)
        return state

    def _assert_project_skill_allowed(self, *, db, skill_id: str | None):
        if not skill_id:
            return None
        skill = db.get(ProjectSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            raise HTTPException(status_code=404, detail="Project skill not found")
        self._assert_workspace_allowed(skill.workspace_id)
        self._assert_project_allowed(skill.project_id)
        return skill

    def _assert_workspace_skill_allowed(self, *, db, skill_id: str | None):
        if not skill_id:
            return None
        skill = db.get(WorkspaceSkill, skill_id)
        if skill is None or bool(skill.is_deleted):
            raise HTTPException(status_code=404, detail="Workspace skill not found")
        self._assert_workspace_allowed(skill.workspace_id)
        return skill

    def _assert_specification_allowed(self, *, db, specification_id: str | None):
        if not specification_id:
            return None
        state = load_specification_command_state(db, specification_id)
        if not state or state.is_deleted:
            raise HTTPException(status_code=404, detail="Specification not found")
        self._assert_workspace_allowed(state.workspace_id)
        self._assert_project_allowed(state.project_id)
        return state

    def _resolve_actor_user(self, user_id: str | None = None) -> UserModel:
        target_user_id = str(user_id or "").strip() or self._actor_user_id or MCP_ACTOR_USER_ID
        with SessionLocal() as db:
            user = db.get(User, target_user_id)
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            return user

    def _resolve_preference_target_user_id(self, user_id: str | None) -> str:
        explicit_user_id = str(user_id or "").strip()
        if explicit_user_id:
            return explicit_user_id
        if self._actor_user_id:
            return self._actor_user_id
        # In containerized runtime the MCP actor is often a dedicated bot account.
        # Preference updates should default to the primary app user unless the caller
        # explicitly targets a different user.
        if MCP_ACTOR_USER_ID != DEFAULT_USER_ID:
            return DEFAULT_USER_ID
        return MCP_ACTOR_USER_ID

    def _resolve_workspace_for_create(self, *, db, explicit_workspace_id: str | None, project_id: str | None) -> tuple[str, str]:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        project = db.execute(select(Project).where(Project.id == project_id, Project.is_deleted == False)).scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        self._assert_project_allowed(project_id)
        if explicit_workspace_id and explicit_workspace_id != project.workspace_id:
            raise HTTPException(status_code=400, detail="Project does not belong to workspace")
        workspace_id = project.workspace_id
        self._assert_workspace_allowed(workspace_id)
        return workspace_id, project_id

    def _resolve_workspace_for_project_create(self, *, explicit_workspace_id: str | None) -> str:
        if explicit_workspace_id:
            self._assert_workspace_allowed(explicit_workspace_id)
            return explicit_workspace_id
        if self._default_workspace_id:
            self._assert_workspace_allowed(self._default_workspace_id)
            return self._default_workspace_id
        if len(self._allowed_workspace_ids) == 1:
            return next(iter(self._allowed_workspace_ids))
        raise HTTPException(
            status_code=400,
            detail="workspace_id is required for project creation when MCP default workspace is not configured",
        )

    def _normalize_command_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [self._normalize_command_payload(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_command_payload(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._normalize_command_payload(value[key])
                for key in sorted(value.keys(), key=lambda item: str(item))
            }
        return value

    def _fallback_command_id(self, *, prefix: str, payload: dict[str, Any]) -> str:
        normalized_payload = self._normalize_command_payload(payload)
        encoded = json.dumps(normalized_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
        return f"{prefix}-{digest}"

    @staticmethod
    def _derive_child_command_id(command_id: str | None, child_key: str) -> str | None:
        normalized = str(command_id or "").strip()
        if not normalized:
            return None
        suffix = str(child_key or "").strip()
        if not suffix:
            return normalized
        candidate = f"{normalized}:{suffix}"
        if len(candidate) <= 64:
            return candidate
        suffix_digest = hashlib.sha1(suffix.encode("utf-8")).hexdigest()[:12]
        keep = max(1, 64 - len(suffix_digest) - 1)
        return f"{normalized[:keep]}:{suffix_digest}"

    def _normalize_project_name(self, value: str) -> str:
        return " ".join(str(value or "").split())

    def _fallback_project_create_command_id(self, *, workspace_id: str, name: str) -> str:
        return self._fallback_command_id(
            prefix="mcp-project-create",
            payload={
                "workspace_id": workspace_id,
                "name_key": self._normalize_project_name(name).casefold(),
            },
        )

    def _fallback_project_template_create_command_id(self, *, workspace_id: str, template_key: str, name: str) -> str:
        return self._fallback_command_id(
            prefix="mcp-project-template-create",
            payload={
                "workspace_id": workspace_id,
                "template_key": str(template_key or "").strip().lower(),
                "name_key": self._normalize_project_name(name).casefold(),
            },
        )

    def _resolve_workspace_for_note_create(
        self,
        *,
        db,
        explicit_workspace_id: str | None,
        project_id: str | None,
        task_id: str | None,
    ) -> tuple[str, str | None, str | None]:
        # task_id is the strongest scope anchor: it implies workspace/project.
        if task_id:
            task_state = self._assert_task_allowed(db=db, task_id=task_id)
            assert task_state is not None
            if explicit_workspace_id and explicit_workspace_id != task_state.workspace_id:
                raise HTTPException(status_code=400, detail="task_id does not belong to workspace_id")
            if project_id and project_id != task_state.project_id:
                raise HTTPException(status_code=400, detail="task_id does not belong to project_id")
            return task_state.workspace_id, task_state.project_id, task_id

        # Else: same logic as tasks/projects.
        ws_id, proj_id = self._resolve_workspace_for_create(db=db, explicit_workspace_id=explicit_workspace_id, project_id=project_id)
        return ws_id, proj_id, None

    def list_tasks(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        view: str | None = None,
        q: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        task_group_id: str | None = None,
        specification_id: str | None = None,
        tags: list[str] | None = None,
        label: str | None = None,
        assignee_id: str | None = None,
        due_from: datetime | None = None,
        due_to: datetime | None = None,
        priority: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            if specification_id:
                self._assert_specification_allowed(db=db, specification_id=specification_id)
            if task_group_id:
                self._assert_task_group_allowed(db=db, task_group_id=task_group_id)
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
                    task_group_id=task_group_id,
                    specification_id=specification_id,
                    tags=tags,
                    label=label,
                    assignee_id=assignee_id,
                    due_from=due_from,
                    due_to=due_to,
                    priority=priority,
                    archived=archived,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_notes(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        note_group_id: str | None = None,
        task_id: str | None = None,
        specification_id: str | None = None,
        q: str | None = None,
        tags: list[str] | None = None,
        archived: bool = False,
        pinned: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            if task_id:
                self._assert_task_allowed(db=db, task_id=task_id)
            if note_group_id:
                self._assert_note_group_allowed(db=db, note_group_id=note_group_id)
            if specification_id:
                self._assert_specification_allowed(db=db, specification_id=specification_id)
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_notes_read_model(
                db,
                user,
                NoteListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    note_group_id=note_group_id,
                    task_id=task_id,
                    specification_id=specification_id,
                    q=q,
                    tags=tags,
                    archived=archived,
                    pinned=pinned,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_task_groups(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_task_groups_read_model(
                db,
                user,
                TaskGroupListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_note_groups(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_note_groups_read_model(
                db,
                user,
                NoteGroupListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_project_rules(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_project_rules_read_model(
                db,
                user,
                ProjectRuleListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_project_members(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        role: str | None = None,
        user_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(0, int(offset or 0))
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            if str(project.workspace_id) != str(workspace_id):
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            stmt = (
                select(ProjectMember, UserModel)
                .join(UserModel, UserModel.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
            )
            normalized_role = str(role or "").strip()
            if normalized_role:
                stmt = stmt.where(ProjectMember.role == normalized_role)
            normalized_user_type = str(user_type or "").strip().lower()
            if normalized_user_type:
                stmt = stmt.where(func.lower(UserModel.user_type) == normalized_user_type)
            normalized_q = str(q or "").strip()
            if normalized_q:
                like = f"%{normalized_q}%"
                stmt = stmt.where(
                    ProjectMember.role.ilike(like)
                    | UserModel.username.ilike(like)
                    | UserModel.full_name.ilike(like)
                )
            total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
            rows = db.execute(
                stmt.order_by(UserModel.full_name.asc(), UserModel.username.asc()).limit(safe_limit).offset(safe_offset)
            ).all()
            return {
                "project_id": str(project_id),
                "workspace_id": str(workspace_id),
                "items": [
                    {
                        "project_id": str(pm.project_id),
                        "user_id": str(pm.user_id),
                        "role": str(pm.role or ""),
                        "user": {
                            "id": str(u.id),
                            "username": str(u.username or ""),
                            "full_name": str(u.full_name or ""),
                            "user_type": str(u.user_type or ""),
                        },
                    }
                    for pm, u in rows
                ],
                "total": int(total),
                "limit": int(safe_limit),
                "offset": int(safe_offset),
            }

    def list_project_skills(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_project_skills_read_model(
                db,
                user,
                ProjectSkillListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_workspace_skills(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_workspace_skills_read_model(
                db,
                user,
                WorkspaceSkillListQuery(
                    workspace_id=workspace_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_specifications(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_specifications_read_model(
                db,
                user,
                SpecificationListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    status=status,
                    tags=tags,
                    archived=archived,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_spec_tasks(
        self,
        *,
        specification_id: str,
        auth_token: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            spec_state = self._assert_specification_allowed(db=db, specification_id=specification_id)
            assert spec_state is not None
            ensure_role(db, spec_state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=spec_state.workspace_id,
                    project_id=spec_state.project_id,
                    specification_id=specification_id,
                    archived=archived,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_spec_notes(
        self,
        *,
        specification_id: str,
        auth_token: str | None = None,
        archived: bool = False,
        pinned: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            spec_state = self._assert_specification_allowed(db=db, specification_id=specification_id)
            assert spec_state is not None
            ensure_role(db, spec_state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_notes_read_model(
                db,
                user,
                NoteListQuery(
                    workspace_id=spec_state.workspace_id,
                    project_id=spec_state.project_id,
                    specification_id=specification_id,
                    archived=archived,
                    pinned=pinned,
                    limit=limit,
                    offset=offset,
                ),
            )

    def get_note(self, *, note_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            if state.task_id:
                self._assert_task_allowed(db=db, task_id=state.task_id)
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            note = load_note_view(db, note_id)
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            return note

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

    def get_project_rule(self, *, rule_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_project_rule_allowed(db=db, rule_id=rule_id)
            assert state is not None
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            rule = load_project_rule_view(db, rule_id)
            if not rule:
                raise HTTPException(status_code=404, detail="Project rule not found")
            return rule

    def get_project_skill(self, *, skill_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_project_skill_allowed(db=db, skill_id=skill_id)
            assert state is not None
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            skill = load_project_skill_view(db, skill_id)
            if not skill:
                raise HTTPException(status_code=404, detail="Project skill not found")
            return skill

    def get_workspace_skill(self, *, skill_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_workspace_skill_allowed(db=db, skill_id=skill_id)
            assert state is not None
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            skill = load_workspace_skill_view(db, skill_id)
            if not skill:
                raise HTTPException(status_code=404, detail="Workspace skill not found")
            return skill

    def get_specification(self, *, specification_id: str, auth_token: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_specification_allowed(db=db, specification_id=specification_id)
            assert state is not None
            ensure_role(db, state.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            specification = load_specification_view(db, specification_id)
            if not specification:
                raise HTTPException(status_code=404, detail="Specification not found")
            return specification

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

    def get_my_preferences(self, *, auth_token: str | None = None, user_id: str | None = None) -> dict:
        self._require_token(auth_token)
        with SessionLocal() as db:
            return self._user_gateway.get_preferences(
                db=db,
                actor_user_id=MCP_ACTOR_USER_ID,
                explicit_target_user_id=user_id,
                implicit_target_user_id=self._resolve_preference_target_user_id(user_id),
            )

    def toggle_my_theme(
        self,
        *,
        auth_token: str | None = None,
        command_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        actor_user_id = MCP_ACTOR_USER_ID
        implicit_target_user_id = self._resolve_preference_target_user_id(user_id)
        with SessionLocal() as db:
            current = self._user_gateway.get_preferences(
                db=db,
                actor_user_id=actor_user_id,
                explicit_target_user_id=user_id,
                implicit_target_user_id=implicit_target_user_id,
            )
        current_theme = str(current.get("theme") or "light").strip().lower()
        next_theme = "light" if current_theme == "dark" else "dark"
        effective_command_id = (
            self._fallback_command_id(
                prefix="mcp-theme-toggle",
                payload={
                    "base_command_id": str(command_id or ""),
                    "user_id": str(current.get("id") or ""),
                    "from_theme": current_theme,
                    "to_theme": next_theme,
                },
            )
            if command_id
            else f"mcp-theme-toggle-{uuid.uuid4()}"
        )
        with SessionLocal() as db:
            return self._user_gateway.patch_preferences(
                db=db,
                actor_user_id=actor_user_id,
                payload=UserPreferencesPatch(theme=next_theme),
                command_id=effective_command_id,
                explicit_target_user_id=user_id,
                implicit_target_user_id=implicit_target_user_id,
            )

    def set_my_theme(
        self,
        *,
        theme: str,
        auth_token: str | None = None,
        command_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized = str(theme or "").strip().lower()
        if normalized not in {"light", "dark"}:
            raise HTTPException(status_code=422, detail="theme must be one of: light, dark")
        actor_user_id = MCP_ACTOR_USER_ID
        implicit_target_user_id = self._resolve_preference_target_user_id(user_id)
        # Theme set is naturally idempotent by target value, so we avoid relying on
        # LLM-provided command_id values that may be unintentionally reused across turns.
        effective_command_id = f"mcp-theme-set-{uuid.uuid4()}"
        with SessionLocal() as db:
            return self._user_gateway.patch_preferences(
                db=db,
                actor_user_id=actor_user_id,
                payload=UserPreferencesPatch(theme=normalized),
                command_id=effective_command_id,
                explicit_target_user_id=user_id,
                implicit_target_user_id=implicit_target_user_id,
            )

    def _load_project_scope(self, *, db, project_id: str):
        project = db.execute(select(Project).where(Project.id == project_id, Project.is_deleted == False)).scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        self._assert_workspace_allowed(project.workspace_id)
        self._assert_project_allowed(project.id)
        return project

    def _resolve_project_for_chat_context(
        self,
        *,
        db,
        user: UserModel,
        project_ref: str,
        workspace_id: str | None = None,
    ) -> tuple[Project, str]:
        normalized_ref = str(project_ref or "").strip()
        if not normalized_ref:
            raise HTTPException(status_code=400, detail="project_ref is required")
        normalized_workspace_id = str(workspace_id or "").strip()
        if normalized_workspace_id:
            self._assert_workspace_allowed(normalized_workspace_id)

        project = db.execute(
            select(Project).where(
                Project.id == normalized_ref,
                Project.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        if project is not None:
            if normalized_workspace_id and str(project.workspace_id) != normalized_workspace_id:
                raise HTTPException(status_code=404, detail="Project not found in workspace")
            self._assert_workspace_allowed(project.workspace_id)
            self._assert_project_allowed(project.id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return project, "id"

        by_name_query = select(Project).where(
            Project.is_deleted == False,  # noqa: E712
            func.lower(Project.name) == normalized_ref.lower(),
        )
        if normalized_workspace_id:
            by_name_query = by_name_query.where(Project.workspace_id == normalized_workspace_id)
        if self._allowed_workspace_ids:
            by_name_query = by_name_query.where(Project.workspace_id.in_(sorted(self._allowed_workspace_ids)))
        if self._allowed_project_ids:
            by_name_query = by_name_query.where(Project.id.in_(sorted(self._allowed_project_ids)))

        matches = (
            db.execute(
                by_name_query.order_by(
                    Project.updated_at.desc(),
                    Project.created_at.desc(),
                    Project.id.asc(),
                ).limit(6)
            )
            .scalars()
            .all()
        )
        if not matches:
            raise HTTPException(status_code=404, detail="Project not found by id or name")
        if len(matches) > 1:
            candidate_ids = ", ".join(str(item.id) for item in matches[:3])
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Multiple projects match '{normalized_ref}'. "
                    f"Use project id or provide workspace_id. Matches: {candidate_ids}"
                ),
            )
        project = matches[0]
        self._assert_workspace_allowed(project.workspace_id)
        self._assert_project_allowed(project.id)
        ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        return project, "name"

    def get_project_chat_context(
        self,
        *,
        project_ref: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        graph_limit: int = 20,
    ) -> dict[str, Any]:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        safe_graph_limit = max(1, min(int(graph_limit or 20), 40))
        resolved_by = "id"
        project_id = ""
        project_name = ""
        project_workspace_id = ""
        project_description = ""
        with SessionLocal() as db:
            project, resolved_by = self._resolve_project_for_chat_context(
                db=db,
                user=user,
                project_ref=project_ref,
                workspace_id=workspace_id,
            )
            project_id = str(project.id)
            project_name = str(project.name or "")
            project_workspace_id = str(project.workspace_id)
            project_description = str(project.description or "")
            rules_rows = db.execute(
                select(ProjectRule.title, ProjectRule.body)
                .where(
                    ProjectRule.project_id == project.id,
                    ProjectRule.is_deleted == False,  # noqa: E712
                )
                .order_by(ProjectRule.updated_at.desc())
            ).all()
            skills_rows = (
                db.execute(
                    select(
                        ProjectSkill.skill_key,
                        ProjectSkill.name,
                        ProjectSkill.summary,
                        ProjectSkill.mode,
                        ProjectSkill.trust_level,
                        ProjectSkill.source_locator,
                    )
                    .where(
                        ProjectSkill.project_id == project.id,
                        ProjectSkill.is_deleted == False,  # noqa: E712
                    )
                    .order_by(ProjectSkill.updated_at.desc())
                )
                .all()
            )

        soul_md = project_description.strip() or "_(empty)_"
        rules_md = _render_project_rules_markdown([(str(title or ""), str(body or "")) for title, body in rules_rows])
        normalized_skills = [
            {
                "skill_key": str(skill_key or ""),
                "name": str(name or ""),
                "summary": str(summary or ""),
                "mode": str(mode or ""),
                "trust_level": str(trust_level or ""),
                "source_locator": str(source_locator or ""),
            }
            for skill_key, name, summary, mode, trust_level, source_locator in skills_rows
        ]
        skills_md = _render_project_skills_markdown(normalized_skills)

        graph_pack = build_graph_context_pack(project_id=project_id, limit=safe_graph_limit)
        graph_md = str(graph_pack.get("markdown") or "").strip() if graph_pack else ""
        if not graph_md:
            graph_md = "_(knowledge graph unavailable)_"
        graph_evidence_json = json.dumps(graph_pack.get("evidence") or [], ensure_ascii=True) if graph_pack else "[]"
        graph_summary_md = _graph_summary_to_markdown(graph_pack.get("summary")) if graph_pack else ""
        if not graph_summary_md:
            graph_summary_md = "_(summary unavailable)_"

        refresh_policy = [
            "If required project details are missing, stale, or uncertain, call `get_project_chat_context` again before continuing.",
            "If project rules, skills, or graph relations may have changed, refresh this context before making decisions.",
            "If claims are not backed by GraphEvidence IDs, refresh context and verify evidence before acting.",
        ]
        context_pack_markdown = _render_project_chat_context_markdown(
            soul_md=soul_md,
            rules_md=rules_md,
            skills_md=skills_md,
            graph_md=graph_md,
            graph_evidence_json=graph_evidence_json,
            graph_summary_md=graph_summary_md,
        )

        return {
            "project_id": project_id,
            "project_name": project_name,
            "workspace_id": project_workspace_id,
            "resolved_by": resolved_by,
            "context_pack": {
                "soul_md": soul_md,
                "project_rules_md": rules_md,
                "project_skills_md": skills_md,
                "graph_context_md": graph_md,
                "graph_evidence_json": graph_evidence_json,
                "graph_summary_md": graph_summary_md,
            },
            "refresh_policy": refresh_policy,
            "context_pack_markdown": context_pack_markdown,
        }

    def graph_get_project_overview(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        top_limit: int = 8,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            require_graph_available()
            return graph_get_project_overview_query(project_id=project_id, top_limit=top_limit)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc

    def graph_get_neighbors(
        self,
        *,
        project_id: str,
        entity_type: str,
        entity_id: str,
        auth_token: str | None = None,
        rel_types: list[str] | None = None,
        depth: int = 1,
        limit: int = 50,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            require_graph_available()
            return graph_get_neighbors_query(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                rel_types=rel_types,
                depth=depth,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc

    def graph_find_related_resources(
        self,
        *,
        project_id: str,
        query: str,
        auth_token: str | None = None,
        limit: int = 20,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            require_graph_available()
            return graph_find_related_resources_query(project_id=project_id, query=query, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc

    def graph_get_dependency_path(
        self,
        *,
        project_id: str,
        from_entity_type: str,
        from_entity_id: str,
        to_entity_type: str,
        to_entity_id: str,
        auth_token: str | None = None,
        max_depth: int = 4,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            require_graph_available()
            return graph_get_dependency_path_query(
                project_id=project_id,
                from_entity_type=from_entity_type,
                from_entity_id=from_entity_id,
                to_entity_type=to_entity_type,
                to_entity_id=to_entity_id,
                max_depth=max_depth,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc

    def graph_context_pack(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        focus_entity_type: str | None = None,
        focus_entity_id: str | None = None,
        limit: int = 20,
    ) -> dict:
        self._require_token(auth_token)
        if bool(str(focus_entity_type or "").strip()) != bool(str(focus_entity_id or "").strip()):
            raise HTTPException(status_code=400, detail="focus_entity_type and focus_entity_id must be provided together")
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            require_graph_available()
            return graph_context_pack_query(
                project_id=project_id,
                focus_entity_type=focus_entity_type,
                focus_entity_id=focus_entity_id,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc

    def search_project_knowledge(
        self,
        *,
        project_id: str,
        query: str,
        auth_token: str | None = None,
        focus_entity_type: str | None = None,
        focus_entity_id: str | None = None,
        limit: int = 20,
    ) -> dict:
        self._require_token(auth_token)
        if bool(str(focus_entity_type or "").strip()) != bool(str(focus_entity_id or "").strip()):
            raise HTTPException(status_code=400, detail="focus_entity_type and focus_entity_id must be provided together")
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        try:
            return search_project_knowledge_query(
                project_id=project_id,
                query=query,
                focus_entity_type=focus_entity_type,
                focus_entity_id=focus_entity_id,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Project knowledge search failed: {exc}") from exc

    @staticmethod
    def _parse_json_list(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw or "[]")
            except Exception:
                return []
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        return []

    @staticmethod
    def _contains_commit_evidence(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        if _COMMIT_SHA_RE.search(normalized):
            return True
        indicators = ("commit", "changeset", "sha", "git rev", "hash")
        return any(token in normalized for token in indicators)

    @classmethod
    def _external_refs_have_commit_evidence(cls, refs: Any) -> bool:
        for item in cls._parse_json_list(refs):
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            lower_url = url.lower()
            if lower_url.startswith("http://") or lower_url.startswith("https://"):
                if "/commit/" in lower_url or "sha=" in lower_url:
                    return True
                if cls._contains_commit_evidence(f"{url} {title}"):
                    return True
        return False

    @staticmethod
    def _has_http_external_ref(refs: Any) -> bool:
        parsed = refs if isinstance(refs, list) else []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            if url.startswith("http://") or url.startswith("https://"):
                return True
        return False

    @staticmethod
    def _has_qa_artifact_text(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        keywords = (
            "test",
            "qa",
            "artifact",
            "report",
            "log",
            "trace",
            "playwright",
            "pytest",
            "coverage",
            "reproduc",
            "screenshot",
        )
        return any(token in normalized for token in keywords)

    @classmethod
    def _project_has_github_context(
        cls,
        *,
        project_description: str,
        project_external_refs: Any,
        project_rules: list[ProjectRuleModel],
    ) -> bool:
        if any(token in str(project_description or "").lower() for token in _GITHUB_HOST_TOKENS):
            return True
        for ref in cls._parse_json_list(project_external_refs):
            url = str(ref.get("url") or "").strip().lower()
            if any(token in url for token in _GITHUB_HOST_TOKENS):
                return True
        for rule in project_rules:
            blob = f"{rule.title or ''} {rule.body or ''}".lower()
            if "github.com" in blob or "github " in blob or blob.endswith("github"):
                return True
        return False

    def verify_team_mode_workflow(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        expected_event_storming_enabled: bool | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            if workspace_id and str(project.workspace_id) != str(workspace_id):
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            members = db.execute(
                select(ProjectMember, UserModel)
                .join(UserModel, UserModel.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
            ).all()
            member_role_by_user_id = {
                str(pm.user_id): str(pm.role or "").strip()
                for pm, _ in members
            }
            tasks_payload = list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=str(project.workspace_id),
                    project_id=project_id,
                    limit=500,
                    offset=0,
                    archived=False,
                ),
            )
        tasks = list(tasks_payload.get("items") or [])

        def _has_status_trigger(
            trigger: dict[str, Any],
            *,
            scope: str,
            to_status: str,
        ) -> bool:
            if str(trigger.get("kind") or "").strip() != "status_change":
                return False
            if str(trigger.get("scope") or "").strip() != scope:
                return False
            to_statuses = [str(item or "").strip() for item in (trigger.get("to_statuses") or [])]
            return to_status in to_statuses

        dev_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "DeveloperAgent"]
        qa_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "QAAgent"]
        lead_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "TeamLeadAgent"]
        deploy_tasks = [
            t
            for t in lead_tasks
            if "deploy" in str(t.get("title") or "").lower() or "docker compose" in str(t.get("title") or "").lower()
        ]

        dev_ids = {str(t.get("id")) for t in dev_tasks}
        qa_ids = {str(t.get("id")) for t in qa_tasks}
        lead_ids = {str(t.get("id")) for t in lead_tasks}

        dev_self_ok = bool(dev_tasks) and all(
            any(
                _has_status_trigger(trigger, scope="self", to_status="QA")
                for trigger in (task.get("execution_triggers") or [])
                if isinstance(trigger, dict)
            )
            for task in dev_tasks
        )

        qa_external_from_dev_ok = any(
            any(
                _has_status_trigger(trigger, scope="external", to_status="QA")
                and dev_ids.issubset(
                    {
                        str(task_id)
                        for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])
                    }
                )
                for trigger in (task.get("execution_triggers") or [])
                if isinstance(trigger, dict)
            )
            for task in qa_tasks
        )

        lead_external_from_qa_ok = any(
            any(
                _has_status_trigger(trigger, scope="external", to_status="Done")
                and bool(
                    qa_ids.intersection(
                        {
                            str(task_id)
                            for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])
                        }
                    )
                )
                for trigger in (task.get("execution_triggers") or [])
                if isinstance(trigger, dict)
            )
            for task in lead_tasks
        )

        deploy_external_from_lead_ok = any(
            any(
                _has_status_trigger(trigger, scope="external", to_status="Done")
                and bool(
                    lead_ids.intersection(
                        {
                            str(task_id)
                            for task_id in ((trigger.get("selector") or {}).get("task_ids") or [])
                        }
                    )
                )
                for trigger in (task.get("execution_triggers") or [])
                if isinstance(trigger, dict)
            )
            for task in deploy_tasks
        )

        lead_recurring_on_lead_ok = any(
            any(
                str(trigger.get("kind") or "").strip() == "schedule"
                and bool(str(trigger.get("recurring_rule") or "").strip())
                and "Lead" in [str(item or "").strip() for item in (trigger.get("run_on_statuses") or [])]
                for trigger in (task.get("execution_triggers") or [])
                if isinstance(trigger, dict)
            )
            for task in lead_tasks
        )

        role_coverage_ok = bool(dev_tasks) and bool(qa_tasks) and bool(lead_tasks)
        required_triggers_ok = (
            dev_self_ok
            and qa_external_from_dev_ok
            and lead_external_from_qa_ok
            and deploy_external_from_lead_ok
            and lead_recurring_on_lead_ok
        )
        event_storming_ok = (
            True
            if expected_event_storming_enabled is None
            else bool(getattr(project, "event_storming_enabled", True)) is bool(expected_event_storming_enabled)
        )
        return {
            "project_id": str(project_id),
            "workspace_id": str(project.workspace_id),
            "checks": {
                "role_coverage_present": role_coverage_ok,
                "dev_self_triggers_to_qa": dev_self_ok,
                "qa_external_trigger_from_dev": qa_external_from_dev_ok,
                "lead_external_trigger_from_qa": lead_external_from_qa_ok,
                "deploy_external_trigger_from_lead": deploy_external_from_lead_ok,
                "lead_recurring_schedule_on_lead": lead_recurring_on_lead_ok,
                "required_triggers_present": required_triggers_ok,
                "event_storming_matches_expectation": event_storming_ok,
            },
            "counts": {
                "tasks_total": len(tasks),
                "developer_tasks": len(dev_tasks),
                "qa_tasks": len(qa_tasks),
                "lead_tasks": len(lead_tasks),
                "deploy_tasks": len(deploy_tasks),
            },
            "event_storming_enabled": bool(getattr(project, "event_storming_enabled", True)),
            "expected_event_storming_enabled": expected_event_storming_enabled,
            "ok": bool(role_coverage_ok and required_triggers_ok and event_storming_ok),
        }

    def verify_delivery_workflow(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            if workspace_id and str(project.workspace_id) != str(workspace_id):
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            members = db.execute(
                select(ProjectMember, UserModel)
                .join(UserModel, UserModel.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
            ).all()
            member_role_by_user_id = {str(pm.user_id): str(pm.role or "").strip() for pm, _ in members}
            tasks_payload = list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=str(project.workspace_id),
                    project_id=project_id,
                    limit=500,
                    offset=0,
                    archived=False,
                ),
            )
            project_rules = db.execute(
                select(ProjectRuleModel).where(
                    ProjectRuleModel.project_id == project_id,
                    ProjectRuleModel.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            notes = db.execute(
                select(Note).where(
                    Note.project_id == project_id,
                    Note.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            comments = db.execute(
                select(TaskComment).join(Task, Task.id == TaskComment.task_id).where(
                    Task.project_id == project_id,
                    Task.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()

        tasks = list(tasks_payload.get("items") or [])
        role_dev_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "DeveloperAgent"]
        role_qa_tasks = [t for t in tasks if member_role_by_user_id.get(str(t.get("assignee_id") or "")) == "QAAgent"]
        dev_tasks = role_dev_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "Dev"]
        qa_tasks = role_qa_tasks or [t for t in tasks if str(t.get("status") or "").strip() == "QA"]

        notes_by_task: dict[str, list[Note]] = {}
        for note in notes:
            task_id = str(note.task_id or "").strip()
            if not task_id:
                continue
            notes_by_task.setdefault(task_id, []).append(note)
        comments_by_task: dict[str, list[TaskComment]] = {}
        for comment in comments:
            task_id = str(comment.task_id or "").strip()
            if not task_id:
                continue
            comments_by_task.setdefault(task_id, []).append(comment)

        def _task_has_commit_evidence(task: dict[str, Any]) -> bool:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                return False
            if self._external_refs_have_commit_evidence(task.get("external_refs")):
                return True
            for note in notes_by_task.get(task_id, []):
                if self._contains_commit_evidence(f"{note.title or ''}\n{note.body or ''}"):
                    return True
                if self._external_refs_have_commit_evidence(note.external_refs):
                    return True
            for comment in comments_by_task.get(task_id, []):
                if self._contains_commit_evidence(comment.body):
                    return True
            return False

        def _task_has_qa_artifacts(task: dict[str, Any]) -> bool:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                return False
            if self._has_http_external_ref(task.get("external_refs")):
                return True
            for note in notes_by_task.get(task_id, []):
                if self._has_qa_artifact_text(f"{note.title or ''}\n{note.body or ''}"):
                    return True
                if self._has_http_external_ref(self._parse_json_list(note.external_refs)):
                    return True
            for comment in comments_by_task.get(task_id, []):
                if self._has_qa_artifact_text(comment.body):
                    return True
            return False

        dev_missing = [
            {
                "task_id": str(task.get("id") or "").strip(),
                "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip(),
            }
            for task in dev_tasks
            if not _task_has_commit_evidence(task)
        ]
        qa_missing = [
            {
                "task_id": str(task.get("id") or "").strip(),
                "title": str(task.get("title") or "").strip() or str(task.get("id") or "").strip(),
            }
            for task in qa_tasks
            if not _task_has_qa_artifacts(task)
        ]

        repo_context_present = self._project_has_github_context(
            project_description=str(getattr(project, "description", "") or ""),
            project_external_refs=getattr(project, "external_refs", "[]"),
            project_rules=project_rules,
        )
        dev_commit_evidence_ok = bool(dev_tasks) and not dev_missing
        qa_artifacts_ok = bool(qa_tasks) and not qa_missing
        git_contract_ok = bool(repo_context_present and dev_commit_evidence_ok)

        return {
            "project_id": str(project_id),
            "workspace_id": str(project.workspace_id),
            "checks": {
                "repo_context_present": repo_context_present,
                "git_contract_ok": git_contract_ok,
                "dev_tasks_have_commit_evidence": dev_commit_evidence_ok,
                "qa_has_verifiable_artifacts": qa_artifacts_ok,
            },
            "counts": {
                "tasks_total": len(tasks),
                "developer_tasks": len(dev_tasks),
                "qa_tasks": len(qa_tasks),
                "dev_missing_commit_evidence": len(dev_missing),
                "qa_missing_artifacts": len(qa_missing),
            },
            "missing": {
                "dev_tasks_missing_commit_evidence": dev_missing,
                "qa_tasks_missing_artifacts": qa_missing,
            },
            "ok": bool(git_contract_ok and dev_commit_evidence_ok and qa_artifacts_ok),
        }

    def ensure_team_mode_project(
        self,
        *,
        project_id: str | None = None,
        project_ref: str | None = None,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        expected_event_storming_enabled: bool | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        resolved_ref = str(project_id or project_ref or "").strip()
        if not resolved_ref:
            raise HTTPException(status_code=400, detail="project_id or project_ref is required")
        with SessionLocal() as db:
            project, _ = self._resolve_project_for_chat_context(
                db=db,
                user=user,
                project_ref=resolved_ref,
                workspace_id=workspace_id,
            )
            resolved_project_id = str(project.id)
            resolved_workspace_id = str(project.workspace_id)
            if workspace_id and resolved_workspace_id != str(workspace_id):
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member"})
            ensure_project_access(db, project.workspace_id, str(project.id), user.id, {"Owner", "Admin", "Member"})
            project_rules = db.execute(
                select(ProjectRuleModel).where(
                    ProjectRuleModel.project_id == str(project.id),
                    ProjectRuleModel.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            has_github_context = self._project_has_github_context(
                project_description=str(getattr(project, "description", "") or ""),
                project_external_refs=getattr(project, "external_refs", "[]"),
                project_rules=project_rules,
            )

            def _workspace_skill_or_404(skill_key: str, *, required: bool) -> WorkspaceSkill | None:
                ws = db.execute(
                    select(WorkspaceSkill).where(
                        WorkspaceSkill.workspace_id == str(project.workspace_id),
                        WorkspaceSkill.skill_key == skill_key,
                        WorkspaceSkill.is_deleted == False,  # noqa: E712
                    )
                ).scalar_one_or_none()
                if required and ws is None:
                    raise HTTPException(status_code=404, detail=f"Workspace skill not found: {skill_key}")
                return ws

            def _ensure_project_skill(ws_skill: WorkspaceSkill, *, attach_prefix: str, apply_prefix: str) -> tuple[ProjectSkill, bool, dict]:
                project_skill = db.execute(
                    select(ProjectSkill).where(
                        ProjectSkill.workspace_id == str(project.workspace_id),
                        ProjectSkill.project_id == str(project.id),
                        ProjectSkill.skill_key == str(ws_skill.skill_key),
                        ProjectSkill.is_deleted == False,  # noqa: E712
                    )
                ).scalar_one_or_none()
                attached_local = False
                if project_skill is None:
                    attach_command_id = command_id or self._fallback_command_id(
                        prefix=attach_prefix,
                        payload={
                        "workspace_id": str(project.workspace_id),
                        "project_ref": str(project.id),
                        "workspace_skill_id": str(ws_skill.id),
                        "skill_key": str(ws_skill.skill_key),
                        },
                    )
                    attached_view = ProjectSkillApplicationService(
                        db,
                        user,
                        command_id=attach_command_id,
                    ).attach_workspace_skill_to_project(
                        workspace_skill_id=str(ws_skill.id),
                        workspace_id=str(project.workspace_id),
                        project_id=str(project.id),
                    )
                    attached_local = True
                    attached_skill_id = str(attached_view.get("id") or "").strip()
                    project_skill = db.get(ProjectSkill, attached_skill_id) if attached_skill_id else None
                if project_skill is None:
                    raise HTTPException(status_code=500, detail=f"Failed to attach skill: {ws_skill.skill_key}")
                apply_command_id = command_id or self._fallback_command_id(
                    prefix=apply_prefix,
                    payload={"project_ref": str(project.id), "project_skill_id": str(project_skill.id)},
                )
                applied_view_local = ProjectSkillApplicationService(
                    db,
                    user,
                    command_id=apply_command_id,
                ).apply_project_skill(str(project_skill.id))
                return project_skill, attached_local, applied_view_local

            team_ws = _workspace_skill_or_404("team_mode", required=True)
            git_ws = _workspace_skill_or_404("git_delivery", required=True)
            github_ws = _workspace_skill_or_404("github_delivery", required=False)
            if team_ws is None or git_ws is None:
                raise HTTPException(status_code=500, detail="Required skills failed to resolve")

            _, team_attached, team_applied_view = _ensure_project_skill(
                team_ws,
                attach_prefix="mcp-ensure-team-mode-attach",
                apply_prefix="mcp-ensure-team-mode-apply",
            )
            git_project_skill, git_attached, git_applied_view = _ensure_project_skill(
                git_ws,
                attach_prefix="mcp-ensure-git-delivery-attach",
                apply_prefix="mcp-ensure-git-delivery-apply",
            )

            github_attached = False
            github_applied_view: dict[str, Any] | None = None
            github_project_skill: ProjectSkill | None = None
            if has_github_context and github_ws is not None:
                github_project_skill, github_attached, github_applied_view = _ensure_project_skill(
                    github_ws,
                    attach_prefix="mcp-ensure-github-delivery-attach",
                    apply_prefix="mcp-ensure-github-delivery-apply",
                )

        verification = self.verify_team_mode_workflow(
            project_id=resolved_project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
            expected_event_storming_enabled=expected_event_storming_enabled,
        )
        delivery_verification = self.verify_delivery_workflow(
            project_id=resolved_project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        members = self.list_project_members(
            workspace_id=workspace_id or verification["workspace_id"],
            project_id=resolved_project_id,
            auth_token=auth_token,
            limit=200,
            offset=0,
        )
        return {
            "project_id": resolved_project_id,
            "workspace_id": verification["workspace_id"],
            "attached": bool(team_attached or git_attached or github_attached),
            "project_skill_id": str(team_applied_view.get("id") or "").strip(),
            "generated_rule_id": str(team_applied_view.get("generated_rule_id") or "").strip() or None,
            "team_mode_contract_complete": bool(team_applied_view.get("team_mode_contract_complete")),
            "team_mode_roster": list(team_applied_view.get("team_mode_roster") or []),
            "git_delivery": {
                "project_skill_id": str(git_project_skill.id),
                "attached": git_attached,
                "applied": bool(git_applied_view),
                "generated_rule_id": str(git_applied_view.get("generated_rule_id") or "").strip() or None,
            },
            "github_delivery": {
                "eligible": bool(has_github_context and github_ws is not None),
                "project_skill_id": str(github_project_skill.id) if github_project_skill is not None else None,
                "attached": github_attached,
                "applied": bool(github_applied_view) if github_applied_view is not None else False,
                "generated_rule_id": (
                    str(github_applied_view.get("generated_rule_id") or "").strip() or None
                    if github_applied_view is not None
                    else None
                ),
            },
            "members": members,
            "verification": verification,
            "delivery_verification": delivery_verification,
            "ok": bool(verification.get("ok"))
            and bool(team_applied_view.get("team_mode_contract_complete"))
            and bool(delivery_verification.get("ok")),
        }

    def list_project_templates(
        self,
        *,
        auth_token: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            return ProjectTemplateApplicationService(db, user).list_templates()

    def get_project_template(
        self,
        *,
        template_key: str,
        auth_token: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            return ProjectTemplateApplicationService(db, user).get_template(template_key)

    def preview_project_from_template(
        self,
        *,
        template_key: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        name: str = "",
        description: str = "",
        custom_statuses: list[str] | None = None,
        member_user_ids: list[str] | None = None,
        embedding_enabled: bool | None = None,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str | None = None,
        chat_attachment_ingestion_mode: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            payload = ProjectFromTemplatePreview(
                workspace_id=resolved_workspace_id,
                template_key=template_key,
                name=name,
                description=description,
                custom_statuses=custom_statuses,
                member_user_ids=member_user_ids or [],
                embedding_enabled=embedding_enabled,
                embedding_model=embedding_model,
                context_pack_evidence_top_k=context_pack_evidence_top_k,
                chat_index_mode=chat_index_mode,
                chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
                parameters=parameters or {},
            )
            return ProjectTemplateApplicationService(db, user).preview_project_from_template(payload)

    def create_project_from_template(
        self,
        *,
        template_key: str,
        name: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        description: str = "",
        custom_statuses: list[str] | None = None,
        member_user_ids: list[str] | None = None,
        embedding_enabled: bool | None = None,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str | None = None,
        chat_attachment_ingestion_mode: str | None = None,
        parameters: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            effective_command_id = command_id or self._fallback_project_template_create_command_id(
                workspace_id=resolved_workspace_id,
                template_key=template_key,
                name=name,
            )
            payload = ProjectFromTemplateCreate(
                workspace_id=resolved_workspace_id,
                template_key=template_key,
                name=name,
                description=description,
                custom_statuses=custom_statuses,
                member_user_ids=member_user_ids or [],
                embedding_enabled=embedding_enabled,
                embedding_model=embedding_model,
                context_pack_evidence_top_k=context_pack_evidence_top_k,
                chat_index_mode=chat_index_mode,
                chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
                parameters=parameters or {},
            )
            return ProjectTemplateApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).create_project_from_template(payload)

    def create_task(
        self,
        *,
        workspace_id: str | None = None,
        title: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        description: str = "",
        status: str | None = None,
        priority: str = "Med",
        due_date: str | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        instruction: str | None = None,
        execution_triggers: Any | None = None,
        recurring_rule: str | None = None,
        specification_id: str | None = None,
        task_group_id: str | None = None,
        task_type: str | None = None,
        scheduled_instruction: str | None = None,
        scheduled_at_utc: str | None = None,
        schedule_timezone: str | None = None,
        assignee_id: str | None = None,
        labels: Any | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        normalized_execution_triggers = self._normalize_execution_triggers_input(execution_triggers)
        normalized_labels = self._normalize_string_list_input(labels, field_name="labels")
        normalized_task_type = str(task_type or "").strip() or None
        normalized_recurring_rule = str(recurring_rule or "").strip() or None
        if (
            normalized_task_type is None
            and normalized_recurring_rule
            and scheduled_at_utc is not None
        ):
            normalized_task_type = "scheduled_instruction"
            if scheduled_instruction is None and instruction is not None:
                scheduled_instruction = instruction
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_create(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if task_group_id:
                group_state = self._assert_task_group_allowed(db=db, task_group_id=task_group_id)
                assert group_state is not None
                if group_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="task_group_id does not belong to workspace_id")
                if group_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="task_group_id does not belong to project_id")
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-create",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "task_group_id": task_group_id,
                    "title": title,
                    "description": description,
                    "status": status,
                    "priority": priority,
                    "due_date": due_date,
                    "external_refs": external_refs or [],
                    "attachment_refs": attachment_refs or [],
                    "instruction": instruction,
                    "execution_triggers": normalized_execution_triggers or [],
                    "recurring_rule": normalized_recurring_rule,
                    "specification_id": specification_id,
                    "task_type": normalized_task_type,
                    "scheduled_instruction": scheduled_instruction,
                    "scheduled_at_utc": scheduled_at_utc,
                    "schedule_timezone": schedule_timezone,
                    "assignee_id": assignee_id,
                    "labels": normalized_labels or [],
                },
            )
            payload_kwargs: dict[str, Any] = {
                "workspace_id": resolved_workspace_id,
                "project_id": resolved_project_id,
                "task_group_id": task_group_id,
                "title": title,
                "description": description,
                "status": status,
                "priority": priority,
                "due_date": due_date,
                "external_refs": external_refs or [],
                "attachment_refs": attachment_refs or [],
                "specification_id": specification_id,
                "assignee_id": assignee_id,
                "labels": normalized_labels or [],
            }
            if instruction is not None:
                payload_kwargs["instruction"] = instruction
            if normalized_execution_triggers is not None:
                payload_kwargs["execution_triggers"] = normalized_execution_triggers
            if normalized_recurring_rule is not None:
                payload_kwargs["recurring_rule"] = normalized_recurring_rule
            if normalized_task_type is not None:
                payload_kwargs["task_type"] = normalized_task_type
            if scheduled_instruction is not None:
                payload_kwargs["scheduled_instruction"] = scheduled_instruction
            if scheduled_at_utc is not None:
                payload_kwargs["scheduled_at_utc"] = scheduled_at_utc
            if schedule_timezone is not None:
                payload_kwargs["schedule_timezone"] = schedule_timezone
            payload = TaskCreate(**payload_kwargs)
            return TaskApplicationService(db, user, command_id=effective_command_id).create_task(payload)

    def create_note(
        self,
        *,
        title: str,
        body: str = "",
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        note_group_id: str | None = None,
        task_id: str | None = None,
        specification_id: str | None = None,
        tags: list[str] | str | None = None,
        pinned: bool = False,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        force_new: bool = False,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        normalized_tags = self._normalize_string_list_input(tags, field_name="tags")
        with SessionLocal() as db:
            ws_id, proj_id, resolved_task_id = self._resolve_workspace_for_note_create(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
            )
            if note_group_id:
                group_state = self._assert_note_group_allowed(db=db, note_group_id=note_group_id)
                assert group_state is not None
                if group_state.workspace_id != ws_id:
                    raise HTTPException(status_code=400, detail="note_group_id does not belong to workspace_id")
                if group_state.project_id != proj_id:
                    raise HTTPException(status_code=400, detail="note_group_id does not belong to project_id")
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-create",
                payload={
                    "workspace_id": ws_id,
                    "project_id": proj_id,
                    "note_group_id": note_group_id,
                    "task_id": resolved_task_id,
                    "specification_id": specification_id,
                    "title": title,
                    "body": body or "",
                    "tags": normalized_tags or [],
                    "pinned": bool(pinned),
                    "external_refs": external_refs or [],
                    "attachment_refs": attachment_refs or [],
                    "force_new": bool(force_new),
                },
            )
            payload = NoteCreate(
                workspace_id=ws_id,
                project_id=proj_id,
                note_group_id=note_group_id,
                task_id=resolved_task_id,
                specification_id=specification_id,
                title=title,
                body=body or "",
                tags=normalized_tags or [],
                pinned=bool(pinned),
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
                force_new=bool(force_new),
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).create_note(payload)

    def create_task_group(
        self,
        *,
        name: str,
        project_id: str,
        workspace_id: str | None = None,
        description: str = "",
        color: str | None = None,
        auth_token: str | None = None,
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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-group-create",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "name_key": str(name or "").strip().casefold(),
                    "description": description,
                    "color": color,
                },
            )
            payload = TaskGroupCreate(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                name=name,
                description=description,
                color=color,
            )
            return TaskGroupApplicationService(db, user, command_id=effective_command_id).create_task_group(payload)

    def update_task_group(self, *, group_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_task_group_allowed(db=db, task_group_id=group_id)
            assert state is not None
            payload = TaskGroupPatch(**patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-group-patch",
                payload={"group_id": group_id, "patch": patch or {}},
            )
            return TaskGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).patch_task_group(group_id, payload)

    def delete_task_group(self, *, group_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_task_group_allowed(db=db, task_group_id=group_id)
            assert state is not None
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-group-delete",
                payload={"group_id": group_id},
            )
            return TaskGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).delete_task_group(group_id)

    def reorder_task_groups(
        self,
        *,
        ordered_ids: list[str],
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
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
            for group_id in ordered_ids:
                group_state = self._assert_task_group_allowed(db=db, task_group_id=group_id)
                assert group_state is not None
                if group_state.workspace_id != resolved_workspace_id or group_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="ordered_ids includes task group outside project scope")
            payload = ReorderPayload(ordered_ids=ordered_ids)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-group-reorder",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "ordered_ids": ordered_ids,
                },
            )
            return TaskGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).reorder_task_groups(resolved_workspace_id, resolved_project_id, payload)

    def create_note_group(
        self,
        *,
        name: str,
        project_id: str,
        workspace_id: str | None = None,
        description: str = "",
        color: str | None = None,
        auth_token: str | None = None,
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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-group-create",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "name_key": str(name or "").strip().casefold(),
                    "description": description,
                    "color": color,
                },
            )
            payload = NoteGroupCreate(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                name=name,
                description=description,
                color=color,
            )
            return NoteGroupApplicationService(db, user, command_id=effective_command_id).create_note_group(payload)

    def update_note_group(self, *, group_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_note_group_allowed(db=db, note_group_id=group_id)
            assert state is not None
            payload = NoteGroupPatch(**patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-group-patch",
                payload={"group_id": group_id, "patch": patch or {}},
            )
            return NoteGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).patch_note_group(group_id, payload)

    def delete_note_group(self, *, group_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_note_group_allowed(db=db, note_group_id=group_id)
            assert state is not None
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-group-delete",
                payload={"group_id": group_id},
            )
            return NoteGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).delete_note_group(group_id)

    def reorder_note_groups(
        self,
        *,
        ordered_ids: list[str],
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
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
            for group_id in ordered_ids:
                group_state = self._assert_note_group_allowed(db=db, note_group_id=group_id)
                assert group_state is not None
                if group_state.workspace_id != resolved_workspace_id or group_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="ordered_ids includes note group outside project scope")
            payload = ReorderPayload(ordered_ids=ordered_ids)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-group-reorder",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "ordered_ids": ordered_ids,
                },
            )
            return NoteGroupApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).reorder_note_groups(resolved_workspace_id, resolved_project_id, payload)

    def create_project(
        self,
        *,
        name: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        description: str = "",
        custom_statuses: list[str] | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        embedding_enabled: bool = False,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str = "OFF",
        chat_attachment_ingestion_mode: str = "METADATA_ONLY",
        event_storming_enabled: bool = True,
        member_user_ids: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            effective_command_id = command_id or self._fallback_project_create_command_id(
                workspace_id=resolved_workspace_id,
                name=name,
            )
            payload = ProjectCreate(
                workspace_id=resolved_workspace_id,
                name=name,
                description=description,
                custom_statuses=custom_statuses,
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
                embedding_enabled=bool(embedding_enabled),
                embedding_model=embedding_model,
                context_pack_evidence_top_k=context_pack_evidence_top_k,
                chat_index_mode=chat_index_mode,
                chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
                event_storming_enabled=bool(event_storming_enabled),
                member_user_ids=member_user_ids or [],
            )
            return ProjectApplicationService(db, user, command_id=effective_command_id).create_project(payload)

    def update_project(
        self,
        *,
        project_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        patch_payload = dict(patch or {})
        if not patch_payload:
            raise HTTPException(status_code=400, detail="patch must include at least one field")
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, user.id, {"Owner", "Admin", "Member"})
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-patch",
                payload={"project_id": project_id, "patch": patch_payload},
            )
            payload = ProjectPatch(**patch_payload)
            return ProjectApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).patch_project(project_id, payload)

    def create_project_rule(
        self,
        *,
        title: str,
        project_id: str,
        workspace_id: str | None = None,
        body: str = "",
        auth_token: str | None = None,
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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-rule-create",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "title": title,
                    "body": body or "",
                },
            )
            payload = ProjectRuleCreate(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                title=title,
                body=body or "",
            )
            return ProjectRuleApplicationService(
                db, user, command_id=effective_command_id
            ).create_project_rule(payload)

    def import_project_skill(
        self,
        *,
        workspace_id: str,
        project_id: str,
        source_url: str,
        auth_token: str | None = None,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-import",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "source_url": source_url,
                    "name": name or "",
                    "skill_key": skill_key or "",
                    "mode": mode,
                    "trust_level": trust_level,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).import_skill_from_url(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                source_url=source_url,
                name=name,
                skill_key=skill_key,
                mode=mode,
                trust_level=trust_level,
            )

    def import_project_skill_file(
        self,
        *,
        workspace_id: str,
        project_id: str,
        file_name: str,
        file_content: bytes,
        file_content_type: str = "",
        auth_token: str | None = None,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        content_sha256 = hashlib.sha256(file_content).hexdigest() if file_content else ""
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_create(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-import-file",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "file_name": file_name,
                    "file_content_type": file_content_type or "",
                    "file_content_sha256": content_sha256,
                    "name": name or "",
                    "skill_key": skill_key or "",
                    "mode": mode,
                    "trust_level": trust_level,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).import_skill_from_file(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                file_name=file_name,
                file_content=file_content,
                file_content_type=file_content_type,
                name=name,
                skill_key=skill_key,
                mode=mode,
                trust_level=trust_level,
            )

    def apply_project_skill(
        self,
        *,
        skill_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_project_skill_allowed(db=db, skill_id=skill_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-apply",
                payload={"skill_id": skill_id},
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).apply_project_skill(skill_id)

    def import_workspace_skill(
        self,
        *,
        workspace_id: str,
        source_url: str,
        auth_token: str | None = None,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin"})
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-import",
                payload={
                    "workspace_id": workspace_id,
                    "source_url": source_url,
                    "name": name or "",
                    "skill_key": skill_key or "",
                    "mode": mode,
                    "trust_level": trust_level,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).import_workspace_skill_from_url(
                workspace_id=workspace_id,
                source_url=source_url,
                name=name,
                skill_key=skill_key,
                mode=mode,
                trust_level=trust_level,
            )

    def import_workspace_skill_file(
        self,
        *,
        workspace_id: str,
        file_name: str,
        file_content: bytes,
        file_content_type: str = "",
        auth_token: str | None = None,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        user = self._resolve_actor_user()
        content_sha256 = hashlib.sha256(file_content).hexdigest() if file_content else ""
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin"})
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-import-file",
                payload={
                    "workspace_id": workspace_id,
                    "file_name": file_name,
                    "file_content_type": file_content_type or "",
                    "file_content_sha256": content_sha256,
                    "name": name or "",
                    "skill_key": skill_key or "",
                    "mode": mode,
                    "trust_level": trust_level,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).import_workspace_skill_from_file(
                workspace_id=workspace_id,
                file_name=file_name,
                file_content=file_content,
                file_content_type=file_content_type,
                name=name,
                skill_key=skill_key,
                mode=mode,
                trust_level=trust_level,
            )

    def update_workspace_skill(
        self,
        *,
        skill_id: str,
        patch: dict,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = self._assert_workspace_skill_allowed(db=db, skill_id=skill_id)
            assert state is not None
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-patch",
                payload={"skill_id": skill_id, "patch": patch or {}},
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).patch_workspace_skill(
                skill_id,
                patch or {},
            )

    def delete_workspace_skill(
        self,
        *,
        skill_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_workspace_skill_allowed(db=db, skill_id=skill_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-delete",
                payload={"skill_id": skill_id},
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).delete_workspace_skill(skill_id)

    def attach_workspace_skill_to_project(
        self,
        *,
        workspace_skill_id: str,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_workspace_skill_allowed(db=db, skill_id=workspace_skill_id)
            self._resolve_workspace_for_create(db=db, explicit_workspace_id=workspace_id, project_id=project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-attach",
                payload={
                    "workspace_skill_id": workspace_skill_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).attach_workspace_skill_to_project(
                workspace_skill_id=workspace_skill_id,
                workspace_id=workspace_id,
                project_id=project_id,
            )

    def create_specification(
        self,
        *,
        title: str,
        project_id: str,
        workspace_id: str | None = None,
        body: str = "",
        status: str = "Draft",
        tags: list[str] | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        force_new: bool = False,
        auth_token: str | None = None,
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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-specification-create",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "title": title,
                    "body": body or "",
                    "status": status,
                    "tags": tags or [],
                    "external_refs": external_refs or [],
                    "attachment_refs": attachment_refs or [],
                    "force_new": bool(force_new),
                },
            )
            payload = SpecificationCreate(
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                title=title,
                body=body or "",
                status=status,
                tags=tags or [],
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
                force_new=bool(force_new),
            )
            return SpecificationApplicationService(
                db, user, command_id=effective_command_id
            ).create_specification(payload)

    def create_tasks_from_spec(
        self,
        *,
        specification_id: str,
        titles: list[str],
        auth_token: str | None = None,
        description: str = "",
        priority: str = "Med",
        due_date: str | None = None,
        assignee_id: str | None = None,
        labels: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-spec-tasks-bulk-create",
                payload={
                    "specification_id": specification_id,
                    "titles": titles,
                    "description": description,
                    "priority": priority,
                    "due_date": due_date,
                    "assignee_id": assignee_id,
                    "labels": labels or [],
                },
            )
            return SpecificationApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).create_tasks_from_specification(
                specification_id,
                titles=titles,
                description=description,
                priority=priority,
                due_date=due_date,
                assignee_id=assignee_id,
                labels=labels or [],
            )

    def link_task_to_spec(
        self,
        *,
        specification_id: str,
        task_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-spec-task-link",
                payload={"specification_id": specification_id, "task_id": task_id},
            )
            return SpecificationApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).link_task_to_specification(specification_id, task_id)

    def unlink_task_from_spec(
        self,
        *,
        specification_id: str,
        task_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-spec-task-unlink",
                payload={"specification_id": specification_id, "task_id": task_id},
            )
            return SpecificationApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).unlink_task_from_specification(specification_id, task_id)

    def link_note_to_spec(
        self,
        *,
        specification_id: str,
        note_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-spec-note-link",
                payload={"specification_id": specification_id, "note_id": note_id},
            )
            return SpecificationApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).link_note_to_specification(specification_id, note_id)

    def unlink_note_from_spec(
        self,
        *,
        specification_id: str,
        note_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-spec-note-unlink",
                payload={"specification_id": specification_id, "note_id": note_id},
            )
            return SpecificationApplicationService(
                db,
                user,
                command_id=effective_command_id,
            ).unlink_note_from_specification(specification_id, note_id)

    def update_project_rule(self, *, rule_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_project_rule_allowed(db=db, rule_id=rule_id)
            payload = ProjectRulePatch(**patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-rule-patch",
                payload={"rule_id": rule_id, "patch": patch or {}},
            )
            return ProjectRuleApplicationService(
                db, user, command_id=effective_command_id
            ).patch_project_rule(rule_id, payload)

    def delete_project_rule(self, *, rule_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_project_rule_allowed(db=db, rule_id=rule_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-rule-delete",
                payload={"rule_id": rule_id},
            )
            return ProjectRuleApplicationService(
                db, user, command_id=effective_command_id
            ).delete_project_rule(rule_id)

    def update_project_skill(
        self,
        *,
        skill_id: str,
        patch: dict,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_project_skill_allowed(db=db, skill_id=skill_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-patch",
                payload={
                    "skill_id": skill_id,
                    "patch": patch or {},
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).patch_project_skill(skill_id, patch or {})

    def delete_project_skill(
        self,
        *,
        skill_id: str,
        delete_linked_rule: bool = True,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_project_skill_allowed(db=db, skill_id=skill_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-delete",
                payload={
                    "skill_id": skill_id,
                    "delete_linked_rule": bool(delete_linked_rule),
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).delete_project_skill(
                skill_id,
                delete_linked_rule=bool(delete_linked_rule),
            )

    def update_specification(
        self, *, specification_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            payload = SpecificationPatch(**patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-specification-patch",
                payload={"specification_id": specification_id, "patch": patch or {}},
            )
            return SpecificationApplicationService(
                db, user, command_id=effective_command_id
            ).patch_specification(specification_id, payload)

    def archive_specification(
        self, *, specification_id: str, auth_token: str | None = None, command_id: str | None = None
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-specification-archive",
                payload={"specification_id": specification_id},
            )
            return SpecificationApplicationService(
                db, user, command_id=effective_command_id
            ).archive_specification(specification_id)

    def restore_specification(
        self, *, specification_id: str, auth_token: str | None = None, command_id: str | None = None
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-specification-restore",
                payload={"specification_id": specification_id},
            )
            return SpecificationApplicationService(
                db, user, command_id=effective_command_id
            ).restore_specification(specification_id)

    def delete_specification(
        self, *, specification_id: str, auth_token: str | None = None, command_id: str | None = None
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_specification_allowed(db=db, specification_id=specification_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-specification-delete",
                payload={"specification_id": specification_id},
            )
            return SpecificationApplicationService(
                db, user, command_id=effective_command_id
            ).delete_specification(specification_id)

    def update_note(self, *, note_id: str, patch: dict, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            payload = NotePatch(**patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-patch",
                payload={"note_id": note_id, "patch": patch or {}},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).patch_note(note_id, payload)

    def archive_note(self, *, note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-archive",
                payload={"note_id": note_id},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).archive_note(note_id)

    def restore_note(self, *, note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-restore",
                payload={"note_id": note_id},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).restore_note(note_id)

    def pin_note(self, *, note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-pin",
                payload={"note_id": note_id},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).pin_note(note_id)

    def unpin_note(self, *, note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-unpin",
                payload={"note_id": note_id},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).unpin_note(note_id)

    def delete_note(self, *, note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_note_command_state(db, note_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Note not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-note-delete",
                payload={"note_id": note_id},
            )
            return NoteApplicationService(db, user, command_id=effective_command_id).delete_note(note_id)

    def update_task(self, *, task_id: str, patch: Any, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            normalized_patch = self._normalize_task_patch_input(patch)
            payload = TaskPatch(**normalized_patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-patch",
                payload={"task_id": task_id, "patch": normalized_patch},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).patch_task(task_id, payload)

    def complete_task(self, *, task_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            state = load_task_command_state(db, task_id)
            if not state or state.is_deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            self._assert_workspace_allowed(state.workspace_id)
            self._assert_project_allowed(state.project_id)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-complete",
                payload={"task_id": task_id},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).complete_task(task_id)

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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-comment",
                payload={"task_id": task_id, "body": body},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).add_comment(task_id, payload)

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
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-run",
                payload={"task_id": task_id, "instruction": instruction},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).request_automation_run(task_id, payload)

    def bulk_task_action(
        self,
        *,
        task_ids: list[str],
        action: str,
        payload: dict | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        payload = payload or {}
        cleaned: list[str] = []
        with SessionLocal() as db:
            for task_id in task_ids:
                try:
                    state = load_task_command_state(db, task_id)
                except Exception:
                    state = None
                if not state or state.is_deleted:
                    continue
                self._assert_workspace_allowed(state.workspace_id)
                self._assert_project_allowed(state.project_id)
                cleaned.append(task_id)
            if not cleaned:
                return {"updated": 0}
            bulk = BulkAction(task_ids=cleaned, action=str(action), payload=payload)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-bulk",
                payload={"task_ids": cleaned, "action": str(action), "payload": payload},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).bulk_action(bulk)

    def archive_all_tasks(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member"})
            page = list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    archived=False,
                    limit=min(int(limit or 200), 200),
                    offset=0,
                ),
            )
            ids = [t["id"] for t in (page.get("items") or []) if t.get("id")]
            if not ids:
                return {"updated": 0}
            bulk = BulkAction(task_ids=ids, action="archive", payload={})
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-archive-all",
                payload={
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "q": q,
                    "ids": ids,
                },
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).bulk_action(bulk)

    def archive_all_notes(
        self,
        *,
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_workspace_allowed(workspace_id)
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        updated = 0
        with SessionLocal() as db:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member"})
            page = list_notes_read_model(
                db,
                user,
                NoteListQuery(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    q=q,
                    archived=False,
                    limit=min(int(limit or 200), 200),
                    offset=0,
                ),
            )
            ids = [n["id"] for n in (page.get("items") or []) if n.get("id")]
            batch_command_id = command_id or self._fallback_command_id(
                prefix="mcp-archive-notes",
                payload={
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "q": q,
                    "ids": ids,
                },
            )
            for note_id in ids:
                # Re-validate scope per note to be safe.
                state = load_note_command_state(db, note_id)
                if not state or state.is_deleted or state.archived:
                    continue
                self._assert_workspace_allowed(state.workspace_id)
                self._assert_project_allowed(state.project_id)
                note_command_id = self._derive_child_command_id(batch_command_id, note_id)
                NoteApplicationService(db, user, command_id=note_command_id).archive_note(note_id)
                updated += 1
            return {"updated": updated}
