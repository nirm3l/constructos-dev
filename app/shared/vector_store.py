from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, inspect, or_, select, text
from sqlalchemy.orm import Session

from .observability import incr, observe
from .settings import (
    ALLOWED_EMBEDDING_MODELS,
    CHAT_VECTOR_RETENTION_MODE,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_GPU_ENABLED,
    VECTOR_INDEX_DISTILL_ENABLED,
    VECTOR_INDEX_DISTILL_MAX_SOURCES_PER_REQUEST,
    VECTOR_INDEX_DISTILL_MAX_SOURCE_TOKENS,
    VECTOR_INDEX_DISTILL_MIN_TOKENS,
    VECTOR_STORE_ENABLED,
    logger,
)
from .classification_cache import ClassificationCache, build_classification_cache_key
from .chat_indexing import (
    CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
    CHAT_ATTACHMENT_INGESTION_METADATA_ONLY,
    CHAT_ATTACHMENT_INGESTION_OFF,
    CHAT_INDEX_MODE_KG_AND_VECTOR,
    CHAT_INDEX_MODE_VECTOR_ONLY,
    normalize_chat_attachment_ingestion_mode,
    normalize_chat_index_mode,
    project_chat_indexing_policy,
)

_WORD_RE = re.compile(r"\S+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CONTEXT_ERROR_MARKERS = (
    "context length",
    "input length exceeds",
    "too long",
)
_MODEL_NOT_FOUND_RE = re.compile(r'model\s+"?([^"]+)"?\s+not\s+found', re.IGNORECASE)
_OLLAMA_MODEL_PULL_LOCK = threading.Lock()
_OLLAMA_MODELS_READY: set[str] = set()
_VECTOR_DISTILLATION_VERSION = "vector-distillation-v1"
_VECTOR_DISTILLATION_SCHEMA_VERSION = "1"
_VECTOR_DISTILLATION_CACHE = ClassificationCache(max_entries=256)
_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parent / "prompt_templates" / "codex"


class EmbeddingRuntimeError(RuntimeError):
    pass


