from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from shared.auth import generate_session_token, hash_session_token, verify_password
from shared.core import AuthSession, User, UserPreferencesPatch, WorkspaceMember, get_command_id, get_current_user, get_db
from shared.settings import AUTH_COOKIE_SECURE, AUTH_SESSION_COOKIE_NAME, AUTH_SESSION_TTL_HOURS

from .application import UserApplicationService

router = APIRouter()

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
ADMIN_ROLES = {"Owner", "Admin"}
WORKSPACE_ROLES = {"Owner", "Admin", "Member", "Guest"}


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AdminCreateUserPayload(BaseModel):
    workspace_id: str
    username: str = Field(min_length=3, max_length=64)
    full_name: str | None = Field(default=None, max_length=128)
    role: str = "Member"


class AdminResetPasswordPayload(BaseModel):
    workspace_id: str


class AdminUpdateUserRolePayload(BaseModel):
    workspace_id: str
    role: str


class AdminDeactivateUserPayload(BaseModel):
    workspace_id: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl_seconds() -> int:
    return max(3600, int(AUTH_SESSION_TTL_HOURS) * 3600)


def _set_auth_cookie(response: Response, token: str):
    response.set_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=bool(AUTH_COOKIE_SECURE),
        samesite="lax",
        max_age=_session_ttl_seconds(),
        path="/",
    )


def _clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        path="/",
    )


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


def _serialize_auth_user(db: Session, user: User) -> dict:
    memberships = db.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(WorkspaceMember.user_id == user.id)
    ).all()
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "user_type": user.user_type,
        "timezone": user.timezone,
        "theme": user.theme,
        "must_change_password": bool(user.must_change_password),
        "memberships": [{"workspace_id": workspace_id, "role": role} for workspace_id, role in memberships],
    }


@router.post("/api/auth/login")
def login(
    payload: LoginPayload,
    response: Response,
    db: Session = Depends(get_db),
):
    username = _normalize_username(payload.username)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= _now_utc()))

    user = db.execute(
        select(User).where(
            func.lower(User.username) == username.lower(),
            User.user_type == "human",
        )
    ).scalar_one_or_none()
    if not user or not bool(user.is_active):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = generate_session_token()
    expires_at = _now_utc() + timedelta(seconds=_session_ttl_seconds())
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    _set_auth_cookie(response, token)
    return {"ok": True, "user": _serialize_auth_user(db, user)}


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    session_token = request.cookies.get(AUTH_SESSION_COOKIE_NAME)
    if session_token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_session_token(session_token)))
        db.commit()
    _clear_auth_cookie(response)
    return {"ok": True}


@router.get("/api/auth/me")
def auth_me(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"ok": True, "user": _serialize_auth_user(db, user)}


@router.post("/api/auth/change-password")
def change_password(
    payload: ChangePasswordPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    current_session_token = request.cookies.get(AUTH_SESSION_COOKIE_NAME)
    current_hash = hash_session_token(current_session_token) if current_session_token else ""
    UserApplicationService(db, user, command_id=command_id).change_password(
        current_password=str(payload.current_password or ""),
        new_password=str(payload.new_password or ""),
        keep_session_hash=current_hash or None,
    )
    return {"ok": True, "user": _serialize_auth_user(db, user)}


@router.get("/api/admin/users")
def list_workspace_users(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_workspace_admin(db, workspace_id, user.id)
    rows = db.execute(
        select(User, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.full_name.asc(), User.username.asc())
    ).all()
    return {
        "workspace_id": workspace_id,
        "items": [
            {
                "id": member_user.id,
                "username": member_user.username,
                "full_name": member_user.full_name,
                "user_type": member_user.user_type,
                "role": membership.role,
                "is_active": bool(member_user.is_active),
                "must_change_password": bool(member_user.must_change_password) if member_user.user_type == "human" else False,
                "can_reset_password": member_user.user_type == "human",
                "can_deactivate": (
                    member_user.user_type == "human"
                    and bool(member_user.is_active)
                    and member_user.id != user.id
                ),
            }
            for member_user, membership in rows
        ],
        "total": len(rows),
    }


@router.post("/api/admin/users")
def create_workspace_user(
    payload: AdminCreateUserPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    username = _normalize_username(payload.username)
    role = _normalize_workspace_role(payload.role)
    full_name = str(payload.full_name or "").strip() or username
    return UserApplicationService(db, user, command_id=command_id).create_workspace_user(
        workspace_id=payload.workspace_id,
        username=username,
        full_name=full_name,
        role=role,
    )


@router.post("/api/admin/users/{target_user_id}/reset-password")
def reset_workspace_user_password(
    target_user_id: str,
    payload: AdminResetPasswordPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return UserApplicationService(db, user, command_id=command_id).reset_workspace_user_password(
        workspace_id=payload.workspace_id,
        target_user_id=target_user_id,
    )


@router.post("/api/admin/users/{target_user_id}/set-role")
def update_workspace_user_role(
    target_user_id: str,
    payload: AdminUpdateUserRolePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    role = _normalize_workspace_role(payload.role)
    return UserApplicationService(db, user, command_id=command_id).update_workspace_user_role(
        workspace_id=payload.workspace_id,
        target_user_id=target_user_id,
        role=role,
    )


@router.post("/api/admin/users/{target_user_id}/deactivate")
def deactivate_workspace_user(
    target_user_id: str,
    payload: AdminDeactivateUserPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return UserApplicationService(db, user, command_id=command_id).deactivate_workspace_user(
        workspace_id=payload.workspace_id,
        target_user_id=target_user_id,
    )


@router.patch("/api/me/preferences")
def patch_me_preferences(
    payload: UserPreferencesPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return UserApplicationService(db, user, command_id=command_id).patch_preferences(payload)
