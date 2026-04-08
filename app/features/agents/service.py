from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from features.projects.application import ProjectApplicationService
from features.project_starters.application import ProjectStarterApplicationService
from features.project_starters.catalog import get_project_starter, list_project_facets, list_project_starters, normalize_starter_key
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
from shared.chat_indexing import CHAT_INDEX_MODE_KG_AND_VECTOR
from shared.classification_cache import ClassificationCache, build_classification_cache_key
from shared.command_ids import derive_child_command_id
from shared.theme import DEFAULT_THEME, VALID_THEMES, normalize_theme, toggle_theme
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
    append_event,
    ensure_project_access,
    load_note_command_state,
    load_note_group_command_state,
    load_note_view,
    load_project_view,
    load_task_command_state,
    load_task_group_command_state,
    load_task_view,
    serialize_notification,
)
from shared.core import load_project_rule_command_state, load_project_rule_view
from shared.core import (
    SpecificationCreate,
    SpecificationPatch,
    load_specification_command_state,
    load_specification_view,
)
from features.agents.agent_mcp_adapter import run_structured_agent_prompt
from features.agents.command_runtime_registry import resolve_provider_for_command_id, resolve_provider_for_workspace_id
from features.agents.execution_provider import parse_execution_model
from features.agents.intent_classifier import (
    AUTOMATION_REQUEST_INTENT_FIELDS,
    classify_instruction_intent,
    resolve_instruction_intent,
)
from features.agents.provider_auth import resolve_provider_effective_auth_source
from features.agents.gates import (
    DEFAULT_REQUIRED_DELIVERY_CHECKS,
    DELIVERY_CORE_CHECK_DESCRIPTIONS,
    DELIVERY_CORE_CHECK_IDS,
    DELIVERY_CORE_CHECK_SET,
    DELIVERY_CHECK_DESCRIPTIONS,
    evaluate_delivery_checks,
    evaluate_required_checks as evaluate_required_policy_checks,
    filter_plugin_policy_scopes,
    merge_plugin_policy_dict,
    run_runtime_deploy_health_check,
)
from plugins import context_policy as plugin_context_policy
from plugins import service_policy as plugin_service_policy
from plugins.runner_policy import is_lead_role
from plugins.team_mode.gates import (
    DEFAULT_REQUIRED_TEAM_MODE_CHECKS,
    TEAM_MODE_CHECK_DESCRIPTIONS,
    TEAM_MODE_CORE_CHECK_DESCRIPTIONS,
    TEAM_MODE_CORE_CHECK_IDS,
    TEAM_MODE_CORE_CHECK_SET,
)
from plugins.team_mode.runtime_context import TeamModeProjectRuntimeContext
from plugins.team_mode.task_roles import TEAM_MODE_ROLES
from plugins.team_mode.semantics import (
    DEFAULT_ASSIGNMENT_POLICY,
    REQUIRED_SEMANTIC_STATUSES,
    RESERVED_LIFECYCLE_LABELS,
    canonicalize_semantic_status_label,
    compile_team_mode_policy,
    default_team_mode_config,
    normalize_review_policy,
    normalize_status_semantics,
    semantic_status_key,
)
from shared.deps import ensure_role
from shared.project_repository import (
    ensure_project_repository_initialized,
    resolve_project_repository_path,
)
from shared.settings import agent_system_username_for_provider
from shared.settings import agent_system_user_id_for_provider
from shared.task_relationships import normalize_task_relationships
from shared.task_delivery import normalize_delivery_mode
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

run_structured_codex_prompt = run_structured_agent_prompt
from shared.models import (
    Notification,
    Note,
    ProjectMember,
    ProjectPluginConfig,
    ProjectRule as ProjectRuleModel,
    ProjectSkill,
    Task,
    TaskComment,
    WorkspaceMember,
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
from shared.typed_notifications import append_notification_created_event
from shared.eventing_rebuild import rebuild_state

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
        "get_project_plugin_config",
        "get_project_capabilities",
        "diff_project_plugin_config",
        "graph_get_project_overview",
        "graph_get_neighbors",
        "graph_find_related_resources",
        "graph_get_dependency_path",
        "graph_context_pack",
        "search_project_knowledge",
        "verify_team_mode_workflow",
        "verify_delivery_workflow",
        "validate_project_plugin_config",
        "list_project_starters",
        "get_project_starter",
        "get_project_setup_profile",
        "list_projects",
    }
)
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_COMMIT_SHA_EXPLICIT_RE = re.compile(
    r"(?i)(?:\b(?:commit|sha|changeset|hash)\s*[:=#]?\s*|/commit/)([0-9a-f]{7,40})\b"
)
_PROJECT_POLICY_CHECKS_LLM_EVAL_VERSION = "project-policy-checks-v1"
_PROJECT_POLICY_CHECKS_LLM_EVAL_SCHEMA_VERSION = "1"
_PROJECT_POLICY_CHECKS_LLM_EVAL_CACHE = ClassificationCache(max_entries=64)
_TEAM_MODE_PLUGIN_KEY = "team_mode"
_PROJECT_PLUGIN_KEYS: set[str] = {"team_mode", "git_delivery", "docker_compose"}


def _safe_json_loads_object(raw: str, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return dict(fallback or {})
    try:
        parsed = json.loads(text)
    except Exception:
        return dict(fallback or {})
    if isinstance(parsed, dict):
        return parsed
    return dict(fallback or {})


def _safe_json_loads_array(raw: str, *, fallback: list[Any] | None = None) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return list(fallback or [])
    try:
        parsed = json.loads(text)
    except Exception:
        return list(fallback or [])
    if isinstance(parsed, list):
        return parsed
    return list(fallback or [])


def _normalize_plugin_key(plugin_key: str) -> str:
    normalized = str(plugin_key or "").strip().lower()
    if normalized not in _PROJECT_PLUGIN_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"plugin_key must be one of: {', '.join(sorted(_PROJECT_PLUGIN_KEYS))}",
        )
    return normalized


def _json_pointer_escape(token: str) -> str:
    return str(token or "").replace("~", "~0").replace("/", "~1")


def _json_diff_values(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        all_keys = sorted(set(before.keys()) | set(after.keys()), key=lambda item: str(item))
        for raw_key in all_keys:
            key = str(raw_key)
            pointer = f"{path}/{_json_pointer_escape(key)}" if path else f"/{_json_pointer_escape(key)}"
            if key not in before:
                changes.append({"op": "add", "path": pointer, "after": after.get(key)})
                continue
            if key not in after:
                changes.append({"op": "remove", "path": pointer, "before": before.get(key)})
                continue
            changes.extend(_json_diff_values(before.get(key), after.get(key), pointer))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [{"op": "replace", "path": path or "/", "before": before, "after": after}]
    if before != after:
        return [{"op": "replace", "path": path or "/", "before": before, "after": after}]
    return []


def _team_mode_default_config() -> dict[str, Any]:
    return {
        "required_checks": {"team_mode": list(DEFAULT_REQUIRED_TEAM_MODE_CHECKS)},
        **default_team_mode_config(),
    }


def _git_delivery_default_config() -> dict[str, Any]:
    return {
        "required_checks": {
            "delivery": list(DEFAULT_REQUIRED_DELIVERY_CHECKS),
        },
        "execution": {
            "require_dev_tests": False,
        },
    }


def _docker_compose_default_config(*, port: int | None = None) -> dict[str, Any]:
    normalized_port: int | None
    if port is None:
        normalized_port = None
    else:
        try:
            normalized_port = int(port)
        except Exception:
            normalized_port = None
    return {
        "compose_project_name": "constructos-ws-default",
        "workspace_root": "/workspace",
        "allowed_services": [],
        "protected_services": [],
        "runtime_deploy_health": {
            "required": False,
            "stack": "constructos-ws-default",
            "host": "gateway",
            "port": normalized_port,
            "health_path": "/health",
            "require_http_200": True,
        },
    }


def _default_plugin_config(plugin_key: str) -> dict[str, Any]:
    normalized = _normalize_plugin_key(plugin_key)
    if normalized == _TEAM_MODE_PLUGIN_KEY:
        return _team_mode_default_config()
    if normalized == "git_delivery":
        return _git_delivery_default_config()
    if normalized == "docker_compose":
        return _docker_compose_default_config()
    return {}


def _team_mode_runtime_context_for_project(
    db,
    *,
    workspace_id: str | None,
    project_id: str | None,
    require_enabled: bool = False,
) -> TeamModeProjectRuntimeContext | None:
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_project_id = str(project_id or "").strip()
    if not normalized_workspace_id or not normalized_project_id:
        return None
    runtime_context = TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=normalized_workspace_id,
        project_id=normalized_project_id,
    )
    if require_enabled and not runtime_context.enabled:
        return None
    return runtime_context


def _validate_team_mode_config(config: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    allowed_checks = set(TEAM_MODE_CORE_CHECK_IDS)

    required_checks = config.get("required_checks")
    if required_checks is not None and not isinstance(required_checks, dict):
        errors.append(
            {
                "path": "required_checks",
                "code": "invalid_type",
                "message": "required_checks must be an object",
            }
        )
    elif isinstance(required_checks, dict):
        team_mode_required = required_checks.get("team_mode")
        if team_mode_required is not None and not isinstance(team_mode_required, list):
            errors.append(
                {
                    "path": "required_checks.team_mode",
                    "code": "invalid_type",
                    "message": "required_checks.team_mode must be an array",
                }
            )
        elif isinstance(team_mode_required, list):
            seen: set[str] = set()
            for idx, value in enumerate(team_mode_required):
                check_id = str(value or "").strip()
                if not check_id:
                    errors.append(
                        {
                            "path": f"required_checks.team_mode[{idx}]",
                            "code": "empty_value",
                            "message": "check id cannot be empty",
                        }
                    )
                    continue
                if check_id not in allowed_checks:
                    errors.append(
                        {
                            "path": f"required_checks.team_mode[{idx}]",
                            "code": "unknown_check",
                            "message": f"unknown team_mode check id: {check_id}",
                        }
                    )
                    continue
                if check_id in seen:
                    warnings.append(f"required_checks.team_mode contains duplicate value: {check_id}")
                seen.add(check_id)

    team = config.get("team")
    status_semantics = config.get("status_semantics")
    routing = config.get("routing")
    oversight = config.get("oversight")
    review_policy = config.get("review_policy")
    labels = config.get("labels")

    if team is None:
        team = {}
    elif not isinstance(team, dict):
        errors.append({"path": "team", "code": "invalid_type", "message": "team must be an object"})
        team = {}
    if not isinstance(status_semantics, dict):
        errors.append({"path": "status_semantics", "code": "invalid_type", "message": "status_semantics must be an object"})
        status_semantics = {}
    if not isinstance(routing, dict):
        errors.append({"path": "routing", "code": "invalid_type", "message": "routing must be an object"})
        routing = {}
    if not isinstance(oversight, dict):
        errors.append({"path": "oversight", "code": "invalid_type", "message": "oversight must be an object"})
        oversight = {}
    if review_policy is None:
        review_policy = {}
    elif not isinstance(review_policy, dict):
        errors.append({"path": "review_policy", "code": "invalid_type", "message": "review_policy must be an object"})
        review_policy = {}
    if not isinstance(labels, dict):
        errors.append({"path": "labels", "code": "invalid_type", "message": "labels must be an object"})
        labels = {}

    roles_in_team: set[str] = set()
    agents = team.get("agents")
    if agents is None:
        agents = []
    elif not isinstance(agents, list):
        errors.append({"path": "team.agents", "code": "invalid_type", "message": "team.agents must be an array"})
        agents = []
    seen_agent_ids: set[str] = set()
    for idx, agent in enumerate(agents):
        if not isinstance(agent, dict):
            errors.append(
                {
                    "path": f"team.agents[{idx}]",
                    "code": "invalid_type",
                    "message": "each team agent must be an object",
                }
            )
            continue
        agent_id = str(agent.get("id") or "").strip()
        name = str(agent.get("name") or "").strip()
        authority_role = str(agent.get("authority_role") or "").strip()
        executor_user_id = str(agent.get("executor_user_id") or "").strip()
        if not agent_id:
            errors.append(
                {"path": f"team.agents[{idx}].id", "code": "required", "message": "agent id is required"}
            )
        elif agent_id in seen_agent_ids:
            errors.append(
                {
                    "path": f"team.agents[{idx}].id",
                    "code": "duplicate_value",
                    "message": f"duplicate agent id: {agent_id}",
                }
            )
        else:
            seen_agent_ids.add(agent_id)
        if not name:
            errors.append(
                {"path": f"team.agents[{idx}].name", "code": "required", "message": "agent name is required"}
            )
        if not authority_role:
            errors.append(
                {
                    "path": f"team.agents[{idx}].authority_role",
                    "code": "required",
                    "message": "agent authority_role is required",
                }
            )
        elif authority_role not in TEAM_MODE_ROLES:
            errors.append(
                {
                    "path": f"team.agents[{idx}].authority_role",
                    "code": "unknown_role",
                    "message": f"unknown authority_role: {authority_role}",
                }
            )
        else:
            roles_in_team.add(authority_role)
        if executor_user_id and not re.fullmatch(r"[0-9a-fA-F-]{36}", executor_user_id):
            errors.append(
                {
                    "path": f"team.agents[{idx}].executor_user_id",
                    "code": "invalid_format",
                    "message": "executor_user_id must be a UUID when provided",
                }
            )
    if not agents:
        errors.append({"path": "team.agents", "code": "required", "message": "team.agents must contain at least one Developer, one QA, and exactly one Lead"})
    if roles_in_team and "Developer" not in roles_in_team:
        errors.append({"path": "team.agents", "code": "missing_role", "message": "at least one Developer agent is required"})
    if roles_in_team and "QA" not in roles_in_team:
        errors.append({"path": "team.agents", "code": "missing_role", "message": "at least one QA agent is required"})
    if sum(1 for agent in agents if isinstance(agent, dict) and str(agent.get("authority_role") or "").strip() == "Lead") != 1:
        errors.append({"path": "team.agents", "code": "invalid_lead_count", "message": "exactly one Lead agent is required"})

    for key, default_status in REQUIRED_SEMANTIC_STATUSES.items():
        value = str(status_semantics.get(key) or "").strip()
        if not value:
            errors.append({"path": f"status_semantics.{key}", "code": "required", "message": f"status_semantics.{key} is required"})
        elif value != default_status:
            errors.append({"path": f"status_semantics.{key}", "code": "invalid_value", "message": f"status_semantics.{key} must be '{default_status}'"})
    for key in sorted(status_semantics.keys()):
        normalized = str(key or "").strip()
        if normalized and normalized not in REQUIRED_SEMANTIC_STATUSES:
            errors.append({"path": f"status_semantics.{normalized}", "code": "unknown_field", "message": f"unknown Team Mode semantic status: {normalized}"})

    for key in ("developer_assignment", "qa_assignment"):
        value = str(routing.get(key) or "").strip()
        if value != DEFAULT_ASSIGNMENT_POLICY:
            errors.append({"path": f"routing.{key}", "code": "invalid_value", "message": f"routing.{key} must be '{DEFAULT_ASSIGNMENT_POLICY}'"})
    try:
        reconciliation_interval_seconds = int(oversight.get("reconciliation_interval_seconds"))
    except Exception:
        reconciliation_interval_seconds = 0
    if reconciliation_interval_seconds < 1:
        errors.append({"path": "oversight.reconciliation_interval_seconds", "code": "out_of_range", "message": "oversight.reconciliation_interval_seconds must be >= 1"})
    human_owner_user_id = str(oversight.get("human_owner_user_id") or "").strip()
    if not human_owner_user_id:
        errors.append({"path": "oversight.human_owner_user_id", "code": "required", "message": "oversight.human_owner_user_id is required"})
    elif not re.fullmatch(r"[0-9a-fA-F-]{36}", human_owner_user_id):
        errors.append({"path": "oversight.human_owner_user_id", "code": "invalid_format", "message": "oversight.human_owner_user_id must be a UUID"})
    require_code_review = review_policy.get("require_code_review")
    if require_code_review is not None and not isinstance(require_code_review, bool):
        errors.append(
            {
                "path": "review_policy.require_code_review",
                "code": "invalid_type",
                "message": "review_policy.require_code_review must be a boolean",
            }
        )
    reviewer_user_id = str(review_policy.get("reviewer_user_id") or "").strip()
    if reviewer_user_id and not re.fullmatch(r"[0-9a-fA-F-]{36}", reviewer_user_id):
        errors.append(
            {
                "path": "review_policy.reviewer_user_id",
                "code": "invalid_format",
                "message": "review_policy.reviewer_user_id must be a UUID",
            }
        )

    expected_label_keys = {label.replace("-", "_"): label for label in RESERVED_LIFECYCLE_LABELS}
    for key, expected_value in expected_label_keys.items():
        value = str(labels.get(key) or "").strip().lower()
        if not value:
            errors.append({"path": f"labels.{key}", "code": "required", "message": f"labels.{key} is required"})
        elif value != expected_value:
            errors.append({"path": f"labels.{key}", "code": "invalid_value", "message": f"labels.{key} must be '{expected_value}'"})
    for key in sorted(labels.keys()):
        normalized = str(key or "").strip()
        if normalized and normalized not in expected_label_keys:
            errors.append({"path": f"labels.{normalized}", "code": "unknown_field", "message": f"unknown Team Mode label key: {normalized}"})
    return errors, warnings


def _effective_completed_status_for_project(db, *, workspace_id: str, project_id: str) -> str:
    semantics = _effective_team_mode_status_semantics_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    return str(semantics.get("completed") or REQUIRED_SEMANTIC_STATUSES["completed"]).strip() or "Done"


def _effective_team_mode_status_semantics_for_project(db, *, workspace_id: str, project_id: str) -> dict[str, str]:
    runtime_context = _team_mode_runtime_context_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        require_enabled=True,
    )
    if runtime_context is None:
        return dict(REQUIRED_SEMANTIC_STATUSES)
    semantics = runtime_context.status_semantics
    effective = dict(REQUIRED_SEMANTIC_STATUSES)
    for key, default_status in REQUIRED_SEMANTIC_STATUSES.items():
        value = str(semantics.get(key) or "").strip()
        if value:
            effective[key] = value
        else:
            effective[key] = default_status
    return effective


def _team_mode_review_required_for_project(db, *, workspace_id: str, project_id: str) -> bool:
    runtime_context = _team_mode_runtime_context_for_project(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        require_enabled=True,
    )
    if runtime_context is None:
        return False
    return runtime_context.review_required


def _priority_rank(value: Any) -> int:
    normalized = str(value or "").strip().casefold()
    if normalized == "high":
        return 0
    if normalized in {"med", "medium"}:
        return 1
    if normalized == "low":
        return 2
    return 3


def _canonicalize_project_status_label(value: Any) -> str:
    status = " ".join(str(value or "").split())
    if not status:
        return ""
    semantic_status = canonicalize_semantic_status_label(status)
    if semantic_status:
        return semantic_status
    normalized = status.casefold()
    if normalized == "done":
        return "Done"
    return status


def _validate_team_mode_project_status_alignment(
    *,
    db,
    workspace_id: str,
    project_id: str,
    status_semantics: dict[str, str],
) -> list[dict[str, str]]:
    project = db.get(Project, str(project_id))
    if project is None or bool(getattr(project, "is_deleted", False)):
        return []
    raw_statuses = []
    try:
        raw_statuses = json.loads(str(getattr(project, "custom_statuses", "") or "").strip() or "[]")
    except Exception:
        raw_statuses = []
    project_statuses = {
        _canonicalize_project_status_label(item)
        for item in (raw_statuses if isinstance(raw_statuses, list) else [])
        if _canonicalize_project_status_label(item)
    }
    required_statuses = [
        str(status_semantics.get(key) or "").strip()
        for key in ("todo", "active", "in_review", "awaiting_decision", "blocked", "completed")
        if str(status_semantics.get(key) or "").strip()
    ]
    missing = [status for status in required_statuses if status not in project_statuses]
    if not missing:
        return []
    return [
        {
            "path": "project.custom_statuses",
            "code": "missing_team_mode_statuses",
            "message": (
                "Team Mode requires project board statuses: "
                + ", ".join(required_statuses)
                + ". Missing: "
                + ", ".join(missing)
            ),
        }
    ]


def _is_completed_transition_request(*, requested_status: str | None, completed_status: str | None) -> bool:
    normalized_requested = str(requested_status or "").strip()
    if not normalized_requested:
        return False
    normalized_completed = str(completed_status or "").strip()
    if normalized_requested.casefold() == "done":
        return True
    if normalized_completed and normalized_requested.casefold() == normalized_completed.casefold():
        return True
    return semantic_status_key(status=normalized_requested) == "completed"