class EmbeddingContextLengthError(EmbeddingRuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectEmbeddingRuntime:
    project_id: str
    enabled: bool
    model: str
    distill_enabled: bool = False


_PGVECTOR_INDEX_LOCK = threading.Lock()
_PGVECTOR_INDEXES_READY: set[tuple[str, int]] = set()


def vector_store_enabled() -> bool:
    return bool(VECTOR_STORE_ENABLED and EMBEDDING_PROVIDER == "ollama" and str(OLLAMA_BASE_URL or "").strip())


def vector_backend_health_summary(db: Session) -> dict[str, Any]:
    bind = db.bind
    dialect_name = str(getattr(getattr(bind, "dialect", None), "name", "")).strip().lower()
    enabled = bool(vector_store_enabled())
    summary: dict[str, Any] = {
        "enabled": enabled,
        "database": dialect_name or None,
        "provider": str(EMBEDDING_PROVIDER or "").strip() or None,
        "status": "disabled" if not enabled else "unknown",
    }
    if not enabled:
        return summary
    if dialect_name != "postgresql":
        summary["status"] = "unsupported_database"
        summary["detail"] = "pgvector retrieval requires PostgreSQL"
        return summary

    extension_ready = False
    vector_column_present = False
    indexed_models = 0
    try:
        extension_ready = bool(db.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar())
        columns = {column["name"] for column in inspect(bind).get_columns("vector_chunks")}
        vector_column_present = "embedding_vector" in columns
        indexed_models = int(
            db.execute(
                text(
                    "SELECT COUNT(*) "
                    "FROM ("
                    "SELECT DISTINCT embedding_model "
                    "FROM vector_chunks "
                    "WHERE is_deleted = FALSE "
                    "AND embedding_vector IS NOT NULL"
                    ") AS indexed_models"
                )
            ).scalar()
            or 0
        )
    except Exception as exc:
        summary["status"] = "error"
        summary["detail"] = str(exc)
        return summary

    summary.update(
        {
            "extension_ready": extension_ready,
            "vector_column_present": vector_column_present,
            "indexed_models": indexed_models,
        }
    )
    summary["status"] = "ready" if extension_ready and vector_column_present else "not_ready"
    return summary


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
        return ProjectEmbeddingRuntime(
            project_id=project_id,
            enabled=False,
            model=normalize_embedding_model(None),
            distill_enabled=bool(VECTOR_INDEX_DISTILL_ENABLED),
        )
    model = normalize_embedding_model(project.embedding_model)
    enabled = bool(vector_store_enabled() and project.embedding_enabled)
    return ProjectEmbeddingRuntime(
        project_id=project_id,
        enabled=enabled,
        model=model,
        distill_enabled=bool(getattr(project, "vector_index_distill_enabled", VECTOR_INDEX_DISTILL_ENABLED)),
    )


def estimate_tokens(text: str) -> int:
    return len(_WORD_RE.findall(str(text or "")))


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    return (_PROMPT_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _render_prompt_template(name: str, values: dict[str, object]) -> str:
    rendered_values = {key: str(value) for key, value in values.items()}
    return _load_prompt_template(name).format(**rendered_values)


def _truncate_to_token_limit(text: str, *, max_tokens: int) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    safe_limit = max(32, int(max_tokens or 0))
    words = raw.split()
    if len(words) <= safe_limit:
        return raw
    return " ".join(words[:safe_limit]).strip()


def _source_type_supports_distillation(source_type: str) -> bool:
    normalized = str(source_type or "").strip().lower()
    return normalized in {
        "task.description",
        "note.body",
        "specification.body",
        "project_rule.body",
        "chat_attachment.text",
    }


def _distillation_candidates(sources: list[tuple[str, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source_type, source_text in sources:
        normalized_text = str(source_text or "").strip()
        if not normalized_text:
            continue
        if not _source_type_supports_distillation(source_type):
            continue
        token_count = estimate_tokens(normalized_text)
        if token_count < max(1, int(VECTOR_INDEX_DISTILL_MIN_TOKENS)):
            continue
        candidates.append(
            {
                "source_type": str(source_type),
                "token_count": token_count,
                "text": _truncate_to_token_limit(
                    normalized_text,
                    max_tokens=max(128, int(VECTOR_INDEX_DISTILL_MAX_SOURCE_TOKENS)),
                ),
            }
        )
    return candidates[: max(1, int(VECTOR_INDEX_DISTILL_MAX_SOURCES_PER_REQUEST or 1))]


def _normalize_distilled_sources(raw: dict[str, Any], *, allowed_source_types: set[str]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for item in (raw.get("sources") or []):
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("source_type") or "").strip()
        if source_type not in allowed_source_types:
            continue
        distilled_text = " ".join(str(item.get("distilled_text") or "").split()).strip()
        if not distilled_text:
            continue
        results.append((f"{source_type}.distilled", distilled_text))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        if item in seen:
            continue
        deduped.append(item)
        seen.add(item)
    return deduped


def _distill_index_sources(
    *,
    enabled: bool,
    workspace_id: str,
    project_id: str,
    entity_type: str,
    entity_id: str,
    sources: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    candidates = _distillation_candidates(sources) if enabled else []
    if not candidates:
        return []

    payload = {
        "entity_type": str(entity_type or "").strip(),
        "entity_id": str(entity_id or "").strip(),
        "sources": [
            {
                "source_type": item["source_type"],
                "token_count": int(item["token_count"]),
                "text": str(item["text"]),
            }
            for item in candidates
        ],
    }
    cache_key = build_classification_cache_key(
        cache_name="vector_source_distillation",
        workspace_id=str(workspace_id or "").strip() or None,
        project_id=str(project_id or "").strip() or None,
        classifier_version=_VECTOR_DISTILLATION_VERSION,
        schema_version=_VECTOR_DISTILLATION_SCHEMA_VERSION,
        payload=payload,
    )
    cached = _VECTOR_DISTILLATION_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return _normalize_distilled_sources(
            cached,
            allowed_source_types={str(item["source_type"]) for item in candidates},
        )

    prompt = _render_prompt_template(
        "vector_index_distillation.md",
        {"payload_json": json.dumps(payload, ensure_ascii=True)},
    )
    output_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_type": {"type": "string"},
                        "distilled_text": {"type": "string"},
                    },
                    "required": ["source_type", "distilled_text"],
                },
            }
        },
        "required": ["sources"],
    }
    payload_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    try:
        from features.agents.agent_mcp_adapter import run_structured_agent_prompt

        parsed = run_structured_agent_prompt(
            prompt=prompt,
            output_schema=output_schema,
            workspace_id=str(workspace_id or "").strip() or None,
            session_key=f"vector-index-distillation:{payload_hash}",
            actor_user_id=None,
            mcp_servers=[],
            use_cache=True,
        )
    except Exception as exc:
        logger.warning(
            "Vector source distillation failed project_id=%s entity=%s:%s err=%s",
            project_id,
            entity_type,
            entity_id,
            exc,
        )
        return []
    if not isinstance(parsed, dict):
        return []
    _VECTOR_DISTILLATION_CACHE.set(cache_key, parsed)
    return _normalize_distilled_sources(
        parsed,
        allowed_source_types={str(item["source_type"]) for item in candidates},
    )


def _split_words_with_overlap(text: str, *, max_tokens: int, overlap_ratio: float) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
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


def _split_oversized_unit(unit: str, *, max_tokens: int, overlap_ratio: float) -> list[str]:
    text = str(unit or "").strip()
    if not text:
        return []
    if estimate_tokens(text) <= max_tokens:
        return [text]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        parts: list[str] = []
        for line in lines:
            parts.extend(_split_oversized_unit(line, max_tokens=max_tokens, overlap_ratio=overlap_ratio))
        if parts:
            return parts

    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if len(sentences) > 1:
        parts = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = estimate_tokens(sentence)
            if sentence_tokens > max_tokens:
                if current:
                    parts.append(" ".join(current).strip())
                    current = []
                    current_tokens = 0
                parts.extend(_split_words_with_overlap(sentence, max_tokens=max_tokens, overlap_ratio=overlap_ratio))
                continue
            if current_tokens and current_tokens + sentence_tokens > max_tokens:
                parts.append(" ".join(current).strip())
                current = [sentence]
                current_tokens = sentence_tokens
                continue
            current.append(sentence)
            current_tokens += sentence_tokens
        if current:
            parts.append(" ".join(current).strip())
        if parts:
            return parts

    return _split_words_with_overlap(text, max_tokens=max_tokens, overlap_ratio=overlap_ratio)


def chunk_text(text: str, *, max_tokens: int = 500, overlap_ratio: float = 0.12) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    max_tokens = max(32, int(max_tokens or 500))
    if estimate_tokens(raw) <= max_tokens:
        return [raw]

    units: list[str] = []
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(raw) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [raw]
    for paragraph in paragraphs:
        units.extend(_split_oversized_unit(paragraph, max_tokens=max_tokens, overlap_ratio=overlap_ratio))

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        unit_tokens = estimate_tokens(unit)
        if unit_tokens > max_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = []
                current_tokens = 0
            chunks.extend(_split_words_with_overlap(unit, max_tokens=max_tokens, overlap_ratio=overlap_ratio))
            continue
        if current_tokens and current_tokens + unit_tokens > max_tokens:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = [unit]
            current_tokens = unit_tokens
            continue
        current_parts.append(unit)
        current_tokens += unit_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts).strip())

    deduped: list[str] = []
    for chunk in chunks:
        if chunk and chunk not in deduped:
            deduped.append(chunk)
    return deduped


