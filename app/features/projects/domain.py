from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event

EVENT_CREATED = "ProjectCreated"
EVENT_DELETED = "ProjectDeleted"
EVENT_UPDATED = "ProjectUpdated"
EVENT_MEMBER_UPSERTED = "ProjectMemberUpserted"
EVENT_MEMBER_REMOVED = "ProjectMemberRemoved"


class ProjectAggregate(Aggregate):
    aggregate_type = "Project"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        name: str,
        description: str,
        custom_statuses: list[str],
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        embedding_enabled: bool = True,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str = "OFF",
        chat_attachment_ingestion_mode: str = "METADATA_ONLY",
        event_storming_enabled: bool = True,
        status: str = "Active",
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.name = name
        self.description = description
        self.custom_statuses = custom_statuses
        self.external_refs = external_refs
        self.attachment_refs = attachment_refs
        self.embedding_enabled = embedding_enabled
        self.embedding_model = embedding_model
        self.context_pack_evidence_top_k = context_pack_evidence_top_k
        self.chat_index_mode = chat_index_mode
        self.chat_attachment_ingestion_mode = chat_attachment_ingestion_mode
        self.event_storming_enabled = event_storming_enabled
        self.status = status
        self.is_deleted = False
        self.member_roles: dict[str, str] = {}

    @event("Updated")
    def update(
        self,
        name: str | None = None,
        description: str | None = None,
        custom_statuses: list[str] | None = None,
        external_refs: list[dict[str, Any]] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
        embedding_enabled: bool | None = None,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str | None = None,
        chat_attachment_ingestion_mode: str | None = None,
        event_storming_enabled: bool | None = None,
        updated_fields: list[str] | None = None,
    ) -> None:
        # Keep an explicit mutation list in event payload so read-model projectors
        # can distinguish intentional null updates from omitted parameters.
        _ = updated_fields
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if custom_statuses is not None:
            self.custom_statuses = custom_statuses
        if external_refs is not None:
            self.external_refs = external_refs
        if attachment_refs is not None:
            self.attachment_refs = attachment_refs
        if embedding_enabled is not None:
            self.embedding_enabled = embedding_enabled
        if embedding_model is not None:
            self.embedding_model = embedding_model
        if context_pack_evidence_top_k is not None:
            self.context_pack_evidence_top_k = context_pack_evidence_top_k
        if chat_index_mode is not None:
            self.chat_index_mode = chat_index_mode
        if chat_attachment_ingestion_mode is not None:
            self.chat_attachment_ingestion_mode = chat_attachment_ingestion_mode
        if event_storming_enabled is not None:
            self.event_storming_enabled = event_storming_enabled

    @event("Deleted")
    def delete(self, deleted_tasks: int = 0, deleted_notes: int = 0) -> None:
        _ = (deleted_tasks, deleted_notes)
        self.is_deleted = True

    @event("MemberUpserted")
    def upsert_member(self, user_id: str, role: str) -> None:
        roles = dict(getattr(self, "member_roles", {}) or {})
        roles[user_id] = role
        self.member_roles = roles

    @event("MemberRemoved")
    def remove_member(self, user_id: str) -> None:
        roles = dict(getattr(self, "member_roles", {}) or {})
        roles.pop(user_id, None)
        self.member_roles = roles
