from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from features.agents.gates import evaluate_required_checks as evaluate_required_policy_checks
from features.agents.gates import evaluate_team_mode_checks
from plugins.github_delivery.service_orchestration import ensure_project_skill_when_github_context
from features.tasks.read_models import TaskListQuery, list_tasks_read_model
from shared.core import ensure_project_access
from shared.deps import ensure_role
from shared.models import (
    Note,
    ProjectMember,
    ProjectPluginConfig,
    ProjectRule as ProjectRuleModel,
    ProjectSkill,
    SessionLocal,
    Task,
    TaskComment,
    User as UserModel,
)

TEAM_MODE_PLUGIN_KEY = "team_mode"


def verify_workflow_core(
    service: Any,
    *,
    project_id: str,
    auth_token: str | None = None,
    workspace_id: str | None = None,
    expected_event_storming_enabled: bool | None = None,
) -> dict:
    service._require_token(auth_token)
    user = service._resolve_actor_user()
    with SessionLocal() as db:
        project = service._load_project_scope(db=db, project_id=project_id)
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
        project_rules = db.execute(
            select(ProjectRuleModel).where(
                ProjectRuleModel.project_id == project_id,
                ProjectRuleModel.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        plugin_config = db.execute(
            select(ProjectPluginConfig).where(
                ProjectPluginConfig.workspace_id == str(project.workspace_id),
                ProjectPluginConfig.project_id == project_id,
                ProjectPluginConfig.plugin_key == TEAM_MODE_PLUGIN_KEY,
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        project_skills = db.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        tasks = list(tasks_payload.get("items") or [])
        service._enrich_tasks_with_automation_state(db=db, tasks=tasks)
    team_mode_enabled = bool(getattr(plugin_config, "enabled", False))
    plugin_policy_source = (
        f"project_plugin_config:{getattr(plugin_config, 'id', '')}" if plugin_config is not None else "project_plugin_config:missing"
    )
    if plugin_config is not None:
        plugin_payload = service.get_project_plugin_config(
            project_id=project_id,
            plugin_key=TEAM_MODE_PLUGIN_KEY,
            workspace_id=str(project.workspace_id),
            auth_token=auth_token,
        )
        plugin_policy = dict(plugin_payload.get("compiled_policy") or {})
    else:
        plugin_policy = {}
    if not team_mode_enabled:
        required_checks = dict((plugin_policy.get("required_checks") or {})) if isinstance(plugin_policy, dict) else {}
        required_checks["team_mode"] = []
        plugin_policy = dict(plugin_policy) if isinstance(plugin_policy, dict) else {}
        plugin_policy["required_checks"] = required_checks
    team_mode_active = bool(team_mode_enabled)
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
    verification = evaluate_team_mode_checks(
        project_id=str(project_id),
        workspace_id=str(project.workspace_id),
        event_storming_enabled=bool(getattr(project, "event_storming_enabled", True)),
        expected_event_storming_enabled=expected_event_storming_enabled,
        plugin_policy=plugin_policy,
        plugin_policy_source=plugin_policy_source,
        tasks=tasks,
        member_role_by_user_id=member_role_by_user_id,
        notes_by_task=notes_by_task,
        comments_by_task=comments_by_task,
        extract_deploy_ports=service._extract_deploy_ports,
        has_deploy_stack_marker=service._has_deploy_stack_marker,
    )
    verification["check_reasons"] = {}
    required_checks = list(verification.get("required_checks") or [])
    checks_ok, required_failed = evaluate_required_policy_checks(verification["checks"], required_checks)
    verification["required_failed_checks"] = required_failed
    verification["ok"] = bool(checks_ok)
    verification["active"] = team_mode_active
    verification["checks"] = dict(verification.get("checks") or {})
    verification["checks"]["team_mode_enabled"] = bool(team_mode_enabled)
    return verification


def ensure_project_contract_core(
    service: Any,
    *,
    project_id: str | None = None,
    project_ref: str | None = None,
    workspace_id: str | None = None,
    auth_token: str | None = None,
    expected_event_storming_enabled: bool | None = None,
    command_id: str | None = None,
) -> dict:
    service._require_token(auth_token)
    user = service._resolve_actor_user()
    resolved_ref = str(project_id or project_ref or "").strip()
    if not resolved_ref:
        raise HTTPException(status_code=400, detail="project_id or project_ref is required")
    with SessionLocal() as db:
        project, _ = service._resolve_project_for_chat_context(
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
        has_github_context = service._project_has_github_context(
            project_description=str(getattr(project, "description", "") or ""),
            project_external_refs=getattr(project, "external_refs", "[]"),
            project_rules=project_rules,
        )

        team_mode_plugin_config = service.set_project_plugin_enabled(
            project_id=str(project.id),
            plugin_key="team_mode",
            enabled=True,
            workspace_id=str(project.workspace_id),
            auth_token=auth_token,
        )
        git_delivery_plugin_config = service.set_project_plugin_enabled(
            project_id=str(project.id),
            plugin_key="git_delivery",
            enabled=True,
            workspace_id=str(project.workspace_id),
            auth_token=auth_token,
        )

        github_delivery = ensure_project_skill_when_github_context(
            db=db,
            service=service,
            user=user,
            project=project,
            has_github_context=has_github_context,
            command_id=command_id,
        )

    verification = service.verify_team_mode_workflow(
        project_id=resolved_project_id,
        workspace_id=workspace_id,
        auth_token=auth_token,
        expected_event_storming_enabled=expected_event_storming_enabled,
    )
    delivery_verification = service.verify_delivery_workflow(
        project_id=resolved_project_id,
        workspace_id=workspace_id,
        auth_token=auth_token,
    )
    members = service.list_project_members(
        workspace_id=workspace_id or verification["workspace_id"],
        project_id=resolved_project_id,
        auth_token=auth_token,
        limit=200,
        offset=0,
    )
    return {
        "project_id": resolved_project_id,
        "workspace_id": verification["workspace_id"],
        "attached": bool(github_delivery.get("attached")),
        "project_skill_id": None,
        "generated_rule_id": None,
        "team_mode_contract_complete": True,
        "team_mode_roster": [],
        "git_delivery": {
            "project_skill_id": None,
            "attached": False,
            "applied": False,
            "generated_rule_id": None,
            "plugin_config_id": str(git_delivery_plugin_config.get("id") or "").strip() or None,
            "enabled": bool(git_delivery_plugin_config.get("enabled")),
        },
        "team_mode_plugin": {
            "plugin_config_id": str(team_mode_plugin_config.get("id") or "").strip() or None,
            "enabled": bool(team_mode_plugin_config.get("enabled")),
        },
        "github_delivery": dict(github_delivery),
        "members": members,
        "verification": verification,
        "delivery_verification": delivery_verification,
        "ok": bool(verification.get("ok"))
        and bool(delivery_verification.get("ok")),
    }
