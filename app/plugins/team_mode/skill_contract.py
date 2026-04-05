from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.models import Project, ProjectMember, ProjectRule, User as UserModel, WorkspaceMember
from shared.project_repository import ensure_project_repository_initialized
from shared.theme import THEME_CONSTRUCTOS_NIGHT

TEAM_MODE_SKILL_KEY = "team_mode"
TEAM_MODE_WORKSPACE_ROLE = "Admin"
TEAM_MODE_AGENT_SPECS: tuple[dict[str, str], ...] = (
    {
        "username": "agent.m0rph3u5",
        "full_name": "M0rph3u5",
        "project_role": "Lead",
    },
    {
        "username": "agent.tr1n1ty",
        "full_name": "Tr1n1ty",
        "project_role": "Developer",
    },
    {
        "username": "agent.n30",
        "full_name": "N30",
        "project_role": "Developer",
    },
    {
        "username": "agent.0r4cl3",
        "full_name": "0r4cl3",
        "project_role": "QA",
    },
)


def ensure_team_mode_workspace_agent(
    *,
    db: Session,
    workspace_id: str,
    username: str,
    full_name: str,
) -> UserModel:
    normalized_username = str(username or "").strip().lower()
    normalized_full_name = str(full_name or "").strip() or normalized_username
    user_row = db.execute(
        select(UserModel).where(func.lower(UserModel.username) == normalized_username)
    ).scalar_one_or_none()
    if user_row is not None:
        if str(user_row.user_type or "").strip().lower() != "agent":
            raise ValueError(
                f'Team Mode requires username "{normalized_username}" to be an agent user. '
                "Found a non-agent user with the same username."
            )
        user_row.full_name = normalized_full_name
        user_row.password_hash = None
        user_row.must_change_password = False
        user_row.password_changed_at = None
        user_row.is_active = True
        user_row.user_type = "agent"
    else:
        user_row = UserModel(
            username=normalized_username,
            full_name=normalized_full_name,
            user_type="agent",
            password_hash=None,
            must_change_password=False,
            password_changed_at=None,
            is_active=True,
            theme=THEME_CONSTRUCTOS_NIGHT,
            timezone="UTC",
            notifications_enabled=True,
            agent_chat_model="",
            agent_chat_reasoning_effort="medium",
        )
        db.add(user_row)
        db.flush()

    workspace_member = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_row.id,
        )
    ).scalar_one_or_none()
    if workspace_member is None:
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user_row.id,
                role=TEAM_MODE_WORKSPACE_ROLE,
            )
        )
    elif str(workspace_member.role or "").strip() != TEAM_MODE_WORKSPACE_ROLE:
        workspace_member.role = TEAM_MODE_WORKSPACE_ROLE
    return user_row


def ensure_team_mode_project_membership(*, db: Session, project: Project) -> None:
    for spec in TEAM_MODE_AGENT_SPECS:
        user_row = ensure_team_mode_workspace_agent(
            db=db,
            workspace_id=project.workspace_id,
            username=spec["username"],
            full_name=spec["full_name"],
        )
        expected_project_role = str(spec["project_role"])
        project_member = db.execute(
            select(ProjectMember).where(
                ProjectMember.workspace_id == project.workspace_id,
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user_row.id,
            )
        ).scalar_one_or_none()
        if project_member is None:
            db.add(
                ProjectMember(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    user_id=user_row.id,
                    role=expected_project_role,
                )
            )
            continue
        if str(project_member.role or "").strip() != expected_project_role:
            project_member.role = expected_project_role