def _planned_source_chunks(sources: list[tuple[str, str]], *, max_tokens: int = 500, overlap_ratio: float = 0.12) -> list[tuple[str, int, str]]:
    planned: list[tuple[str, int, str]] = []
    for source_type, source_text in sources:
        chunk_index = 0
        for chunk in chunk_text(source_text, max_tokens=max_tokens, overlap_ratio=overlap_ratio):
            planned.append((source_type, chunk_index, chunk))
            chunk_index += 1
    return planned


def _entity_chunks_match_existing(
    db: Session,
    *,
    project_id: str,
    entity_type: str,
    entity_id: str,
    model: str,
    planned_chunks: list[tuple[str, int, str]],
) -> bool:
    from .models import VectorChunk

    existing_rows = db.execute(
        select(VectorChunk).where(
            VectorChunk.project_id == project_id,
            VectorChunk.entity_type == entity_type,
            VectorChunk.entity_id == entity_id,
            VectorChunk.is_deleted == False,
        )
    ).scalars().all()
    if len(existing_rows) != len(planned_chunks):
        return False
    existing_rows.sort(key=lambda row: (str(row.source_type or ""), int(row.chunk_index or 0), int(row.id or 0)))
    normalized_planned_chunks = sorted(
        planned_chunks,
        key=lambda item: (str(item[0] or ""), int(item[1] or 0), str(item[2] or "")),
    )
    for row, (source_type, chunk_index, chunk_text_value) in zip(existing_rows, normalized_planned_chunks):
        if normalize_embedding_model(row.embedding_model) != model:
            return False
        if str(row.source_type or "") != source_type:
            return False
        if int(row.chunk_index or 0) != chunk_index:
            return False
        if str(row.text_chunk or "") != chunk_text_value:
            return False
    return True


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


