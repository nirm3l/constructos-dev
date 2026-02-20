from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.auth import generate_temporary_password, hash_password, verify_password
from shared.core import AggregateEventRepository, User, UserPreferencesPatch, WorkspaceMember, allocate_id, coerce_originator_id
from shared.settings import BOOTSTRAP_WORKSPACE_ID

from .domain import (
    UserAggregate,
)

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
ADMIN_ROLES = {"Owner", "Admin"}
WORKSPACE_ROLES = {"Owner", "Admin", "Member", "Guest"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _normalize_username(raw: str) -> str:
    username = str(raw or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(
            status_code=422,
            detail="username must be 3-64 chars and contain only letters, numbers, dot, underscore, or dash",
        )
    return username


def _normalize_workspace_role(raw: str) -> str:
    role = str(raw or "Member").strip() or "Member"
    if role not in WORKSPACE_ROLES:
        allowed = ", ".join(sorted(WORKSPACE_ROLES))
        raise HTTPException(status_code=422, detail=f"role must be one of: {allowed}")
    return role


def _require_workspace_admin(db: Session, workspace_id: str, user_id: str) -> WorkspaceMember:
    membership = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not membership or membership.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return membership


def _workspace_id_for_actor(db: Session, user_id: str) -> str:
    return (
        db.execute(select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)).scalar()
        or BOOTSTRAP_WORKSPACE_ID
    )


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class PatchUserPreferencesHandler:
    ctx: CommandContext
    payload: UserPreferencesPatch

    def __call__(self) -> dict:
        data = self.payload.model_dump(exclude_unset=True)
        event_payload: dict[str, object] = {}
        if "theme" in data:
            event_payload["theme"] = data.get("theme")
        if "timezone" in data:
            event_payload["timezone"] = data.get("timezone")
        if "notifications_enabled" in data:
            event_payload["notifications_enabled"] = data.get("notifications_enabled")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="User",
            aggregate_id=self.ctx.user.id,
            aggregate_cls=UserAggregate,
        )
        aggregate.update_preferences(**event_payload)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": _workspace_id_for_actor(self.ctx.db, self.ctx.user.id),
            },
        )
        self.ctx.db.commit()
        return {
            "id": self.ctx.user.id,
            "theme": data.get("theme", self.ctx.user.theme),
            "timezone": data.get("timezone", self.ctx.user.timezone),
            "notifications_enabled": bool(data.get("notifications_enabled", self.ctx.user.notifications_enabled)),
        }


@dataclass(frozen=True, slots=True)
class ChangePasswordHandler:
    ctx: CommandContext
    current_password: str
    new_password: str
    keep_session_hash: str | None

    def __call__(self) -> dict:
        current_password = str(self.current_password or "")
        new_password = str(self.new_password or "")
        if len(new_password) < 8:
            raise HTTPException(status_code=422, detail="new_password must be at least 8 characters")
        if not verify_password(current_password, self.ctx.user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if verify_password(new_password, self.ctx.user.password_hash):
            raise HTTPException(status_code=422, detail="new_password must differ from current password")

        changed_at = _now_utc()
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="User",
            aggregate_id=self.ctx.user.id,
            aggregate_cls=UserAggregate,
        )
        aggregate.change_password(
            password_hash=hash_password(new_password),
            must_change_password=False,
            password_changed_at=_to_iso_utc(changed_at),
            keep_session_hash=self.keep_session_hash or None,
        )
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": _workspace_id_for_actor(self.ctx.db, self.ctx.user.id),
            },
        )
        self.ctx.db.commit()
        return {"ok": True}


@dataclass(frozen=True, slots=True)
class CreateWorkspaceUserHandler:
    ctx: CommandContext
    workspace_id: str
    username: str
    full_name: str | None
    role: str

    def __call__(self) -> dict:
        _require_workspace_admin(self.ctx.db, self.workspace_id, self.ctx.user.id)
        username = _normalize_username(self.username)
        role = _normalize_workspace_role(self.role)
        full_name = str(self.full_name or "").strip() or username

        existing_user = self.ctx.db.execute(select(User).where(func.lower(User.username) == username.lower())).scalar_one_or_none()
        if existing_user:
            raise HTTPException(status_code=409, detail="username is already in use")

        target_user_id = allocate_id(self.ctx.db)
        temp_password = generate_temporary_password(12)
        aggregate = UserAggregate(
            id=coerce_originator_id(target_user_id),
            username=username,
            full_name=full_name,
            user_type="human",
            password_hash=hash_password(temp_password),
            must_change_password=True,
            password_changed_at=None,
            is_active=True,
            timezone="UTC",
            theme="light",
            notifications_enabled=True,
            workspace_id=self.workspace_id,
            workspace_role=role,
        )
        AggregateEventRepository(self.ctx.db).persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.workspace_id,
            },
            expected_version=0,
        )
        self.ctx.db.commit()
        created_user = self.ctx.db.get(User, target_user_id)
        if created_user is None:
            raise HTTPException(status_code=500, detail="User was not created")
        return {
            "workspace_id": self.workspace_id,
            "user": {
                "id": created_user.id,
                "username": created_user.username,
                "full_name": created_user.full_name,
                "user_type": created_user.user_type,
                "role": role,
                "must_change_password": True,
                "is_active": True,
            },
            "temporary_password": temp_password,
        }


