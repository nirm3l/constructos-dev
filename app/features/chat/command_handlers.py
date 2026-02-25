from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from shared.aggregates import AggregateEventRepository, coerce_originator_id
from shared.deps import ensure_project_access, ensure_role
from shared.eventing_rebuild import rebuild_state
from shared.models import Project, User

from .domain import ChatSessionAggregate


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_session_key(value: str | None) -> str:
    session_key = str(value or "").strip()
    if not session_key:
        return str(uuid.uuid4())
    if len(session_key) > 128:
        return session_key[:128]
    return session_key


def _normalize_message_id(value: str | None) -> str:
    message_id = str(value or "").strip()
    if message_id:
        try:
            return str(uuid.UUID(message_id))
        except ValueError:
            pass
    return str(uuid.uuid4())


def _normalize_mcp_servers(value: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in value or []:
        server = str(item or "").strip().lower()
        if not server or server in seen:
            continue
        seen.add(server)
        out.append(server)
    return out


def _normalize_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, raw_value in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            out[normalized_key] = raw_value
            continue
        if isinstance(raw_value, list):
            out[normalized_key] = raw_value
            continue
        if isinstance(raw_value, dict):
            out[normalized_key] = raw_value
    return out


def _normalize_attachment_refs(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        normalized: dict[str, Any] = {"path": path}
        name = str(item.get("name") or "").strip()
        mime_type = str(item.get("mime_type") or "").strip()
        if name:
            normalized["name"] = name
        if mime_type:
            normalized["mime_type"] = mime_type
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, int) and size_bytes >= 0:
            normalized["size_bytes"] = size_bytes
        checksum = str(item.get("checksum") or "").strip()
        if checksum:
            normalized["checksum"] = checksum[:128]
        extraction_status = str(item.get("extraction_status") or "").strip().lower()
        if extraction_status:
            normalized["extraction_status"] = extraction_status[:32]
        extracted_text = str(item.get("extracted_text") or "").strip()
        if extracted_text:
            normalized["extracted_text"] = extracted_text[:12000]
        out.append(normalized)
    return out


def _attachment_refs_signature(value: list[dict[str, Any]] | None) -> list[str]:
    refs = _normalize_attachment_refs(value)
    return [str(item.get("path") or "").strip().lower() for item in refs if str(item.get("path") or "").strip()]


def _attachment_event_id(*, session_key: str, message_id: str, path: str, index: int) -> str:
    digest = hashlib.sha256(f"{session_key}:{message_id}:{path}:{index}".encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat-attachment:{digest}"))


def _derive_title(content: str) -> str:
    compact = " ".join(str(content or "").split()).strip()
    if not compact:
        return "Session"
    return compact[:96]


def _normalize_created_at(value: str | None) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return _now_iso_utc()
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return _now_iso_utc()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.replace(microsecond=0).isoformat()


def _normalized_project_id(project_id: str | None) -> str | None:
    normalized = str(project_id or "").strip()
    return normalized or None


def _chat_session_aggregate_id(*, workspace_id: str, session_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat-session:{workspace_id}:{session_key}"))


def _ensure_project_scope(db: Session, user: User, *, workspace_id: str, project_id: str | None) -> str | None:
    normalized = _normalized_project_id(project_id)
    if not normalized:
        return None
    project = db.get(Project, normalized)
    if not project or bool(project.is_deleted):
        raise HTTPException(status_code=404, detail="Project not found")
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail="Project does not belong to workspace")
    ensure_project_access(db, workspace_id, normalized, user.id, {"Owner", "Admin", "Member", "Guest"})
    return normalized


def _load_or_create_session_aggregate(
    *,
    db: Session,
    repo: AggregateEventRepository,
    workspace_id: str,
    project_id: str | None,
    session_key: str,
    title: str,
    created_by: str,
    mcp_servers: list[str],
    session_attachment_refs: list[dict[str, Any]] | None = None,
) -> tuple[ChatSessionAggregate, str, int | None]:
    aggregate_id = _chat_session_aggregate_id(workspace_id=workspace_id, session_key=session_key)
    state, version = rebuild_state(db, "ChatSession", aggregate_id)
    if not state and version <= 0:
        aggregate = ChatSessionAggregate(
            id=coerce_originator_id(aggregate_id),
            workspace_id=workspace_id,
            project_id=project_id,
            session_key=session_key,
            title=title,
            created_by=created_by,
            mcp_servers=mcp_servers,
            session_attachment_refs=_normalize_attachment_refs(session_attachment_refs),
        )
        return aggregate, aggregate_id, 0

    aggregate = repo.load_with_class(
        aggregate_type="ChatSession",
        aggregate_id=aggregate_id,
        aggregate_cls=ChatSessionAggregate,
    )
    if bool(getattr(aggregate, "is_archived", False)):
        raise HTTPException(status_code=409, detail="Chat session is archived")
    if str(getattr(aggregate, "created_by", "") or "").strip() != str(created_by or "").strip():
        raise HTTPException(status_code=403, detail="Chat session belongs to another user")
    next_session_attachment_refs = (
        _normalize_attachment_refs(session_attachment_refs)
        if session_attachment_refs is not None
        else None
    )
    current_session_attachment_refs = _normalize_attachment_refs(
        list(getattr(aggregate, "session_attachment_refs", []) or [])
    )
    has_session_attachment_changes = False
    if next_session_attachment_refs is not None:
        has_session_attachment_changes = (
            _attachment_refs_signature(next_session_attachment_refs)
            != _attachment_refs_signature(current_session_attachment_refs)
        )
    if (
        project_id != getattr(aggregate, "project_id", None)
        or mcp_servers != list(getattr(aggregate, "mcp_servers", []) or [])
        or has_session_attachment_changes
    ):
        context_patch: dict[str, Any] = {
            "project_id": project_id,
            "mcp_servers": mcp_servers,
        }
        if next_session_attachment_refs is not None:
            context_patch["session_attachment_refs"] = next_session_attachment_refs
        aggregate.update_context(
            **context_patch,
        )
    return aggregate, aggregate_id, None


def _persist_aggregate(
    *,
    repo: AggregateEventRepository,
    aggregate: ChatSessionAggregate,
    actor_id: str,
    workspace_id: str,
    project_id: str | None,
    session_id: str,
    expected_version: int | None = None,
) -> None:
    repo.persist(
        aggregate,
        base_metadata={
            "actor_id": actor_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "session_id": session_id,
        },
        expected_version=expected_version,
    )


@dataclass(frozen=True, slots=True)
class CommandContext:
    db: Session
    user: User


@dataclass(frozen=True, slots=True)
class AppendUserMessagePayload:
    workspace_id: str
    project_id: str | None
    session_id: str | None
    message_id: str | None
    content: str
    created_at: str | None = None
    mcp_servers: list[str] = field(default_factory=list)
    attachment_refs: list[dict[str, Any]] = field(default_factory=list)
    session_attachment_refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AppendAssistantMessagePayload:
    workspace_id: str
    project_id: str | None
    session_id: str | None
    message_id: str | None
    content: str
    created_at: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    codex_session_id: str | None = None
    mcp_servers: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class UpdateSessionContextPayload:
    workspace_id: str
    project_id: str | None
    session_id: str
    session_attachment_refs: list[dict[str, Any]] | None = None
    mcp_servers: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ArchiveSessionPayload:
    workspace_id: str
    project_id: str | None
    session_id: str


@dataclass(frozen=True, slots=True)
class LinkMessageResourcePayload:
    workspace_id: str
    project_id: str | None
    session_id: str
    message_id: str
    resource_type: str
    resource_id: str
    relation: str = "created"


@dataclass(frozen=True, slots=True)
class AppendUserMessageHandler:
    ctx: CommandContext
    payload: AppendUserMessagePayload

    def __call__(self) -> dict[str, Any]:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member", "Guest"})
        project_id = _ensure_project_scope(
            self.ctx.db,
            self.ctx.user,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
        )
        content = str(self.payload.content or "").strip()
        if not content:
            raise HTTPException(status_code=422, detail="Chat user message cannot be empty")

        session_key = _normalize_session_key(self.payload.session_id)
        mcp_servers = _normalize_mcp_servers(self.payload.mcp_servers)
        session_attachment_refs = _normalize_attachment_refs(self.payload.session_attachment_refs)
        repo = AggregateEventRepository(self.ctx.db)
        aggregate, aggregate_id, expected_version = _load_or_create_session_aggregate(
            db=self.ctx.db,
            repo=repo,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_key=session_key,
            title=_derive_title(content),
            created_by=self.ctx.user.id,
            mcp_servers=mcp_servers,
            session_attachment_refs=session_attachment_refs,
        )

        message_id = _normalize_message_id(self.payload.message_id)
        created_at = _normalize_created_at(self.payload.created_at)
        order_index = int(getattr(aggregate, "next_message_index", 0)) + 1
        attachment_refs = _normalize_attachment_refs(self.payload.attachment_refs)
        # Emit message append before attachment links so projection order never
        # violates chat_attachments.message_id FK constraints.
        aggregate.append_user_message(
            message_id=message_id,
            content=content,
            order_index=order_index,
            created_at=created_at,
            attachment_refs=attachment_refs,
            mcp_servers=mcp_servers,
        )
        for idx, attachment in enumerate(attachment_refs):
            aggregate.link_attachment(
                attachment_id=_attachment_event_id(
                    session_key=session_key,
                    message_id=message_id,
                    path=str(attachment.get("path") or ""),
                    index=idx,
                ),
                message_id=message_id,
                path=str(attachment.get("path") or ""),
                name=attachment.get("name"),
                mime_type=attachment.get("mime_type"),
                size_bytes=attachment.get("size_bytes"),
                checksum=attachment.get("checksum"),
                extraction_status=str(attachment.get("extraction_status") or "pending"),
                extracted_text=attachment.get("extracted_text"),
            )
        _persist_aggregate(
            repo=repo,
            aggregate=aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_id=session_key,
            expected_version=expected_version,
        )
        self.ctx.db.commit()
        return {
            "ok": True,
            "aggregate_id": aggregate_id,
            "session_id": session_key,
            "message_id": message_id,
            "order_index": order_index,
            "created_at": created_at,
        }


@dataclass(frozen=True, slots=True)
class AppendAssistantMessageHandler:
    ctx: CommandContext
    payload: AppendAssistantMessagePayload

    def __call__(self) -> dict[str, Any]:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member", "Guest"})
        project_id = _ensure_project_scope(
            self.ctx.db,
            self.ctx.user,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
        )
        content = str(self.payload.content or "").strip()
        if not content:
            raise HTTPException(status_code=422, detail="Chat assistant message cannot be empty")

        session_key = _normalize_session_key(self.payload.session_id)
        mcp_servers = _normalize_mcp_servers(self.payload.mcp_servers)
        repo = AggregateEventRepository(self.ctx.db)
        aggregate, aggregate_id, expected_version = _load_or_create_session_aggregate(
            db=self.ctx.db,
            repo=repo,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_key=session_key,
            title="Session",
            created_by=self.ctx.user.id,
            mcp_servers=mcp_servers,
        )

        message_id = _normalize_message_id(self.payload.message_id)
        created_at = _normalize_created_at(self.payload.created_at)
        order_index = int(getattr(aggregate, "next_message_index", 0)) + 1
        usage = _normalize_usage(self.payload.usage)
        aggregate.append_assistant_message(
            message_id=message_id,
            content=content,
            order_index=order_index,
            created_at=created_at,
            usage=usage,
            codex_session_id=str(self.payload.codex_session_id or "").strip() or None,
        )
        _persist_aggregate(
            repo=repo,
            aggregate=aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_id=session_key,
            expected_version=expected_version,
        )
        self.ctx.db.commit()
        return {
            "ok": True,
            "aggregate_id": aggregate_id,
            "session_id": session_key,
            "message_id": message_id,
            "order_index": order_index,
            "created_at": created_at,
        }


@dataclass(frozen=True, slots=True)
class UpdateSessionContextHandler:
    ctx: CommandContext
    payload: UpdateSessionContextPayload

    def __call__(self) -> dict[str, Any]:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member", "Guest"})
        project_id = _ensure_project_scope(
            self.ctx.db,
            self.ctx.user,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
        )
        session_key = _normalize_session_key(self.payload.session_id)
        aggregate_id = _chat_session_aggregate_id(workspace_id=self.payload.workspace_id, session_key=session_key)
        state, _ = rebuild_state(self.ctx.db, "ChatSession", aggregate_id)
        if not state:
            raise HTTPException(status_code=404, detail="Chat session not found")

        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="ChatSession",
            aggregate_id=aggregate_id,
            aggregate_cls=ChatSessionAggregate,
        )
        if bool(getattr(aggregate, "is_archived", False)):
            raise HTTPException(status_code=409, detail="Chat session is archived")

        next_session_attachment_refs = (
            _normalize_attachment_refs(self.payload.session_attachment_refs)
            if self.payload.session_attachment_refs is not None
            else None
        )
        next_mcp_servers = (
            _normalize_mcp_servers(self.payload.mcp_servers)
            if self.payload.mcp_servers is not None
            else list(getattr(aggregate, "mcp_servers", []) or [])
        )
        context_patch: dict[str, Any] = {
            "project_id": project_id,
            "mcp_servers": next_mcp_servers,
        }
        if next_session_attachment_refs is not None:
            context_patch["session_attachment_refs"] = next_session_attachment_refs
        aggregate.update_context(**context_patch)
        _persist_aggregate(
            repo=repo,
            aggregate=aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_id=session_key,
        )
        self.ctx.db.commit()
        return {"ok": True, "session_id": session_key, "aggregate_id": aggregate_id}


@dataclass(frozen=True, slots=True)
class ArchiveSessionHandler:
    ctx: CommandContext
    payload: ArchiveSessionPayload

    def __call__(self) -> dict[str, Any]:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member", "Guest"})
        project_id = _ensure_project_scope(
            self.ctx.db,
            self.ctx.user,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
        )
        session_key = _normalize_session_key(self.payload.session_id)
        aggregate_id = _chat_session_aggregate_id(workspace_id=self.payload.workspace_id, session_key=session_key)
        state, _ = rebuild_state(self.ctx.db, "ChatSession", aggregate_id)
        if not state:
            raise HTTPException(status_code=404, detail="Chat session not found")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="ChatSession",
            aggregate_id=aggregate_id,
            aggregate_cls=ChatSessionAggregate,
        )
        if not bool(getattr(aggregate, "is_archived", False)):
            aggregate.archive()
            _persist_aggregate(
                repo=repo,
                aggregate=aggregate,
                actor_id=self.ctx.user.id,
                workspace_id=self.payload.workspace_id,
                project_id=project_id,
                session_id=session_key,
            )
            self.ctx.db.commit()
        return {"ok": True, "session_id": session_key}