def build_team_mode_roster_snapshot(*, db: Session, project: Project) -> list[dict[str, Any]]:
    roster: list[dict[str, Any]] = []
    for spec in TEAM_MODE_AGENT_SPECS:
        normalized_username = str(spec["username"]).strip().lower()
        user_row = db.execute(
            select(UserModel).where(func.lower(UserModel.username) == normalized_username)
        ).scalar_one_or_none()
        user_id = str(user_row.id) if user_row is not None else ""
        workspace_member = None
        project_member = None
        if user_row is not None:
            workspace_member = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == project.workspace_id,
                    WorkspaceMember.user_id == user_row.id,
                )
            ).scalar_one_or_none()
            project_member = db.execute(
                select(ProjectMember).where(
                    ProjectMember.workspace_id == project.workspace_id,
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == user_row.id,
                )
            ).scalar_one_or_none()
        roster.append(
            {
                "username": str(spec["username"]),
                "full_name": str(spec["full_name"]),
                "expected_project_role": str(spec["project_role"]),
                "user_id": user_id or None,
                "user_type": (str(user_row.user_type or "").strip() if user_row is not None else None),
                "workspace_member_role": (
                    str(workspace_member.role or "").strip() if workspace_member is not None else None
                ),
                "project_member_role": (
                    str(project_member.role or "").strip() if project_member is not None else None
                ),
                "workspace_member_present": workspace_member is not None,
                "project_member_present": project_member is not None,
            }
        )
    return roster


def _slugify_project_name(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def ensure_team_mode_repository_context(
    *,
    db: Session,
    project: Project,
    actor_user_id: str,
    default_codex_workdir: str,
    repository_context_rule_title: str,
    ensure_local_repository_bootstrap_fn: Any,
) -> None:
    project_slug = _slugify_project_name(str(project.name or "").strip(), fallback=str(project.id)[:8] or "project")
    repo_root = ensure_project_repository_initialized(
        project_name=str(project.name or "").strip(),
        project_id=str(project.id or "").strip(),
    )
    repo_path = str(repo_root)
    repo_url = f"file://{repo_path}"
    ensure_local_repository_bootstrap_fn(repo_path=repo_root)

    parsed_refs: list[dict[str, str]] = []
    try:
        loaded_refs = json.loads(str(project.external_refs or "[]"))
    except Exception:
        loaded_refs = []
    if isinstance(loaded_refs, list):
        for item in loaded_refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            normalized: dict[str, str] = {"url": url}
            title = str(item.get("title") or "").strip()
            label = str(item.get("label") or "").strip()
            if title:
                normalized["title"] = title
            if label:
                normalized["label"] = label
            parsed_refs.append(normalized)

    desired_ref = {
        "url": repo_url,
        "title": repository_context_rule_title,
        "label": "Local workspace repository path",
    }
    expected_suffix = f"/{project_slug}"
    existing_idx: int | None = None
    for idx, item in enumerate(parsed_refs):
        title_lower = str(item.get("title") or "").strip().lower()
        url_lower = str(item.get("url") or "").strip().lower()
        if title_lower in {"repository context", "repo context"}:
            existing_idx = idx
            break
        if url_lower.startswith("file://") and url_lower.endswith(expected_suffix.lower()):
            existing_idx = idx
            break
        if ("/home/app/workspace/" in url_lower) and expected_suffix.lower() in url_lower:
            existing_idx = idx
            break

    if existing_idx is None:
        parsed_refs.append(desired_ref)
    elif parsed_refs[existing_idx] != desired_ref:
        parsed_refs[existing_idx] = desired_ref

    project.external_refs = json.dumps(parsed_refs, ensure_ascii=True, sort_keys=True)

    rule_body = "```json\n" + json.dumps(
        {
            "repository_path": repo_path,
            "repository_url": repo_url,
            "default_branch": "main",
            "branch_naming": "task/<task-id>-<slug>",
        },
        ensure_ascii=True,
        indent=2,
    ) + "\n```"
    existing_rule = db.execute(
        select(ProjectRule).where(
            ProjectRule.workspace_id == project.workspace_id,
            ProjectRule.project_id == project.id,
            func.lower(ProjectRule.title) == repository_context_rule_title.lower(),
            ProjectRule.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if existing_rule is None:
        db.add(
            ProjectRule(
                workspace_id=project.workspace_id,
                project_id=project.id,
                title=repository_context_rule_title,
                body=rule_body,
                created_by=actor_user_id,
                updated_by=actor_user_id,
                is_deleted=False,
            )
        )
        return
    if str(existing_rule.body or "") != rule_body:
        existing_rule.body = rule_body
        existing_rule.updated_by = actor_user_id