def _embedding_to_vector_literal(embedding: list[float]) -> str:
    values = [format(float(value), ".12g") for value in embedding]
    return "[" + ",".join(values) + "]"


def _session_uses_postgresql(db: Session) -> bool:
    bind = db.bind
    if bind is None:
        return False
    return str(getattr(bind.dialect, "name", "")).strip().lower() == "postgresql"


def _sql_quote_literal(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _pgvector_index_name(model: str, dimension: int) -> str:
    digest = hashlib.sha1(f"{model}:{dimension}".encode("utf-8")).hexdigest()[:12]
    return f"ix_vector_chunks_hnsw_{digest}"


def _ensure_pgvector_model_index(db: Session, *, model: str, dimension: int) -> None:
    normalized_model = str(model or "").strip()
    normalized_dimension = max(1, int(dimension or 0))
    cache_key = (normalized_model, normalized_dimension)
    if cache_key in _PGVECTOR_INDEXES_READY:
        return
    if not _session_uses_postgresql(db):
        return
    with _PGVECTOR_INDEX_LOCK:
        if cache_key in _PGVECTOR_INDEXES_READY:
            return
        index_name = _pgvector_index_name(normalized_model, normalized_dimension)
        db.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON vector_chunks USING hnsw ((embedding_vector::vector({normalized_dimension})) vector_cosine_ops) "
                f"WHERE embedding_model = {_sql_quote_literal(normalized_model)} "
                f"AND is_deleted = FALSE "
                f"AND vector_dims(embedding_vector) = {normalized_dimension}"
            )
        )
        db.flush()
        _PGVECTOR_INDEXES_READY.add(cache_key)