def _compile_plugin_policy(plugin_key: str, config: dict[str, Any]) -> dict[str, Any]:
    if plugin_key == _TEAM_MODE_PLUGIN_KEY:
        automation = config.get("automation") if isinstance(config.get("automation"), dict) else {}
        required_checks_cfg = config.get("required_checks") if isinstance(config.get("required_checks"), dict) else {}
        team_mode_required_raw = required_checks_cfg.get("team_mode") if isinstance(required_checks_cfg, dict) else None
        team_mode_required = (
            [str(item or "").strip() for item in team_mode_required_raw if str(item or "").strip()]
            if isinstance(team_mode_required_raw, list)
            else list(DEFAULT_REQUIRED_TEAM_MODE_CHECKS)
        )
        team_mode_required = [item for item in team_mode_required if item in TEAM_MODE_CORE_CHECK_SET]
        _ = automation
        return compile_team_mode_policy(
            config=config,
            required_checks=team_mode_required,
            available_checks=TEAM_MODE_CORE_CHECK_DESCRIPTIONS,
        )
    if plugin_key == "git_delivery":
        required_checks_cfg = config.get("required_checks") if isinstance(config.get("required_checks"), dict) else {}
        delivery_required_raw = required_checks_cfg.get("delivery") if isinstance(required_checks_cfg, dict) else None
        delivery_required = (
            [str(item or "").strip() for item in delivery_required_raw if str(item or "").strip()]
            if isinstance(delivery_required_raw, list)
            else list(DEFAULT_REQUIRED_DELIVERY_CHECKS)
        )
        delivery_required = [item for item in delivery_required if item in DELIVERY_CORE_CHECK_SET]
        execution_cfg = config.get("execution") if isinstance(config.get("execution"), dict) else {}
        require_dev_tests = bool(execution_cfg.get("require_dev_tests", False))
        compiled = {
            "version": 1,
            "required_checks": {"delivery": delivery_required},
            "available_checks": {"delivery": dict(DELIVERY_CORE_CHECK_DESCRIPTIONS)},
            "execution": {"require_dev_tests": require_dev_tests},
        }
        return compiled
    if plugin_key == "docker_compose":
        runtime_cfg_raw = config.get("runtime_deploy_health") if isinstance(config.get("runtime_deploy_health"), dict) else {}
        runtime_cfg = runtime_cfg_raw if isinstance(runtime_cfg_raw, dict) else {}
        return {
            "version": 1,
            "docker_compose": {
                "compose_project_name": str(config.get("compose_project_name") or "constructos-ws-default"),
                "workspace_root": str(config.get("workspace_root") or "/workspace"),
                "allowed_services": [
                    str(item or "").strip()
                    for item in (config.get("allowed_services") if isinstance(config.get("allowed_services"), list) else [])
                    if str(item or "").strip()
                ],
                "protected_services": [
                    str(item or "").strip()
                    for item in (config.get("protected_services") if isinstance(config.get("protected_services"), list) else [])
                    if str(item or "").strip()
                ],
            },
            "runtime_deploy_health": {
                "required": bool(runtime_cfg.get("required", False)),
                "stack": str(runtime_cfg.get("stack") or "constructos-ws-default"),
                "port": runtime_cfg.get("port"),
                "health_path": str(runtime_cfg.get("health_path") or "/health"),
                "require_http_200": bool(runtime_cfg.get("require_http_200", True)),
            },
        }
    return {"version": 1, "plugin_key": plugin_key}


