from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectFromTemplateCreate(BaseModel):
    workspace_id: str
    template_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    custom_statuses: list[str] | None = None
    member_user_ids: list[str] = Field(default_factory=list)
    embedding_enabled: bool | None = None
    embedding_model: str | None = None
    context_pack_evidence_top_k: int | None = Field(default=None, ge=1, le=40)
    chat_index_mode: str | None = None
    chat_attachment_ingestion_mode: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProjectFromTemplatePreview(BaseModel):
    workspace_id: str
    template_key: str = Field(min_length=1)
    name: str = ""
    description: str = ""
    custom_statuses: list[str] | None = None
    member_user_ids: list[str] = Field(default_factory=list)
    embedding_enabled: bool | None = None
    embedding_model: str | None = None
    context_pack_evidence_top_k: int | None = Field(default=None, ge=1, le=40)
    chat_index_mode: str | None = None
    chat_attachment_ingestion_mode: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