def _insert_vector_chunk(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    entity_type: str,
    entity_id: str,
    source_type: str,
    chunk_index: int,
    text_chunk: str,
    token_count: int,
    embedding: list[float],
    embedding_model: str,
    content_hash: str,
    source_updated_at: datetime | None,
) -> None:
    from .models import VectorChunk

    embedding_json = _embedding_to_json(embedding)
    if not _session_uses_postgresql(db):
        db.add(
            VectorChunk(
                workspace_id=workspace_id,
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                source_type=source_type,
                chunk_index=chunk_index,
                text_chunk=text_chunk,
                token_count=token_count,
                embedding_json=embedding_json,
                embedding_model=embedding_model,
                content_hash=content_hash,
                source_updated_at=source_updated_at,
                is_deleted=False,
            )
        )
        return

    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "INSERT INTO vector_chunks ("
            "workspace_id, project_id, entity_type, entity_id, source_type, chunk_index, "
            "text_chunk, token_count, embedding_json, embedding_model, content_hash, "
            "source_updated_at, is_deleted, created_at, updated_at, embedding_vector"
            ") VALUES ("
            ":workspace_id, :project_id, :entity_type, :entity_id, :source_type, :chunk_index, "
            ":text_chunk, :token_count, :embedding_json, :embedding_model, :content_hash, "
            ":source_updated_at, FALSE, :created_at, :updated_at, CAST(:embedding_vector AS vector)"
            ")"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source_type": source_type,
            "chunk_index": chunk_index,
            "text_chunk": text_chunk,
            "token_count": token_count,
            "embedding_json": embedding_json,
            "embedding_model": embedding_model,
            "content_hash": content_hash,
            "source_updated_at": source_updated_at,
            "created_at": now,
            "updated_at": now,
            "embedding_vector": _embedding_to_vector_literal(embedding),
        },
    )


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
            }:
                sources.append(("chat_attachment.metadata", "\n".join(metadata_parts)))

        extracted_text = str(state.get("extracted_text") or "").strip()
        if extracted_text and ingestion_mode in {
            CHAT_ATTACHMENT_INGESTION_FULL_TEXT,
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


def _retention_mode_purges(retention_mode: str | None) -> bool:
    normalized = str(retention_mode or "purge").strip().lower()
    return normalized != "keep"


def purge_project_chat_chunks(db: Session, *, project_id: str) -> int:
    from .models import VectorChunk

    result = db.execute(
        delete(VectorChunk).where(
            VectorChunk.project_id == project_id,
            VectorChunk.entity_type.in_(("ChatMessage", "ChatAttachment")),
        )
    )
    return int(result.rowcount or 0)


def sync_project_chat_vector_chunks(
    db: Session,
    *,
    project_id: str,
    retention_mode: str | None = None,
    runtime_override: ProjectEmbeddingRuntime | None = None,
    policy_override: Any | None = None,
) -> tuple[int, int]:
    from .models import ChatAttachment, ChatMessage, Project

    project = db.get(Project, project_id)
    if project is None or bool(project.is_deleted):
        return 0, purge_project_chat_chunks(db, project_id=project_id)

    policy = policy_override or project_chat_indexing_policy(
        chat_index_mode=getattr(project, "chat_index_mode", None),
        chat_attachment_ingestion_mode=getattr(project, "chat_attachment_ingestion_mode", None),
    )
    runtime = runtime_override or resolve_project_embedding_runtime(db, project_id)
    should_purge = _retention_mode_purges(retention_mode if retention_mode is not None else CHAT_VECTOR_RETENTION_MODE)

    if not should_purge and (not runtime.enabled or not policy.vector_enabled):
        return 0, 0

    purged = purge_project_chat_chunks(db, project_id=project_id)
    if not runtime.enabled or not policy.vector_enabled:
        return 0, purged

    indexed = 0
    messages = db.execute(
        select(ChatMessage).where(
            ChatMessage.project_id == project_id,
            ChatMessage.is_deleted == False,
        )
    ).scalars().all()
    for message in messages:
        indexed += index_entity_state(
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

    if policy.attachment_ingestion_mode == CHAT_ATTACHMENT_INGESTION_OFF:
        return indexed, purged

    attachments = db.execute(
        select(ChatAttachment).where(
            ChatAttachment.project_id == project_id,
            ChatAttachment.is_deleted == False,
        )
    ).scalars().all()
    for attachment in attachments:
        indexed += index_entity_state(
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
                "chat_attachment_ingestion_mode": policy.attachment_ingestion_mode,
                "is_deleted": bool(attachment.is_deleted),
                "updated_at": attachment.updated_at,
            },
            force_reindex=True,
            runtime_override=runtime,
        )
    return indexed, purged


def index_entity_state(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    state: dict[str, Any],
    force_reindex: bool = False,
    runtime_override: ProjectEmbeddingRuntime | None = None,
) -> int:
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
    distilled_sources = _distill_index_sources(
        enabled=bool(runtime.distill_enabled),
        workspace_id=workspace_id,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        sources=sources,
    )
    if distilled_sources:
        sources = [*sources, *distilled_sources]
    planned_chunks = _planned_source_chunks(sources, max_tokens=500, overlap_ratio=0.12)
    if planned_chunks and _entity_chunks_match_existing(
        db,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        model=runtime.model,
        planned_chunks=planned_chunks,
    ):
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
    ensured_dimensions: set[int] = set()
    for source_type, source_text in sources:
        chunk_items = chunk_text(source_text, max_tokens=500, overlap_ratio=0.12)
        chunk_index = 0
        for chunk in chunk_items:
            for effective_chunk, embedding in _embed_text_with_split_retry(chunk, runtime.model):
                embedding_dimension = len(embedding)
                if _session_uses_postgresql(db) and embedding_dimension not in ensured_dimensions:
                    _ensure_pgvector_model_index(db, model=runtime.model, dimension=embedding_dimension)
                    ensured_dimensions.add(embedding_dimension)
                token_count = estimate_tokens(effective_chunk)
                content_hash = hashlib.sha256(
                    f"{entity_type}:{entity_id}:{source_type}:{effective_chunk}".encode("utf-8")
                ).hexdigest()
                _insert_vector_chunk(
                    db,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source_type=source_type,
                    chunk_index=chunk_index,
                    text_chunk=effective_chunk,
                    token_count=token_count,
                    embedding=embedding,
                    embedding_model=runtime.model,
                    content_hash=content_hash,
                    source_updated_at=source_updated_at,
                )
                chunk_index += 1
                indexed += 1

    if indexed:
        incr("vector_indexed_chunks", indexed)
    return indexed


def reindex_project(db: Session, *, project_id: str) -> int:
    runtime = resolve_project_embedding_runtime(db, project_id)
    return reindex_project_with_runtime(db, project_id=project_id, runtime=runtime)


def search_project_chunks(
    db: Session,
    *,
    project_id: str,
    query: str,
    limit: int,
    entity_filters: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    runtime = resolve_project_embedding_runtime(db, project_id)
    if not runtime.enabled:
        return []
    text_query = str(query or "").strip()
    if not text_query:
        return []
    if not _session_uses_postgresql(db):
        raise EmbeddingRuntimeError("pgvector retrieval requires PostgreSQL")

    started_at = time.perf_counter()
    query_embedding = _ollama_embed_text(text_query, runtime.model)
    embedding_dimension = len(query_embedding)
    if embedding_dimension <= 0:
        return []
    _ensure_pgvector_model_index(db, model=runtime.model, dimension=embedding_dimension)

    where_clauses = [
        "project_id = :project_id",
        "is_deleted = FALSE",
        "embedding_model = :embedding_model",
        "embedding_vector IS NOT NULL",
        "vector_dims(embedding_vector) = :embedding_dimension",
    ]
    params: dict[str, Any] = {
        "project_id": project_id,
        "embedding_model": runtime.model,
        "embedding_dimension": embedding_dimension,
        "query_vector": _embedding_to_vector_literal(query_embedding),
        "limit": max(1, int(limit or 10)),
    }
    filters = entity_filters or set()
    if filters:
        filter_fragments: list[str] = []
        for idx, (entity_type, entity_id) in enumerate(sorted(filters)):
            entity_type_key = f"entity_type_{idx}"
            entity_id_key = f"entity_id_{idx}"
            params[entity_type_key] = entity_type
            params[entity_id_key] = entity_id
            filter_fragments.append(f"(entity_type = :{entity_type_key} AND entity_id = :{entity_id_key})")
        where_clauses.append("(" + " OR ".join(filter_fragments) + ")")

    distance_expr = (
        f"(embedding_vector::vector({embedding_dimension}) <=> CAST(:query_vector AS vector({embedding_dimension})))"
    )
    rows = db.execute(
        text(
            "SELECT entity_type, entity_id, source_type, chunk_index, text_chunk, source_updated_at, "
            f"(1 - {distance_expr}) AS vector_similarity "
            "FROM vector_chunks "
            f"WHERE {' AND '.join(where_clauses)} "
            f"ORDER BY {distance_expr} ASC, source_type ASC, entity_id ASC, chunk_index ASC "
            "LIMIT :limit"
        ),
        params,
    ).mappings().all()
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    observe("vector_retrieval_latency_ms", latency_ms)
    return [
        {
            "entity_type": str(row.get("entity_type") or ""),
            "entity_id": str(row.get("entity_id") or ""),
            "source_type": str(row.get("source_type") or ""),
            "chunk_index": int(row.get("chunk_index") or 0),
            "snippet": str(row.get("text_chunk") or ""),
            "vector_similarity": max(0.0, min(1.0, float(row.get("vector_similarity") or 0.0))),
            "source_updated_at": row.get("source_updated_at"),
        }
        for row in rows
    ]


def maybe_reindex_project(
    db: Session,
    *,
    project_id: str,
    embedding_enabled: bool | None = None,
    embedding_model: str | None = None,
    vector_index_distill_enabled: bool | None = None,
    chat_index_mode: str | None = None,
    chat_attachment_ingestion_mode: str | None = None,
) -> int:
    from .models import Project

    runtime_override: ProjectEmbeddingRuntime | None = None
    if embedding_enabled is not None or embedding_model is not None or vector_index_distill_enabled is not None:
        project = db.get(Project, project_id)
        resolved_enabled = bool(embedding_enabled if embedding_enabled is not None else (project.embedding_enabled if project else False))
        resolved_model = normalize_embedding_model(embedding_model if embedding_model is not None else (project.embedding_model if project else None))
        runtime_override = ProjectEmbeddingRuntime(
            project_id=project_id,
            enabled=bool(vector_store_enabled() and resolved_enabled),
            model=resolved_model,
            distill_enabled=bool(
                vector_index_distill_enabled
                if vector_index_distill_enabled is not None
                else (
                    getattr(project, "vector_index_distill_enabled", VECTOR_INDEX_DISTILL_ENABLED)
                    if project is not None
                    else VECTOR_INDEX_DISTILL_ENABLED
                )
            ),
        )
    try:
        if runtime_override is None:
            return reindex_project(db, project_id=project_id)
        return reindex_project_with_runtime(
            db,
            project_id=project_id,
            runtime=runtime_override,
            chat_index_mode=chat_index_mode,
            chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
        )
    except Exception as exc:
        logger.warning("Vector project reindex failed project_id=%s err=%s", project_id, exc)
        return 0


def reindex_project_with_runtime(
    db: Session,
    *,
    project_id: str,
    runtime: ProjectEmbeddingRuntime,
    chat_index_mode: str | None = None,
    chat_attachment_ingestion_mode: str | None = None,
) -> int:
    from .models import Note, Project, ProjectRule, Specification, Task

    project = db.get(Project, project_id)
    if project is None or project.is_deleted:
        purge_project_chunks(db, project_id=project_id)
        return 0
    if not runtime.enabled:
        purge_project_chunks(db, project_id=project_id)
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

    policy = project_chat_indexing_policy(
        chat_index_mode=(getattr(project, "chat_index_mode", None) if chat_index_mode is None else chat_index_mode),
        chat_attachment_ingestion_mode=(
            getattr(project, "chat_attachment_ingestion_mode", None)
            if chat_attachment_ingestion_mode is None
            else chat_attachment_ingestion_mode
        ),
    )
    if policy.index_mode in {CHAT_INDEX_MODE_VECTOR_ONLY, CHAT_INDEX_MODE_KG_AND_VECTOR}:
        chat_indexed, _ = sync_project_chat_vector_chunks(
            db,
            project_id=project_id,
            retention_mode="purge",
            runtime_override=runtime,
            policy_override=policy,
        )
        total += chat_indexed

    return total


def project_embedding_index_status(
    db: Session,
    *,
    project_id: str,
    embedding_enabled: bool | None = None,
    embedding_model: str | None = None,
) -> str:
    snapshot = project_embedding_index_snapshot(
        db,
        project_id=project_id,
        embedding_enabled=embedding_enabled,
        embedding_model=embedding_model,
    )
    return str(snapshot.get("status") or "not_indexed")


def _non_empty_text_column(column) -> Any:
    return func.length(func.trim(func.coalesce(column, ""))) > 0


def _project_indexable_entity_count(
    db: Session,
    *,
    project_id: str,
    policy,
) -> int:
    from .models import ChatAttachment, ChatMessage, Note, ProjectRule, Specification, Task

    total = 0

    task_count = db.execute(
        select(func.count(Task.id)).where(
            Task.project_id == project_id,
            Task.is_deleted == False,
            Task.archived == False,
            or_(_non_empty_text_column(Task.title), _non_empty_text_column(Task.description)),
        )
    ).scalar_one()
    total += int(task_count or 0)

    note_count = db.execute(
        select(func.count(Note.id)).where(
            Note.project_id == project_id,
            Note.is_deleted == False,
            Note.archived == False,
            or_(_non_empty_text_column(Note.title), _non_empty_text_column(Note.body)),
        )
    ).scalar_one()
    total += int(note_count or 0)

    specification_count = db.execute(
        select(func.count(Specification.id)).where(
            Specification.project_id == project_id,
            Specification.is_deleted == False,
            Specification.archived == False,
            or_(_non_empty_text_column(Specification.title), _non_empty_text_column(Specification.body)),
        )
    ).scalar_one()
    total += int(specification_count or 0)

    rule_count = db.execute(
        select(func.count(ProjectRule.id)).where(
            ProjectRule.project_id == project_id,
            ProjectRule.is_deleted == False,
            or_(_non_empty_text_column(ProjectRule.title), _non_empty_text_column(ProjectRule.body)),
        )
    ).scalar_one()
    total += int(rule_count or 0)

    if not bool(getattr(policy, "vector_enabled", False)):
        return total

    message_count = db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.project_id == project_id,
            ChatMessage.is_deleted == False,
            _non_empty_text_column(ChatMessage.content),
        )
    ).scalar_one()
    total += int(message_count or 0)

    attachment_mode = str(getattr(policy, "attachment_ingestion_mode", "") or "").strip().upper()
    if attachment_mode == CHAT_ATTACHMENT_INGESTION_OFF:
        return total

    attachment_metadata_present = or_(
        _non_empty_text_column(ChatAttachment.path),
        _non_empty_text_column(ChatAttachment.name),
        _non_empty_text_column(ChatAttachment.mime_type),
        ChatAttachment.size_bytes.is_not(None),
    )
    attachment_indexable = attachment_metadata_present
    if attachment_mode == CHAT_ATTACHMENT_INGESTION_FULL_TEXT:
        attachment_indexable = or_(attachment_metadata_present, _non_empty_text_column(ChatAttachment.extracted_text))

    attachment_count = db.execute(
        select(func.count(ChatAttachment.id)).where(
            ChatAttachment.project_id == project_id,
            ChatAttachment.is_deleted == False,
            attachment_indexable,
        )
    ).scalar_one()
    total += int(attachment_count or 0)
    return total


