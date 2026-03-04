from __future__ import annotations

from typing import Any

from sqlalchemy import select

from features.project_skills.application import ProjectSkillApplicationService
from shared.models import ProjectSkill, WorkspaceSkill


def ensure_project_skill_when_github_context(
    *,
    db: Any,
    service: Any,
    user: Any,
    project: Any,
    has_github_context: bool,
    command_id: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "eligible": False,
        "project_skill_id": None,
        "attached": False,
        "applied": False,
        "generated_rule_id": None,
    }
    if not has_github_context:
        return result
    github_ws = db.execute(
        select(WorkspaceSkill).where(
            WorkspaceSkill.workspace_id == str(project.workspace_id),
            WorkspaceSkill.skill_key == "github_delivery",
            WorkspaceSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if github_ws is None:
        return result
    result["eligible"] = True
    github_project_skill = db.execute(
        select(ProjectSkill).where(
            ProjectSkill.workspace_id == str(project.workspace_id),
            ProjectSkill.project_id == str(project.id),
            ProjectSkill.skill_key == "github_delivery",
            ProjectSkill.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    attached = False
    if github_project_skill is None:
        attach_command_id = command_id or service._fallback_command_id(
            prefix="mcp-ensure-github-delivery-attach",
            payload={
                "workspace_id": str(project.workspace_id),
                "project_ref": str(project.id),
                "workspace_skill_id": str(github_ws.id),
                "skill_key": "github_delivery",
            },
        )
        attached_view = ProjectSkillApplicationService(
            db,
            user,
            command_id=attach_command_id,
        ).attach_workspace_skill_to_project(
            workspace_skill_id=str(github_ws.id),
            workspace_id=str(project.workspace_id),
            project_id=str(project.id),
        )
        attached = True
        attached_skill_id = str(attached_view.get("id") or "").strip()
        github_project_skill = db.get(ProjectSkill, attached_skill_id) if attached_skill_id else None
    if github_project_skill is None:
        return result
    apply_command_id = command_id or service._fallback_command_id(
        prefix="mcp-ensure-github-delivery-apply",
        payload={"project_ref": str(project.id), "project_skill_id": str(github_project_skill.id)},
    )
    applied_view = ProjectSkillApplicationService(
        db,
        user,
        command_id=apply_command_id,
    ).apply_project_skill(str(github_project_skill.id))
    result.update(
        {
            "project_skill_id": str(github_project_skill.id),
            "attached": attached,
            "applied": bool(applied_view),
            "generated_rule_id": str(applied_view.get("generated_rule_id") or "").strip() or None,
        }
    )
    return result

