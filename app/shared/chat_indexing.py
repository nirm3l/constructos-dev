from __future__ import annotations

from dataclasses import dataclass

CHAT_INDEX_MODE_OFF = "OFF"
CHAT_INDEX_MODE_VECTOR_ONLY = "VECTOR_ONLY"
CHAT_INDEX_MODE_KG_AND_VECTOR = "KG_AND_VECTOR"

CHAT_ATTACHMENT_INGESTION_OFF = "OFF"
CHAT_ATTACHMENT_INGESTION_METADATA_ONLY = "METADATA_ONLY"
CHAT_ATTACHMENT_INGESTION_FULL_TEXT = "FULL_TEXT"

_CHAT_INDEX_MODES = {
    CHAT_INDEX_MODE_OFF,
    CHAT_INDEX_MODE_VECTOR_ONLY,
    CHAT_INDEX_MODE_KG_AND_VECTOR,
}

_CHAT_ATTACHMENT_INGESTION_MODES = {
    CHAT_ATTACHMENT_INGESTION_OFF,
    CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
}


@dataclass(frozen=True, slots=True)
class ProjectChatIndexingPolicy:
    index_mode: str = CHAT_INDEX_MODE_OFF
    attachment_ingestion_mode: str = CHAT_ATTACHMENT_INGESTION_METADATA_ONLY

    @property
    def vector_enabled(self) -> bool:
        return self.index_mode in {CHAT_INDEX_MODE_VECTOR_ONLY, CHAT_INDEX_MODE_KG_AND_VECTOR}

    @property
    def graph_enabled(self) -> bool:
        return self.index_mode == CHAT_INDEX_MODE_KG_AND_VECTOR



def normalize_chat_index_mode(value: str | None) -> str:
    mode = str(value or "").strip().upper() or CHAT_INDEX_MODE_OFF
    if mode not in _CHAT_INDEX_MODES:
        return CHAT_INDEX_MODE_OFF
    return mode



def normalize_chat_attachment_ingestion_mode(value: str | None) -> str:
    mode = str(value or "").strip().upper() or CHAT_ATTACHMENT_INGESTION_METADATA_ONLY
    if mode == "FULL_TEXT_OCR":
        return CHAT_ATTACHMENT_INGESTION_FULL_TEXT
    if mode not in _CHAT_ATTACHMENT_INGESTION_MODES:
        return CHAT_ATTACHMENT_INGESTION_METADATA_ONLY
    return mode



def project_chat_indexing_policy(
    *,
    chat_index_mode: str | None,
    chat_attachment_ingestion_mode: str | None,
) -> ProjectChatIndexingPolicy:
    return ProjectChatIndexingPolicy(
        index_mode=normalize_chat_index_mode(chat_index_mode),
        attachment_ingestion_mode=normalize_chat_attachment_ingestion_mode(chat_attachment_ingestion_mode),
    )
