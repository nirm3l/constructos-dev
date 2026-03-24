from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .deps import run_command_with_retry
from .models import CommandExecution
from .observability import incr

_T = TypeVar("_T")
logger = logging.getLogger(__name__)


def execute_command(
    db: Session,
    *,
    command_name: str,
    user_id: str,
    command_id: str | None,
    handler: Callable[[], _T],
) -> _T:
    incr("commands_total")
    if command_id:
        existing = db.execute(select(CommandExecution).where(CommandExecution.command_id == command_id)).scalar_one_or_none()
        if existing:
            existing_command_name = str(getattr(existing, "command_name", "") or "").strip()
            existing_user_id = str(getattr(existing, "user_id", "") or "").strip()
            if existing_command_name != command_name or existing_user_id != str(user_id or "").strip():
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "command_id already used for different command intent; "
                        "use a unique command_id per command_name and user"
                    ),
                )
            logger.info("command.replay command_name=%s command_id=%s user_id=%s", command_name, command_id, user_id)
            return json.loads(existing.response_json)

    result = run_command_with_retry(db, handler)
    if command_id:
        db.add(
            CommandExecution(
                command_id=command_id,
                command_name=command_name,
                user_id=user_id,
                response_json=json.dumps(result, default=str),
            )
        )
        db.commit()
    return result