def _validate_plugin_config(plugin_key: str, config: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    if plugin_key == _TEAM_MODE_PLUGIN_KEY:
        errors, warnings = _validate_team_mode_config(config)
        allowed_keys = {"required_checks", "team", "status_semantics", "routing", "oversight", "review_policy", "labels"}
        for key in sorted(config.keys()):
            normalized = str(key or "").strip()
            if normalized and normalized not in allowed_keys:
                errors.append(
                    {
                        "path": normalized,
                        "code": "unknown_field",
                        "message": f"unknown field for team_mode config: {normalized}",
                    }
                )
        return errors, warnings
    if plugin_key == "git_delivery":
        errors: list[dict[str, str]] = []
        warnings: list[str] = []
        allowed_keys = {"required_checks", "execution"}
        for key in sorted(config.keys()):
            normalized = str(key or "").strip()
            if not normalized:
                continue
            if normalized not in allowed_keys:
                errors.append(
                    {
                        "path": normalized,
                        "code": "unknown_field",
                        "message": f"unknown field for git_delivery config: {normalized}",
                    }
                )
        allowed_checks = set(DELIVERY_CORE_CHECK_IDS)
        required_checks = config.get("required_checks")
        if required_checks is not None and not isinstance(required_checks, dict):
            errors.append(
                {
                    "path": "required_checks",
                    "code": "invalid_type",
                    "message": "required_checks must be an object",
                }
            )
        elif isinstance(required_checks, dict):
            delivery = required_checks.get("delivery")
            if delivery is not None and not isinstance(delivery, list):
                errors.append(
                    {
                        "path": "required_checks.delivery",
                        "code": "invalid_type",
                        "message": "required_checks.delivery must be an array",
                    }
                )
            elif isinstance(delivery, list):
                seen: set[str] = set()
                for idx, value in enumerate(delivery):
                    check_id = str(value or "").strip()
                    if not check_id:
                        errors.append(
                            {
                                "path": f"required_checks.delivery[{idx}]",
                                "code": "empty_value",
                                "message": "check id cannot be empty",
                            }
                        )
                        continue
                    if check_id not in allowed_checks:
                        errors.append(
                            {
                                "path": f"required_checks.delivery[{idx}]",
                                "code": "unknown_check",
                                "message": f"unknown delivery check id: {check_id}",
                            }
                        )
                        continue
                    if check_id in seen:
                        warnings.append(f"required_checks.delivery contains duplicate value: {check_id}")
                    seen.add(check_id)
        execution = config.get("execution")
        if execution is not None and not isinstance(execution, dict):
            errors.append(
                {
                    "path": "execution",
                    "code": "invalid_type",
                    "message": "execution must be an object",
                }
            )
        elif isinstance(execution, dict):
            for key in sorted(execution.keys()):
                normalized = str(key or "").strip()
                if normalized != "require_dev_tests":
                    errors.append(
                        {
                            "path": f"execution.{normalized}" if normalized else "execution",
                            "code": "unknown_field",
                            "message": f"unknown field for execution config: {normalized}",
                        }
                    )
            if "require_dev_tests" in execution and not isinstance(execution.get("require_dev_tests"), bool):
                errors.append(
                    {
                        "path": "execution.require_dev_tests",
                        "code": "invalid_type",
                        "message": "execution.require_dev_tests must be a boolean",
                    }
                )
        return errors, warnings
    if plugin_key == "docker_compose":
        errors: list[dict[str, str]] = []
        warnings: list[str] = []
        allowed_keys = {
            "compose_project_name",
            "workspace_root",
            "allowed_services",
            "protected_services",
            "runtime_deploy_health",
        }
        for key in sorted(config.keys()):
            normalized = str(key or "").strip()
            if normalized and normalized not in allowed_keys:
                errors.append(
                    {
                        "path": normalized,
                        "code": "unknown_field",
                        "message": f"unknown field for docker_compose config: {normalized}",
                    }
                )
        runtime = config.get("runtime_deploy_health")
        if runtime is not None and not isinstance(runtime, dict):
            errors.append(
                {
                    "path": "runtime_deploy_health",
                    "code": "invalid_type",
                    "message": "runtime_deploy_health must be an object",
                }
            )
        elif isinstance(runtime, dict):
            allowed_runtime_keys = {"required", "stack", "host", "port", "health_path", "require_http_200"}
            for key in sorted(runtime.keys()):
                normalized_key = str(key or "").strip()
                if normalized_key and normalized_key not in allowed_runtime_keys:
                    errors.append(
                        {
                            "path": f"runtime_deploy_health.{normalized_key}",
                            "code": "unknown_field",
                            "message": f"unknown field for runtime_deploy_health: {normalized_key}",
                        }
                    )
            host = str(runtime.get("host") or "").strip()
            if host and any(ch.isspace() for ch in host):
                errors.append(
                    {
                        "path": "runtime_deploy_health.host",
                        "code": "invalid_format",
                        "message": "runtime_deploy_health.host must not contain whitespace",
                    }
                )
            port = runtime.get("port")
            if port is not None:
                try:
                    port_value = int(port)
                except Exception:
                    errors.append(
                        {
                            "path": "runtime_deploy_health.port",
                            "code": "invalid_type",
                            "message": "runtime_deploy_health.port must be an integer or null",
                        }
                    )
                else:
                    if port_value < 1 or port_value > 65535:
                        errors.append(
                            {
                                "path": "runtime_deploy_health.port",
                                "code": "out_of_range",
                                "message": "runtime_deploy_health.port must be between 1 and 65535",
                            }
                        )
            health_path = str(runtime.get("health_path") or "").strip()
            if health_path and not health_path.startswith("/"):
                errors.append(
                    {
                        "path": "runtime_deploy_health.health_path",
                        "code": "invalid_format",
                        "message": "runtime_deploy_health.health_path must start with '/'",
                    }
                )
            if bool(runtime.get("required")) and runtime.get("port") in (None, "", "null"):
                warnings.append("runtime_deploy_health.required=true without explicit port may rely on auto-discovery")
        return errors, warnings
    return [], []


def _effective_compiled_policy_from_row(*, plugin_key: str, config_json: str, compiled_policy_json: str | None = None) -> dict[str, Any]:
    default_config = _default_plugin_config(plugin_key)
    config_obj = _safe_json_loads_object(config_json, fallback=default_config)
    try:
        return _compile_plugin_policy(plugin_key, config_obj)
    except Exception:
        return _safe_json_loads_object(str(compiled_policy_json or "").strip(), fallback={})


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

    def _require_token(self, auth_token: str | None):
        if self._require_mcp_token and MCP_AUTH_TOKEN:
            if not auth_token or not hmac.compare_digest(auth_token, MCP_AUTH_TOKEN):
                raise HTTPException(status_code=401, detail="Invalid MCP token")

    def _assert_workspace_allowed(self, workspace_id: str):
        if self._allowed_workspace_ids and workspace_id not in self._allowed_workspace_ids:
            raise HTTPException(status_code=403, detail="Workspace is outside MCP allowlist")

    def _assert_project_allowed(self, project_id: str | None):
        if not project_id:
            return
        if self._allowed_project_ids and project_id not in self._allowed_project_ids:
            raise HTTPException(status_code=403, detail="Project is outside MCP allowlist")

    @staticmethod
    def _resolve_task_assignee_role(
        *,
        db,
        workspace_id: str,
        project_id: str | None,
        assignee_id: str | None,
        assigned_agent_code: str | None = None,
        task_labels: object | None = None,
        task_status: str | None = None,
    ) -> str:
        normalized_assignee_id = str(assignee_id or "").strip()
        normalized_assigned_agent_code = str(assigned_agent_code or "").strip().lower()
        runtime_context = _team_mode_runtime_context_for_project(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if runtime_context is None:
            return ""
        return str(
            runtime_context.derive_workflow_role(
                task_like={
                    "assignee_id": normalized_assignee_id,
                    "assigned_agent_code": normalized_assigned_agent_code,
                    "labels": task_labels,
                    "status": str(task_status or "").strip(),
                }
            )
            or ""
        ).strip()

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

    def _resolve_mcp_actor_user_id(self) -> str:
        return str(self._actor_user_id or MCP_ACTOR_USER_ID).strip() or MCP_ACTOR_USER_ID

    def _resolve_command_execution_provider(
        self,
        *,
        command_id: str | None,
        workspace_id: str | None,
        actor_user: UserModel | None,
    ) -> str | None:
        resolved = resolve_provider_for_command_id(command_id)
        if resolved:
            return resolved
        resolved_workspace = resolve_provider_for_workspace_id(workspace_id)
        if resolved_workspace:
            return resolved_workspace
        actor_model = str(getattr(actor_user, "agent_chat_model", "") or "").strip()
        provider, _model = parse_execution_model(actor_model)
        return provider

    @staticmethod
    def _resolve_project_agent_user_id_for_provider(
        *,
        db,
        workspace_id: str,
        project_id: str | None,
        provider: str | None,
    ) -> str:
        normalized_provider = str(provider or "").strip().lower()
        target_user_id = str(agent_system_user_id_for_provider(normalized_provider) or "").strip()
        normalized_project_id = str(project_id or "").strip()
        if not target_user_id or not normalized_project_id:
            return target_user_id
        member_row = db.execute(
            select(ProjectMember.user_id)
            .join(UserModel, UserModel.id == ProjectMember.user_id)
            .where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == normalized_project_id,
                ProjectMember.user_id == target_user_id,
                UserModel.is_active == True,  # noqa: E712
                UserModel.user_type == "agent",
            )
            .limit(1)
        ).first()
        if member_row is not None:
            return str(member_row[0] or "").strip() or target_user_id
        return target_user_id

    def _resolve_preference_target_user_id(self, user_id: str | None) -> str:
        explicit_user_id = str(user_id or "").strip()
        if explicit_user_id:
            return explicit_user_id
        if self._actor_user_id:
            return self._actor_user_id
        # In containerized runtime the MCP actor is often a dedicated bot account.
        # Preference updates should default to the primary app user unless the caller
        # explicitly targets a different user.
        actor_user_id = self._resolve_mcp_actor_user_id()
        if actor_user_id != DEFAULT_USER_ID:
            return DEFAULT_USER_ID
        return actor_user_id

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

    def _resolve_workspace_for_read(
        self,
        *,
        db,
        explicit_workspace_id: str | None,
        project_id: str | None = None,
    ) -> tuple[str, str | None]:
        normalized_project_id = str(project_id or "").strip() or None
        if normalized_project_id:
            workspace_id, resolved_project_id = self._resolve_workspace_for_create(
                db=db,
                explicit_workspace_id=explicit_workspace_id,
                project_id=normalized_project_id,
            )
            return workspace_id, resolved_project_id
        workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=explicit_workspace_id)
        return workspace_id, None

    def _augment_project_member_user_ids_for_human_visibility(
        self,
        *,
        db,
        workspace_id: str,
        actor_user: UserModel,
        member_user_ids: list[str] | None,
    ) -> list[str]:
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for raw in list(member_user_ids or []):
            user_id = str(raw or "").strip()
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            normalized_ids.append(user_id)

        workspace_agent_rows = db.execute(
            select(WorkspaceMember.user_id, UserModel.username)
            .join(UserModel, UserModel.id == WorkspaceMember.user_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                UserModel.is_active == True,  # noqa: E712
                UserModel.user_type == "agent",
                UserModel.username.in_(
                    [
                        agent_system_username_for_provider("codex"),
                        agent_system_username_for_provider("claude"),
                        agent_system_username_for_provider("opencode"),
                    ]
                ),
            )
            .order_by(WorkspaceMember.id.asc())
        ).all()
        available_agent_member_ids_by_provider: dict[str, str] = {}
        for user_id, username in workspace_agent_rows:
            normalized_user_id = str(user_id or "").strip()
            normalized_username = str(username or "").strip().lower()
            if not normalized_user_id:
                continue
            if normalized_username == agent_system_username_for_provider("codex").lower():
                available_agent_member_ids_by_provider["codex"] = normalized_user_id
            elif normalized_username == agent_system_username_for_provider("claude").lower():
                available_agent_member_ids_by_provider["claude"] = normalized_user_id
            elif normalized_username == agent_system_username_for_provider("opencode").lower():
                available_agent_member_ids_by_provider["opencode"] = normalized_user_id

        for provider in ("codex", "claude", "opencode"):
            member_id = str(available_agent_member_ids_by_provider.get(provider) or "").strip()
            if not member_id:
                continue
            if member_id in seen:
                continue
            seen.add(member_id)
            normalized_ids.append(member_id)

        actor_user_type = str(getattr(actor_user, "user_type", "") or "").strip().lower()
        if actor_user_type != "agent":
            return normalized_ids

        workspace_human_ids = [
            str(user_id or "").strip()
            for user_id in db.execute(
                select(WorkspaceMember.user_id)
                .join(UserModel, UserModel.id == WorkspaceMember.user_id)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    UserModel.is_active == True,  # noqa: E712
                    UserModel.user_type != "agent",
                )
                .order_by(WorkspaceMember.id.asc())
            ).scalars().all()
            if str(user_id or "").strip()
        ]
        preferred_human_id = None
        if DEFAULT_USER_ID in workspace_human_ids:
            preferred_human_id = DEFAULT_USER_ID
        elif workspace_human_ids:
            preferred_human_id = workspace_human_ids[0]
        if preferred_human_id and preferred_human_id not in seen:
            normalized_ids.append(preferred_human_id)
        return normalized_ids

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
        return derive_child_command_id(command_id, child_key, max_length=64)

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

    def _normalize_facet_keys(self, facet_keys: list[str] | None) -> list[str]:
        normalized: list[str] = []
        allowed = {item.lower() for item in list_project_facets()}
        for item in facet_keys or []:
            key = normalize_starter_key(item)
            if not key or key.lower() not in allowed:
                continue
            if key not in normalized:
                normalized.append(key)
        return normalized

    def _resolve_starter_setup(
        self,
        *,
        primary_starter_key: str | None,
        facet_keys: list[str] | None,
    ) -> tuple[dict[str, Any] | None, list[str], list[str]]:
        starter = get_project_starter(primary_starter_key)
        normalized_facets = self._normalize_facet_keys(facet_keys)
        if starter is None:
            return None, normalized_facets, []
        for default_facet in starter.facet_defaults:
            if default_facet not in normalized_facets and default_facet != starter.key:
                normalized_facets.append(default_facet)
        retrieval_hints: list[str] = []
        for hint in starter.retrieval_hints:
            if hint not in retrieval_hints:
                retrieval_hints.append(hint)
        for facet in normalized_facets:
            facet_starter = get_project_starter(facet)
            if facet_starter is None:
                continue
            for hint in facet_starter.retrieval_hints:
                if hint not in retrieval_hints:
                    retrieval_hints.append(hint)
        return {
            "key": starter.key,
            "label": starter.label,
            "default_custom_statuses": list(starter.default_custom_statuses),
            "definition": starter,
        }, normalized_facets, retrieval_hints

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
        workspace_id: str | None = None,
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
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            if specification_id:
                spec_state = self._assert_specification_allowed(db=db, specification_id=specification_id)
                assert spec_state is not None
                if spec_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to workspace")
                if resolved_project_id and spec_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to project")
            if task_group_id:
                group_state = self._assert_task_group_allowed(db=db, task_group_id=task_group_id)
                assert group_state is not None
                if group_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="task_group_id does not belong to workspace")
                if resolved_project_id and group_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="task_group_id does not belong to project")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=resolved_workspace_id,
                    view=view,
                    q=q,
                    status=status,
                    project_id=resolved_project_id,
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
        workspace_id: str | None = None,
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
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            if task_id:
                task_state = self._assert_task_allowed(db=db, task_id=task_id)
                assert task_state is not None
                if task_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="task_id does not belong to workspace")
                if resolved_project_id and task_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="task_id does not belong to project")
            if note_group_id:
                group_state = self._assert_note_group_allowed(db=db, note_group_id=note_group_id)
                assert group_state is not None
                if group_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="note_group_id does not belong to workspace")
                if resolved_project_id and group_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="note_group_id does not belong to project")
            if specification_id:
                spec_state = self._assert_specification_allowed(db=db, specification_id=specification_id)
                assert spec_state is not None
                if spec_state.workspace_id != resolved_workspace_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to workspace")
                if resolved_project_id and spec_state.project_id != resolved_project_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to project")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_notes_read_model(
                db,
                user,
                NoteListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
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
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_task_groups_read_model(
                db,
                user,
                TaskGroupListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=str(resolved_project_id or ""),
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_note_groups(
        self,
        *,
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_note_groups_read_model(
                db,
                user,
                NoteGroupListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=str(resolved_project_id or ""),
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_project_rules(
        self,
        *,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_project_rules_read_model(
                db,
                user,
                ProjectRuleListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_project_members(
        self,
        *,
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        role: str | None = None,
        user_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(0, int(offset or 0))
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            project = self._load_project_scope(db=db, project_id=str(resolved_project_id or ""))
            if str(project.workspace_id) != str(resolved_workspace_id):
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            stmt = (
                select(ProjectMember, UserModel)
                .join(UserModel, UserModel.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == resolved_project_id)
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
                "project_id": str(resolved_project_id),
                "workspace_id": str(resolved_workspace_id),
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
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_project_skills_read_model(
                db,
                user,
                ProjectSkillListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=str(resolved_project_id or ""),
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_workspace_skills(
        self,
        *,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_workspace_skills_read_model(
                db,
                user,
                WorkspaceSkillListQuery(
                    workspace_id=resolved_workspace_id,
                    q=q,
                    limit=limit,
                    offset=offset,
                ),
            )

    def list_projects(
        self,
        *,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        safe_limit = max(1, min(int(limit or 30), 200))
        safe_offset = max(0, int(offset or 0))
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            workspace_membership = db.execute(
                select(WorkspaceMember.role).where(
                    WorkspaceMember.workspace_id == resolved_workspace_id,
                    WorkspaceMember.user_id == user.id,
                )
            ).scalar_one_or_none()
            stmt = select(Project.id).where(
                Project.workspace_id == resolved_workspace_id,
                Project.is_deleted == False,  # noqa: E712
            )
            if str(workspace_membership or "") not in {"Owner", "Admin"}:
                assigned_projects = (
                    select(ProjectMember.project_id)
                    .where(
                        ProjectMember.workspace_id == resolved_workspace_id,
                        ProjectMember.user_id == user.id,
                    )
                    .subquery()
                )
                stmt = stmt.where(Project.id.in_(select(assigned_projects.c.project_id)))
            normalized_q = str(q or "").strip()
            if normalized_q:
                like = f"%{normalized_q}%"
                stmt = stmt.where(
                    or_(
                        Project.name.ilike(like),
                        Project.description.ilike(like),
                    )
                )
            total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
            project_ids = db.execute(
                stmt.order_by(Project.updated_at.desc(), Project.created_at.desc(), Project.name.asc())
                .limit(safe_limit)
                .offset(safe_offset)
            ).scalars().all()
            items = [load_project_view(db, str(project_id)) for project_id in project_ids]
            return {
                "workspace_id": resolved_workspace_id,
                "items": [item for item in items if item],
                "total": int(total),
                "limit": int(safe_limit),
                "offset": int(safe_offset),
            }

    def list_specifications(
        self,
        *,
        workspace_id: str | None = None,
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
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            return list_specifications_read_model(
                db,
                user,
                SpecificationListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
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

    def get_project_plugin_config(
        self,
        *,
        project_id: str,
        plugin_key: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized_plugin_key = _normalize_plugin_key(plugin_key)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            resolved_workspace_id = str(project.workspace_id)
            self._assert_workspace_allowed(resolved_workspace_id)
            if workspace_id and str(workspace_id) != resolved_workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            row = db.execute(
                select(ProjectPluginConfig).where(
                    ProjectPluginConfig.workspace_id == resolved_workspace_id,
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key == normalized_plugin_key,
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).scalar_one_or_none()
            if row is None:
                default_config = _default_plugin_config(normalized_plugin_key)
                return {
                    "workspace_id": resolved_workspace_id,
                    "project_id": str(project_id),
                    "plugin_key": normalized_plugin_key,
                    "enabled": False,
                    "version": 0,
                    "schema_version": 1,
                    "config": default_config,
                    "compiled_policy": _compile_plugin_policy(normalized_plugin_key, default_config),
                    "last_validation_errors": [],
                    "last_validated_at": None,
                    "exists": False,
                }
            row_config = _safe_json_loads_object(row.config_json, fallback={})
            if not row_config:
                row_config = _default_plugin_config(normalized_plugin_key)
            effective_compiled = _effective_compiled_policy_from_row(
                plugin_key=normalized_plugin_key,
                config_json=json.dumps(row_config, ensure_ascii=False),
                compiled_policy_json=row.compiled_policy_json,
            )
            return {
                "workspace_id": str(row.workspace_id),
                "project_id": str(row.project_id),
                "plugin_key": str(row.plugin_key),
                "enabled": bool(row.enabled),
                "version": int(row.version or 1),
                "schema_version": int(row.schema_version or 1),
                "config": row_config,
                "compiled_policy": effective_compiled,
                "last_validation_errors": _safe_json_loads_array(row.last_validation_errors_json),
                "last_validated_at": row.last_validated_at.isoformat() if row.last_validated_at else None,
                "exists": True,
            }

    def get_project_capabilities(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            resolved_workspace_id = str(project.workspace_id)
            self._assert_workspace_allowed(resolved_workspace_id)
            if workspace_id and str(workspace_id) != resolved_workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
            rows = db.execute(
                select(ProjectPluginConfig).where(
                    ProjectPluginConfig.workspace_id == resolved_workspace_id,
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key.in_(sorted(_PROJECT_PLUGIN_KEYS)),
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
        row_by_key = {
            str(getattr(row, "plugin_key", "") or "").strip(): row
            for row in rows
            if str(getattr(row, "plugin_key", "") or "").strip()
        }
        plugins: list[dict[str, Any]] = []
        enabled_plugin_keys: list[str] = []
        for plugin_key in sorted(_PROJECT_PLUGIN_KEYS):
            row = row_by_key.get(plugin_key)
            exists = row is not None
            enabled = bool(getattr(row, "enabled", False)) if row is not None else False
            if enabled:
                enabled_plugin_keys.append(plugin_key)
            plugins.append(
                {
                    "plugin_key": plugin_key,
                    "exists": exists,
                    "enabled": enabled,
                    "version": int(getattr(row, "version", 0) or 0) if row is not None else 0,
                    "schema_version": int(getattr(row, "schema_version", 1) or 1) if row is not None else 1,
                }
            )
        return {
            "workspace_id": resolved_workspace_id,
            "project_id": str(project_id),
            "enabled_plugin_keys": enabled_plugin_keys,
            "plugins": plugins,
            "capabilities": {
                "team_mode": "team_mode" in enabled_plugin_keys,
                "git_delivery": "git_delivery" in enabled_plugin_keys,
                "docker_compose": "docker_compose" in enabled_plugin_keys,
            },
        }

    def validate_project_plugin_config(
        self,
        *,
        project_id: str,
        plugin_key: str,
        draft_config: dict[str, Any] | str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized_plugin_key = _normalize_plugin_key(plugin_key)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        normalized_config: dict[str, Any]
        if isinstance(draft_config, str):
            normalized_config = _safe_json_loads_object(draft_config)
        elif isinstance(draft_config, dict):
            normalized_config = dict(draft_config)
        else:
            raise HTTPException(status_code=422, detail="draft_config must be an object or JSON object string")
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            resolved_workspace_id = str(project.workspace_id)
            self._assert_workspace_allowed(resolved_workspace_id)
            if workspace_id and str(workspace_id) != resolved_workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member"})
            errors, warnings = _validate_plugin_config(normalized_plugin_key, normalized_config)
            if normalized_plugin_key == _TEAM_MODE_PLUGIN_KEY:
                effective_semantics = normalize_status_semantics(normalized_config.get("status_semantics"))
                errors.extend(
                    _validate_team_mode_project_status_alignment(
                        db=db,
                        workspace_id=resolved_workspace_id,
                        project_id=str(project_id),
                        status_semantics=effective_semantics,
                    )
                )
        compiled_policy = _compile_plugin_policy(normalized_plugin_key, normalized_config)
        return {
            "workspace_id": resolved_workspace_id,
            "project_id": str(project_id),
            "plugin_key": normalized_plugin_key,
            "schema_version": 1,
            "errors": errors,
            "warnings": warnings,
            "blocking": bool(errors),
            "normalized_config": normalized_config,
            "compiled_policy": compiled_policy,
        }

    def diff_project_plugin_config(
        self,
        *,
        project_id: str,
        plugin_key: str,
        draft_config: dict[str, Any] | str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized_plugin_key = _normalize_plugin_key(plugin_key)
        current = self.get_project_plugin_config(
            project_id=project_id,
            plugin_key=normalized_plugin_key,
            auth_token=auth_token,
            workspace_id=workspace_id,
        )
        validation = self.validate_project_plugin_config(
            project_id=project_id,
            plugin_key=normalized_plugin_key,
            draft_config=draft_config,
            auth_token=auth_token,
            workspace_id=workspace_id,
        )
        current_config = dict(current.get("config") or {})
        current_compiled_policy = dict(current.get("compiled_policy") or {})
        next_config = dict(validation.get("normalized_config") or {})
        next_compiled_policy = dict(validation.get("compiled_policy") or {})
        config_changes = _json_diff_values(current_config, next_config)
        compiled_policy_changes = _json_diff_values(current_compiled_policy, next_compiled_policy)
        return {
            "workspace_id": str(current.get("workspace_id") or ""),
            "project_id": str(project_id),
            "plugin_key": normalized_plugin_key,
            "current_version": int(current.get("version") or 0),
            "exists": bool(current.get("exists", False)),
            "blocking": bool(validation.get("blocking")),
            "errors": list(validation.get("errors") or []),
            "warnings": list(validation.get("warnings") or []),
            "config_changes": config_changes,
            "compiled_policy_changes": compiled_policy_changes,
            "current_config": current_config,
            "next_config": next_config,
            "current_compiled_policy": current_compiled_policy,
            "next_compiled_policy": next_compiled_policy,
            "changed": bool(config_changes or compiled_policy_changes),
        }

    def apply_project_plugin_config(
        self,
        *,
        project_id: str,
        plugin_key: str,
        config: dict[str, Any] | str,
        expected_version: int | None = None,
        enabled: bool | None = None,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized_plugin_key = _normalize_plugin_key(plugin_key)
        self._assert_project_allowed(project_id)
        validation = self.validate_project_plugin_config(
            project_id=project_id,
            plugin_key=normalized_plugin_key,
            draft_config=config,
            auth_token=auth_token,
            workspace_id=workspace_id,
        )
        if bool(validation.get("blocking")):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Plugin config validation failed",
                    "plugin_key": normalized_plugin_key,
                    "errors": validation.get("errors") or [],
                },
            )
        normalized_config = dict(validation.get("normalized_config") or {})
        compiled_policy = dict(validation.get("compiled_policy") or {})
        user = self._resolve_actor_user()
        now_utc = datetime.now(timezone.utc)
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            resolved_workspace_id = str(project.workspace_id)
            self._assert_workspace_allowed(resolved_workspace_id)
            if workspace_id and str(workspace_id) != resolved_workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member"})
            row = db.execute(
                select(ProjectPluginConfig).where(
                    ProjectPluginConfig.workspace_id == resolved_workspace_id,
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key == normalized_plugin_key,
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).scalar_one_or_none()
            if row is None:
                row = ProjectPluginConfig(
                    workspace_id=resolved_workspace_id,
                    project_id=str(project_id),
                    plugin_key=normalized_plugin_key,
                    enabled=bool(enabled if enabled is not None else True),
                    version=1,
                    schema_version=1,
                    config_json=json.dumps(normalized_config, ensure_ascii=False),
                    compiled_policy_json=json.dumps(compiled_policy, ensure_ascii=False),
                    last_validation_errors_json="[]",
                    last_validated_at=now_utc,
                    created_by=str(user.id),
                    updated_by=str(user.id),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
                created = True
            else:
                current_version = int(row.version or 1)
                if expected_version is not None and int(expected_version) != current_version:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Version mismatch for {normalized_plugin_key}: "
                            f"expected_version={int(expected_version)}, current_version={current_version}"
                        ),
                    )
                row.config_json = json.dumps(normalized_config, ensure_ascii=False)
                row.compiled_policy_json = json.dumps(compiled_policy, ensure_ascii=False)
                row.last_validation_errors_json = "[]"
                row.last_validated_at = now_utc
                row.enabled = bool(enabled if enabled is not None else row.enabled)
                row.version = current_version + 1
                row.schema_version = 1
                row.updated_by = str(user.id)
                db.add(row)
                db.commit()
                db.refresh(row)
                created = False
            return {
                "workspace_id": str(row.workspace_id),
                "project_id": str(row.project_id),
                "plugin_key": str(row.plugin_key),
                "enabled": bool(row.enabled),
                "version": int(row.version or 1),
                "schema_version": int(row.schema_version or 1),
                "config": _safe_json_loads_object(row.config_json),
                "compiled_policy": _effective_compiled_policy_from_row(
                    plugin_key=normalized_plugin_key,
                    config_json=row.config_json,
                    compiled_policy_json=row.compiled_policy_json,
                ),
                "created": created,
            }

    def set_project_plugin_enabled(
        self,
        *,
        project_id: str,
        plugin_key: str,
        enabled: bool,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        normalized_plugin_key = _normalize_plugin_key(plugin_key)
        self._assert_project_allowed(project_id)
        user = self._resolve_actor_user()
        now_utc = datetime.now(timezone.utc)
        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            resolved_workspace_id = str(project.workspace_id)
            self._assert_workspace_allowed(resolved_workspace_id)
            if workspace_id and str(workspace_id) != resolved_workspace_id:
                raise HTTPException(status_code=400, detail="Project does not belong to workspace")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member"})
            row = db.execute(
                select(ProjectPluginConfig).where(
                    ProjectPluginConfig.workspace_id == resolved_workspace_id,
                    ProjectPluginConfig.project_id == str(project_id),
                    ProjectPluginConfig.plugin_key == normalized_plugin_key,
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).scalar_one_or_none()
            if row is None:
                default_config = _default_plugin_config(normalized_plugin_key)
                row = ProjectPluginConfig(
                    workspace_id=resolved_workspace_id,
                    project_id=str(project_id),
                    plugin_key=normalized_plugin_key,
                    enabled=bool(enabled),
                    version=1,
                    schema_version=1,
                    config_json=json.dumps(default_config, ensure_ascii=False),
                    compiled_policy_json=json.dumps(_compile_plugin_policy(normalized_plugin_key, default_config), ensure_ascii=False),
                    last_validation_errors_json="[]",
                    last_validated_at=now_utc,
                    created_by=str(user.id),
                    updated_by=str(user.id),
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            else:
                row_config = _safe_json_loads_object(str(row.config_json or "").strip(), fallback={})
                if bool(enabled) and not row_config:
                    row_config = _default_plugin_config(normalized_plugin_key)
                    row.config_json = json.dumps(row_config, ensure_ascii=False)
                effective_row_config = _safe_json_loads_object(str(row.config_json or "").strip(), fallback={})
                row.enabled = bool(enabled)
                row.compiled_policy_json = json.dumps(
                    _effective_compiled_policy_from_row(
                        plugin_key=normalized_plugin_key,
                        config_json=json.dumps(effective_row_config, ensure_ascii=False),
                        compiled_policy_json=row.compiled_policy_json,
                    ),
                    ensure_ascii=False,
                )
                row.version = int(row.version or 1) + 1
                row.updated_by = str(user.id)
                row.last_validated_at = now_utc
                db.add(row)
                db.commit()
                db.refresh(row)
            if normalized_plugin_key == _TEAM_MODE_PLUGIN_KEY and bool(enabled):
                git_delivery_row = db.execute(
                    select(ProjectPluginConfig).where(
                        ProjectPluginConfig.workspace_id == resolved_workspace_id,
                        ProjectPluginConfig.project_id == str(project_id),
                        ProjectPluginConfig.plugin_key == "git_delivery",
                        ProjectPluginConfig.is_deleted == False,  # noqa: E712
                    )
                ).scalar_one_or_none()
                if git_delivery_row is None:
                    git_default_config: dict[str, Any] = _default_plugin_config("git_delivery")
                    git_delivery_row = ProjectPluginConfig(
                        workspace_id=resolved_workspace_id,
                        project_id=str(project_id),
                        plugin_key="git_delivery",
                        enabled=True,
                        version=1,
                        schema_version=1,
                        config_json=json.dumps(git_default_config, ensure_ascii=False),
                        compiled_policy_json=json.dumps(
                            _compile_plugin_policy("git_delivery", git_default_config),
                            ensure_ascii=False,
                        ),
                        last_validation_errors_json="[]",
                        last_validated_at=now_utc,
                        created_by=str(user.id),
                        updated_by=str(user.id),
                    )
                    db.add(git_delivery_row)
                    db.commit()
                elif not bool(git_delivery_row.enabled):
                    git_row_config = _safe_json_loads_object(str(git_delivery_row.config_json or "").strip(), fallback={})
                    if not git_row_config:
                        git_row_config = _default_plugin_config("git_delivery")
                        git_delivery_row.config_json = json.dumps(git_row_config, ensure_ascii=False)
                    git_delivery_row.enabled = True
                    git_delivery_row.compiled_policy_json = json.dumps(
                        _effective_compiled_policy_from_row(
                            plugin_key="git_delivery",
                            config_json=git_delivery_row.config_json,
                            compiled_policy_json=git_delivery_row.compiled_policy_json,
                        ),
                        ensure_ascii=False,
                    )
                    git_delivery_row.version = int(git_delivery_row.version or 1) + 1
                    git_delivery_row.updated_by = str(user.id)
                    git_delivery_row.last_validated_at = now_utc
                    db.add(git_delivery_row)
                    db.commit()
            return {
                "workspace_id": str(row.workspace_id),
                "project_id": str(row.project_id),
                "plugin_key": str(row.plugin_key),
                "enabled": bool(row.enabled),
                "version": int(row.version or 1),
                "schema_version": int(row.schema_version or 1),
            }

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
        actor_user_id = self._resolve_mcp_actor_user_id()
        with SessionLocal() as db:
            return self._user_gateway.get_preferences(
                db=db,
                actor_user_id=actor_user_id,
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
        actor_user_id = self._resolve_mcp_actor_user_id()
        implicit_target_user_id = self._resolve_preference_target_user_id(user_id)
        with SessionLocal() as db:
            current = self._user_gateway.get_preferences(
                db=db,
                actor_user_id=actor_user_id,
                explicit_target_user_id=user_id,
                implicit_target_user_id=implicit_target_user_id,
            )
        current_theme = normalize_theme(current.get("theme"), default=DEFAULT_THEME)
        next_theme = toggle_theme(current_theme)
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
        normalized = normalize_theme(theme, default="")
        if normalized not in VALID_THEMES:
            allowed = ", ".join(sorted(VALID_THEMES))
            raise HTTPException(status_code=422, detail=f"theme must be one of: {allowed}")
        actor_user_id = self._resolve_mcp_actor_user_id()
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

    @staticmethod
    def _extract_commit_shas_from_text(text: str) -> set[str]:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return set()
        return {str(match.group(1) or "").lower() for match in _COMMIT_SHA_EXPLICIT_RE.finditer(normalized)}

    @classmethod
    def _extract_commit_shas_from_refs(cls, refs: Any) -> set[str]:
        shas: set[str] = set()
        for item in cls._parse_json_list(refs):
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            shas.update(cls._extract_commit_shas_from_text(f"{url} {title}"))
        return shas

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
        # Evidence extraction only. This is not allowed to classify user workflow intent.
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        tooling_keywords = (
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
        result_keywords = (
            "pass",
            "passed",
            "fail",
            "failed",
            "green",
            "red",
            "ok",
            "success",
            "error",
            "regression",
        )
        return any(token in normalized for token in tooling_keywords) and any(
            token in normalized for token in result_keywords
        )

    @staticmethod
    def _has_deploy_artifact_text(text: str) -> bool:
        # Evidence extraction only. This is not allowed to classify user workflow intent.
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        action_keywords = (
            "deploy",
            "docker compose up",
            "docker compose",
            "release",
            "rolled out",
            "rollout",
            "kubectl",
            "helm",
        )
        verification_keywords = (
            "healthy",
            "running",
            "up",
            "http://",
            "https://",
            "/health",
            "smoke",
            "status 200",
            "ready",
        )
        return any(token in normalized for token in action_keywords) and any(
            token in normalized for token in verification_keywords
        )

    @staticmethod
    def _extract_deploy_ports(text: str) -> set[str]:
        # Deterministic artifact parsing only. Missing/ambiguous input must fail closed.
        normalized = str(text or "").strip().lower()
        if not normalized:
            return set()
        ports: set[str] = set()
        for match in re.finditer(r"\bport\s*[:=]?\s*(\d{2,5})\b", normalized):
            candidate = str(match.group(1) or "").strip()
            if candidate:
                ports.add(candidate)
        for match in re.finditer(r"localhost:(\d{2,5})\b", normalized):
            candidate = str(match.group(1) or "").strip()
            if candidate:
                ports.add(candidate)
        for match in re.finditer(r"0\.0\.0\.0:(\d{2,5})\b", normalized):
            candidate = str(match.group(1) or "").strip()
            if candidate:
                ports.add(candidate)
        return ports

    @staticmethod
    def _has_deploy_stack_marker(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return False
        return (
            "constructos-ws-default" in normalized
            or "docker compose -p" in normalized
            or "stack" in normalized
        )

    @staticmethod
    def _extract_deploy_stack(text: str) -> str | None:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return None
        explicit = re.search(r"docker\s+compose\s+-p\s+([a-z0-9][a-z0-9_-]*)", normalized)
        if explicit:
            candidate = str(explicit.group(1) or "").strip()
            if candidate:
                return candidate
        fallback = re.search(r"\b(constructos-[a-z0-9_-]+)\b", normalized)
        if fallback:
            candidate = str(fallback.group(1) or "").strip()
            if candidate:
                return candidate
        return None

    @staticmethod
    def _evaluate_required_checks(checks: dict[str, Any], required_checks: list[str]) -> tuple[bool, list[str]]:
        return evaluate_required_policy_checks(checks, required_checks)

    @classmethod
    def _resolve_deploy_target_from_artifacts(
        cls,
        *,
        deploy_tasks: list[dict[str, Any]],
        notes_by_task: dict[str, list[Note]],
        comments_by_task: dict[str, list[TaskComment]],
        runtime_policy: dict[str, Any],
    ) -> tuple[str, int | None, str]:
        stack = str(runtime_policy.get("stack") or "").strip() or "constructos-ws-default"
        port_value = runtime_policy.get("port")
        port: int | None = None
        if isinstance(port_value, int):
            port = port_value if 1 <= int(port_value) <= 65535 else None
        elif isinstance(port_value, str) and port_value.strip().isdigit():
            parsed_port = int(port_value.strip())
            port = parsed_port if 1 <= parsed_port <= 65535 else None
        health_path = str(runtime_policy.get("health_path") or "/health").strip() or "/health"
        if not health_path.startswith("/"):
            health_path = f"/{health_path}"

        for task in deploy_tasks:
            task_id = str(task.get("id") or "").strip()
            corpus = "\n".join(
                [
                    str(task.get("title") or ""),
                    str(task.get("description") or ""),
                    str(task.get("instruction") or ""),
                ]
            )
            for note in notes_by_task.get(task_id, []):
                corpus = f"{corpus}\n{note.title or ''}\n{note.body or ''}"
            for comment in comments_by_task.get(task_id, []):
                corpus = f"{corpus}\n{comment.body or ''}"
            if not stack:
                extracted_stack = cls._extract_deploy_stack(corpus)
                if extracted_stack:
                    stack = extracted_stack
            if port is None:
                extracted_ports = cls._extract_deploy_ports(corpus)
                if extracted_ports:
                    try:
                        port = int(sorted(extracted_ports)[0])
                    except Exception:
                        port = None
        return stack or "constructos-ws-default", port, health_path

    @staticmethod
    def _run_runtime_deploy_health_check(
        *,
        stack: str,
        port: int | None,
        health_path: str,
        require_http_200: bool,
        host: str | None = None,
    ) -> dict[str, Any]:
        return run_runtime_deploy_health_check(
            stack=stack,
            port=port,
            health_path=health_path,
            require_http_200=require_http_200,
            host=host,
        )

    @staticmethod
    def _enrich_tasks_with_automation_state(
        *,
        db,
        tasks: list[dict[str, Any]],
    ) -> None:
        if not tasks:
            return
        for task in tasks:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            try:
                state, _ = rebuild_state(db, "Task", task_id)
            except Exception:
                continue
            if not isinstance(state, dict) or not state:
                continue
            task["automation_state"] = state.get("automation_state", task.get("automation_state", "idle"))
            task["last_agent_run_at"] = state.get("last_agent_run_at")
            task["last_requested_source"] = state.get("last_requested_source")
            task["last_requested_triggered_at"] = state.get("last_requested_triggered_at")
            if str(state.get("last_lead_handoff_token") or "").strip():
                task["last_lead_handoff_token"] = str(state.get("last_lead_handoff_token") or "").strip()
            if isinstance(state.get("last_lead_handoff_deploy_execution"), dict):
                task["last_lead_handoff_deploy_execution"] = state.get("last_lead_handoff_deploy_execution")
            if isinstance(state.get("last_deploy_execution"), dict):
                task["last_deploy_execution"] = state.get("last_deploy_execution")
            if not str(task.get("instruction") or "").strip():
                instruction = str(state.get("instruction") or state.get("scheduled_instruction") or "").strip()
                if instruction:
                    task["instruction"] = instruction
            scheduled_instruction = str(state.get("scheduled_instruction") or "").strip()
            if scheduled_instruction and not str(task.get("scheduled_instruction") or "").strip():
                task["scheduled_instruction"] = scheduled_instruction

    @classmethod
    def _classify_project_context_signals(
        cls,
        *,
        project_description: str,
        project_external_refs: Any,
        project_rules: list[ProjectRuleModel],
        allow_llm: bool = True,
    ) -> dict[str, Any]:
        return plugin_context_policy.classify_project_delivery_context(
            project_description=project_description,
            project_external_refs=project_external_refs,
            project_rules=project_rules,
            parse_json_list=cls._parse_json_list,
            allow_llm=allow_llm,
        )

    @classmethod
    def _project_has_github_context(
        cls,
        *,
        project_description: str,
        project_external_refs: Any,
        project_rules: list[ProjectRuleModel],
        allow_llm: bool = True,
    ) -> bool:
        parsed = plugin_context_policy.classify_project_delivery_context(
            project_description=project_description,
            project_external_refs=project_external_refs,
            project_rules=project_rules,
            parse_json_list=cls._parse_json_list,
            allow_llm=allow_llm,
        )
        return bool(parsed.get("has_github_context"))

    @classmethod
    def _project_has_repo_context(
        cls,
        *,
        project_description: str,
        project_external_refs: Any,
        project_rules: list[ProjectRuleModel],
        allow_llm: bool = True,
    ) -> bool:
        parsed = plugin_context_policy.classify_project_delivery_context(
            project_description=project_description,
            project_external_refs=project_external_refs,
            project_rules=project_rules,
            parse_json_list=cls._parse_json_list,
            allow_llm=allow_llm,
        )
        return bool(parsed.get("has_repo_context"))

    @classmethod
    def _evaluate_project_policy_checks_with_llm(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        plugin_policy: dict[str, Any],
        tasks: list[dict[str, Any]],
        member_role_by_user_id: dict[str, str],
        notes_by_task: dict[str, list[Any]],
        comments_by_task: dict[str, list[Any]],
        project_rules: list[ProjectRuleModel],
        project_skills: list[Any],
        project_description: str,
        project_external_refs: Any,
    ) -> dict[str, dict[str, Any]]:
        available_checks = plugin_policy.get("available_checks") if isinstance(plugin_policy, dict) else {}
        required_checks = plugin_policy.get("required_checks") if isinstance(plugin_policy, dict) else {}
        requested_by_scope: dict[str, list[str]] = {}
        available_by_scope: dict[str, dict[str, Any]] = {}
        required_by_scope: dict[str, list[str]] = {}
        if isinstance(available_checks, dict):
            for scope_name_raw, scope_available_raw in available_checks.items():
                scope_name = str(scope_name_raw or "").strip()
                if not scope_name:
                    continue
                scope_available = dict(scope_available_raw) if isinstance(scope_available_raw, dict) else {}
                available_by_scope[scope_name] = scope_available
        if isinstance(required_checks, dict):
            for scope_name_raw, scope_required_raw in required_checks.items():
                scope_name = str(scope_name_raw or "").strip()
                if not scope_name:
                    continue
                if isinstance(scope_required_raw, list):
                    scope_required = [str(item or "").strip() for item in scope_required_raw if str(item or "").strip()]
                else:
                    scope_required = []
                required_by_scope[scope_name] = scope_required

        scope_names = sorted(set(available_by_scope.keys()) | set(required_by_scope.keys()))
        for scope_name in scope_names:
            requested = sorted(
                {
                    str(item or "").strip()
                    for item in list((available_by_scope.get(scope_name) or {}).keys()) + list(required_by_scope.get(scope_name) or [])
                    if str(item or "").strip()
                }
            )
            if requested:
                requested_by_scope[scope_name] = requested

        if not requested_by_scope:
            return {
                "team_mode": {"checks": {}, "reasons": {}},
                "delivery": {"checks": {}, "reasons": {}},
            }

        serialized_rules = [
            {
                "id": str(getattr(rule, "id", "") or "").strip(),
                "title": str(getattr(rule, "title", "") or "").strip(),
                "body": str(getattr(rule, "body", "") or "")[:8000],
            }
            for rule in project_rules
        ]
        serialized_skills = [
            {
                "skill_key": str(getattr(skill, "skill_key", "") or "").strip(),
                "enabled": bool(getattr(skill, "enabled", True)),
                "mode": str(getattr(skill, "mode", "") or "").strip(),
            }
            for skill in project_skills
        ]
        serialized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            task_state, _ = rebuild_state(db, "Task", task_id)
            serialized_tasks.append(
                {
                    "id": task_id,
                    "title": str(task.get("title") or "").strip(),
                    "status": str(task.get("status") or "").strip(),
                    "assignee_id": str(task.get("assignee_id") or "").strip(),
                    "assignee_role": str(member_role_by_user_id.get(str(task.get("assignee_id") or "").strip()) or "").strip(),
                    "description": str(task.get("description") or "")[:4000],
                    "instruction": str(task.get("instruction") or "")[:4000],
                    "scheduled_instruction": str(task.get("scheduled_instruction") or "")[:4000],
                    "execution_triggers": task.get("execution_triggers") if isinstance(task.get("execution_triggers"), list) else [],
                    "external_refs": cls._parse_json_list(task.get("external_refs")),
                    "last_lead_handoff_token": str(task_state.get("last_lead_handoff_token") or "").strip() or None,
                    "last_lead_handoff_deploy_execution": (
                        task_state.get("last_lead_handoff_deploy_execution")
                        if isinstance(task_state.get("last_lead_handoff_deploy_execution"), dict)
                        else None
                    ),
                    "last_deploy_execution": (
                        task.get("last_deploy_execution")
                        if isinstance(task.get("last_deploy_execution"), dict)
                        else (
                            task_state.get("last_deploy_execution")
                            if isinstance(task_state.get("last_deploy_execution"), dict)
                            else None
                        )
                    ),
                    "last_agent_run_at": str(task.get("last_agent_run_at") or "").strip(),
                }
            )

        serialized_notes: dict[str, list[dict[str, str]]] = {}
        for task_id, items in notes_by_task.items():
            normalized_task_id = str(task_id or "").strip()
            if not normalized_task_id:
                continue
            serialized_notes[normalized_task_id] = [
                {
                    "id": str(getattr(item, "id", "") or "").strip(),
                    "title": str(getattr(item, "title", "") or "").strip(),
                    "body": str(getattr(item, "body", "") or "")[:4000],
                }
                for item in items
            ]
        serialized_comments: dict[str, list[dict[str, str]]] = {}
        for task_id, items in comments_by_task.items():
            normalized_task_id = str(task_id or "").strip()
            if not normalized_task_id:
                continue
            serialized_comments[normalized_task_id] = [
                {
                    "id": str(getattr(item, "id", "") or "").strip(),
                    "body": str(getattr(item, "body", "") or "")[:4000],
                    "details": str(getattr(item, "details", "") or "")[:4000],
                }
                for item in items
            ]

        payload = {
            "project_id": str(project_id or "").strip(),
            "workspace_id": str(workspace_id or "").strip(),
            "project_description": str(project_description or "")[:8000],
            "project_external_refs": cls._parse_json_list(project_external_refs),
            "project_rules": serialized_rules[:80],
            "project_skills": serialized_skills,
            "tasks": serialized_tasks[:500],
            "notes_by_task": serialized_notes,
            "comments_by_task": serialized_comments,
            "checks": {
                scope_name: {
                    "required": list(required_by_scope.get(scope_name) or []),
                    "available": dict(available_by_scope.get(scope_name) or {}),
                    "requested": list(requested_by_scope.get(scope_name) or []),
                }
                for scope_name in sorted(requested_by_scope.keys())
            },
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        cache_key = build_classification_cache_key(
            cache_name="project_policy_checks",
            workspace_id=workspace_id,
            project_id=project_id,
            classifier_version=_PROJECT_POLICY_CHECKS_LLM_EVAL_VERSION,
            schema_version=_PROJECT_POLICY_CHECKS_LLM_EVAL_SCHEMA_VERSION,
            payload=payload,
        )
        cached = _PROJECT_POLICY_CHECKS_LLM_EVAL_CACHE.get(cache_key)
        if isinstance(cached, dict):
            return cached

        scope_enum = sorted(requested_by_scope.keys())
        output_schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "scope": {"type": "string", "enum": scope_enum},
                            "check_id": {"type": "string"},
                            "passed": {"type": "boolean"},
                            "reason": {"type": "string"},
                        },
                        "required": ["scope", "check_id", "passed", "reason"],
                    },
                }
            },
            "required": ["results"],
        }
        prompt = (
            "Evaluate project policy checks strictly from provided project snapshot.\n"
            "Return JSON matching schema.\n"
            "You must evaluate every requested check_id in each scope.\n"
            "Do not infer missing evidence. If evidence is absent, mark passed=false.\n"
            "Reasons must be short and grounded in provided snapshot.\n\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True)}\n"
        )
        try:
            parsed = run_structured_codex_prompt(
                prompt=prompt,
                output_schema=output_schema,
                workspace_id=workspace_id,
                session_key=f"project-policy-checks-evaluator:{payload_hash}",
                mcp_servers=[],
                use_cache=True,
            )
        except Exception:
            parsed = {"results": []}

        result_map: dict[str, dict[str, Any]] = {
            scope_name: {"checks": {}, "reasons": {}}
            for scope_name in scope_enum
        }
        result_map.setdefault("team_mode", {"checks": {}, "reasons": {}})
        result_map.setdefault("delivery", {"checks": {}, "reasons": {}})
        for item in (parsed.get("results") or []):
            if not isinstance(item, dict):
                continue
            scope = str(item.get("scope") or "").strip()
            check_id = str(item.get("check_id") or "").strip()
            if scope not in result_map or not check_id:
                continue
            result_map[scope]["checks"][check_id] = bool(item.get("passed"))
            result_map[scope]["reasons"][check_id] = str(item.get("reason") or "").strip()

        _PROJECT_POLICY_CHECKS_LLM_EVAL_CACHE.set(cache_key, result_map)
        return result_map

    @staticmethod
    def _open_developer_tasks(*, db, project_id: str) -> list[dict[str, str]]:
        return plugin_service_policy.open_plugin_developer_tasks(
            plugin_key=_TEAM_MODE_PLUGIN_KEY,
            db=db,
            project_id=project_id,
        )

    def _enforce_team_mode_done_transition(
        self,
        *,
        db,
        state,
        assignee_role: str,
        auth_token: str | None,
    ) -> None:
        plugin_service_policy.enforce_plugin_done_transition(
            plugin_key=_TEAM_MODE_PLUGIN_KEY,
            db=db,
            state=state,
            assignee_role=assignee_role,
            verify_delivery_workflow_fn=self.verify_delivery_workflow,
            auth_token=auth_token,
        )

    def verify_team_mode_workflow(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        expected_event_storming_enabled: bool | None = None,
    ) -> dict:
        plugin_result = plugin_service_policy.verify_plugin_workflow(
            plugin_key=_TEAM_MODE_PLUGIN_KEY,
            project_id=project_id,
            auth_token=auth_token,
            workspace_id=workspace_id,
            expected_event_storming_enabled=expected_event_storming_enabled,
            verify_workflow_core=self._verify_team_mode_workflow_core,
        )
        if isinstance(plugin_result, dict):
            return plugin_result
        return self._verify_team_mode_workflow_core(
            project_id=project_id,
            auth_token=auth_token,
            workspace_id=workspace_id,
            expected_event_storming_enabled=expected_event_storming_enabled,
        )

    def _verify_team_mode_workflow_core(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        expected_event_storming_enabled: bool | None = None,
    ) -> dict:
        from plugins.team_mode import service_orchestration as team_mode_service_orchestration

        return team_mode_service_orchestration.verify_workflow_core(
            self,
            project_id=project_id,
            auth_token=auth_token,
            workspace_id=workspace_id,
            expected_event_storming_enabled=expected_event_storming_enabled,
        )

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
            project_skills = db.execute(
                select(ProjectSkill).where(
                    ProjectSkill.project_id == project_id,
                    ProjectSkill.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            plugin_configs = db.execute(
                select(ProjectPluginConfig).where(
                    ProjectPluginConfig.workspace_id == str(project.workspace_id),
                    ProjectPluginConfig.project_id == project_id,
                    ProjectPluginConfig.plugin_key.in_(["team_mode", "git_delivery", "docker_compose"]),
                    ProjectPluginConfig.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            tasks = list(tasks_payload.get("items") or [])
            self._enrich_tasks_with_automation_state(db=db, tasks=tasks)
            runtime_context = _team_mode_runtime_context_for_project(
                db,
                workspace_id=str(project.workspace_id),
                project_id=project_id,
            )
        notes_by_task: dict[str, list[Note]] = {}
        for note in notes:
            task_id = str(note.task_id or "").strip()
            if task_id:
                notes_by_task.setdefault(task_id, []).append(note)
        comments_by_task: dict[str, list[TaskComment]] = {}
        for comment in comments:
            task_id = str(comment.task_id or "").strip()
            if task_id:
                comments_by_task.setdefault(task_id, []).append(comment)
        plugin_by_key = {
            str(getattr(row, "plugin_key", "") or "").strip(): row
            for row in plugin_configs
            if str(getattr(row, "plugin_key", "") or "").strip()
        }
        team_mode_row = plugin_by_key.get("team_mode")
        git_delivery_row = plugin_by_key.get("git_delivery")
        docker_compose_row = plugin_by_key.get("docker_compose")
        team_mode_enabled = bool(
            runtime_context.enabled
            if runtime_context is not None
            else getattr(team_mode_row, "enabled", False)
        )
        git_delivery_enabled = bool(getattr(git_delivery_row, "enabled", False))
        delivery_active = bool(git_delivery_enabled or team_mode_enabled)
        source_ids = [
            str(getattr(row, "id", "") or "").strip()
            for row in (git_delivery_row, docker_compose_row, team_mode_row)
            if row is not None and str(getattr(row, "id", "") or "").strip()
        ]
        plugin_policy_source = (
            f"project_plugin_config:{','.join(source_ids)}"
            if source_ids
            else "project_plugin_config:missing"
        )
        plugin_policy: dict[str, Any] = {}
        for row in (git_delivery_row, docker_compose_row, team_mode_row):
            if row is None:
                continue
            compiled = _effective_compiled_policy_from_row(
                plugin_key=str(getattr(row, "plugin_key", "") or "").strip(),
                config_json=str(getattr(row, "config_json", "") or "").strip(),
                compiled_policy_json=str(getattr(row, "compiled_policy_json", "") or "").strip(),
            )
            plugin_policy = merge_plugin_policy_dict(plugin_policy, compiled)
        effective_scopes = {"delivery"}
        if team_mode_enabled:
            effective_scopes.add("team_mode")
        plugin_policy = filter_plugin_policy_scopes(plugin_policy, include_scopes=effective_scopes)
        if not delivery_active:
            required_checks = dict((plugin_policy.get("required_checks") or {})) if isinstance(plugin_policy, dict) else {}
            required_checks["delivery"] = []
            plugin_policy = dict(plugin_policy) if isinstance(plugin_policy, dict) else {}
            plugin_policy["required_checks"] = required_checks
        verification = evaluate_delivery_checks(
            project_id=str(project_id),
            project_name=str(getattr(project, "name", "") or "").strip(),
            workspace_id=str(project.workspace_id),
            plugin_policy=plugin_policy,
            plugin_policy_source=plugin_policy_source,
            tasks=tasks,
            member_role_by_user_id=member_role_by_user_id,
            notes_by_task=notes_by_task,
            comments_by_task=comments_by_task,
            project_rules=project_rules,
            project_skills=project_skills,
            project_description=str(getattr(project, "description", "") or ""),
            project_external_refs=getattr(project, "external_refs", "[]"),
            team_mode_enabled=team_mode_enabled,
            extract_commit_shas_from_refs=self._extract_commit_shas_from_refs,
            parse_json_list=self._parse_json_list,
            has_http_external_ref=self._has_http_external_ref,
            resolve_deploy_target_from_artifacts=self._resolve_deploy_target_from_artifacts,
            run_runtime_deploy_health_check_fn=self._run_runtime_deploy_health_check,
            project_has_repo_context=lambda **kwargs: self._project_has_repo_context(allow_llm=False, **kwargs),
        )
        verification["check_reasons"] = {}
        required_checks = list(verification.get("required_checks") or [])
        checks_ok, required_failed = evaluate_required_policy_checks(verification["checks"], required_checks)
        verification["required_failed_checks"] = required_failed
        verification["ok"] = bool(checks_ok)
        verification["active"] = delivery_active
        verification["checks"] = dict(verification.get("checks") or {})
        verification["checks"]["git_delivery_enabled"] = bool(git_delivery_enabled)
        role_scoped_tasks = [
            task
            for task in tasks
            if str(
                (runtime_context.derive_workflow_role(
                    task_like={
                        "assignee_id": str(task.get("assignee_id") or "").strip(),
                        "assigned_agent_code": str(task.get("assigned_agent_code") or "").strip(),
                        "labels": task.get("labels"),
                        "status": str(task.get("status") or "").strip(),
                    }
                ) if runtime_context is not None else "")
                or ""
            ).strip()
            in {"Developer", "Lead", "QA"}
        ]
        has_kickoff_signal = any(
            bool(
                str(task.get("last_requested_source") or "").strip()
                or str(task.get("last_agent_run_at") or "").strip()
                or str(task.get("automation_state") or "").strip().lower() in {"queued", "running", "completed", "failed"}
            )
            for task in role_scoped_tasks
        )
        kickoff_required = bool(team_mode_enabled and role_scoped_tasks and not has_kickoff_signal)
        verification["kickoff_required"] = kickoff_required
        verification["kickoff_hint"] = (
            "Execution is not started yet. Start kickoff from chat when you are ready."
            if kickoff_required
            else "Kickoff already requested or execution has started."
        )
        return verification

    @staticmethod
    def _setup_error_payload(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, HTTPException):
            detail = exc.detail
            message: str
            if isinstance(detail, dict):
                message = str(detail.get("message") or detail)
            else:
                message = str(detail or f"HTTP {exc.status_code}")
            return {
                "type": "http_error",
                "status_code": int(exc.status_code),
                "message": message,
                "detail": detail,
            }
        return {
            "type": "runtime_error",
            "status_code": None,
            "message": str(exc),
            "detail": str(exc),
        }

    @staticmethod
    def _is_retryable_setup_error(error: dict[str, Any]) -> bool:
        status_code = error.get("status_code")
        if status_code is None:
            return False
        try:
            code = int(status_code)
        except Exception:
            return False
        return code in {409, 429, 500, 502, 503, 504}

    def _run_setup_step(
        self,
        *,
        steps: list[dict[str, Any]],
        blocking_errors: list[dict[str, Any]],
        step_id: str,
        title: str,
        action,
        blocking: bool = True,
        max_attempts: int = 1,
    ) -> Any | None:
        attempts = 0
        while attempts < max(1, int(max_attempts)):
            attempts += 1
            try:
                result = action()
                steps.append(
                    {
                        "id": step_id,
                        "title": title,
                        "status": "ok",
                        "blocking": bool(blocking),
                        "attempts": attempts,
                    }
                )
                return result
            except Exception as exc:
                error = self._setup_error_payload(exc)
                retryable = self._is_retryable_setup_error(error)
                if retryable and attempts < max(1, int(max_attempts)):
                    continue
                step_payload = {
                    "id": step_id,
                    "title": title,
                    "status": "error",
                    "blocking": bool(blocking),
                    "attempts": attempts,
                    "error": error,
                }
                steps.append(step_payload)
                if blocking:
                    blocking_errors.append(step_payload)
                return None
        return None

    @staticmethod
    def _append_skipped_setup_step(
        *,
        steps: list[dict[str, Any]],
        step_id: str,
        title: str,
        reason: str,
    ) -> None:
        steps.append(
            {
                "id": step_id,
                "title": title,
                "status": "skipped",
                "blocking": False,
                "attempts": 0,
                "reason": reason,
            }
        )

    @staticmethod
    def _normalize_optional_config_object(raw: dict[str, Any] | str | None, *, field_name: str) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str):
            parsed = _safe_json_loads_object(raw)
            if parsed:
                return parsed
            text = str(raw or "").strip()
            if text in {"{}", ""}:
                return {}
        raise HTTPException(status_code=422, detail=f"{field_name} must be an object or JSON object string")

    def _apply_plugin_config_with_retry(
        self,
        *,
        project_id: str,
        workspace_id: str,
        plugin_key: str,
        config: dict[str, Any],
        auth_token: str | None,
    ) -> dict[str, Any]:
        current = self.get_project_plugin_config(
            project_id=project_id,
            plugin_key=plugin_key,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        expected_version_raw = current.get("version")
        expected_version: int | None
        try:
            expected_version = int(expected_version_raw) if int(expected_version_raw) >= 1 else None
        except Exception:
            expected_version = None
        try:
            return self.apply_project_plugin_config(
                project_id=project_id,
                plugin_key=plugin_key,
                config=config,
                workspace_id=workspace_id,
                expected_version=expected_version,
                auth_token=auth_token,
            )
        except HTTPException as exc:
            detail_text = str(exc.detail or "")
            if int(exc.status_code) != 409 or "Version mismatch" not in detail_text:
                raise
            refreshed = self.get_project_plugin_config(
                project_id=project_id,
                plugin_key=plugin_key,
                workspace_id=workspace_id,
                auth_token=auth_token,
            )
            refreshed_version_raw = refreshed.get("version")
            try:
                refreshed_version = int(refreshed_version_raw) if int(refreshed_version_raw) >= 1 else None
            except Exception:
                refreshed_version = None
            return self.apply_project_plugin_config(
                project_id=project_id,
                plugin_key=plugin_key,
                config=config,
                workspace_id=workspace_id,
                expected_version=refreshed_version,
                auth_token=auth_token,
            )

    def _seed_team_mode_default_tasks(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None,
        command_id: str | None,
    ) -> dict[str, Any]:
        return {
            "created_task_ids": [],
            "seeded_at_utc": datetime.now(timezone.utc).isoformat(),
            "message": (
                "Team Mode no longer seeds role-specific default tasks. "
                "Create implementation tasks explicitly; runtime will move each task through the shared lifecycle."
            ),
        }

    def _derive_setup_backlog_strategy(
        self,
        *,
        starter_setup: dict[str, Any] | None,
        seed_team_tasks: bool,
    ) -> str:
        if not isinstance(starter_setup, dict):
            return "manual"
        return "starter_seeded" if bool(seed_team_tasks) else "custom_planned"

    def _validate_setup_kickoff_backlog_readiness(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None,
        backlog_strategy: str,
    ) -> dict[str, Any]:
        payload = self.list_tasks(
            workspace_id=workspace_id,
            project_id=project_id,
            archived=False,
            limit=500,
            offset=0,
            auth_token=auth_token,
        )
        tasks = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
        active_tasks = [
            item
            for item in tasks
            if str(item.get("task_type") or "manual").strip().lower() != "scheduled_instruction"
        ]
        if not active_tasks:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff requires at least one actionable implementation task. "
                    "Create the canonical task set first, then run kickoff."
                ),
            )

        title_counts: dict[str, int] = {}
        for item in active_tasks:
            normalized = " ".join(str(item.get("title") or "").strip().casefold().split())
            if not normalized:
                continue
            title_counts[normalized] = int(title_counts.get(normalized, 0) or 0) + 1
        duplicate_titles = [key for key, count in title_counts.items() if count > 1]
        if duplicate_titles:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: duplicate task titles detected. "
                    "Consolidate duplicate tasks before kickoff."
                ),
            )

        missing_delivery_mode = [
            str(item.get("id") or "").strip()
            for item in active_tasks
            if normalize_delivery_mode(item.get("delivery_mode")) is None
        ]
        if missing_delivery_mode:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: one or more tasks are missing delivery_mode. "
                    "Set delivery_mode on all implementation tasks before kickoff."
                ),
            )
        tasks_by_id = {
            str(item.get("id") or "").strip(): item
            for item in active_tasks
            if str(item.get("id") or "").strip()
        }
        impossible_dependency_messages: list[str] = []
        for item in active_tasks:
            task_id = str(item.get("id") or "").strip()
            if not task_id:
                continue
            relationships = normalize_task_relationships(item.get("task_relationships"))
            for relationship in relationships:
                if str(relationship.get("kind") or "").strip().lower() != "depends_on":
                    continue
                statuses = {
                    str(status or "").strip().casefold()
                    for status in (relationship.get("statuses") or [])
                    if str(status or "").strip()
                }
                if "deployed" not in statuses:
                    continue
                source_task_ids = [
                    str(source_task_id or "").strip()
                    for source_task_id in (relationship.get("task_ids") or [])
                    if str(source_task_id or "").strip() and str(source_task_id or "").strip() != task_id
                ]
                for source_task_id in source_task_ids:
                    source_task = tasks_by_id.get(source_task_id)
                    if not isinstance(source_task, dict):
                        continue
                    source_delivery_mode = normalize_delivery_mode(source_task.get("delivery_mode"))
                    if source_delivery_mode == "deployable_slice":
                        continue
                    impossible_dependency_messages.append(
                        (
                            f"Task {task_id} depends on deployed milestone from source {source_task_id}, "
                            f"but source delivery_mode is '{source_delivery_mode or 'unknown'}'."
                        )
                    )
        if impossible_dependency_messages:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: one or more dependency milestones are impossible for the "
                    "current delivery_mode configuration. "
                    + " ".join(impossible_dependency_messages[:6])
                ),
            )

        missing_scope = [
            str(item.get("id") or "").strip()
            for item in active_tasks
            if not str(item.get("instruction") or "").strip()
            and not str(item.get("description") or "").strip()
        ]
        if missing_scope:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: one or more tasks are missing instruction/description scope. "
                    "Add task scope details before kickoff."
                ),
            )

        seeded_count = 0
        custom_count = 0
        unlabeled_count = 0
        explicit_developer_routed_count = 0
        role_by_code: dict[str, str] = {}
        with SessionLocal() as db:
            runtime_context = _team_mode_runtime_context_for_project(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            if runtime_context is not None and runtime_context.enabled:
                role_by_code = runtime_context.agent_role_by_code
        for item in active_tasks:
            labels = self._normalize_string_list_input(item.get("labels"), field_name="labels")
            if not labels:
                unlabeled_count += 1
            if "starter-seeded" in labels:
                seeded_count += 1
            else:
                custom_count += 1
            assigned_agent_code = str(item.get("assigned_agent_code") or "").strip()
            if assigned_agent_code and role_by_code.get(assigned_agent_code) == "Developer":
                explicit_developer_routed_count += 1

        mixed_origin = bool(seeded_count > 0 and custom_count > 0)
        if mixed_origin and backlog_strategy in {"starter_seeded", "custom_planned"}:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: mixed starter-seeded and custom task sets detected. "
                    "Choose one strategy (starter-seeded or custom-planned), archive redundant tasks, then rerun kickoff."
                ),
            )
        if explicit_developer_routed_count <= 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Kickoff backlog validation failed: no task is explicitly routed to a Developer agent slot. "
                    "Assign at least one actionable task to dev-a/dev-b (or another configured Developer slot) before kickoff."
                ),
            )

        return {
            "ok": True,
            "active_task_count": len(active_tasks),
            "seeded_task_count": seeded_count,
            "custom_task_count": custom_count,
            "unlabeled_task_count": unlabeled_count,
            "explicit_developer_routed_count": explicit_developer_routed_count,
            "mixed_origin_detected": mixed_origin,
            "backlog_strategy": backlog_strategy,
        }

    def _maybe_backfill_team_mode_topology(
        self,
        *,
        workspace_id: str,
        project_id: str,
        specification_id: str | None,
        auth_token: str | None,
        command_id: str | None,
    ) -> None:
        if not specification_id:
            return
        with SessionLocal() as db:
            runtime_context = _team_mode_runtime_context_for_project(
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
                require_enabled=True,
            )
            if runtime_context is None:
                return
            docker_compose_enabled = plugin_service_policy.project_has_plugin_enabled(
                plugin_key="docker_compose",
                db=db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            task_rows = (
                db.query(Task)
                .filter(
                    Task.workspace_id == str(workspace_id),
                    Task.project_id == str(project_id),
                    Task.specification_id == str(specification_id),
                    Task.is_deleted == False,  # noqa: E712
                )
                .order_by(Task.created_at.asc(), Task.id.asc())
                .all()
            )
            developer_tasks: list[dict[str, Any]] = []
            for row in task_rows:
                task_like = {
                    "id": str(getattr(row, "id", "") or "").strip(),
                    "title": str(getattr(row, "title", "") or "").strip(),
                    "status": str(getattr(row, "status", "") or "").strip(),
                    "priority": str(getattr(row, "priority", "") or "").strip(),
                    "assigned_agent_code": str(getattr(row, "assigned_agent_code", "") or "").strip(),
                    "assignee_id": str(getattr(row, "assignee_id", "") or "").strip(),
                    "labels": getattr(row, "labels", None),
                    "task_relationships": normalize_task_relationships(getattr(row, "task_relationships", None)),
                    "delivery_mode": normalize_delivery_mode(getattr(row, "delivery_mode", None)),
                }
                if runtime_context.derive_workflow_role(task_like=task_like) != "Developer":
                    continue
                developer_tasks.append(task_like)
        if len(developer_tasks) < 2:
            return

        developer_tasks.sort(
            key=lambda task: (
                _priority_rank(task.get("priority")),
                str(task.get("id") or "").strip(),
            )
        )
        desired_relationships_by_task_id: dict[str, list[dict[str, Any]]] = {}
        for task in developer_tasks:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            existing_relationships = normalize_task_relationships(task.get("task_relationships"))
            task_rank = _priority_rank(task.get("priority"))
            dependency_ids = [
                str(candidate.get("id") or "").strip()
                for candidate in developer_tasks
                if str(candidate.get("id") or "").strip()
                and str(candidate.get("id") or "").strip() != task_id
                and _priority_rank(candidate.get("priority")) < task_rank
            ]
            if not dependency_ids:
                continue
            merged_existing = False
            normalized_existing: list[dict[str, Any]] = []
            for relationship in existing_relationships:
                if str(relationship.get("kind") or "").strip().lower() != "depends_on":
                    normalized_existing.append(relationship)
                    continue
                task_ids = [
                    str(item or "").strip()
                    for item in (relationship.get("task_ids") or [])
                    if str(item or "").strip()
                ]
                if not merged_existing:
                    task_ids = sorted({*task_ids, *dependency_ids})
                    normalized_existing.append(
                        {
                            "kind": "depends_on",
                            "task_ids": task_ids,
                            "match_mode": "all",
                            "statuses": ["merged"],
                        }
                    )
                    merged_existing = True
                else:
                    normalized_existing.append(relationship)
            if not merged_existing:
                normalized_existing.append(
                    {
                        "kind": "depends_on",
                        "task_ids": dependency_ids,
                        "match_mode": "all",
                        "statuses": ["merged"],
                    }
                )
            desired_relationships_by_task_id[task_id] = normalized_existing

        for task_id, relationships in desired_relationships_by_task_id.items():
            self.update_task(
                task_id=task_id,
                patch={"task_relationships": relationships},
                auth_token=auth_token,
                command_id=self._derive_child_command_id(
                    command_id or "tm-structural",
                    f"depends-on:{task_id[:8]}",
                ),
            )

        final_relationships_by_task_id: dict[str, list[dict[str, Any]]] = {
            str(task.get("id") or "").strip(): normalize_task_relationships(task.get("task_relationships"))
            for task in developer_tasks
            if str(task.get("id") or "").strip()
        }
        final_relationships_by_task_id.update(desired_relationships_by_task_id)
        dependency_sources: set[str] = set()
        for relationships in final_relationships_by_task_id.values():
            for relationship in relationships:
                if str(relationship.get("kind") or "").strip().lower() != "depends_on":
                    continue
                for source_task_id in (relationship.get("task_ids") or []):
                    normalized_source_task_id = str(source_task_id or "").strip()
                    if normalized_source_task_id:
                        dependency_sources.add(normalized_source_task_id)

        dependency_targets: set[str] = set(
            task_id
            for task_id, relationships in final_relationships_by_task_id.items()
            if any(str(relationship.get("kind") or "").strip().lower() == "depends_on" for relationship in relationships)
        )
        deployable_task_id: str | None = None
        if docker_compose_enabled and developer_tasks:
            leaf_candidates = [
                str(task.get("id") or "").strip()
                for task in developer_tasks
                if str(task.get("id") or "").strip() and str(task.get("id") or "").strip() not in dependency_sources
            ]
            if not leaf_candidates:
                leaf_candidates = [str(developer_tasks[-1].get("id") or "").strip()]
            ranked_candidates = [
                str(task.get("id") or "").strip()
                for task in developer_tasks
                if str(task.get("id") or "").strip() in set(leaf_candidates)
            ]
            deployable_task_id = ranked_candidates[-1] if ranked_candidates else None

        for task in developer_tasks:
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            if docker_compose_enabled:
                target_delivery_mode = "deployable_slice" if task_id == deployable_task_id else "merged_increment"
            else:
                target_delivery_mode = (
                    "merged_increment"
                    if task_id in dependency_sources
                    else "deployable_slice"
                )
            current_delivery_mode = normalize_delivery_mode(task.get("delivery_mode"))
            if current_delivery_mode == "merged_increment" and target_delivery_mode == "deployable_slice":
                # Preserve explicit non-deployable tasks. Auto-derivation should only
                # demote dependency-source tasks, not silently upgrade a task back into
                # the deployable lifecycle once another workflow path marked it otherwise.
                continue
            if current_delivery_mode == target_delivery_mode:
                continue
            self.update_task(
                task_id=task_id,
                patch={"delivery_mode": target_delivery_mode},
                auth_token=auth_token,
                command_id=self._derive_child_command_id(
                    command_id or "tm-structural",
                    f"delivery-mode:{task_id[:8]}",
                ),
            )
        return

    @staticmethod
    def _select_primary_team_mode_lead_task(lead_tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not lead_tasks:
            return None

        def _has_schedule_trigger(task: dict[str, Any]) -> bool:
            for trigger in (task.get("execution_triggers") or []):
                if not isinstance(trigger, dict):
                    continue
                if str(trigger.get("kind") or "").strip() == "schedule":
                    return True
            return False

        for task in lead_tasks:
            if not _has_schedule_trigger(task):
                return task
        return lead_tasks[0]

    def _normalize_team_mode_lead_schedule_triggers(
        self,
        *,
        workspace_id: str,
        project_id: str,
        lead_tasks: list[dict[str, Any]],
        auth_token: str | None,
        command_id: str | None,
    ) -> None:
        with SessionLocal() as db:
            status_semantics = _effective_team_mode_status_semantics_for_project(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        awaiting_decision_status = status_semantics["awaiting_decision"]

        for lead_task in lead_tasks:
            lead_task_id = str(lead_task.get("id") or "").strip()
            if not lead_task_id:
                continue
            execution_triggers = self._normalize_execution_triggers_input(lead_task.get("execution_triggers")) or []
            normalized_execution_triggers: list[dict[str, Any]] = []
            changed = False
            for trigger in execution_triggers:
                if not isinstance(trigger, dict):
                    continue
                trigger_payload = dict(trigger)
                if str(trigger_payload.get("kind") or "").strip() == "schedule":
                    run_on_statuses = [
                        str(item or "").strip()
                        for item in (trigger_payload.get("run_on_statuses") or [])
                        if str(item or "").strip()
                    ]
                    if run_on_statuses != [awaiting_decision_status]:
                        trigger_payload["run_on_statuses"] = [awaiting_decision_status]
                        changed = True
                normalized_execution_triggers.append(trigger_payload)
            if not changed:
                continue
            self.update_task(
                task_id=lead_task_id,
                patch={
                    "instruction": str(lead_task.get("instruction") or "").strip() or None,
                    "execution_triggers": normalized_execution_triggers,
                },
                auth_token=auth_token,
                command_id=self._derive_child_command_id(command_id, f"tm-schedule-{lead_task_id[:8]}"),
            )

    @staticmethod
    def _slugify_project_name(value: str, *, fallback: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        return normalized or fallback

    def _ensure_default_repository_context_for_project(
        self,
        *,
        project_id: str,
        workspace_id: str,
        project_name: str,
        auth_token: str | None,
        command_id: str | None,
    ) -> dict[str, Any]:
        try:
            repo_root = ensure_project_repository_initialized(
                project_name=str(project_name or "").strip(),
                project_id=str(project_id or "").strip(),
            )
        except Exception:
            repo_root = resolve_project_repository_path(
                project_name=str(project_name or "").strip(),
                project_id=str(project_id or "").strip(),
            )
        repo_path = str(repo_root)
        repo_url = f"file://{repo_path}"

        with SessionLocal() as db:
            project = self._load_project_scope(db=db, project_id=project_id)
            ensure_role(db, project.workspace_id, self._resolve_actor_user().id, {"Owner", "Admin", "Member"})
            refs = self._parse_json_list(getattr(project, "external_refs", "[]"))

        project_slug = self._slugify_project_name(str(project_name or "").strip(), fallback=str(project_id)[:8] or "project")
        existing_idx: int | None = None
        for idx, item in enumerate(refs):
            if not isinstance(item, dict):
                continue
            title_lower = str(item.get("title") or "").strip().lower()
            url_value = str(item.get("url") or "").strip()
            url_lower = url_value.lower()
            if title_lower in {"repository context", "repo context"}:
                existing_idx = idx
                break
            if url_lower.startswith("file://") and ("/home/app/workspace/" in url_lower or url_lower.endswith(f"/{project_slug}")):
                existing_idx = idx
                break

        desired = {
            "url": repo_url,
            "title": "Repository context",
            "source": "setup_orchestration_default",
        }

        changed = False
        if existing_idx is None:
            refs.append(desired)
            changed = True
        elif refs[existing_idx] != desired:
            refs[existing_idx] = desired
            changed = True

        if not changed:
            return {"updated": False, "repository_url": repo_url}

        self.update_project(
            project_id=project_id,
            patch={"external_refs": refs},
            auth_token=auth_token,
            command_id=self._derive_child_command_id(command_id, "repo-context"),
        )
        return {"updated": True, "repository_url": repo_url}

    def setup_project_orchestration(
        self,
        *,
        name: str | None = None,
        short_description: str = "",
        primary_starter_key: str | None = None,
        facet_keys: list[str] | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        enable_team_mode: bool | None = None,
        enable_git_delivery: bool | None = None,
        enable_docker_compose: bool | None = None,
        docker_port: int | None = None,
        team_mode_config: dict[str, Any] | str | None = None,
        git_delivery_config: dict[str, Any] | str | None = None,
        docker_compose_config: dict[str, Any] | str | None = None,
        expected_event_storming_enabled: bool | None = None,
        seed_team_tasks: bool = True,
        kickoff_after_setup: bool = False,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_token(auth_token)
        normalized_name = str(name or "").strip()
        normalized_project_id = str(project_id or "").strip()
        is_new_project_setup = not bool(normalized_project_id)
        starter_setup, normalized_facet_keys, retrieval_hints = self._resolve_starter_setup(
            primary_starter_key=primary_starter_key,
            facet_keys=facet_keys,
        )
        backlog_strategy = self._derive_setup_backlog_strategy(
            starter_setup=starter_setup,
            seed_team_tasks=bool(seed_team_tasks),
        )
        normalized_docker_port: int | None
        if docker_port is None:
            normalized_docker_port = None
        else:
            try:
                normalized_docker_port = int(docker_port)
            except Exception:
                raise HTTPException(status_code=422, detail="docker_port must be an integer")
            if normalized_docker_port < 1 or normalized_docker_port > 65535:
                raise HTTPException(status_code=422, detail="docker_port must be between 1 and 65535")
        docker_port = normalized_docker_port
        if docker_port is not None and enable_docker_compose is None:
            enable_docker_compose = True

        missing_inputs: list[dict[str, Any]] = []

        def _add_missing_input(
            *,
            key: str,
            question: str,
            value_type: str,
            options: list[str] | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "key": key,
                "question": question,
                "type": value_type,
            }
            if isinstance(options, list) and options:
                payload["options"] = list(options)
            missing_inputs.append(payload)

        if is_new_project_setup and starter_setup is None:
            _add_missing_input(
                key="primary_starter_key",
                question="Which project starter should be used?",
                value_type="string",
                options=[item.key for item in list_project_starters()],
            )

        if is_new_project_setup and not normalized_name:
            _add_missing_input(
                key="name",
                question="What should the new project be named?",
                value_type="string",
            )

        normalized_short_description = str(short_description or "").strip()
        if is_new_project_setup and not normalized_short_description:
            _add_missing_input(
                key="short_description",
                question="What should this project do in short?",
                value_type="string",
            )

        if is_new_project_setup and enable_team_mode is None:
            _add_missing_input(
                key="enable_team_mode",
                question="Do you want Team Mode for this project?",
                value_type="boolean",
                options=["yes", "no"],
            )

        effective_git_for_questions: bool | None = None
        if enable_team_mode is True:
            effective_git_for_questions = True
        elif enable_team_mode is False:
            if enable_git_delivery is None and is_new_project_setup:
                _add_missing_input(
                    key="enable_git_delivery",
                    question="Team Mode is off. Do you want Git Delivery?",
                    value_type="boolean",
                    options=["yes", "no"],
                )
            if enable_git_delivery is not None:
                effective_git_for_questions = bool(enable_git_delivery)
        elif enable_git_delivery is not None:
            effective_git_for_questions = bool(enable_git_delivery)

        if is_new_project_setup and effective_git_for_questions is True and enable_docker_compose is None:
            _add_missing_input(
                key="enable_docker_compose",
                question="Git Delivery is enabled. Should deployment run via Docker Compose?",
                value_type="boolean",
                options=["yes", "no"],
            )

        if (
            is_new_project_setup
            and effective_git_for_questions is True
            and enable_docker_compose is True
            and docker_port is None
        ):
            _add_missing_input(
                key="docker_port",
                question="Which port should Docker Compose use?",
                value_type="integer",
            )

        if missing_inputs:
            resolved_inputs = {
                "primary_starter_key": starter_setup["key"] if isinstance(starter_setup, dict) else None,
                "facet_keys": normalized_facet_keys,
                "name": normalized_name or None,
                "short_description": normalized_short_description or None,
                "enable_team_mode": enable_team_mode,
                "enable_git_delivery": enable_git_delivery,
                "enable_docker_compose": enable_docker_compose,
                "docker_port": docker_port,
            }
            setup_path = {
                "is_new_project": bool(is_new_project_setup),
                "primary_starter_key": starter_setup["key"] if isinstance(starter_setup, dict) else None,
                "facet_keys": normalized_facet_keys,
                "team_mode_selected": bool(enable_team_mode) if enable_team_mode is not None else None,
                "git_delivery_selected": (
                    bool(enable_git_delivery)
                    if enable_git_delivery is not None
                    else (True if enable_team_mode is True else None)
                ),
                "docker_compose_selected": bool(enable_docker_compose) if enable_docker_compose is not None else None,
            }
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Missing required setup inputs for setup_project_orchestration",
                    "code": "missing_setup_inputs",
                    "missing_inputs": missing_inputs,
                    "next_question": str(missing_inputs[0].get("question") or "").strip(),
                    "next_input_key": str(missing_inputs[0].get("key") or "").strip(),
                    "resolved_inputs": resolved_inputs,
                    "setup_path": setup_path,
                },
            )

        normalized_team_cfg = self._normalize_optional_config_object(team_mode_config, field_name="team_mode_config")
        normalized_git_cfg = self._normalize_optional_config_object(git_delivery_config, field_name="git_delivery_config")
        normalized_docker_cfg = self._normalize_optional_config_object(
            docker_compose_config,
            field_name="docker_compose_config",
        )

        steps: list[dict[str, Any]] = []
        blocking_errors: list[dict[str, Any]] = []
        created_project = False
        resolved_project_id = normalized_project_id
        resolved_workspace_id = str(workspace_id or "").strip() or None
        resolved_project_name = normalized_name or None

        if not normalized_project_id:
            created = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="create_project",
                title="Create project",
                blocking=True,
                max_attempts=2,
                action=lambda: self.create_project(
                    name=normalized_name,
                    description=short_description,
                    workspace_id=workspace_id,
                    auth_token=auth_token,
                    command_id=command_id,
                    event_storming_enabled=(
                        bool(expected_event_storming_enabled)
                        if expected_event_storming_enabled is not None
                        else True
                    ),
                ),
            )
            if isinstance(created, dict):
                resolved_project_id = str(created.get("id") or "").strip()
                resolved_workspace_id = str(created.get("workspace_id") or "").strip() or resolved_workspace_id
                resolved_project_name = str(created.get("name") or "").strip() or resolved_project_name
                created_project = bool(resolved_project_id)
        else:
            resolved = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="resolve_project",
                title="Resolve existing project",
                blocking=True,
                max_attempts=1,
                action=lambda: self.get_project_capabilities(
                    project_id=normalized_project_id,
                    workspace_id=workspace_id,
                    auth_token=auth_token,
                ),
            )
            if isinstance(resolved, dict):
                resolved_workspace_id = str(resolved.get("workspace_id") or "").strip() or resolved_workspace_id
                with SessionLocal() as db:
                    project_row = self._load_project_scope(db=db, project_id=normalized_project_id)
                    resolved_project_name = str(getattr(project_row, "name", "") or "").strip() or resolved_project_name

        if not resolved_project_id or not resolved_workspace_id:
            return {
                "contract_version": 1,
                "ok": False,
                "blocking": True,
                "execution_state": "setup_failed",
                "project": {
                    "id": resolved_project_id or None,
                    "workspace_id": resolved_workspace_id or None,
                    "name": resolved_project_name,
                    "created": created_project,
                    "link": f"?tab=projects&project={resolved_project_id}" if resolved_project_id else None,
                },
                "requested": {},
                "effective": {},
                "steps": steps,
                "verification": {},
                "errors": [item.get("error") for item in blocking_errors if isinstance(item.get("error"), dict)],
            }

        current_event_storming_enabled: bool | None = None
        with SessionLocal() as db:
            project_row = self._load_project_scope(db=db, project_id=resolved_project_id)
            current_event_storming_enabled = bool(getattr(project_row, "event_storming_enabled", True))

        if not blocking_errors and expected_event_storming_enabled is not None:
            if current_event_storming_enabled != bool(expected_event_storming_enabled):
                updated_project = self._run_setup_step(
                    steps=steps,
                    blocking_errors=blocking_errors,
                    step_id="apply_project_event_storming_setting",
                    title="Apply Event Storming setting",
                    blocking=True,
                    max_attempts=1,
                    action=lambda: self.update_project(
                        project_id=resolved_project_id,
                        patch={"event_storming_enabled": bool(expected_event_storming_enabled)},
                        auth_token=auth_token,
                        command_id=command_id,
                    ),
                )
                if isinstance(updated_project, dict):
                    current_event_storming_enabled = bool(updated_project.get("event_storming_enabled"))
            else:
                self._append_skipped_setup_step(
                    steps=steps,
                    step_id="apply_project_event_storming_setting",
                    title="Apply Event Storming setting",
                    reason="Project already matches requested Event Storming setting",
                )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="apply_project_event_storming_setting",
                title="Apply Event Storming setting",
                reason="No explicit Event Storming target was requested",
            )

        setup_profile: dict[str, Any] | None = None
        if not blocking_errors and isinstance(starter_setup, dict):
            def _persist_setup_profile() -> dict[str, Any]:
                with SessionLocal() as db:
                    return ProjectStarterApplicationService(db, self._resolve_actor_user()).upsert_setup_profile(
                        project_id=resolved_project_id,
                        workspace_id=resolved_workspace_id,
                        primary_starter_key=starter_setup["key"],
                        facet_keys=normalized_facet_keys,
                        resolved_inputs={
                            "name": normalized_name,
                            "short_description": normalized_short_description,
                            "primary_starter_key": starter_setup["key"],
                            "facet_keys": normalized_facet_keys,
                            "enable_team_mode": enable_team_mode,
                            "enable_git_delivery": enable_git_delivery,
                            "enable_docker_compose": enable_docker_compose,
                            "docker_port": docker_port,
                            "expected_event_storming_enabled": expected_event_storming_enabled,
                        },
                        retrieval_hints=retrieval_hints,
                    )

            setup_profile = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="persist_setup_profile",
                title="Persist starter setup profile",
                blocking=True,
                max_attempts=2,
                action=_persist_setup_profile,
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="persist_setup_profile",
                title="Persist starter setup profile",
                reason="No starter setup profile was requested",
            )

        starter_artifacts: dict[str, Any] | None = None
        if (
            not blocking_errors
            and created_project
            and isinstance(starter_setup, dict)
            and backlog_strategy == "starter_seeded"
        ):
            def _bootstrap_starter_artifacts() -> dict[str, Any]:
                with SessionLocal() as db:
                    return ProjectStarterApplicationService(db, self._resolve_actor_user()).bootstrap_starter_artifacts(
                        project_id=resolved_project_id,
                        workspace_id=resolved_workspace_id,
                        starter=starter_setup["definition"],
                    )

            starter_artifacts = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="bootstrap_starter_artifacts",
                title="Bootstrap starter artifacts",
                blocking=False,
                max_attempts=1,
                action=_bootstrap_starter_artifacts,
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="bootstrap_starter_artifacts",
                title="Bootstrap starter artifacts",
                reason=(
                    "Starter artifacts are skipped unless backlog strategy is starter_seeded "
                    "for a newly created starter-driven project."
                ),
            )

        if not blocking_errors and created_project and isinstance(starter_setup, dict):
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="apply_starter_statuses",
                title="Apply starter default statuses",
                blocking=False,
                max_attempts=1,
                action=lambda: self.update_project(
                    project_id=resolved_project_id,
                    patch={"custom_statuses": starter_setup["default_custom_statuses"]},
                    auth_token=auth_token,
                    command_id=self._derive_child_command_id(command_id, "starter-statuses"),
                ),
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="apply_starter_statuses",
                title="Apply starter default statuses",
                reason="Starter default statuses apply only when a new starter-driven project is created",
            )

        capabilities = self._run_setup_step(
            steps=steps,
            blocking_errors=blocking_errors,
            step_id="read_capabilities",
            title="Read current plugin capabilities",
            blocking=True,
            max_attempts=1,
            action=lambda: self.get_project_capabilities(
                project_id=resolved_project_id,
                workspace_id=resolved_workspace_id,
                auth_token=auth_token,
            ),
        )
        plugin_state = {
            "team_mode": False,
            "git_delivery": False,
            "docker_compose": False,
        }
        if isinstance(capabilities, dict):
            caps = capabilities.get("capabilities") if isinstance(capabilities.get("capabilities"), dict) else {}
            plugin_state = {
                "team_mode": bool(caps.get("team_mode")),
                "git_delivery": bool(caps.get("git_delivery")),
                "docker_compose": bool(caps.get("docker_compose")),
            }

        requested_team = plugin_state["team_mode"] if enable_team_mode is None else bool(enable_team_mode)
        requested_git = plugin_state["git_delivery"] if enable_git_delivery is None else bool(enable_git_delivery)
        requested_docker = plugin_state["docker_compose"] if enable_docker_compose is None else bool(enable_docker_compose)
        adjustments: list[str] = []
        if requested_team and not requested_git:
            requested_git = True
            adjustments.append("Git Delivery was auto-enabled because Team Mode is enabled.")
        if requested_docker and not requested_git:
            validation_error = {
                "type": "validation_error",
                "status_code": 422,
                "message": "docker_compose requires git_delivery enabled",
                "detail": "Enable git_delivery or disable docker_compose.",
            }
            steps.append(
                {
                    "id": "validate_plugin_dependencies",
                    "title": "Validate plugin dependencies",
                    "status": "error",
                    "blocking": True,
                    "attempts": 1,
                    "error": validation_error,
                }
            )
            blocking_errors.append({"error": validation_error})

        requested = {
            "primary_starter_key": starter_setup["key"] if isinstance(starter_setup, dict) else None,
            "facet_keys": normalized_facet_keys,
            "team_mode_enabled": requested_team,
            "git_delivery_enabled": requested_git,
            "docker_compose_enabled": requested_docker,
            "docker_port": docker_port,
            "seed_team_tasks": bool(seed_team_tasks),
            "backlog_strategy": backlog_strategy,
            "kickoff_after_setup": bool(kickoff_after_setup),
        }

        def _align_project_team_mode_statuses() -> dict[str, Any]:
            with SessionLocal() as db:
                project_state = self._load_project_scope(db=db, project_id=resolved_project_id)
                raw_statuses = []
                try:
                    raw_statuses = json.loads(str(getattr(project_state, "custom_statuses", "") or "").strip() or "[]")
                except Exception:
                    raw_statuses = []
            current_statuses = self._normalize_custom_statuses(raw_statuses) or []
            required_statuses = [
                REQUIRED_SEMANTIC_STATUSES["todo"],
                REQUIRED_SEMANTIC_STATUSES["active"],
                REQUIRED_SEMANTIC_STATUSES["in_review"],
                REQUIRED_SEMANTIC_STATUSES["awaiting_decision"],
                REQUIRED_SEMANTIC_STATUSES["blocked"],
                REQUIRED_SEMANTIC_STATUSES["completed"],
            ]
            next_statuses = list(current_statuses)
            for status in required_statuses:
                if status not in next_statuses:
                    next_statuses.append(status)
            if next_statuses == current_statuses:
                return {"updated": False, "custom_statuses": current_statuses}
            updated = self.update_project(
                project_id=resolved_project_id,
                patch={"custom_statuses": next_statuses},
                auth_token=auth_token,
                command_id=self._derive_child_command_id(command_id, "align-team-mode-statuses"),
            )
            adjustments.append(
                "Project board statuses were aligned to the required Team Mode lifecycle: "
                + ", ".join(required_statuses)
                + "."
            )
            return {"updated": True, "project": updated, "custom_statuses": next_statuses}

        if not blocking_errors:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="set_plugin_team_mode",
                title="Set Team Mode plugin enabled",
                blocking=True,
                max_attempts=2,
                action=lambda: self.set_project_plugin_enabled(
                    project_id=resolved_project_id,
                    plugin_key="team_mode",
                    enabled=requested_team,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                ),
            )
        if not blocking_errors:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="set_plugin_git_delivery",
                title="Set Git Delivery plugin enabled",
                blocking=True,
                max_attempts=2,
                action=lambda: self.set_project_plugin_enabled(
                    project_id=resolved_project_id,
                    plugin_key="git_delivery",
                    enabled=requested_git,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                ),
            )
        if not blocking_errors:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="set_plugin_docker_compose",
                title="Set Docker Compose plugin enabled",
                blocking=True,
                max_attempts=2,
                action=lambda: self.set_project_plugin_enabled(
                    project_id=resolved_project_id,
                    plugin_key="docker_compose",
                    enabled=requested_docker,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                ),
            )

        if not blocking_errors and requested_team:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="align_project_team_mode_statuses",
                title="Align project board statuses",
                blocking=True,
                max_attempts=1,
                action=_align_project_team_mode_statuses,
            )

        if not blocking_errors and requested_team:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="apply_config_team_mode",
                title="Apply Team Mode config",
                blocking=True,
                max_attempts=2,
                action=lambda: self._apply_plugin_config_with_retry(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    plugin_key="team_mode",
                    config=normalized_team_cfg or _team_mode_default_config(),
                    auth_token=auth_token,
                ),
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="apply_config_team_mode",
                title="Apply Team Mode config",
                reason="Team Mode is disabled",
            )

        if not blocking_errors and requested_git:
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="apply_config_git_delivery",
                title="Apply Git Delivery config",
                blocking=True,
                max_attempts=2,
                action=lambda: self._apply_plugin_config_with_retry(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    plugin_key="git_delivery",
                    config=normalized_git_cfg or _git_delivery_default_config(),
                    auth_token=auth_token,
                ),
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="apply_config_git_delivery",
                title="Apply Git Delivery config",
                reason="Git Delivery is disabled",
            )

        repository_context_result: dict[str, Any] | None = None
        if not blocking_errors and requested_git:
            repo_ctx = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="ensure_default_repository_context",
                title="Ensure default repository context",
                blocking=False,
                max_attempts=1,
                action=lambda: self._ensure_default_repository_context_for_project(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    project_name=resolved_project_name or resolved_project_id,
                    auth_token=auth_token,
                    command_id=command_id,
                ),
            )
            if isinstance(repo_ctx, dict):
                repository_context_result = repo_ctx
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="ensure_default_repository_context",
                title="Ensure default repository context",
                reason="Git Delivery is disabled",
            )

        if not blocking_errors and requested_docker:
            docker_default = _docker_compose_default_config(port=docker_port)
            runtime_default = docker_default.get("runtime_deploy_health")
            if isinstance(runtime_default, dict):
                runtime_default["required"] = True
            if normalized_docker_cfg:
                runtime = normalized_docker_cfg.get("runtime_deploy_health")
                if isinstance(runtime, dict):
                    runtime["required"] = True
                    if docker_port is not None:
                        runtime["port"] = int(docker_port)
                elif docker_port is not None:
                    normalized_docker_cfg["runtime_deploy_health"] = {
                        "required": True,
                        "stack": "constructos-ws-default",
                        "port": int(docker_port),
                        "health_path": "/health",
                        "require_http_200": True,
                    }
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="apply_config_docker_compose",
                title="Apply Docker Compose config",
                blocking=True,
                max_attempts=2,
                action=lambda: self._apply_plugin_config_with_retry(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    plugin_key="docker_compose",
                    config=normalized_docker_cfg or docker_default,
                    auth_token=auth_token,
                ),
            )
            self._append_skipped_setup_step(
                steps=steps,
                step_id="ensure_default_docker_compose_manifest",
                title="Ensure default docker compose manifest",
                reason=(
                    "Disabled by policy: Lead deploy automation must synthesize compose "
                    "from repository evidence instead of using starter manifests."
                ),
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="apply_config_docker_compose",
                title="Apply Docker Compose config",
                reason="Docker Compose is disabled",
            )
            self._append_skipped_setup_step(
                steps=steps,
                step_id="ensure_default_docker_compose_manifest",
                title="Ensure default docker compose manifest",
                reason="Docker Compose is disabled",
            )

        seeded_entities: dict[str, Any] = {}
        existing_project_tasks = self.list_tasks(
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            auth_token=auth_token,
            archived=False,
            limit=10,
            offset=0,
        )
        existing_task_count = len(existing_project_tasks.get("items") or []) if isinstance(existing_project_tasks, dict) else 0
        if not blocking_errors and requested_team and bool(seed_team_tasks):
            if existing_task_count > 0:
                self._append_skipped_setup_step(
                    steps=steps,
                    step_id="seed_team_mode_tasks",
                    title="Seed Team Mode default tasks",
                    reason="Project already contains tasks; default Team Mode seeding was skipped to preserve the requested task set",
                )
            else:
                seeded = self._run_setup_step(
                    steps=steps,
                    blocking_errors=blocking_errors,
                    step_id="seed_team_mode_tasks",
                    title="Seed Team Mode default tasks",
                    blocking=True,
                    max_attempts=1,
                    action=lambda: self._seed_team_mode_default_tasks(
                        workspace_id=resolved_workspace_id,
                        project_id=resolved_project_id,
                        auth_token=auth_token,
                        command_id=command_id,
                    ),
                )
                if isinstance(seeded, dict):
                    seeded_entities["team_mode_tasks"] = seeded
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="seed_team_mode_tasks",
                title="Seed Team Mode default tasks",
                reason="Team Mode is disabled or task seeding is disabled",
            )

        if not blocking_errors and requested_docker and bool(kickoff_after_setup):
            self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="validate_runtime_deploy_health_contract",
                title="Validate runtime deploy health contract",
                blocking=True,
                max_attempts=1,
                action=lambda: self._validate_setup_runtime_deploy_health_contract(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                ),
            )
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="validate_runtime_deploy_health_contract",
                title="Validate runtime deploy health contract",
                reason="Docker Compose is disabled or kickoff_after_setup is disabled",
            )

        backlog_validation_result: dict[str, Any] | None = None
        if not blocking_errors and requested_team and bool(kickoff_after_setup):
            validated_backlog = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="validate_kickoff_backlog_readiness",
                title="Validate kickoff backlog readiness",
                blocking=True,
                max_attempts=1,
                action=lambda: self._validate_setup_kickoff_backlog_readiness(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    auth_token=auth_token,
                    backlog_strategy=backlog_strategy,
                ),
            )
            if isinstance(validated_backlog, dict):
                backlog_validation_result = validated_backlog
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="validate_kickoff_backlog_readiness",
                title="Validate kickoff backlog readiness",
                reason="kickoff_after_setup is disabled or Team Mode is not active",
            )

        kickoff_result: dict[str, Any] | None = None
        if not blocking_errors and requested_team and bool(kickoff_after_setup):
            kicked = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="dispatch_team_mode_kickoff",
                title="Dispatch Team Mode kickoff",
                blocking=True,
                max_attempts=1,
                action=lambda: self._dispatch_team_mode_kickoff_after_setup(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    auth_token=auth_token,
                    command_id=command_id,
                ),
            )
            if isinstance(kicked, dict):
                kickoff_result = kicked
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="dispatch_team_mode_kickoff",
                title="Dispatch Team Mode kickoff",
                reason="kickoff_after_setup is disabled or Team Mode is not active",
            )

        verification: dict[str, Any] = {}
        if not blocking_errors and requested_team:
            verify_team = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="verify_team_mode_workflow",
                title="Verify Team Mode workflow",
                blocking=False,
                max_attempts=1,
                action=lambda: self.verify_team_mode_workflow(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                    expected_event_storming_enabled=expected_event_storming_enabled,
                ),
            )
            if isinstance(verify_team, dict):
                verification["team_mode"] = verify_team
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="verify_team_mode_workflow",
                title="Verify Team Mode workflow",
                reason="Team Mode is disabled",
            )

        if not blocking_errors and requested_git:
            verify_delivery = self._run_setup_step(
                steps=steps,
                blocking_errors=blocking_errors,
                step_id="verify_delivery_workflow",
                title="Verify delivery workflow",
                blocking=False,
                max_attempts=1,
                action=lambda: self.verify_delivery_workflow(
                    project_id=resolved_project_id,
                    workspace_id=resolved_workspace_id,
                    auth_token=auth_token,
                ),
            )
            if isinstance(verify_delivery, dict):
                verification["delivery"] = verify_delivery
        else:
            self._append_skipped_setup_step(
                steps=steps,
                step_id="verify_delivery_workflow",
                title="Verify delivery workflow",
                reason="Git Delivery is disabled",
            )

        final_configs: dict[str, Any] = {}
        docker_runtime_target: dict[str, Any] | None = None
        for key in ("team_mode", "git_delivery", "docker_compose"):
            payload = self.get_project_plugin_config(
                project_id=resolved_project_id,
                plugin_key=key,
                workspace_id=resolved_workspace_id,
                auth_token=auth_token,
            )
            final_configs[key] = {
                "enabled": bool(payload.get("enabled")),
                "version": int(payload.get("version") or 0),
                "exists": bool(payload.get("exists")),
            }
            if key == "docker_compose":
                config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
                runtime = config.get("runtime_deploy_health") if isinstance(config.get("runtime_deploy_health"), dict) else {}
                stack = str(runtime.get("stack") or "").strip() or "constructos-ws-default"
                host = str(runtime.get("host") or "gateway").strip() or "gateway"
                health_path = str(runtime.get("health_path") or "").strip() or "/health"
                if not health_path.startswith("/"):
                    health_path = f"/{health_path}"
                raw_port = runtime.get("port")
                try:
                    runtime_port = int(raw_port) if raw_port is not None else None
                except Exception:
                    runtime_port = None
                docker_runtime_target = {
                    "stack": stack,
                    "port": runtime_port,
                    "health_path": health_path,
                    "endpoint": (
                        f"http://{host}:{runtime_port}{health_path}"
                        if runtime_port is not None
                        else None
                    ),
                }

        blocking = bool(blocking_errors)
        delivery_required_for_success = bool(kickoff_after_setup)
        workflow_ok = True
        if requested_team:
            workflow_ok = workflow_ok and bool((verification.get("team_mode") or {}).get("ok"))
        if requested_git and delivery_required_for_success:
            workflow_ok = workflow_ok and bool((verification.get("delivery") or {}).get("ok"))

        def _failed_checks_with_descriptions(scope_payload: dict[str, Any] | None) -> list[dict[str, str]]:
            payload = scope_payload if isinstance(scope_payload, dict) else {}
            failed_ids = [str(item or "").strip() for item in (payload.get("required_failed_checks") or []) if str(item or "").strip()]
            descriptions = payload.get("check_descriptions") if isinstance(payload.get("check_descriptions"), dict) else {}
            results: list[dict[str, str]] = []
            for check_id in failed_ids:
                results.append(
                    {
                        "id": check_id,
                        "description": str(descriptions.get(check_id) or "Verification requirement is not satisfied.").strip(),
                    }
                )
            return results

        team_verification = verification.get("team_mode") if isinstance(verification.get("team_mode"), dict) else {}
        delivery_verification = verification.get("delivery") if isinstance(verification.get("delivery"), dict) else {}
        status_semantics_payload = (
            team_verification.get("plugin_policy")
            if isinstance(team_verification.get("plugin_policy"), dict)
            else delivery_verification.get("plugin_policy")
            if isinstance(delivery_verification.get("plugin_policy"), dict)
            else {}
        )
        status_semantics = (
            status_semantics_payload.get("status_semantics")
            if isinstance(status_semantics_payload.get("status_semantics"), dict)
            else {}
        )

        kickoff_dispatched = bool((kickoff_result or {}).get("kickoff_dispatched"))
        developer_dispatch_confirmed = bool((kickoff_result or {}).get("developer_dispatch_confirmed"))
        kickoff_queued_by_role = (
            dict(kickoff_result.get("queued_by_role") or {})
            if isinstance(kickoff_result, dict) and isinstance(kickoff_result.get("queued_by_role"), dict)
            else {"Developer": 0, "Lead": 0, "QA": 0}
        )
        queued_dev = int(kickoff_queued_by_role.get("Developer", 0) or 0)
        queued_lead = int(kickoff_queued_by_role.get("Lead", 0) or 0)
        queued_qa = int(kickoff_queued_by_role.get("QA", 0) or 0)
        kickoff_required = (
            (not bool(kickoff_after_setup))
            or (bool(kickoff_after_setup) and (not kickoff_dispatched or not developer_dispatch_confirmed))
        )
        kickoff_in_progress = bool(kickoff_after_setup) and kickoff_dispatched and not developer_dispatch_confirmed
        kickoff_hint = (
            "Kickoff was dispatched and Developer execution started as part of setup."
            if (bool(kickoff_after_setup) and kickoff_dispatched and developer_dispatch_confirmed)
            else "Kickoff was dispatched and is still propagating to Developer execution."
            if kickoff_in_progress
            else str((kickoff_result or {}).get("comment") or "").strip()
            if (bool(kickoff_after_setup) and kickoff_result is not None)
            else "Start execution only when ready by running kickoff from chat."
        )
        kickoff_state_message = (
            "Kickoff is running and Developer execution started; QA waits for explicit Lead handoff."
            if (kickoff_dispatched and developer_dispatch_confirmed)
            else "Kickoff is in progress. Developer execution has not started yet, and QA will wait for the later Lead handoff."
            if kickoff_in_progress
            else "Kickoff was requested, but no Developer task started yet."
            if kickoff_dispatched
            else "Kickoff has not started yet."
        )
        setup_verification_ok = bool((not blocking) and ((not requested_team) or bool(team_verification.get("ok"))))
        setup_verification_status = "PASS" if setup_verification_ok else "Needs attention"
        delivery_ok = bool(delivery_verification.get("ok")) if requested_git else None
        delivery_verification_status = (
            "PASS"
            if delivery_ok is True
            else "Needs attention"
            if delivery_ok is False
            else "Not requested"
        )
        blocking_state = {
            "code": (
                "setup_blocked"
                if blocking
                else "kickoff_in_progress"
                if kickoff_in_progress
                else "delivery_pending"
                if requested_git and delivery_required_for_success and delivery_ok is False
                else "execution_not_started"
                if kickoff_required
                else "none"
            ),
            "message": (
                "Blocking setup errors are present."
                if blocking
                else "No setup blockers. Kickoff is still propagating to Developer execution."
                if kickoff_in_progress
                else "No setup blockers. Delivery requirements are not satisfied yet."
                if requested_git and delivery_required_for_success and delivery_ok is False
                else "No setup blockers. Execution has not started yet."
                if kickoff_required
                else "No blockers detected."
            ),
        }

        task_snapshot_payload = self.list_tasks(
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            archived=False,
            limit=500,
            offset=0,
            auth_token=auth_token,
        )
        task_snapshot_items = (
            [item for item in (task_snapshot_payload.get("items") or []) if isinstance(item, dict)]
            if isinstance(task_snapshot_payload, dict)
            else []
        )
        by_status: dict[str, int] = {}
        by_semantic_status = {
            "todo": 0,
            "active": 0,
            "in_review": 0,
            "awaiting_decision": 0,
            "blocked": 0,
            "completed": 0,
            "unknown": 0,
        }
        semantic_to_status_name = {
            str(key or "").strip(): str(value or "").strip().casefold()
            for key, value in status_semantics.items()
            if str(key or "").strip() and str(value or "").strip()
        }
        for item in task_snapshot_items:
            raw_status = str(item.get("status") or "").strip() or "Unspecified"
            by_status[raw_status] = int(by_status.get(raw_status, 0) or 0) + 1
            normalized = raw_status.casefold()
            matched_semantic = None
            for semantic_key in ("todo", "active", "in_review", "awaiting_decision", "blocked", "completed"):
                expected = semantic_to_status_name.get(semantic_key)
                if expected and normalized == expected:
                    matched_semantic = semantic_key
                    break
            if matched_semantic is None:
                by_semantic_status["unknown"] = int(by_semantic_status.get("unknown", 0) or 0) + 1
            else:
                by_semantic_status[matched_semantic] = int(by_semantic_status.get(matched_semantic, 0) or 0) + 1

        lifecycle_notice = None
        if requested_team and len(task_snapshot_items) == 0:
            lifecycle_notice = (
                "No active tasks are currently persisted in this project. "
                "If tasks were archived/removed or the workspace was recreated, previous execution progress is invalidated. "
                "Create or restore tasks, then run kickoff again."
            )

        user_facing_summary = {
            "project_link": f"?tab=projects&project={resolved_project_id}",
            "configured": {
                "team_mode_enabled": bool(final_configs.get("team_mode", {}).get("enabled")),
                "git_delivery_enabled": bool(final_configs.get("git_delivery", {}).get("enabled")),
                "docker_compose_enabled": bool(final_configs.get("docker_compose", {}).get("enabled")),
                "docker_port": int(docker_port) if docker_port is not None else None,
                "repository_url": (
                    str(repository_context_result.get("repository_url") or "").strip()
                    if isinstance(repository_context_result, dict)
                    else None
                ),
                "event_storming_enabled": current_event_storming_enabled,
                "runtime_deploy_target": docker_runtime_target,
                "primary_starter_key": setup_profile.get("primary_starter_key") if isinstance(setup_profile, dict) else None,
                "facet_keys": setup_profile.get("facet_keys") if isinstance(setup_profile, dict) else [],
                "backlog_strategy": backlog_strategy,
            },
            "kickoff_required": kickoff_required,
            "kickoff_hint": kickoff_hint or "Start execution only when ready by running kickoff from chat.",
            "kickoff_state": {
                "mode": "lead_first",
                "dispatched": kickoff_dispatched,
                "queued_by_role": {
                    "Developer": queued_dev,
                    "Lead": queued_lead,
                    "QA": queued_qa,
                },
                "developer_dispatch_confirmed": developer_dispatch_confirmed,
                "qa_waiting_for_lead_handoff": bool(
                    kickoff_dispatched and developer_dispatch_confirmed and queued_qa == 0 and queued_lead > 0
                ),
                "message": kickoff_state_message,
            },
            "verification": {
                "setup_status": setup_verification_status,
                "team_mode_ok": bool(team_verification.get("ok")) if requested_team else None,
                "team_mode_failed_requirements": _failed_checks_with_descriptions(team_verification),
                "delivery_status": delivery_verification_status,
                "delivery_ok": delivery_ok,
                "delivery_required_for_success": delivery_required_for_success,
                "delivery_failed_requirements": (
                    []
                    if kickoff_in_progress
                    else _failed_checks_with_descriptions(delivery_verification)
                ),
            },
            "blocking_state": blocking_state,
            "execution_snapshot": {
                "total_tasks": len(task_snapshot_items),
                "by_status": by_status,
                "by_semantic_status": by_semantic_status,
            },
            "backlog_validation": backlog_validation_result,
            "next_action_hint": (
                "Setup is complete and kickoff dispatched Developer execution."
                if (bool(kickoff_after_setup) and kickoff_dispatched and developer_dispatch_confirmed and (not blocking and workflow_ok))
                else "Setup is complete. Kickoff is running and the first Developer handoff is still pending."
                if kickoff_in_progress
                else "Setup is complete, but kickoff did not start Developer execution. Review the kickoff blocker before treating execution as started."
                if (bool(kickoff_after_setup) and kickoff_dispatched and not developer_dispatch_confirmed)
                else "Setup is complete. Execution is not started automatically; run kickoff when you want the team to start implementation."
                if ((not blocking and workflow_ok) and (not bool(kickoff_after_setup) or not kickoff_dispatched))
                else "Some required checks failed. Review failed requirements and apply the suggested fixes before execution."
            ),
        }
        if lifecycle_notice:
            user_facing_summary["lifecycle_notice"] = lifecycle_notice
        if kickoff_result is not None:
            user_facing_summary["kickoff"] = {
                "ok": bool(kickoff_result.get("ok")),
                "summary": str(kickoff_result.get("summary") or "").strip(),
                "comment": str(kickoff_result.get("comment") or "").strip() or None,
                "queued_task_ids": list(kickoff_result.get("queued_task_ids") or []),
                "queued_by_role": dict(kickoff_result.get("queued_by_role") or {}),
                "developer_dispatch_confirmed": developer_dispatch_confirmed,
                "developer_active_task_ids": list(kickoff_result.get("developer_active_task_ids") or []),
            }
        if isinstance(setup_profile, dict):
            user_facing_summary["setup_profile"] = setup_profile

        if isinstance(starter_artifacts, dict):
            seeded_entities["starter_artifacts"] = starter_artifacts

        return {
            "contract_version": 1,
            "ok": (not blocking) and bool(workflow_ok),
            "blocking": blocking,
            "execution_state": "setup_complete" if (not blocking) else "setup_failed",
            "project": {
                "id": resolved_project_id,
                "workspace_id": resolved_workspace_id,
                "name": resolved_project_name,
                "created": created_project,
                "link": f"?tab=projects&project={resolved_project_id}",
            },
            "requested": requested,
            "effective": {
                "primary_starter_key": setup_profile.get("primary_starter_key") if isinstance(setup_profile, dict) else None,
                "facet_keys": setup_profile.get("facet_keys") if isinstance(setup_profile, dict) else [],
                "retrieval_hints": setup_profile.get("retrieval_hints") if isinstance(setup_profile, dict) else [],
                "backlog_strategy": backlog_strategy,
                "team_mode_enabled": bool(final_configs.get("team_mode", {}).get("enabled")),
                "git_delivery_enabled": bool(final_configs.get("git_delivery", {}).get("enabled")),
                "docker_compose_enabled": bool(final_configs.get("docker_compose", {}).get("enabled")),
            },
            "plugins": final_configs,
            "seeded_entities": seeded_entities,
            "verification": verification,
            "steps": steps,
            "adjustments": adjustments,
            "errors": [item.get("error") for item in blocking_errors if isinstance(item.get("error"), dict)],
            "user_facing_summary": user_facing_summary,
            "kickoff": kickoff_result,
        }

    def _dispatch_team_mode_kickoff_after_setup(
        self,
        *,
        workspace_id: str,
        project_id: str,
        auth_token: str | None,
        command_id: str | None,
    ) -> dict[str, Any]:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        stack = "constructos-ws-default"
        host = "gateway"
        port: int | None = None
        health_path = "/health"

        docker_payload = self.get_project_plugin_config(
            project_id=project_id,
            plugin_key="docker_compose",
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        docker_cfg = docker_payload.get("config") if isinstance(docker_payload, dict) else {}
        runtime_cfg = docker_cfg.get("runtime_deploy_health") if isinstance(docker_cfg, dict) else {}
        if not isinstance(runtime_cfg, dict):
            runtime_cfg = {}
        stack_candidate = str(runtime_cfg.get("stack") or "").strip()
        if stack_candidate:
            stack = stack_candidate
        host_candidate = str(runtime_cfg.get("host") or "").strip()
        if host_candidate:
            host = host_candidate
        health_candidate = str(runtime_cfg.get("health_path") or "").strip()
        if health_candidate:
            health_path = health_candidate if health_candidate.startswith("/") else f"/{health_candidate}"
        raw_port = runtime_cfg.get("port")
        try:
            candidate = int(raw_port) if raw_port is not None else None
        except Exception:
            candidate = None
        if candidate is not None and 1 <= candidate <= 65535:
            port = candidate

        endpoint = (
            f"http://{host}:{port}{health_path}"
            if port is not None
            else f"http://{host}:<port>{health_path}"
        )
        kickoff_instruction = (
            f"Team Mode kickoff for project {project_id}.\n"
            "Act as Lead and coordinate execution asynchronously.\n"
            "Kickoff run must be dispatch-only: never implement code, run tests, or run deploy commands in kickoff.\n"
            "Do not complete the Lead task in kickoff.\n"
            "During oversight cycles, enforce deterministic handoff: Developer implementation -> Lead review/deploy -> QA validation.\n"
            "Require Developer completion evidence before merge: commit + task branch in external_refs.\n"
            f"Canonical deploy target: stack={stack}, endpoint={endpoint}.\n"
            "After successful deploy, request QA automation handoff explicitly and keep the Lead task active until QA completes.\n"
            "If deploy/health fails, set Blocked and record exact failure evidence in external_refs.\n"
            f"If unresolved after one cycle, assign to human and notify requester user_id={str(user.id)}."
        )

        with SessionLocal() as db:
            from plugins.team_mode.api_kickoff import maybe_dispatch_execution_kickoff

            result = maybe_dispatch_execution_kickoff(
                db=db,
                user=user,
                workspace_id=workspace_id,
                project_id=project_id,
                intent_flags={
                    "execution_intent": True,
                    "execution_kickoff_intent": True,
                    "project_creation_intent": False,
                    "workflow_scope": "team_mode",
                    "execution_mode": "kickoff_only",
                },
                allow_mutations=True,
                command_id=command_id,
                promote_plugin_policy_to_execution_mode_if_needed=lambda **_kwargs: None,
                build_team_lead_kickoff_instruction=lambda **_kwargs: kickoff_instruction,
                command_id_with_suffix=self._derive_child_command_id,
            )
            if not isinstance(result, dict):
                raise HTTPException(status_code=409, detail="Team Mode kickoff could not be dispatched")
            return result

    def _validate_setup_runtime_deploy_health_contract(
        self,
        *,
        project_id: str,
        workspace_id: str,
        auth_token: str | None,
    ) -> dict[str, Any]:
        payload = self.get_project_plugin_config(
            project_id=project_id,
            plugin_key="docker_compose",
            workspace_id=workspace_id,
            auth_token=auth_token,
        )
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        runtime = config.get("runtime_deploy_health") if isinstance(config.get("runtime_deploy_health"), dict) else {}
        required = bool(runtime.get("required"))
        stack = str(runtime.get("stack") or "").strip()
        host = str(runtime.get("host") or "gateway").strip() or "gateway"
        health_path = str(runtime.get("health_path") or "").strip()
        raw_port = runtime.get("port")
        port: int | None = None
        try:
            port = int(raw_port) if raw_port is not None else None
        except Exception:
            port = None

        if not required:
            return {
                "required": False,
                "stack": stack or None,
                "host": host or None,
                "port": port,
                "health_path": health_path or None,
            }

        if port is None or port < 1 or port > 65535:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Runtime deploy health is required for kickoff_after_setup, "
                    "but docker_compose.runtime_deploy_health.port is missing or invalid."
                ),
            )
        if not stack:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Runtime deploy health is required for kickoff_after_setup, "
                    "but docker_compose.runtime_deploy_health.stack is empty."
                ),
            )
        if not health_path or not health_path.startswith("/"):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Runtime deploy health is required for kickoff_after_setup, "
                    "but docker_compose.runtime_deploy_health.health_path is invalid."
                ),
            )
        return {
            "required": True,
            "stack": stack,
            "host": host,
            "port": port,
            "health_path": health_path,
            "endpoint": f"http://{host}:{port}{health_path}",
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
        plugin_result = plugin_service_policy.ensure_plugin_project_contract(
            plugin_key=_TEAM_MODE_PLUGIN_KEY,
            project_id=project_id,
            project_ref=project_ref,
            workspace_id=workspace_id,
            auth_token=auth_token,
            expected_event_storming_enabled=expected_event_storming_enabled,
            command_id=command_id,
            ensure_project_contract_core=self._ensure_team_mode_project_core,
        )
        deprecation_payload = {
            "deprecated": True,
            "deprecated_tool": "ensure_team_mode_project",
            "replacement_tool": "setup_project_orchestration",
            "message": "ensure_team_mode_project is deprecated; use setup_project_orchestration.",
        }
        if isinstance(plugin_result, dict):
            return {**plugin_result, **deprecation_payload}
        result = self._ensure_team_mode_project_core(
            project_id=project_id,
            project_ref=project_ref,
            workspace_id=workspace_id,
            auth_token=auth_token,
            expected_event_storming_enabled=expected_event_storming_enabled,
            command_id=command_id,
        )
        if isinstance(result, dict):
            return {**result, **deprecation_payload}
        return deprecation_payload

    def _ensure_team_mode_project_core(
        self,
        *,
        project_id: str | None = None,
        project_ref: str | None = None,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        expected_event_storming_enabled: bool | None = None,
        command_id: str | None = None,
    ) -> dict:
        from plugins.team_mode import service_orchestration as team_mode_service_orchestration

        return team_mode_service_orchestration.ensure_project_contract_core(
            self,
            project_id=project_id,
            project_ref=project_ref,
            workspace_id=workspace_id,
            auth_token=auth_token,
            expected_event_storming_enabled=expected_event_storming_enabled,
            command_id=command_id,
        )

    def list_project_starters(
        self,
        *,
        auth_token: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            return ProjectStarterApplicationService(db, user).list_starters()

    def get_project_starter(
        self,
        *,
        starter_key: str,
        auth_token: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            return ProjectStarterApplicationService(db, user).get_starter(starter_key)

    def get_project_setup_profile(
        self,
        *,
        project_id: str,
        auth_token: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            return ProjectStarterApplicationService(db, user).get_setup_profile(project_id)

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
        task_relationships: Any | None = None,
        delivery_mode: str | None = None,
        recurring_rule: str | None = None,
        specification_id: str | None = None,
        task_group_id: str | None = None,
        task_type: str | None = None,
        scheduled_instruction: str | None = None,
        scheduled_at_utc: str | None = None,
        schedule_timezone: str | None = None,
        assignee_id: str | None = None,
        assigned_agent_code: str | None = None,
        labels: Any | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        normalized_execution_triggers = self._normalize_execution_triggers_input(execution_triggers)
        normalized_task_relationships = normalize_task_relationships(task_relationships)
        normalized_delivery_mode = normalize_delivery_mode(delivery_mode)
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
        resolved_workspace_id = ""
        resolved_project_id = str(project_id or "").strip()
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
                    "task_relationships": normalized_task_relationships or [],
                    "delivery_mode": normalized_delivery_mode,
                    "recurring_rule": normalized_recurring_rule,
                    "specification_id": specification_id,
                    "task_type": normalized_task_type,
                    "scheduled_instruction": scheduled_instruction,
                    "scheduled_at_utc": scheduled_at_utc,
                    "schedule_timezone": schedule_timezone,
                    "assignee_id": assignee_id,
                    "assigned_agent_code": assigned_agent_code,
                    "labels": normalized_labels or [],
                },
            )
            effective_assignee_id = str(assignee_id or "").strip() or None
            command_provider = self._resolve_command_execution_provider(
                command_id=effective_command_id,
                workspace_id=resolved_workspace_id,
                actor_user=user,
            )
            provider_agent_assignee_id = self._resolve_project_agent_user_id_for_provider(
                db=db,
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                provider=command_provider,
            )
            if provider_agent_assignee_id:
                if effective_assignee_id:
                    assignee_user = db.get(UserModel, effective_assignee_id)
                    assignee_user_type = str(getattr(assignee_user, "user_type", "") or "").strip().lower()
                    # Keep explicit human assignees; enforce provider-specific assignment for agent assignees.
                    if assignee_user_type == "agent" and effective_assignee_id != provider_agent_assignee_id:
                        effective_assignee_id = provider_agent_assignee_id
                else:
                    effective_assignee_id = provider_agent_assignee_id
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
                "assignee_id": effective_assignee_id,
                "assigned_agent_code": assigned_agent_code,
                "labels": normalized_labels or [],
            }
            if instruction is not None:
                payload_kwargs["instruction"] = instruction
            if normalized_execution_triggers is not None:
                payload_kwargs["execution_triggers"] = normalized_execution_triggers
            if normalized_task_relationships:
                payload_kwargs["task_relationships"] = normalized_task_relationships
            if normalized_delivery_mode:
                payload_kwargs["delivery_mode"] = normalized_delivery_mode
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
            created = TaskApplicationService(db, user, command_id=effective_command_id).create_task(payload)

        self._maybe_backfill_team_mode_topology(
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
            specification_id=specification_id,
            auth_token=auth_token,
            command_id=effective_command_id,
        )
        created_id = str(created.get("id") or "").strip()
        if created_id:
            return self.get_task(task_id=created_id, auth_token=auth_token)
        return created

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
        custom_statuses: Any | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        embedding_enabled: bool = True,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        automation_max_parallel_tasks: int = 4,
        chat_index_mode: str = CHAT_INDEX_MODE_KG_AND_VECTOR,
        chat_attachment_ingestion_mode: str = "METADATA_ONLY",
        vector_index_distill_enabled: bool = False,
        event_storming_enabled: bool = True,
        member_user_ids: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id = self._resolve_workspace_for_project_create(explicit_workspace_id=workspace_id)
            effective_member_user_ids = self._augment_project_member_user_ids_for_human_visibility(
                db=db,
                workspace_id=resolved_workspace_id,
                actor_user=user,
                member_user_ids=member_user_ids,
            )
            effective_command_id = command_id or self._fallback_project_create_command_id(
                workspace_id=resolved_workspace_id,
                name=name,
            )
            payload = ProjectCreate(
                workspace_id=resolved_workspace_id,
                name=name,
                description=description,
                custom_statuses=self._normalize_custom_statuses(custom_statuses),
                external_refs=external_refs or [],
                attachment_refs=attachment_refs or [],
                embedding_enabled=bool(embedding_enabled),
                embedding_model=embedding_model,
                context_pack_evidence_top_k=context_pack_evidence_top_k,
                automation_max_parallel_tasks=int(automation_max_parallel_tasks or 4),
                chat_index_mode=chat_index_mode,
                chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
                vector_index_distill_enabled=bool(vector_index_distill_enabled),
                event_storming_enabled=bool(event_storming_enabled),
                member_user_ids=effective_member_user_ids,
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
        if "custom_statuses" in patch_payload:
            patch_payload["custom_statuses"] = self._normalize_custom_statuses(patch_payload.get("custom_statuses"))
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
        project_id: str,
        workspace_id: str | None = None,
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
            skill_row = db.get(ProjectSkill, skill_id)
            if skill_row is None or bool(getattr(skill_row, "is_deleted", False)):
                raise HTTPException(status_code=404, detail="Project skill not found")
            updated_at = getattr(skill_row, "updated_at", None)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-skill-apply",
                payload={
                    "skill_id": skill_id,
                    "skill_updated_at": updated_at.isoformat() if updated_at is not None else "",
                    "generated_rule_id": str(getattr(skill_row, "generated_rule_id", "") or ""),
                },
            )
            applied = ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).apply_project_skill(skill_id)
            project_workspace_id = str(getattr(skill_row, "workspace_id", "") or "").strip()
            project_scope_id = str(getattr(skill_row, "project_id", "") or "").strip()
            enabled_project_skills = db.execute(
                select(ProjectSkill.skill_key).where(
                    ProjectSkill.workspace_id == project_workspace_id,
                    ProjectSkill.project_id == project_scope_id,
                    ProjectSkill.enabled == True,  # noqa: E712
                    ProjectSkill.is_deleted == False,  # noqa: E712
                )
            ).scalars().all()
            enabled_plugin_keys = {
                str(item or "").strip().lower()
                for item in enabled_project_skills
                if str(item or "").strip().lower() in _PROJECT_PLUGIN_KEYS
            }
            if enabled_plugin_keys:
                now_utc = datetime.now(timezone.utc)
                for plugin_key in enabled_plugin_keys:
                    plugin_row = db.execute(
                        select(ProjectPluginConfig).where(
                            ProjectPluginConfig.workspace_id == project_workspace_id,
                            ProjectPluginConfig.project_id == project_scope_id,
                            ProjectPluginConfig.plugin_key == plugin_key,
                            ProjectPluginConfig.is_deleted == False,  # noqa: E712
                        )
                    ).scalar_one_or_none()
                    if plugin_row is None:
                        config = _default_plugin_config(plugin_key)
                        plugin_row = ProjectPluginConfig(
                            workspace_id=project_workspace_id,
                            project_id=project_scope_id,
                            plugin_key=plugin_key,
                            enabled=True,
                            version=1,
                            schema_version=1,
                            config_json=json.dumps(config, ensure_ascii=False),
                            compiled_policy_json=json.dumps(_compile_plugin_policy(plugin_key, config), ensure_ascii=False),
                            last_validation_errors_json="[]",
                            last_validated_at=now_utc,
                            created_by=str(user.id),
                            updated_by=str(user.id),
                        )
                    else:
                        config = _safe_json_loads_object(str(getattr(plugin_row, "config_json", "") or "").strip(), fallback={})
                        if not config:
                            config = _default_plugin_config(plugin_key)
                        plugin_row.enabled = True
                        plugin_row.version = int(getattr(plugin_row, "version", 1) or 1) + 1
                        plugin_row.schema_version = 1
                        plugin_row.config_json = json.dumps(config, ensure_ascii=False)
                        plugin_row.compiled_policy_json = json.dumps(_compile_plugin_policy(plugin_key, config), ensure_ascii=False)
                        plugin_row.last_validation_errors_json = "[]"
                        plugin_row.last_validated_at = now_utc
                        plugin_row.updated_by = str(user.id)
                    db.add(plugin_row)
                db.commit()
            return applied

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
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            self._assert_workspace_skill_allowed(db=db, skill_id=workspace_skill_id)
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_create(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-workspace-skill-attach",
                payload={
                    "workspace_skill_id": workspace_skill_id,
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                },
            )
            return ProjectSkillApplicationService(
                db, user, command_id=effective_command_id
            ).attach_workspace_skill_to_project(
                workspace_skill_id=workspace_skill_id,
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
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
            normalized_patch = self._normalize_project_rule_patch(patch)
            payload = ProjectRulePatch(**normalized_patch)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-project-rule-patch",
                payload={"rule_id": rule_id, "patch": normalized_patch},
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
            requested_status = str(normalized_patch.get("status") or "").strip()
            completed_status = _effective_completed_status_for_project(
                db,
                workspace_id=str(state.workspace_id),
                project_id=str(state.project_id),
            )
            if _is_completed_transition_request(
                requested_status=requested_status,
                completed_status=completed_status,
            ):
                current_task_row = db.get(Task, task_id)
                automation_state, _ = rebuild_state(db, "Task", task_id)
                current_automation_state = str(automation_state.get("automation_state") or "idle").strip().lower()
                if current_automation_state in {"queued", "running"}:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Completed transition blocked while automation is still active. "
                            f"automation_state={current_automation_state}"
                        ),
                    )
                effective_assignee_id = str(
                    normalized_patch.get("assignee_id")
                    or (getattr(current_task_row, "assignee_id", None) if current_task_row is not None else None)
                    or getattr(state, "assignee_id", None)
                    or ""
                ).strip()
                effective_assigned_agent_code = str(
                    normalized_patch.get("assigned_agent_code")
                    or (getattr(current_task_row, "assigned_agent_code", None) if current_task_row is not None else None)
                    or ""
                ).strip()
                effective_labels = normalized_patch.get("labels")
                if effective_labels is None and current_task_row is not None:
                    effective_labels = getattr(current_task_row, "labels", None)
                assignee_role = self._resolve_task_assignee_role(
                    db=db,
                    workspace_id=str(state.workspace_id),
                    project_id=str(state.project_id),
                    assignee_id=effective_assignee_id,
                    assigned_agent_code=effective_assigned_agent_code,
                    task_labels=effective_labels,
                    task_status=requested_status or str(getattr(state, "status", "") or ""),
                )
                self._enforce_team_mode_done_transition(
                    db=db,
                    state=state,
                    assignee_role=assignee_role,
                    auth_token=auth_token,
                )
                if is_lead_role(assignee_role):
                    team_mode_verification = self.verify_team_mode_workflow(
                        project_id=str(state.project_id),
                        workspace_id=str(state.workspace_id),
                        auth_token=auth_token,
                    )
                    delivery_verification = self.verify_delivery_workflow(
                        project_id=str(state.project_id),
                        workspace_id=str(state.workspace_id),
                        auth_token=auth_token,
                    )
                    if not bool(team_mode_verification.get("ok")) or not bool(delivery_verification.get("ok")):
                        team_mode_failed = ", ".join(team_mode_verification.get("required_failed_checks") or [])
                        delivery_failed = ", ".join(delivery_verification.get("required_failed_checks") or [])
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "Completed transition blocked by project policy checks. "
                                f"team_mode_ok={bool(team_mode_verification.get('ok'))}"
                                + (f"; team_mode_failed=[{team_mode_failed}]" if team_mode_failed else "")
                                + f"; delivery_ok={bool(delivery_verification.get('ok'))}"
                                + (f"; delivery_failed=[{delivery_failed}]" if delivery_failed else "")
                            ),
                        )
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
            completed_status = _effective_completed_status_for_project(
                db,
                workspace_id=str(state.workspace_id),
                project_id=str(state.project_id),
            )
            assignee_role = ""
            current_task_row = db.get(Task, task_id)
            automation_state, _ = rebuild_state(db, "Task", task_id)
            current_automation_state = str(automation_state.get("automation_state") or "idle").strip().lower()
            if current_automation_state in {"queued", "running"}:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Completed transition blocked while automation is still active. "
                        f"automation_state={current_automation_state}"
                    ),
                )
            effective_assignee_id = str(
                (getattr(current_task_row, "assignee_id", None) if current_task_row is not None else None)
                or getattr(state, "assignee_id", None)
                or ""
            ).strip()
            assignee_role = self._resolve_task_assignee_role(
                db=db,
                workspace_id=str(state.workspace_id),
                project_id=str(state.project_id),
                assignee_id=effective_assignee_id,
                assigned_agent_code=(
                    str(getattr(current_task_row, "assigned_agent_code", None) or "").strip()
                    if current_task_row is not None
                    else ""
                ),
                task_labels=(getattr(current_task_row, "labels", None) if current_task_row is not None else None),
                task_status=str(getattr(current_task_row, "status", None) or getattr(state, "status", "") or ""),
            )
            self._enforce_team_mode_done_transition(
                db=db,
                state=state,
                assignee_role=assignee_role,
                auth_token=auth_token,
            )
            if is_lead_role(assignee_role):
                team_mode_verification = self.verify_team_mode_workflow(
                    project_id=str(state.project_id),
                    workspace_id=str(state.workspace_id),
                    auth_token=auth_token,
                )
                delivery_verification = self.verify_delivery_workflow(
                    project_id=str(state.project_id),
                    workspace_id=str(state.workspace_id),
                    auth_token=auth_token,
                )
                if not bool(team_mode_verification.get("ok")) or not bool(delivery_verification.get("ok")):
                    team_mode_failed = ", ".join(team_mode_verification.get("required_failed_checks") or [])
                    delivery_failed = ", ".join(delivery_verification.get("required_failed_checks") or [])
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Completed transition blocked by project policy checks. "
                            f"team_mode_ok={bool(team_mode_verification.get('ok'))}"
                            + (f"; team_mode_failed=[{team_mode_failed}]" if team_mode_failed else "")
                            + f"; delivery_ok={bool(delivery_verification.get('ok'))}"
                            + (f"; delivery_failed=[{delivery_failed}]" if delivery_failed else "")
                        ),
                    )
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
        source: str | None = None,
        source_task_id: str | None = None,
        chat_session_id: str | None = None,
        execution_intent: bool | None = None,
        execution_kickoff_intent: bool | None = None,
        project_creation_intent: bool | None = None,
        workflow_scope: str | None = None,
        execution_mode: str | None = None,
        task_completion_requested: bool | None = None,
        classifier_reason: str | None = None,
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
            task_view = load_task_view(db, task_id) or {}
            team_mode_role: str | None = None
            normalized_project_id = str(state.project_id or "").strip()
            if normalized_project_id:
                runtime_context = _team_mode_runtime_context_for_project(
                    db,
                    workspace_id=state.workspace_id,
                    project_id=normalized_project_id,
                    require_enabled=True,
                )
                if runtime_context is not None:
                    team_mode_role = runtime_context.derive_workflow_role(
                        task_like={
                            "assignee_id": str((task_view or {}).get("assignee_id") or "").strip(),
                            "assigned_agent_code": str((task_view or {}).get("assigned_agent_code") or "").strip(),
                            "labels": (task_view or {}).get("labels"),
                            "status": str((task_view or {}).get("status") or state.status or "").strip(),
                        }
                    ) or None
            classification = resolve_instruction_intent(
                instruction=instruction,
                workspace_id=str(state.workspace_id or ""),
                project_id=str(state.project_id or "").strip() or None,
                session_id=None,
                current={
                    "execution_intent": execution_intent,
                    "execution_kickoff_intent": execution_kickoff_intent,
                    "project_creation_intent": project_creation_intent,
                    "project_knowledge_lookup_intent": False,
                    "grounded_answer_required": False,
                    "workflow_scope": str(workflow_scope or "").strip() or None,
                    "execution_mode": str(execution_mode or "").strip() or None,
                    "task_completion_requested": task_completion_requested,
                    "reason": str(classifier_reason or "").strip() or None,
                },
                classify_fn=classify_instruction_intent,
                required_fields=AUTOMATION_REQUEST_INTENT_FIELDS,
            )
            if str(team_mode_role or "").strip() in TEAM_MODE_ROLES:
                if str(team_mode_role or "").strip() != "Lead":
                    classification["execution_intent"] = True
                    classification["execution_kickoff_intent"] = False
                    classification["workflow_scope"] = "team_mode"
                    classification["execution_mode"] = "resume_execution"
            payload = TaskAutomationRun(
                instruction=instruction,
                source=source,
                source_task_id=str(source_task_id or "").strip() or None,
                chat_session_id=str(chat_session_id or "").strip() or None,
                execution_intent=classification.get("execution_intent"),
                execution_kickoff_intent=classification.get("execution_kickoff_intent"),
                project_creation_intent=classification.get("project_creation_intent"),
                workflow_scope=str(classification.get("workflow_scope") or "").strip() or None,
                execution_mode=str(classification.get("execution_mode") or "").strip() or None,
                task_completion_requested=classification.get("task_completion_requested"),
                classifier_reason=str(classification.get("reason") or "").strip() or None,
            )
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-run",
                payload={"task_id": task_id, "instruction": instruction, "source": source, "source_task_id": source_task_id},
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
        normalized_action = str(action or "").strip().lower()
        payload = payload or {}
        cleaned: list[str] = []
        seen_ids: set[str] = set()
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
                normalized_id = str(state.id or task_id or "").strip()
                if not normalized_id:
                    continue
                dedupe_key = normalized_id.casefold()
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                cleaned.append(normalized_id)
            bulk = BulkAction(task_ids=cleaned, action=normalized_action, payload=payload)
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-bulk",
                payload={"task_ids": cleaned, "action": normalized_action, "payload": payload},
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).bulk_action(bulk)

    def archive_all_tasks(
        self,
        *,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member"})
            page = list_tasks_read_model(
                db,
                user,
                TaskListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    q=q,
                    archived=False,
                    limit=min(int(limit or 200), 200),
                    offset=0,
                ),
            )
            raw_ids = [t["id"] for t in (page.get("items") or []) if t.get("id")]
            ids: list[str] = []
            seen_ids: set[str] = set()
            for raw_id in raw_ids:
                normalized_id = str(raw_id or "").strip()
                if not normalized_id:
                    continue
                dedupe_key = normalized_id.casefold()
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                ids.append(normalized_id)
            bulk = BulkAction(task_ids=ids, action="archive", payload={})
            effective_command_id = command_id or self._fallback_command_id(
                prefix="mcp-task-archive-all",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "q": q,
                    "ids": ids,
                },
            )
            return TaskApplicationService(db, user, command_id=effective_command_id).bulk_action(bulk)

    def archive_all_notes(
        self,
        *,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        user = self._resolve_actor_user()
        with SessionLocal() as db:
            resolved_workspace_id, resolved_project_id = self._resolve_workspace_for_read(
                db=db,
                explicit_workspace_id=workspace_id,
                project_id=project_id,
            )
            if not resolved_project_id:
                raise HTTPException(status_code=400, detail="project_id is required")
            ensure_role(db, resolved_workspace_id, user.id, {"Owner", "Admin", "Member"})
            page = list_notes_read_model(
                db,
                user,
                NoteListQuery(
                    workspace_id=resolved_workspace_id,
                    project_id=resolved_project_id,
                    q=q,
                    archived=False,
                    limit=min(int(limit or 200), 200),
                    offset=0,
                ),
            )
            raw_ids = [n["id"] for n in (page.get("items") or []) if n.get("id")]
            ids: list[str] = []
            seen_ids: set[str] = set()
            for raw_id in raw_ids:
                normalized_id = str(raw_id or "").strip()
                if not normalized_id:
                    continue
                dedupe_key = normalized_id.casefold()
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                ids.append(normalized_id)
            batch_command_id = command_id or self._fallback_command_id(
                prefix="mcp-archive-notes",
                payload={
                    "workspace_id": resolved_workspace_id,
                    "project_id": resolved_project_id,
                    "q": q,
                    "ids": ids,
                },
            )
            validated_ids: list[str] = []
            seen_ids: set[str] = set()
            for note_id in ids:
                state = load_note_command_state(db, note_id)
                if not state or state.is_deleted or state.archived:
                    continue
                self._assert_workspace_allowed(state.workspace_id)
                self._assert_project_allowed(state.project_id)
                normalized_id = str(state.id or note_id or "").strip()
                if not normalized_id:
                    continue
                dedupe_key = normalized_id.casefold()
                if dedupe_key in seen_ids:
                    continue
                seen_ids.add(dedupe_key)
                validated_ids.append(normalized_id)
            return NoteApplicationService(db, user, command_id=batch_command_id).archive_notes(validated_ids)

    def send_in_app_notification(
        self,
        *,
        user_id: str,
        message: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        note_id: str | None = None,
        specification_id: str | None = None,
        notification_type: str | None = "ManualMessage",
        severity: str | None = "info",
        dedupe_key: str | None = None,
        payload: dict[str, Any] | str | None = None,
        source_event: str | None = "mcp.manual_notification",
        command_id: str | None = None,
    ) -> dict:
        self._require_token(auth_token)
        target_user_id = str(user_id or "").strip()
        clean_message = str(message or "").strip()
        if not target_user_id:
            raise HTTPException(status_code=422, detail="user_id is required")
        if not clean_message:
            raise HTTPException(status_code=422, detail="message is required")

        payload_dict: dict[str, Any] | None
        if payload is None:
            payload_dict = None
        elif isinstance(payload, str):
            parsed = self._parse_json_string(payload, field_name="payload")
            if parsed is not None and not isinstance(parsed, dict):
                raise HTTPException(status_code=422, detail="payload must be a JSON object")
            payload_dict = parsed
        elif isinstance(payload, dict):
            payload_dict = dict(payload)
        else:
            raise HTTPException(status_code=422, detail="payload must be an object or JSON object string")

        actor = self._resolve_actor_user()
        with SessionLocal() as db:
            target_user = db.get(UserModel, target_user_id)
            if target_user is None or not bool(target_user.is_active):
                raise HTTPException(status_code=404, detail="Target user not found")

            resolved_workspace_id = str(workspace_id or "").strip() or None
            resolved_project_id = str(project_id or "").strip() or None
            resolved_task_id = str(task_id or "").strip() or None
            resolved_note_id = str(note_id or "").strip() or None
            resolved_specification_id = str(specification_id or "").strip() or None

            if resolved_project_id:
                project = self._load_project_scope(db=db, project_id=resolved_project_id)
                if resolved_workspace_id and resolved_workspace_id != str(project.workspace_id):
                    raise HTTPException(status_code=400, detail="project_id does not belong to workspace_id")
                resolved_workspace_id = str(project.workspace_id)

            if resolved_task_id:
                task_state = self._assert_task_allowed(db=db, task_id=resolved_task_id)
                assert task_state is not None
                if resolved_workspace_id and resolved_workspace_id != task_state.workspace_id:
                    raise HTTPException(status_code=400, detail="task_id does not belong to workspace_id")
                if resolved_project_id and resolved_project_id != task_state.project_id:
                    raise HTTPException(status_code=400, detail="task_id does not belong to project_id")
                resolved_workspace_id = task_state.workspace_id
                resolved_project_id = task_state.project_id

            if resolved_note_id:
                note_state = load_note_command_state(db, resolved_note_id)
                if not note_state or note_state.is_deleted:
                    raise HTTPException(status_code=404, detail="Note not found")
                self._assert_workspace_allowed(note_state.workspace_id)
                self._assert_project_allowed(note_state.project_id)
                if resolved_workspace_id and resolved_workspace_id != note_state.workspace_id:
                    raise HTTPException(status_code=400, detail="note_id does not belong to workspace_id")
                if resolved_project_id and resolved_project_id != note_state.project_id:
                    raise HTTPException(status_code=400, detail="note_id does not belong to project_id")
                resolved_workspace_id = note_state.workspace_id
                resolved_project_id = note_state.project_id

            if resolved_specification_id:
                specification_state = self._assert_specification_allowed(db=db, specification_id=resolved_specification_id)
                assert specification_state is not None
                if resolved_workspace_id and resolved_workspace_id != specification_state.workspace_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to workspace_id")
                if resolved_project_id and resolved_project_id != specification_state.project_id:
                    raise HTTPException(status_code=400, detail="specification_id does not belong to project_id")
                resolved_workspace_id = specification_state.workspace_id
                resolved_project_id = specification_state.project_id

            if resolved_workspace_id:
                self._assert_workspace_allowed(resolved_workspace_id)
            elif self._default_workspace_id:
                resolved_workspace_id = self._default_workspace_id
                self._assert_workspace_allowed(resolved_workspace_id)
            elif len(self._allowed_workspace_ids) == 1:
                resolved_workspace_id = next(iter(self._allowed_workspace_ids))

            effective_dedupe_key = str(dedupe_key or "").strip() or None
            if effective_dedupe_key is None and command_id:
                effective_dedupe_key = f"mcp-command:{command_id}"

            created = append_notification_created_event(
                db,
                append_event_fn=append_event,
                user_id=target_user_id,
                message=clean_message,
                actor_id=actor.id,
                workspace_id=resolved_workspace_id,
                project_id=resolved_project_id,
                task_id=resolved_task_id,
                note_id=resolved_note_id,
                specification_id=resolved_specification_id,
                notification_type=notification_type,
                severity=severity,
                dedupe_key=effective_dedupe_key,
                payload=payload_dict,
                source_event=source_event,
            )
            db.commit()

            notification = None
            if effective_dedupe_key:
                notification = db.execute(
                    select(Notification).where(
                        Notification.user_id == target_user_id,
                        Notification.dedupe_key == effective_dedupe_key,
                    ).order_by(Notification.created_at.desc())
                ).scalars().first()
            if notification is None:
                notification = db.execute(
                    select(Notification).where(
                        Notification.user_id == target_user_id,
                        Notification.message == clean_message,
                    ).order_by(Notification.created_at.desc())
                ).scalars().first()
            if notification is None:
                raise HTTPException(status_code=500, detail="Notification was not created")

            return {
                "ok": True,
                "created": bool(created),
                "notification": serialize_notification(notification),
            }
    @staticmethod
    def _normalize_project_rule_patch(patch: dict | None) -> dict:
        normalized = dict(patch or {})
        body = normalized.get("body", None)
        if isinstance(body, (dict, list)):
            normalized["body"] = json.dumps(body, ensure_ascii=False)
        return normalized

    @staticmethod
    def _normalize_custom_statuses(value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            parsed: object | None = None
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
            if isinstance(parsed, list):
                candidates = parsed
            elif "," in raw:
                candidates = [part.strip() for part in raw.split(",")]
            else:
                candidates = [raw]
        elif isinstance(value, (list, tuple, set)):
            candidates = list(value)
        else:
            raise HTTPException(status_code=422, detail="custom_statuses must be an array of strings")
        normalized: list[str] = []
        for item in candidates:
            status = _canonicalize_project_status_label(item)
            if not status or status in normalized:
                continue
            normalized.append(status)
        return normalized or None