@dataclass(frozen=True, slots=True)
class LinkMessageResourceHandler:
    ctx: CommandContext
    payload: LinkMessageResourcePayload

    def __call__(self) -> dict[str, Any]:
        ensure_role(self.ctx.db, self.payload.workspace_id, self.ctx.user.id, {"Owner", "Admin", "Member", "Guest"})
        project_id = _ensure_project_scope(
            self.ctx.db,
            self.ctx.user,
            workspace_id=self.payload.workspace_id,
            project_id=self.payload.project_id,
        )
        session_key = _normalize_session_key(self.payload.session_id)
        aggregate_id = _chat_session_aggregate_id(workspace_id=self.payload.workspace_id, session_key=session_key)
        state, _ = rebuild_state(self.ctx.db, "ChatSession", aggregate_id)
        if not state:
            raise HTTPException(status_code=404, detail="Chat session not found")
        message_id = _normalize_message_id(self.payload.message_id)
        resource_type = str(self.payload.resource_type or "").strip()
        resource_id = str(self.payload.resource_id or "").strip()
        relation = str(self.payload.relation or "created").strip() or "created"
        if not resource_type or not resource_id:
            raise HTTPException(status_code=422, detail="resource_type and resource_id are required")
        repo = AggregateEventRepository(self.ctx.db)
        aggregate = repo.load_with_class(
            aggregate_type="ChatSession",
            aggregate_id=aggregate_id,
            aggregate_cls=ChatSessionAggregate,
        )
        aggregate.link_message_resource(
            message_id=message_id,
            resource_type=resource_type,
            resource_id=resource_id,
            relation=relation,
        )
        _persist_aggregate(
            repo=repo,
            aggregate=aggregate,
            actor_id=self.ctx.user.id,
            workspace_id=self.payload.workspace_id,
            project_id=project_id,
            session_id=session_key,
        )
        self.ctx.db.commit()
        return {
            "ok": True,
            "session_id": session_key,
            "message_id": message_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "relation": relation,
        }
