from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .observability import incr, observe
from .settings import (
    ALLOWED_EMBEDDING_MODELS,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_GPU_ENABLED,
    VECTOR_STORE_ENABLED,
    logger,
)
from .chat_indexing import (
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT_OCR,
    CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
    CHAT_ATTACHMENT_INGESTION_OFF,
    CHAT_INDEX_MODE_KG_AND_VECTOR,
    CHAT_INDEX_MODE_VECTOR_ONLY,
    normalize_chat_attachment_ingestion_mode,
    normalize_chat_index_mode,
)

_WORD_RE = re.compile(r"\S+")
_CONTEXT_ERROR_MARKERS = (
    "context length",
    "input length exceeds",
    "too long",
)
_MODEL_NOT_FOUND_RE = re.compile(r'model\s+"?([^"]+)"?\s+not\s+found', re.IGNORECASE)
_OLLAMA_MODEL_PULL_LOCK = threading.Lock()
_OLLAMA_MODELS_READY: set[str] = set()


class EmbeddingRuntimeError(RuntimeError):
    pass


class EmbeddingContextLengthError(EmbeddingRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectEmbeddingRuntime:
    project_id: str
    enabled: bool
    model: str


def vector_store_enabled() -> bool:
    return bool(VECTOR_STORE_ENABLED and EMBEDDING_PROVIDER == "ollama" and str(OLLAMA_BASE_URL or "").strip())


def _allowed_embedding_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for model in ALLOWED_EMBEDDING_MODELS:
        normalized = str(model or "").strip()
        if not normalized:
            continue
        out.setdefault(normalized.casefold(), normalized)
    return out


def normalize_embedding_model(model: str | None) -> str:
    normalized = str(model or "").strip()
    allowed_map = _allowed_embedding_map()
    if not normalized:
        normalized = str(DEFAULT_EMBEDDING_MODEL or "").strip()
    canonical = allowed_map.get(normalized.casefold())
    if canonical is not None:
        return canonical
    if allowed_map:
        return next(iter(allowed_map.values()))
    return normalized or "nomic-embed-text"


def resolve_project_embedding_runtime(db: Session, project_id: str) -> ProjectEmbeddingRuntime:
    from .models import Project

    project = db.get(Project, project_id)
    if project is None or project.is_deleted:
        return ProjectEmbeddingRuntime(project_id=project_id, enabled=False, model=normalize_embedding_model(None))
    model = normalize_embedding_model(project.embedding_model)
    enabled = bool(vector_store_enabled() and project.embedding_enabled)
    return ProjectEmbeddingRuntime(project_id=project_id, enabled=enabled, model=model)


def estimate_tokens(text: str) -> int:
    return len(_WORD_RE.findall(str(text or "")))


def chunk_text(text: str, *, max_tokens: int = 500, overlap_ratio: float = 0.12) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    max_tokens = max(32, int(max_tokens or 500))
    words = raw.split()
    if len(words) <= max_tokens:
        return [raw]
    overlap = max(1, int(max_tokens * max(0.0, min(float(overlap_ratio), 0.45))))
    step = max(1, max_tokens - overlap)
    chunks: list[str] = []
    for idx in range(0, len(words), step):
        part = " ".join(words[idx : idx + max_tokens]).strip()
        if not part:
            continue
        if part in chunks:
            continue
        chunks.append(part)
        if idx + max_tokens >= len(words):
            break
    return chunks


def _is_context_length_error(message: str) -> bool:
    low = str(message or "").lower()
    return any(marker in low for marker in _CONTEXT_ERROR_MARKERS)


def _is_model_not_found_error(message: str, *, model: str | None = None) -> bool:
    raw_text = str(message or "").strip()
    if not raw_text:
        return False
    text = raw_text
    try:
        payload = json.loads(raw_text)
        if isinstance(payload, dict):
            candidate = payload.get("error")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate.strip()
    except Exception:
        pass
    if not text:
        return False
    match = _MODEL_NOT_FOUND_RE.search(text)
    if not match:
        low = text.lower()
        return "model" in low and "not found" in low and "pulling it first" in low
    if not model:
        return True
    missing = str(match.group(1) or "").strip().casefold()
    expected = str(model).strip().casefold()
    return not missing or missing == expected


def _ensure_ollama_model_available(model: str) -> None:
    normalized = str(model or "").strip()
    if not normalized:
        return
    if normalized in _OLLAMA_MODELS_READY:
        return
    with _OLLAMA_MODEL_PULL_LOCK:
        if normalized in _OLLAMA_MODELS_READY:
            return
        pull_url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/pull"
        response = httpx.post(
            pull_url,
            json={"model": normalized, "stream": False},
            timeout=600.0,
        )
        if response.status_code >= 400:
            detail = (response.text or f"Ollama pull request failed ({response.status_code})").strip()
            raise EmbeddingRuntimeError(detail)
        _OLLAMA_MODELS_READY.add(normalized)


def _ollama_embed_text(text: str, model: str) -> list[float]:
    started_at = time.perf_counter()
    incr("embedding_requests_total")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": text,
        "options": {"num_gpu": 1 if OLLAMA_EMBED_GPU_ENABLED else 0},
    }
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
    try:
        data: dict[str, Any] | None = None
        for attempt in (0, 1):
            response = httpx.post(url, json=payload, timeout=45.0)
            if response.status_code < 400:
                data = response.json()
                break
            detail = (response.text or f"Ollama embedding request failed ({response.status_code})").strip()
            if _is_context_length_error(detail):
                incr("embedding_context_length_errors")
                raise EmbeddingContextLengthError(detail)
            if attempt == 0 and _is_model_not_found_error(detail, model=model):
                _ensure_ollama_model_available(model)
                continue
            raise EmbeddingRuntimeError(detail)
        if data is None:
            raise EmbeddingRuntimeError("Embedding request failed without response payload")
    except Exception as exc:
        detail = str(exc)
        if _is_context_length_error(detail):
            incr("embedding_context_length_errors")
            raise EmbeddingContextLengthError(detail) from exc
        raise EmbeddingRuntimeError(detail) from exc
    finally:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        observe("embedding_ingest_latency_ms", latency_ms)
    embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise EmbeddingRuntimeError("Embedding response is missing vector payload")
    out: list[float] = []
    for value in embedding:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    if not out:
        raise EmbeddingRuntimeError("Embedding vector is empty")
    return out


