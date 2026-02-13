from __future__ import annotations

import time
import logging
from collections.abc import Callable
from typing import TypeVar

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import ConcurrencyConflictError
from .models import SessionLocal, User, WorkspaceMember
from .observability import incr
from .settings import DEFAULT_USER_ID

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None),
    user_id: str | None = Query(default=None),
) -> User:
    effective_user_id = x_user_id or user_id or DEFAULT_USER_ID
    user = db.get(User, effective_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
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