def project_embedding_index_snapshot(
    db: Session,
    *,
    project_id: str,
    embedding_enabled: bool | None = None,
    embedding_model: str | None = None,
    chat_index_mode: str | None = None,
    chat_attachment_ingestion_mode: str | None = None,
) -> dict[str, Any]:
    from .models import Project, VectorChunk

    enabled = embedding_enabled
    model = embedding_model
    chat_mode = chat_index_mode
    attachment_mode = chat_attachment_ingestion_mode
    if enabled is None or model is None or chat_mode is None or attachment_mode is None:
        project = db.get(Project, project_id)
        if project is None or project.is_deleted:
            return {
                "status": "not_indexed",
                "progress_pct": None,
                "indexed_entities": 0,
                "expected_entities": 0,
                "indexed_chunks": 0,
            }
        if enabled is None:
            enabled = bool(project.embedding_enabled)
        if model is None:
            model = project.embedding_model
        if chat_mode is None:
            chat_mode = getattr(project, "chat_index_mode", None)
        if attachment_mode is None:
            attachment_mode = getattr(project, "chat_attachment_ingestion_mode", None)

    if not bool(enabled):
        return {
            "status": "not_indexed",
            "progress_pct": None,
            "indexed_entities": 0,
            "expected_entities": 0,
            "indexed_chunks": 0,
        }
    if not vector_store_enabled():
        return {
            "status": "not_indexed",
            "progress_pct": None,
            "indexed_entities": 0,
            "expected_entities": 0,
            "indexed_chunks": 0,
        }

    expected_model = normalize_embedding_model(model)
    policy = project_chat_indexing_policy(
        chat_index_mode=chat_mode,
        chat_attachment_ingestion_mode=attachment_mode,
    )
    expected_entities = _project_indexable_entity_count(db, project_id=project_id, policy=policy)
    indexed_entities = int(
        db.execute(
            select(func.count()).select_from(
                select(VectorChunk.entity_type, VectorChunk.entity_id)
                .where(
                    VectorChunk.project_id == project_id,
                    VectorChunk.is_deleted == False,
                )
                .distinct()
                .subquery()
            )
        ).scalar_one()
        or 0
    )
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
        stats = {}
    chunk_count = int(stats.get("chunk_count") or 0)

    model_count = int(stats.get("model_count") or 0)
    max_model = str(stats.get("max_model") or "").strip()
    min_model = str(stats.get("min_model") or "").strip()
    status = "ready"
    if model_count > 1:
        status = "stale"
    elif max_model and min_model and max_model != min_model:
        status = "stale"
    elif expected_model and max_model and normalize_embedding_model(max_model) != expected_model:
        status = "stale"
    elif expected_entities <= 0:
        status = "ready"
    elif chunk_count <= 0 or indexed_entities < expected_entities:
        status = "indexing"

    progress_pct: int | None = None
    if expected_entities <= 0:
        progress_pct = 100
    else:
        ratio = min(1.0, max(0.0, float(indexed_entities) / float(expected_entities)))
        progress_pct = int(round(ratio * 100))

    return {
        "status": status,
        "progress_pct": progress_pct,
        "indexed_entities": indexed_entities,
        "expected_entities": expected_entities,
        "indexed_chunks": chunk_count,
    }