def _embed_text_with_split_retry(text: str, model: str) -> list[tuple[str, list[float]]]:
    queue: list[str] = [str(text or "").strip()]
    out: list[tuple[str, list[float]]] = []
    while queue:
        current = queue.pop(0).strip()
        if not current:
            continue
        try:
            out.append((current, _ollama_embed_text(current, model)))
            continue
        except EmbeddingContextLengthError:
            tokens = estimate_tokens(current)
            if tokens <= 60:
                raise
            split_chunks = chunk_text(current, max_tokens=max(60, tokens // 2), overlap_ratio=0.1)
            if len(split_chunks) <= 1:
                raise
            queue = split_chunks + queue
    return out


def _embedding_to_json(embedding: list[float]) -> str:
    return json.dumps(embedding, separators=(",", ":"))


def _entity_state_sources(entity_type: str, state: dict[str, Any]) -> list[tuple[str, str]]:
    et = str(entity_type or "").strip().lower()
    sources: list[tuple[str, str]] = []
    if et == "task":
        title = str(state.get("title") or "").strip()
        description = str(state.get("description") or "").strip()
        if title:
            sources.append(("task.title", title))
        if description:
            sources.append(("task.description", description))
    elif et == "note":
        title = str(state.get("title") or "").strip()
        body = str(state.get("body") or "").strip()
        if title:
            sources.append(("note.title", title))
        if body:
            sources.append(("note.body", body))
    elif et == "specification":
        title = str(state.get("title") or "").strip()
        body = str(state.get("body") or "").strip()
        if title:
            sources.append(("specification.title", title))
        if body:
            sources.append(("specification.body", body))
    elif et == "projectrule":
        title = str(state.get("title") or "").strip()
        body = str(state.get("body") or "").strip()
        if title:
            sources.append(("project_rule.title", title))
        if body:
            sources.append(("project_rule.body", body))
    elif et == "chatmessage":
        content = str(state.get("content") or "").strip()
        role = str(state.get("role") or "").strip().lower()
        if content:
            normalized_role = role if role in {"user", "assistant"} else "message"
            sources.append((f"chat_message.{normalized_role}", content))
    elif et == "chatattachment":
        ingestion_mode = normalize_chat_attachment_ingestion_mode(state.get("chat_attachment_ingestion_mode"))
        if ingestion_mode != CHAT_ATTACHMENT_INGESTION_OFF:
            name = str(state.get("name") or "").strip()
            path = str(state.get("path") or "").strip()
            mime_type = str(state.get("mime_type") or "").strip()
            size_bytes = state.get("size_bytes")
            metadata_parts: list[str] = []
            if name:
                metadata_parts.append(f"name: {name}")
            if path:
                metadata_parts.append(f"path: {path}")
            if mime_type:
                metadata_parts.append(f"mime_type: {mime_type}")
            if isinstance(size_bytes, int) and size_bytes >= 0:
                metadata_parts.append(f"size_bytes: {size_bytes}")
            if metadata_parts and ingestion_mode in {
                CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
                CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
                CHAT_ATTACHMENT_INGESTION_FULL_TEXT_OCR,
            }:
                sources.append(("chat_attachment.metadata", "\n".join(metadata_parts)))

        extracted_text = str(state.get("extracted_text") or "").strip()
        if extracted_text and ingestion_mode in {
            CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
            CHAT_ATTACHMENT_INGESTION_FULL_TEXT_OCR,
        }:
            sources.append(("chat_attachment.text", extracted_text))
    return sources


def _state_is_indexable(entity_type: str, state: dict[str, Any]) -> bool:
    et = str(entity_type or "").strip().lower()
    if not state:
        return False
    if bool(state.get("is_deleted", False)):
        return False
    if et in {"task", "note", "specification"} and bool(state.get("archived", False)):
        return False
    if et == "task" and not str(state.get("project_id") or "").strip():
        return False
    if et in {"task", "note", "specification", "projectrule", "chatmessage", "chatattachment"} and not str(
        state.get("project_id") or ""
    ).strip():
        return False
    if et == "chatattachment":
        ingestion_mode = normalize_chat_attachment_ingestion_mode(state.get("chat_attachment_ingestion_mode"))
        if ingestion_mode == CHAT_ATTACHMENT_INGESTION_OFF:
            return False
    if et == "chatmessage":
        if not str(state.get("content") or "").strip():
            return False
    return True


def purge_entity_chunks(db: Session, *, project_id: str, entity_type: str, entity_id: str) -> int:
    from .models import VectorChunk

    result = db.execute(
        delete(VectorChunk).where(
            VectorChunk.project_id == project_id,
            VectorChunk.entity_type == entity_type,
            VectorChunk.entity_id == entity_id,
        )
    )
    return int(result.rowcount or 0)


def purge_project_chunks(db: Session, *, project_id: str) -> int:
    from .models import VectorChunk

    result = db.execute(delete(VectorChunk).where(VectorChunk.project_id == project_id))
    return int(result.rowcount or 0)


def index_entity_state(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    state: dict[str, Any],
    force_reindex: bool = False,
    runtime_override: ProjectEmbeddingRuntime | None = None,
) -> int:
    from .models import VectorChunk

    project_id = str(state.get("project_id") or "").strip()
    workspace_id = str(state.get("workspace_id") or "").strip()
    if not project_id or not workspace_id:
        return 0
    runtime = runtime_override or resolve_project_embedding_runtime(db, project_id)
    if not runtime.enabled:
        return 0
    if not _state_is_indexable(entity_type, state):
        purge_entity_chunks(db, project_id=project_id, entity_type=entity_type, entity_id=entity_id)
        return 0

    sources = _entity_state_sources(entity_type, state)
    if not sources:
        purge_entity_chunks(db, project_id=project_id, entity_type=entity_type, entity_id=entity_id)
        return 0

    if force_reindex:
        purge_entity_chunks(db, project_id=project_id, entity_type=entity_type, entity_id=entity_id)
    else:
        purge_entity_chunks(db, project_id=project_id, entity_type=entity_type, entity_id=entity_id)

    source_updated_at: datetime | None = None
    raw_updated_at = state.get("updated_at")
    if isinstance(raw_updated_at, datetime):
        source_updated_at = raw_updated_at if raw_updated_at.tzinfo else raw_updated_at.replace(tzinfo=timezone.utc)

    indexed = 0
    for source_type, source_text in sources:
        chunk_items = chunk_text(source_text, max_tokens=500, overlap_ratio=0.12)
        chunk_index = 0
        for chunk in chunk_items:
            for effective_chunk, embedding in _embed_text_with_split_retry(chunk, runtime.model):
                token_count = estimate_tokens(effective_chunk)
                content_hash = hashlib.sha256(
                    f"{entity_type}:{entity_id}:{source_type}:{effective_chunk}".encode("utf-8")
                ).hexdigest()
                db.add(
                    VectorChunk(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        source_type=source_type,
                        chunk_index=chunk_index,
                        text_chunk=effective_chunk,
                        token_count=token_count,
                        embedding_json=_embedding_to_json(embedding),
                        embedding_model=runtime.model,
                        content_hash=content_hash,
                        source_updated_at=source_updated_at,
                        is_deleted=False,
                    )
                )
                chunk_index += 1
                indexed += 1

    if indexed:
        incr("vector_indexed_chunks", indexed)
    return indexed


def reindex_project(db: Session, *, project_id: str) -> int:
    runtime = resolve_project_embedding_runtime(db, project_id)
    return reindex_project_with_runtime(db, project_id=project_id, runtime=runtime)


def _parse_embedding(raw: str) -> list[float]:
    try:
        payload = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: list[float] = []
    for value in payload:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    size = min(len(a), len(b))
    if size <= 0:
        return 0.0
    lhs = a[:size]
    rhs = b[:size]
    dot = sum(x * y for x, y in zip(lhs, rhs))
    lhs_norm = math.sqrt(sum(x * x for x in lhs))
    rhs_norm = math.sqrt(sum(y * y for y in rhs))
    if lhs_norm <= 0 or rhs_norm <= 0:
        return 0.0
    return dot / (lhs_norm * rhs_norm)


def search_project_chunks(
    db: Session,
    *,
    project_id: str,
    query: str,
    limit: int,
    entity_filters: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    from .models import VectorChunk

    runtime = resolve_project_embedding_runtime(db, project_id)
    if not runtime.enabled:
        return []
    text_query = str(query or "").strip()
    if not text_query:
        return []

    started_at = time.perf_counter()
    query_embedding = _ollama_embed_text(text_query, runtime.model)
    rows = db.execute(
        select(VectorChunk).where(
            VectorChunk.project_id == project_id,
            VectorChunk.is_deleted == False,
        )
    ).scalars().all()

    evidence: list[dict[str, Any]] = []
    filters = entity_filters or set()
    for row in rows:
        if filters and (row.entity_type, row.entity_id) not in filters:
            continue
        vector = _parse_embedding(row.embedding_json)
        if not vector:
            continue
        similarity = _cosine_similarity(query_embedding, vector)
        evidence.append(
            {
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "source_type": row.source_type,
                "chunk_index": row.chunk_index,
                "snippet": row.text_chunk,
                "vector_similarity": similarity,
                "source_updated_at": row.source_updated_at,
            }
        )

    evidence.sort(
        key=lambda item: (
            -float(item.get("vector_similarity") or 0.0),
            str(item.get("source_type") or ""),
            str(item.get("entity_id") or ""),
            int(item.get("chunk_index") or 0),
        )
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    observe("vector_retrieval_latency_ms", latency_ms)
    return evidence[: max(1, int(limit or 10))]


def maybe_reindex_project(
    db: Session,
    *,
    project_id: str,
    embedding_enabled: bool | None = None,
    embedding_model: str | None = None,
) -> int:
    from .models import Project

    runtime_override: ProjectEmbeddingRuntime | None = None
    if embedding_enabled is not None or embedding_model is not None:
        project = db.get(Project, project_id)
        resolved_enabled = bool(embedding_enabled if embedding_enabled is not None else (project.embedding_enabled if project else False))
        resolved_model = normalize_embedding_model(embedding_model if embedding_model is not None else (project.embedding_model if project else None))
        runtime_override = ProjectEmbeddingRuntime(
            project_id=project_id,
            enabled=bool(vector_store_enabled() and resolved_enabled),
            model=resolved_model,
        )
    try:
        if runtime_override is None:
            return reindex_project(db, project_id=project_id)
        return reindex_project_with_runtime(db, project_id=project_id, runtime=runtime_override)
    except Exception as exc:
        logger.warning("Vector project reindex failed project_id=%s err=%s", project_id, exc)
        return 0


def reindex_project_with_runtime(db: Session, *, project_id: str, runtime: ProjectEmbeddingRuntime) -> int:
    from .models import ChatAttachment, ChatMessage, Note, Project, ProjectRule, Specification, Task

    project = db.get(Project, project_id)
    if project is None or project.is_deleted:
        purge_project_chunks(db, project_id=project_id)
        return 0
    if not runtime.enabled:
        return 0

    purge_project_chunks(db, project_id=project_id)
    total = 0

    tasks = db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.is_deleted == False,
            Task.archived == False,
        )
    ).scalars().all()
    for task in tasks:
        total += index_entity_state(
            db,
            entity_type="Task",
            entity_id=task.id,
            state={
                "workspace_id": task.workspace_id,
                "project_id": task.project_id,
                "title": task.title or "",
                "description": task.description or "",
                "archived": bool(task.archived),
                "is_deleted": bool(task.is_deleted),
                "updated_at": task.updated_at,
            },
            force_reindex=True,
            runtime_override=runtime,
        )

    notes = db.execute(
        select(Note).where(
            Note.project_id == project_id,
            Note.is_deleted == False,
            Note.archived == False,
        )
    ).scalars().all()
    for note in notes:
        total += index_entity_state(
            db,
            entity_type="Note",
            entity_id=note.id,
            state={
                "workspace_id": note.workspace_id,
                "project_id": note.project_id,
                "title": note.title or "",
                "body": note.body or "",
                "archived": bool(note.archived),
                "is_deleted": bool(note.is_deleted),
                "updated_at": note.updated_at,
            },
            force_reindex=True,
            runtime_override=runtime,
        )

    specifications = db.execute(
        select(Specification).where(
            Specification.project_id == project_id,
            Specification.is_deleted == False,
            Specification.archived == False,
        )
    ).scalars().all()
    for specification in specifications:
        total += index_entity_state(
            db,
            entity_type="Specification",
            entity_id=specification.id,
            state={
                "workspace_id": specification.workspace_id,
                "project_id": specification.project_id,
                "title": specification.title or "",
                "body": specification.body or "",
                "archived": bool(specification.archived),
                "is_deleted": bool(specification.is_deleted),
                "updated_at": specification.updated_at,
            },
            force_reindex=True,
            runtime_override=runtime,
        )

    rules = db.execute(
        select(ProjectRule).where(
            ProjectRule.project_id == project_id,
            ProjectRule.is_deleted == False,
        )
    ).scalars().all()
    for rule in rules:
        total += index_entity_state(
            db,
            entity_type="ProjectRule",
            entity_id=rule.id,
            state={
                "workspace_id": rule.workspace_id,
                "project_id": rule.project_id,
                "title": rule.title or "",
                "body": rule.body or "",
                "is_deleted": bool(rule.is_deleted),
                "updated_at": rule.updated_at,
            },
            force_reindex=True,
            runtime_override=runtime,
        )

    chat_index_mode = normalize_chat_index_mode(getattr(project, "chat_index_mode", None))
    chat_attachment_ingestion_mode = normalize_chat_attachment_ingestion_mode(
        getattr(project, "chat_attachment_ingestion_mode", None)
    )
    if chat_index_mode in {CHAT_INDEX_MODE_VECTOR_ONLY, CHAT_INDEX_MODE_KG_AND_VECTOR}:
        messages = db.execute(
            select(ChatMessage).where(
                ChatMessage.project_id == project_id,
                ChatMessage.is_deleted == False,
            )
        ).scalars().all()
        for message in messages:
            total += index_entity_state(
                db,
                entity_type="ChatMessage",
                entity_id=message.id,
                state={
                    "workspace_id": message.workspace_id,
                    "project_id": message.project_id,
                    "role": message.role or "",
                    "content": message.content or "",
                    "is_deleted": bool(message.is_deleted),
                    "updated_at": message.updated_at,
                },
                force_reindex=True,
                runtime_override=runtime,
            )

        attachments = db.execute(
            select(ChatAttachment).where(
                ChatAttachment.project_id == project_id,
                ChatAttachment.is_deleted == False,
            )
        ).scalars().all()
        for attachment in attachments:
            total += index_entity_state(
                db,
                entity_type="ChatAttachment",
                entity_id=attachment.id,
                state={
                    "workspace_id": attachment.workspace_id,
                    "project_id": attachment.project_id,
                    "path": attachment.path or "",
                    "name": attachment.name or "",
                    "mime_type": attachment.mime_type or "",
                    "size_bytes": attachment.size_bytes,
                    "extraction_status": attachment.extraction_status or "pending",
                    "extracted_text": attachment.extracted_text or "",
                    "chat_attachment_ingestion_mode": chat_attachment_ingestion_mode,
                    "is_deleted": bool(attachment.is_deleted),
                    "updated_at": attachment.updated_at,
                },
                force_reindex=True,
                runtime_override=runtime,
            )

    return total


def project_embedding_index_status(
    db: Session,
    *,
    project_id: str,
    embedding_enabled: bool | None = None,
    embedding_model: str | None = None,
) -> str:
    from .models import Project, VectorChunk

    enabled = embedding_enabled
    model = embedding_model
    if enabled is None or model is None:
        project = db.get(Project, project_id)
        if project is None or project.is_deleted:
            return "not_indexed"
        if enabled is None:
            enabled = bool(project.embedding_enabled)
        if model is None:
            model = project.embedding_model

    if not bool(enabled):
        return "not_indexed"
    if not vector_store_enabled():
        return "not_indexed"

    expected_model = normalize_embedding_model(model)
    stats = db.execute(
        select(
            func.count(VectorChunk.id).label("chunk_count"),
            func.count(func.distinct(VectorChunk.embedding_model)).label("model_count"),
            func.max(VectorChunk.embedding_model).label("max_model"),
            func.min(VectorChunk.embedding_model).label("min_model"),
        ).where(
            VectorChunk.project_id == project_id,
            VectorChunk.is_deleted == False,
        )
    ).mappings().first()
    if not stats:
        return "indexing"

    chunk_count = int(stats.get("chunk_count") or 0)
    if chunk_count <= 0:
        return "indexing"

    model_count = int(stats.get("model_count") or 0)
    max_model = str(stats.get("max_model") or "").strip()
    min_model = str(stats.get("min_model") or "").strip()
    if model_count > 1:
        return "stale"
    if max_model and min_model and max_model != min_model:
        return "stale"
    if expected_model and max_model and normalize_embedding_model(max_model) != expected_model:
        return "stale"
    return "ready"
