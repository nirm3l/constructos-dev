from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import User, UserPreferencesPatch, WorkspaceMember

from .application import UserApplicationService

ADMIN_WORKSPACE_ROLES = {"Owner", "Admin"}


@dataclass(frozen=True, slots=True)
class ResolvedUserTarget:
    actor: User
    target: User
    explicit_cross_user: bool


class UserOperationGateway:
    """Shared gateway for user-scoped actions used by both UI and MCP adapters."""

    def _load_user(self, db: Session, user_id: str) -> User:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    def _assert_explicit_cross_user_admin(self, *, db: Session, actor_user_id: str, target_user_id: str) -> None:
        actor_admin_workspace_ids = set(
            db.execute(
                select(WorkspaceMember.workspace_id).where(
                    WorkspaceMember.user_id == actor_user_id,
                    WorkspaceMember.role.in_(list(ADMIN_WORKSPACE_ROLES)),
                )
            ).scalars()
        )
        if not actor_admin_workspace_ids:
            raise HTTPException(status_code=403, detail="Admin access required for cross-user actions")

        target_workspace_ids = set(
            db.execute(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == target_user_id)).scalars()
        )
        if actor_admin_workspace_ids.isdisjoint(target_workspace_ids):
            raise HTTPException(status_code=403, detail="Admin access required for cross-user actions")

    def resolve_actor_and_target(
        self,
        *,
        db: Session,
        actor_user_id: str,
        explicit_target_user_id: str | None = None,
        implicit_target_user_id: str | None = None,
        require_admin_for_explicit_cross_user: bool = True,
    ) -> ResolvedUserTarget:
        actor_id = str(actor_user_id or "").strip()
        if not actor_id:
            raise HTTPException(status_code=401, detail="User not found")

        explicit_target = str(explicit_target_user_id or "").strip()
        implicit_target = str(implicit_target_user_id or "").strip()
        target_id = explicit_target or implicit_target or actor_id

        actor = self._load_user(db, actor_id)
        target = self._load_user(db, target_id)
        explicit_cross_user = bool(explicit_target) and actor.id != target.id
        if explicit_cross_user and require_admin_for_explicit_cross_user:
            self._assert_explicit_cross_user_admin(db=db, actor_user_id=actor.id, target_user_id=target.id)
        return ResolvedUserTarget(actor=actor, target=target, explicit_cross_user=explicit_cross_user)

    def get_preferences(
        self,
        *,
        db: Session,
        actor_user_id: str,
        explicit_target_user_id: str | None = None,
        implicit_target_user_id: str | None = None,
        require_admin_for_explicit_cross_user: bool = True,
    ) -> dict:
        resolved = self.resolve_actor_and_target(
            db=db,
            actor_user_id=actor_user_id,
            explicit_target_user_id=explicit_target_user_id,
            implicit_target_user_id=implicit_target_user_id,
            require_admin_for_explicit_cross_user=require_admin_for_explicit_cross_user,
        )
        return {
            "id": resolved.target.id,
            "theme": str(resolved.target.theme or "light"),
            "timezone": str(resolved.target.timezone or "UTC"),
            "notifications_enabled": bool(resolved.target.notifications_enabled),
            "agent_chat_model": str(resolved.target.agent_chat_model or ""),
            "agent_chat_reasoning_effort": str(resolved.target.agent_chat_reasoning_effort or "medium"),
        }

    def patch_preferences(
        self,
        *,
        db: Session,
        actor_user_id: str,
        payload: UserPreferencesPatch,
        command_id: str | None = None,
        explicit_target_user_id: str | None = None,
        implicit_target_user_id: str | None = None,
        require_admin_for_explicit_cross_user: bool = True,
    ) -> dict:
        resolved = self.resolve_actor_and_target(
            db=db,
            actor_user_id=actor_user_id,
            explicit_target_user_id=explicit_target_user_id,
            implicit_target_user_id=implicit_target_user_id,
            require_admin_for_explicit_cross_user=require_admin_for_explicit_cross_user,
        )
        return UserApplicationService(
            db,
            resolved.target,
            command_id=command_id,
        ).patch_preferences(payload)