@dataclass(frozen=True, slots=True)
class ResetWorkspaceUserPasswordHandler:
    ctx: CommandContext
    workspace_id: str
    target_user_id: str

    def __call__(self) -> dict:
        _require_workspace_admin(self.ctx.db, self.workspace_id, self.ctx.user.id)
        target_membership = self.ctx.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == self.workspace_id,
                WorkspaceMember.user_id == self.target_user_id,
            )
        ).scalar_one_or_none()
        if not target_membership:
            raise HTTPException(status_code=404, detail="Workspace member not found")
        target_user = self.ctx.db.get(User, self.target_user_id)
        if not target_user or target_user.user_type != "human":
            raise HTTPException(status_code=404, detail="User not found")

        temp_password = generate_temporary_password(12)
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="User",
            aggregate_id=self.target_user_id,
            aggregate_cls=UserAggregate,
        )
        aggregate.reset_password(
            password_hash=hash_password(temp_password),
            must_change_password=True,
            password_changed_at=None,
            revoke_all_sessions=True,
        )
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.workspace_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "user_id": self.target_user_id, "temporary_password": temp_password}


@dataclass(frozen=True, slots=True)
class UpdateWorkspaceUserRoleHandler:
    ctx: CommandContext
    workspace_id: str
    target_user_id: str
    role: str

    def __call__(self) -> dict:
        _require_workspace_admin(self.ctx.db, self.workspace_id, self.ctx.user.id)
        role = _normalize_workspace_role(self.role)
        target_membership = self.ctx.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == self.workspace_id,
                WorkspaceMember.user_id == self.target_user_id,
            )
        ).scalar_one_or_none()
        if not target_membership:
            raise HTTPException(status_code=404, detail="Workspace member not found")

        target_user = self.ctx.db.get(User, self.target_user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        if target_user.user_type != "human" and role not in ADMIN_ROLES:
            raise HTTPException(status_code=422, detail="Non-human users must keep admin role")

        if target_membership.role in ADMIN_ROLES and role not in ADMIN_ROLES:
            admin_count = self.ctx.db.execute(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == self.workspace_id,
                    WorkspaceMember.role.in_(tuple(ADMIN_ROLES)),
                )
            ).scalar_one()
            if int(admin_count or 0) <= 1:
                raise HTTPException(status_code=409, detail="Workspace must have at least one admin")

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="User",
            aggregate_id=self.target_user_id,
            aggregate_cls=UserAggregate,
        )
        aggregate.set_workspace_role(workspace_id=self.workspace_id, role=role)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.workspace_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "workspace_id": self.workspace_id, "user_id": self.target_user_id, "role": role}


@dataclass(frozen=True, slots=True)
class DeactivateWorkspaceUserHandler:
    ctx: CommandContext
    workspace_id: str
    target_user_id: str

    def __call__(self) -> dict:
        _require_workspace_admin(self.ctx.db, self.workspace_id, self.ctx.user.id)
        target_membership = self.ctx.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == self.workspace_id,
                WorkspaceMember.user_id == self.target_user_id,
            )
        ).scalar_one_or_none()
        if not target_membership:
            raise HTTPException(status_code=404, detail="Workspace member not found")

        target_user = self.ctx.db.get(User, self.target_user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        if target_user.user_type != "human":
            raise HTTPException(status_code=422, detail="Only human users can be deactivated")
        if target_user.id == self.ctx.user.id:
            raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
        if not bool(target_user.is_active):
            return {"ok": True, "workspace_id": self.workspace_id, "user_id": self.target_user_id, "is_active": False}

        if target_membership.role in ADMIN_ROLES:
            active_human_admin_count = self.ctx.db.execute(
                select(func.count())
                .select_from(WorkspaceMember)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(
                    WorkspaceMember.workspace_id == self.workspace_id,
                    WorkspaceMember.role.in_(tuple(ADMIN_ROLES)),
                    User.user_type == "human",
                    User.is_active.is_(True),
                )
            ).scalar_one()
            if int(active_human_admin_count or 0) <= 1:
                raise HTTPException(status_code=409, detail="Workspace must have at least one active human admin")

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="User",
            aggregate_id=self.target_user_id,
            aggregate_cls=UserAggregate,
        )
        aggregate.deactivate(workspace_id=self.workspace_id, revoke_all_sessions=True)
        repo.persist(
            aggregate,
            base_metadata={
                "actor_id": self.ctx.user.id,
                "workspace_id": self.workspace_id,
            },
        )
        self.ctx.db.commit()
        return {"ok": True, "workspace_id": self.workspace_id, "user_id": self.target_user_id, "is_active": False}
