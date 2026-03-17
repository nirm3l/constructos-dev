from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from shared.auth import generate_session_token, hash_session_token, verify_password
from shared.core import AuthSession, User, UserPreferencesPatch, WorkspaceMember, get_command_id, get_current_user, get_db
from shared.settings import BOOTSTRAP_PASSWORD, BOOTSTRAP_USERNAME, DEFAULT_USER_ID
from shared.settings import AUTH_COOKIE_SECURE, AUTH_SESSION_COOKIE_NAME, AUTH_SESSION_TTL_HOURS

from features.agents.provider_auth import resolve_provider_effective_auth_source
from features.agents.workspace_runtime import list_workspace_runtime_targets, upsert_workspace_runtime_target

from .application import UserApplicationService
from .gateway import UserOperationGateway

router = APIRouter()

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
OWNER_ROLE = "Owner"
ADMIN_ROLES = {"Owner", "Admin"}
WORKSPACE_ROLES = {"Owner", "Admin", "Member", "Guest"}


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=0, max_length=256)


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


class AdminUpdateUserAgentRuntimePayload(BaseModel):
    workspace_id: str
    model: str | None = None
    reasoning_effort: str | None = None
    use_for_background_processing: bool | None = None


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


def _allow_blank_default_admin_password(*, user: User, password: str) -> bool:
    if str(password or "").strip():
        return False
    if str(user.user_type or "").strip().lower() != "human":
        return False
    if str(user.id or "").strip() != str(DEFAULT_USER_ID):
        return False
    if str(user.username or "").strip().lower() != str(BOOTSTRAP_USERNAME or "").strip().lower():
        return False
    return verify_password(str(BOOTSTRAP_PASSWORD or ""), user.password_hash)


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
        "agent_chat_model": str(user.agent_chat_model or ""),
        "agent_chat_reasoning_effort": str(user.agent_chat_reasoning_effort or "medium"),
        "onboarding_quick_tour_completed": bool(user.onboarding_quick_tour_completed),
        "onboarding_advanced_tour_completed": bool(user.onboarding_advanced_tour_completed),
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
        if not _allow_blank_default_admin_password(user=user, password=payload.password):
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
    actor_membership = _require_workspace_admin(db, workspace_id, user.id)
    actor_is_owner = actor_membership.role == OWNER_ROLE
    runtime_targets = list_workspace_runtime_targets(db, workspace_id)
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
                "can_reset_password": (
                    member_user.user_type == "human"
                    and (actor_is_owner or membership.role not in ADMIN_ROLES)
                ),
                "can_deactivate": (
                    member_user.user_type == "human"
                    and bool(member_user.is_active)
                    and member_user.id != user.id
                    and (actor_is_owner or membership.role not in ADMIN_ROLES)
                ),
                "can_update_role": (
                    member_user.user_type == "human"
                    and (actor_is_owner or membership.role not in ADMIN_ROLES)
                ),
                "background_agent_model": (
                    runtime_targets[str(member_user.id)].model
                    if str(member_user.id) in runtime_targets
                    else None
                ),
                "background_agent_provider": (
                    runtime_targets[str(member_user.id)].provider
                    if str(member_user.id) in runtime_targets
                    else None
                ),
                "background_agent_available": (
                    resolve_provider_effective_auth_source(runtime_targets[str(member_user.id)].provider) != "none"
                    if str(member_user.id) in runtime_targets
                    else False
                ),
                "background_agent_reasoning_effort": (
                    runtime_targets[str(member_user.id)].reasoning_effort
                    if str(member_user.id) in runtime_targets
                    else None
                ),
                "background_agent_model_is_fallback": (
                    runtime_targets[str(member_user.id)].model_is_fallback
                    if str(member_user.id) in runtime_targets
                    else None
                ),
                "background_agent_reasoning_is_fallback": (
                    runtime_targets[str(member_user.id)].reasoning_is_fallback
                    if str(member_user.id) in runtime_targets
                    else None
                ),
                "is_background_execution_selected": (
                    runtime_targets[str(member_user.id)].is_background_default
                    if str(member_user.id) in runtime_targets
                    else False
                ),
                "can_configure_background_execution": str(member_user.id) in runtime_targets,
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


@router.post("/api/admin/users/{target_user_id}/agent-runtime")
def update_workspace_user_agent_runtime(
    target_user_id: str,
    payload: AdminUpdateUserAgentRuntimePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_workspace_admin(db, payload.workspace_id, user.id)
    runtime_targets = list_workspace_runtime_targets(db, payload.workspace_id)
    selected_target = runtime_targets.get(str(target_user_id))
    if payload.use_for_background_processing and selected_target is not None:
        if resolve_provider_effective_auth_source(selected_target.provider) == "none":
            raise HTTPException(
                status_code=422,
                detail=f"{selected_target.provider.title()} is not configured for this runtime.",
            )
    try:
        target = upsert_workspace_runtime_target(
            db=db,
            workspace_id=payload.workspace_id,
            target_user_id=target_user_id,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
            set_as_background_default=payload.use_for_background_processing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {
        "ok": True,
        "workspace_id": payload.workspace_id,
        "user_id": target.user_id,
        "provider": target.provider,
        "model": target.model,
        "reasoning_effort": target.reasoning_effort,
        "is_background_execution_selected": target.is_background_default,
    }


@router.patch("/api/me/preferences")
def patch_me_preferences(
    payload: UserPreferencesPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = UserOperationGateway()
    return gateway.patch_preferences(
        db=db,
        actor_user_id=user.id,
        payload=payload,
        command_id=command_id,
    )
