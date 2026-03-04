from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from features.agents.gates import evaluate_required_checks as evaluate_required_gate_checks
from features.agents.gates import evaluate_team_mode_gates
from features.project_skills.application import ProjectSkillApplicationService
from plugins.github_delivery.service_orchestration import ensure_project_skill_when_github_context
from features.tasks.read_models import TaskListQuery, list_tasks_read_model
from shared.core import ensure_project_access
from shared.deps import ensure_role
from shared.models import (
    Note,
    ProjectMember,
    ProjectRule as ProjectRuleModel,
    ProjectSkill,
    SessionLocal,
    Task,
    TaskComment,
    User as UserModel,
    WorkspaceSkill,
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
        project_skills = db.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
        ).scalars().all()
        tasks = list(tasks_payload.get("items") or [])
        service._enrich_tasks_with_automation_state(db=db, tasks=tasks)
    gate_policy, gate_policy_source = service._parse_gate_policy_rule(project_rules=project_rules)
    team_mode_enabled = any(
        str(getattr(skill, "skill_key", "") or "").strip() == TEAM_MODE_PLUGIN_KEY
        for skill in project_skills
    )
    team_mode_active = bool(team_mode_enabled or gate_policy_source != "default")
    if not team_mode_active:
        required_checks = dict((gate_policy.get("required_checks") or {})) if isinstance(gate_policy, dict) else {}
        required_checks["team_mode"] = []
        gate_policy = dict(gate_policy) if isinstance(gate_policy, dict) else {}
        gate_policy["required_checks"] = required_checks
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
    verification = evaluate_team_mode_gates(
        project_id=str(project_id),
        workspace_id=str(project.workspace_id),
        event_storming_enabled=bool(getattr(project, "event_storming_enabled", True)),
        expected_event_storming_enabled=expected_event_storming_enabled,
        gate_policy=gate_policy,
        gate_policy_source=gate_policy_source,
        tasks=tasks,
        member_role_by_user_id=member_role_by_user_id,
        notes_by_task=notes_by_task,
        comments_by_task=comments_by_task,
        extract_deploy_ports=service._extract_deploy_ports,
        has_deploy_stack_marker=service._has_deploy_stack_marker,
    )
    llm_eval = service._evaluate_project_gates_with_llm(
        project_id=str(project_id),
        workspace_id=str(project.workspace_id),
        gate_policy=gate_policy,
        tasks=tasks,
        member_role_by_user_id=member_role_by_user_id,
        notes_by_task=notes_by_task,
        comments_by_task=comments_by_task,
        project_rules=project_rules,
        project_skills=project_skills,
        project_description=str(getattr(project, "description", "") or ""),
        project_external_refs=getattr(project, "external_refs", "[]"),
    )
    llm_team_checks = dict((llm_eval.get("team_mode") or {}).get("checks") or {})
    llm_team_reasons = dict((llm_eval.get("team_mode") or {}).get("reasons") or {})
    evaluation_cfg = gate_policy.get("evaluation") if isinstance(gate_policy.get("evaluation"), dict) else {}
    evaluation_mode = str((evaluation_cfg or {}).get("mode") or "hybrid").strip().lower()
    authoritative = evaluation_mode == "llm_authoritative"
    if authoritative:
        available = list(verification.get("available_checks") or [])
        required = list(verification.get("required_checks") or [])
        requested = sorted({str(item or "").strip() for item in (available + required) if str(item or "").strip()})
        baseline_checks = dict(verification.get("checks") or {})
        authoritative_checks: dict[str, bool] = {}
        for check_id in requested:
            if check_id in llm_team_checks:
                authoritative_checks[check_id] = bool(llm_team_checks.get(check_id))
            else:
                authoritative_checks[check_id] = bool(baseline_checks.get(check_id))
        verification["checks"] = authoritative_checks
    else:
        merged_checks = dict(verification.get("checks") or {})
        merged_checks.update({str(k): bool(v) for k, v in llm_team_checks.items()})
        verification["checks"] = merged_checks
    verification["check_reasons"] = llm_team_reasons
    required_checks = list(verification.get("required_checks") or [])
    checks_ok, required_failed = evaluate_required_gate_checks(verification["checks"], required_checks)
    verification["required_failed_checks"] = required_failed
    verification["ok"] = bool(checks_ok)
    verification["active"] = team_mode_active
    verification["checks"] = dict(verification.get("checks") or {})
    verification["checks"]["team_mode_skill_enabled"] = bool(team_mode_enabled)
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
                attach_command_id = command_id or service._fallback_command_id(
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
            apply_command_id = command_id or service._fallback_command_id(
                prefix=apply_prefix,
                payload={"project_ref": str(project.id), "project_skill_id": str(project_skill.id)},
            )
            applied_view_local = ProjectSkillApplicationService(
                db,
                user,
                command_id=apply_command_id,
            ).apply_project_skill(str(project_skill.id))
            return project_skill, attached_local, applied_view_local

        team_ws = _workspace_skill_or_404(TEAM_MODE_PLUGIN_KEY, required=True)
        if team_ws is None:
            raise HTTPException(status_code=500, detail="Required skills failed to resolve")

        _, team_attached, team_applied_view = _ensure_project_skill(
            team_ws,
            attach_prefix="mcp-ensure-team-mode-attach",
            apply_prefix="mcp-ensure-team-mode-apply",
        )
        team_dependencies = list(team_applied_view.get("resolved_dependencies") or [])
        git_dependency_from_team = next(
            (item for item in team_dependencies if str(item.get("skill_key") or "").strip() == "git_delivery"),
            None,
        )
        git_project_skill = db.execute(
            select(ProjectSkill).where(
                ProjectSkill.workspace_id == str(project.workspace_id),
                ProjectSkill.project_id == str(project.id),
                ProjectSkill.skill_key == "git_delivery",
                ProjectSkill.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        if git_project_skill is None:
            raise HTTPException(status_code=500, detail="Team Mode dependency git_delivery was not provisioned")

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
        "attached": bool(
            team_attached
            or bool(git_dependency_from_team and git_dependency_from_team.get("attached"))
            or bool(github_delivery.get("attached"))
        ),
        "project_skill_id": str(team_applied_view.get("id") or "").strip(),
        "generated_rule_id": str(team_applied_view.get("generated_rule_id") or "").strip() or None,
        "team_mode_contract_complete": bool(team_applied_view.get("team_mode_contract_complete")),
        "team_mode_roster": list(team_applied_view.get("team_mode_roster") or []),
        "git_delivery": {
            "project_skill_id": str(git_project_skill.id),
            "attached": bool(git_dependency_from_team and git_dependency_from_team.get("attached")),
            "applied": bool(git_dependency_from_team and git_dependency_from_team.get("applied")),
            "generated_rule_id": str(git_project_skill.generated_rule_id or "").strip() or None,
        },
        "github_delivery": dict(github_delivery),
        "members": members,
        "verification": verification,
        "delivery_verification": delivery_verification,
        "ok": bool(verification.get("ok"))
        and bool(team_applied_view.get("team_mode_contract_complete"))
        and bool(delivery_verification.get("ok")),
    }
