from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


EVENT_CREATED = "ProjectCreated"
EVENT_DELETED = "ProjectDeleted"
EVENT_UPDATED = "ProjectUpdated"
EVENT_MEMBER_UPSERTED = "ProjectMemberUpserted"
EVENT_MEMBER_REMOVED = "ProjectMemberRemoved"


class ProjectAggregate(AggregateRoot):
    aggregate_type = "Project"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.workspace_id = str(payload.get("workspace_id") or "")
            self.name = str(payload.get("name") or "")
            self.description = str(payload.get("description") or "")
            self.custom_statuses = list(payload.get("custom_statuses") or [])
            self.external_refs = list(payload.get("external_refs") or [])
            self.attachment_refs = list(payload.get("attachment_refs") or [])
            self.embedding_enabled = bool(payload.get("embedding_enabled", False))
            self.embedding_model = payload.get("embedding_model")
            self.context_pack_evidence_top_k = payload.get("context_pack_evidence_top_k")
            self.status = str(payload.get("status") or "Active")
            self.is_deleted = bool(payload.get("is_deleted", False))
            self.member_roles = dict(payload.get("member_roles") or {})
            return

        if event_type == EVENT_UPDATED:
            for key, value in dict(payload).items():
                setattr(self, key, value)
            return

        if event_type == EVENT_DELETED:
            self.is_deleted = True
            return

        if event_type == EVENT_MEMBER_UPSERTED:
            member_roles = dict(getattr(self, "member_roles", {}) or {})
            user_id = str(payload.get("user_id") or "")
            role = str(payload.get("role") or "")
            if user_id and role:
                member_roles[user_id] = role
                self.member_roles = member_roles
            return

        if event_type == EVENT_MEMBER_REMOVED:
            member_roles = dict(getattr(self, "member_roles", {}) or {})
            user_id = str(payload.get("user_id") or "")
            if user_id:
                member_roles.pop(user_id, None)
                self.member_roles = member_roles
            return

        raise ValueError(f"Unknown event type: {event_type}")

