from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_STARTED = "ChatSessionStarted"
EVENT_RENAMED = "ChatSessionRenamed"
EVENT_ARCHIVED = "ChatSessionArchived"
EVENT_CONTEXT_UPDATED = "ChatSessionContextUpdated"
EVENT_USER_MESSAGE_APPENDED = "ChatSessionUserMessageAppended"
EVENT_ASSISTANT_MESSAGE_APPENDED = "ChatSessionAssistantMessageAppended"
EVENT_ASSISTANT_MESSAGE_UPDATED = "ChatSessionAssistantMessageUpdated"
EVENT_MESSAGE_DELETED = "ChatSessionMessageDeleted"
EVENT_ATTACHMENT_LINKED = "ChatSessionAttachmentLinked"
EVENT_RESOURCE_LINKED = "ChatSessionMessageResourceLinked"


class ChatSessionAggregate(Aggregate):
    aggregate_type = "ChatSession"

    @event("Started")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str | None,
        session_key: str,
        title: str,
        created_by: str,
        mcp_servers: list[str] | None = None,
        session_attachment_refs: list[dict[str, Any]] | None = None,
        codex_session_id: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.session_key = session_key
        self.title = title
        self.created_by = created_by
        self.mcp_servers = mcp_servers or []
        self.session_attachment_refs = session_attachment_refs or []
        self.codex_session_id = codex_session_id
        self.usage = usage or {}
        self.is_archived = False
        self.last_message_at: str | None = None
        self.last_message_preview = ""
        self.last_task_event_at: str | None = None
        self.next_message_index = 0

    @event("Renamed")
    def rename(self, title: str) -> None:
        self.title = title

    @event("Archived")
    def archive(self) -> None:
        self.is_archived = True

    @event("ContextUpdated")
    def update_context(
        self,
        project_id: str | None = None,
        mcp_servers: list[str] | None = None,
        session_attachment_refs: list[dict[str, Any]] | None = None,
        codex_session_id: str | None = None,
        usage: dict[str, Any] | None = None,
        last_task_event_at: str | None = None,
    ) -> None:
        if project_id is not None:
            self.project_id = project_id
        if mcp_servers is not None:
            self.mcp_servers = mcp_servers
        if session_attachment_refs is not None:
            self.session_attachment_refs = session_attachment_refs
        if codex_session_id is not None:
            self.codex_session_id = codex_session_id
        if usage is not None:
            self.usage = usage
        if last_task_event_at is not None:
            self.last_task_event_at = last_task_event_at

    @event("UserMessageAppended")
    def append_user_message(
        self,
        message_id: str,
        content: str,
        order_index: int,
        created_at: str,
        attachment_refs: list[dict[str, Any]] | None = None,
        mcp_servers: list[str] | None = None,
    ) -> None:
        _ = (message_id, attachment_refs)
        self.next_message_index = max(int(self.next_message_index), int(order_index))
        self.last_message_at = created_at
        self.last_message_preview = str(content or "")[:240]
        if mcp_servers is not None:
            self.mcp_servers = mcp_servers

    @event("AssistantMessageAppended")
    def append_assistant_message(
        self,
        message_id: str,
        content: str,
        order_index: int,
        created_at: str,
        usage: dict[str, Any] | None = None,
        codex_session_id: str | None = None,
    ) -> None:
        _ = message_id
        self.next_message_index = max(int(self.next_message_index), int(order_index))
        self.last_message_at = created_at
        self.last_message_preview = str(content or "")[:240]
        if usage is not None:
            self.usage = usage
        if codex_session_id is not None:
            self.codex_session_id = codex_session_id

    @event("AssistantMessageUpdated")
    def update_assistant_message(
        self,
        message_id: str,
        content: str,
        usage: dict[str, Any] | None = None,
        codex_session_id: str | None = None,
    ) -> None:
        _ = message_id
        self.last_message_preview = str(content or "")[:240]
        if usage is not None:
            self.usage = usage
        if codex_session_id is not None:
            self.codex_session_id = codex_session_id

    @event("MessageDeleted")
    def delete_message(self, message_id: str) -> None:
        _ = message_id

    @event("AttachmentLinked")
    def link_attachment(
        self,
        attachment_id: str,
        message_id: str,
        path: str,
        name: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        checksum: str | None = None,
        extraction_status: str = "pending",
        extracted_text: str | None = None,
    ) -> None:
        _ = (
            attachment_id,
            message_id,
            path,
            name,
            mime_type,
            size_bytes,
            checksum,
            extraction_status,
            extracted_text,
        )

    @event("MessageResourceLinked")
    def link_message_resource(
        self,
        message_id: str,
        resource_type: str,
        resource_id: str,
        relation: str = "created",
    ) -> None:
        _ = (message_id, resource_type, resource_id, relation)
