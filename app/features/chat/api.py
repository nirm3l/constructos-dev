from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.deps import ensure_project_access, ensure_role, get_command_id, get_current_user, get_db
from shared.contracts import AttachmentRef
from shared.models import ChatMessage, ChatSession, User

from .application import ChatApplicationService
from .command_handlers import ArchiveSessionPayload, LinkMessageResourcePayload, UpdateSessionContextPayload

router = APIRouter()


class ChatResourceLinkCreate(BaseModel):
    workspace_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    relation: str = "created"


class ChatSessionContextPatch(BaseModel):
    workspace_id: str = Field(min_length=1)
    session_attachment_refs: list[AttachmentRef] | None = None


def _serialize_session(row: ChatSession) -> dict:
    return {
        "id": row.session_key,
        "aggregate_id": row.id,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "title": row.title,
        "is_archived": bool(row.is_archived),
        "codex_session_id": row.codex_session_id,
        "mcp_servers": json.loads(row.mcp_servers or "[]"),
        "session_attachment_refs": json.loads(row.session_attachment_refs or "[]"),
        "usage": json.loads(row.usage_json or "{}"),
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "last_message_preview": row.last_message_preview or "",
        "last_task_event_at": row.last_task_event_at.isoformat() if row.last_task_event_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _load_session_with_access(
    db: Session,
    *,
    user: User,
    workspace_id: str,
    session_key: str,
) -> ChatSession:
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    session = db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.session_key == session_key,
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.project_id:
        ensure_project_access(db, workspace_id, session.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return session


@router.get("/api/chat/sessions")
def list_chat_sessions(
    workspace_id: str = Query(min_length=1),
    project_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=40, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    normalized_project_id = str(project_id or "").strip() or None
    if normalized_project_id:
        ensure_project_access(db, workspace_id, normalized_project_id, user.id, {"Owner", "Admin", "Member", "Guest"})

    query = select(ChatSession).where(ChatSession.workspace_id == workspace_id)
    if normalized_project_id is not None:
        query = query.where(ChatSession.project_id == normalized_project_id)
    if not include_archived:
        query = query.where(ChatSession.is_archived == False)
    rows = db.execute(
        query.order_by(
            ChatSession.last_message_at.desc(),
            ChatSession.updated_at.desc(),
        ).limit(limit)
    ).scalars().all()

    out: list[dict] = []
    for row in rows:
        out.append(_serialize_session(row))
    return out


@router.patch("/api/chat/sessions/{session_id}")
def update_chat_session_context(
    session_id: str,
    payload: ChatSessionContextPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    session = _load_session_with_access(
        db,
        user=user,
        workspace_id=payload.workspace_id,
        session_key=session_id,
    )
    ChatApplicationService(db, user, command_id=command_id).update_session_context(
        UpdateSessionContextPayload(
            workspace_id=payload.workspace_id,
            project_id=session.project_id,
            session_id=session_id,
            session_attachment_refs=[item.model_dump() for item in payload.session_attachment_refs or []],
        )
    )
    db.refresh(session)
    return _serialize_session(session)


@router.get("/api/chat/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: str,
    workspace_id: str = Query(min_length=1),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=400, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _load_session_with_access(
        db,
        user=user,
        workspace_id=workspace_id,
        session_key=session_id,
    )
    query = select(ChatMessage).where(ChatMessage.session_id == session.id)
    if not include_deleted:
        query = query.where(ChatMessage.is_deleted == False)
    rows = db.execute(
        query.order_by(ChatMessage.order_index.asc(), ChatMessage.turn_created_at.asc(), ChatMessage.created_at.asc()).limit(limit)
    ).scalars().all()
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "session_id": session.session_key,
                "workspace_id": row.workspace_id,
                "project_id": row.project_id,
                "role": row.role,
                "content": row.content or "",
                "order_index": int(row.order_index or 0),
                "attachment_refs": json.loads(row.attachment_refs or "[]"),
                "usage": json.loads(row.usage_json or "{}"),
                "is_deleted": bool(row.is_deleted),
                "created_at": row.turn_created_at.isoformat() if row.turn_created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return out


@router.post("/api/chat/sessions/{session_id}/messages/{message_id}/resources")
def link_chat_message_resource(
    session_id: str,
    message_id: str,
    payload: ChatResourceLinkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    session = _load_session_with_access(
        db,
        user=user,
        workspace_id=payload.workspace_id,
        session_key=session_id,
    )
    link_result = ChatApplicationService(db, user, command_id=command_id).link_message_resource(
        LinkMessageResourcePayload(
            workspace_id=payload.workspace_id,
            project_id=session.project_id,
            session_id=session_id,
            message_id=message_id,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            relation=payload.relation,
        )
    )
    return link_result


@router.post("/api/chat/sessions/{session_id}/archive")
def archive_chat_session(
    session_id: str,
    workspace_id: str = Query(min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    session = _load_session_with_access(
        db,
        user=user,
        workspace_id=workspace_id,
        session_key=session_id,
    )
    return ChatApplicationService(db, user, command_id=command_id).archive_session(
        ArchiveSessionPayload(
            workspace_id=workspace_id,
            project_id=session.project_id,
            session_id=session_id,
        )
    )
