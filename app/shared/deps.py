from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from collections.abc import Callable
from typing import TypeVar

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_session_token
from .contracts import ConcurrencyConflictError
from .models import AuthSession, ProjectMember, SessionLocal, User, WorkspaceMember
from .observability import incr
from .settings import AUTH_SESSION_COOKIE_NAME, LICENSE_ENFORCEMENT_ENABLED

try:
    from eventsourcing.utils import retry as eventsourcing_retry
except Exception:  # pragma: no cover
    eventsourcing_retry = None

try:
    from eventsourcing.persistence import RecordConflictError
except Exception:  # pragma: no cover
    RecordConflictError = Exception

_T = TypeVar("_T")
logger = logging.getLogger(__name__)
LICENSE_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LICENSE_WRITE_EXEMPT_PATHS = (
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/change-password",
    "/api/license/status",
    "/api/license/activate",
    "/api/public",
)


def _normalize_api_path(path: str) -> str:
    value = str(path or "").strip() or "/"
    if value != "/" and value.endswith("/"):
        value = value[:-1]
    return value


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def request_targets_write_path(request: Request) -> bool:
    method = str(getattr(request, "method", "")).upper()
    if method not in LICENSE_WRITE_METHODS:
        return False
    path = _normalize_api_path(request.url.path)
    if not path.startswith("/api/"):
        return False
    for prefix in LICENSE_WRITE_EXEMPT_PATHS:
        if _path_matches_prefix(path, prefix):
            return False
    return True


def is_license_write_allowed(request: Request) -> tuple[bool, dict[str, object] | None]:
    if not LICENSE_ENFORCEMENT_ENABLED:
        return True, None
    if not request_targets_write_path(request):
        return True, None
    # Unauthenticated requests should continue and be handled by auth dependencies.
    if not request.cookies.get(AUTH_SESSION_COOKIE_NAME):
        return True, None
    from features.licensing.read_models import license_status_read_model

    with SessionLocal() as db:
        payload = license_status_read_model(db)
    return bool(payload.get("write_access")), payload


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    session_token = request.cookies.get(AUTH_SESSION_COOKIE_NAME)
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_hash = hash_session_token(session_token)
    auth_session = db.execute(select(AuthSession).where(AuthSession.token_hash == session_hash)).scalar_one_or_none()
    if not auth_session:
        raise HTTPException(status_code=401, detail="Invalid session")
    now = datetime.now(timezone.utc)
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        db.delete(auth_session)
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, auth_session.user_id)
    if not user or not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=401, detail="User not found")
    if bool(getattr(user, "must_change_password", False)):
        path = request.url.path
        allowed_paths = {
            "/api/auth/me",
            "/api/auth/change-password",
            "/api/auth/logout",
        }
        if path not in allowed_paths:
            raise HTTPException(status_code=403, detail="Password change required")
    return user


def get_command_id(
    x_command_id: str | None = Header(default=None),
    command_id: str | None = Query(default=None),
) -> str | None:
    return x_command_id or command_id


def ensure_role(db: Session, workspace_id: str, user_id: str, allowed: set[str]):
    membership = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not membership or membership.role not in allowed:
        raise HTTPException(status_code=403, detail="Forbidden")


def ensure_project_access(
    db: Session,
    workspace_id: str,
    project_id: str,
    user_id: str,
    allowed_workspace_roles: set[str],
) -> None:
    membership = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not membership or membership.role not in allowed_workspace_roles:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Workspace Owner/Admin can access all workspace projects.
    if membership.role in {"Owner", "Admin"}:
        return

    assigned = db.execute(
        select(ProjectMember.id).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not assigned:
        raise HTTPException(status_code=403, detail="Project access required")


def run_command_with_retry(db: Session, handler: Callable[[], _T], *, max_attempts: int = 5, initial_backoff_seconds: float = 0.01) -> _T:
    conflict_errors = (ConcurrencyConflictError, RecordConflictError)
    if eventsourcing_retry is not None:

        def attempt_once() -> _T:
            try:
                return handler()
            except conflict_errors:
                db.rollback()
                raise

        wrapped = eventsourcing_retry(
            exc=conflict_errors,
            max_attempts=max_attempts,
            wait=initial_backoff_seconds,
            stall=0.1,
        )(attempt_once)
        try:
            return wrapped()
        except conflict_errors as exc:
            raise HTTPException(status_code=409, detail=f"Concurrency conflict after {max_attempts} retries: {exc}") from exc

    backoff = initial_backoff_seconds
    for attempt in range(1, max_attempts + 1):
        try:
            return handler()
        except conflict_errors as exc:
            incr("commands_retried")
            db.rollback()
            if attempt >= max_attempts:
                incr("command_conflicts")
                raise HTTPException(status_code=409, detail=f"Concurrency conflict after {max_attempts} retries: {exc}") from exc
            logger.warning("command.retry attempt=%s max=%s error=%s", attempt, max_attempts, exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 0.25)
    raise HTTPException(status_code=409, detail="Concurrency conflict")
