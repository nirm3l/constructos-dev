from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import queue
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import AgentChatRun, User, ensure_project_access, ensure_role, get_command_id, get_current_user, get_db
from shared.models import ActivityLog, ChatMessage, ChatSession
from shared.settings import (
    ATTACHMENTS_DIR,
    AGENT_CHAT_HISTORY_COMPACT_THRESHOLD,
    AGENT_CHAT_HISTORY_RECENT_TAIL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)

from .executor import AutomationOutcome, execute_task_automation, execute_task_automation_stream
from .mcp_registry import normalize_chat_mcp_servers as normalize_chat_mcp_servers_registry
from features.chat.application import ChatApplicationService
from features.chat.command_handlers import (
    AppendAssistantMessagePayload,
    AppendUserMessagePayload,
    LinkMessageResourcePayload,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/x-yaml",
    "application/yaml",
    "application/toml",
    "application/x-toml",
    "application/javascript",
}
_PDF_MIME_TYPES = {"application/pdf"}
_DOCX_MIME_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".html",
    ".sql",
    ".sh",
    ".env",
}
_MAX_CHAT_ATTACHMENT_FILES = 6
_MAX_CHAT_ATTACHMENT_CHARS_PER_FILE = 12_000
_MAX_CHAT_ATTACHMENT_CHARS_TOTAL = 36_000
_CREATED_RESOURCE_ACTIONS: dict[str, str] = {
    "TaskCreated": "task",
    "NoteCreated": "note",
    "SpecificationCreated": "specification",
    "ProjectRuleCreated": "project_rule",
}


def _normalize_chat_mcp_servers(raw_servers: list[str] | None) -> list[str]:
    try:
        return normalize_chat_mcp_servers_registry(raw_servers, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _upload_root() -> Path:
    raw = os.getenv("ATTACHMENTS_DIR", ATTACHMENTS_DIR).strip() or ATTACHMENTS_DIR
    return Path(raw).expanduser().resolve()


def _project_id_from_path(path: str) -> str | None:
    parts = [part for part in Path(path).as_posix().split("/") if part]
    if len(parts) >= 4 and parts[0] == "workspace" and parts[2] == "project":
        project_id = parts[3]
        if project_id and project_id != "_none":
            return project_id
    return None


def _resolve_attachment_candidate(workspace_id: str, path: str) -> Path:
    upload_root = _upload_root()
    rel = Path(path)
    if rel.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid attachment path")
    candidate = (upload_root / rel).resolve()
    if not str(candidate).startswith(str(upload_root)):
        raise HTTPException(status_code=400, detail="Invalid attachment path")
    expected_prefix = f"workspace/{workspace_id}/"
    if not str(path).startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Attachment does not belong to workspace")
    return candidate


def _is_text_attachment(*, file_name: str, mime_type: str | None) -> bool:
    lower_mime = str(mime_type or "").strip().lower()
    if lower_mime and lower_mime.startswith(_TEXT_MIME_PREFIXES):
        return True
    if lower_mime in _TEXT_MIME_TYPES:
        return True
    suffix = Path(file_name or "").suffix.lower()
    return suffix in _TEXT_EXTENSIONS


def _is_pdf_attachment(*, file_name: str, mime_type: str | None) -> bool:
    lower_mime = str(mime_type or "").strip().lower()
    if lower_mime in _PDF_MIME_TYPES:
        return True
    return Path(file_name or "").suffix.lower() == ".pdf"


def _is_docx_attachment(*, file_name: str, mime_type: str | None) -> bool:
    lower_mime = str(mime_type or "").strip().lower()
    if lower_mime in _DOCX_MIME_TYPES:
        return True
    return Path(file_name or "").suffix.lower() == ".docx"


def _read_attachment_snippet(path: Path, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return "", False
    # Use a byte budget that comfortably exceeds max_chars for UTF-8 text.
    byte_budget = max(1, max_chars * 4)
    with path.open("rb") as f:
        raw = f.read(byte_budget + 1)
    had_byte_truncation = len(raw) > byte_budget
    clipped = raw[:byte_budget]
    text = clipped.decode("utf-8", errors="replace")
    had_char_truncation = len(text) > max_chars
    snippet = text[:max_chars]
    return snippet, (had_byte_truncation or had_char_truncation)


def _extract_docx_text(path: Path, *, max_chars: int) -> tuple[str, bool, str | None]:
    if max_chars <= 0:
        return "", False, "Content: omitted (chat attachment context limit reached)."
    try:
        with zipfile.ZipFile(path, "r") as archive:
            raw_xml = archive.read("word/document.xml")
    except KeyError:
        return "", False, "Content: omitted (DOCX has no word/document.xml)."
    except zipfile.BadZipFile:
        return "", False, "Content: omitted (invalid DOCX format)."
    except Exception as exc:
        logger.warning("Failed reading DOCX attachment %s: %s", path, exc)
        return "", False, "Content: omitted (failed to read DOCX)."

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return "", False, "Content: omitted (invalid DOCX XML)."

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        pieces: list[str] = []
        for run_text in paragraph.findall(".//w:t", ns):
            text_value = str(run_text.text or "")
            if text_value:
                pieces.append(text_value)
        line = "".join(pieces).strip()
        if line:
            paragraphs.append(line)

    full_text = "\n\n".join(paragraphs).strip()
    if not full_text:
        return "", False, "Content: omitted (no extractable text found in DOCX)."

    truncated = len(full_text) > max_chars
    snippet = full_text[:max_chars]
    return snippet, truncated, None


def _extract_pdf_text(path: Path, *, max_chars: int) -> tuple[str, bool, str | None]:
    if max_chars <= 0:
        return "", False, "Content: omitted (chat attachment context limit reached)."
    try:
        from pypdf import PdfReader
    except Exception:
        return "", False, "Content: omitted (PDF parser unavailable; install pypdf)."

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        logger.warning("Failed opening PDF attachment %s: %s", path, exc)
        return "", False, "Content: omitted (failed to open PDF)."

    chunks: list[str] = []
    used_chars = 0
    truncated = False
    for page in reader.pages:
        try:
            page_text = str(page.extract_text() or "")
        except Exception:
            page_text = ""
        if not page_text:
            continue
        remaining = max_chars - used_chars
        if remaining <= 0:
            truncated = True
            break
        if len(page_text) > remaining:
            chunks.append(page_text[:remaining])
            used_chars += remaining
            truncated = True
            break
        chunks.append(page_text)
        used_chars += len(page_text)

    full_text = "\n\n".join(part.strip() for part in chunks if part.strip()).strip()
    if not full_text:
        return "", False, "Content: omitted (no extractable text found in PDF)."
    return full_text, truncated, None


def _build_attachment_context(
    *,
    payload: AgentChatRun,
    db: Session,
    user: User,
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    def _ref_value(ref: object, field: str) -> object:
        if isinstance(ref, dict):
            return ref.get(field)
        return getattr(ref, field, None)

    message_refs = list(payload.attachment_refs or [])
    session_refs = list(payload.session_attachment_refs or [])
    if not message_refs and not session_refs:
        return "", [], []

    refs: list = []
    seen_paths: set[str] = set()
    for ref in [*message_refs, *session_refs]:
        path = str(_ref_value(ref, "path") or "").strip()
        if not path:
            continue
        dedupe_key = path.lower()
        if dedupe_key in seen_paths:
            continue
        seen_paths.add(dedupe_key)
        refs.append(ref)
    if not refs:
        return "", [], []

    message_ref_paths = {
        str(_ref_value(ref, "path") or "").strip().lower()
        for ref in message_refs
        if str(_ref_value(ref, "path") or "").strip()
    }
    session_ref_paths = {
        str(_ref_value(ref, "path") or "").strip().lower()
        for ref in session_refs
        if str(_ref_value(ref, "path") or "").strip()
    }

    lines: list[str] = []
    processed_message_refs: list[dict[str, object]] = []
    processed_session_refs: list[dict[str, object]] = []
    total_chars = 0
    for index, ref in enumerate(refs[:_MAX_CHAT_ATTACHMENT_FILES], start=1):
        path = str(_ref_value(ref, "path") or "").strip()
        if not path:
            continue
        path_key = path.lower()
        candidate = _resolve_attachment_candidate(payload.workspace_id, path)
        project_id = _project_id_from_path(path)
        if project_id:
            ensure_project_access(db, payload.workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        if payload.project_id and project_id and project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="Attachment project mismatch with selected chat project")
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Attachment not found: {path}")

        display_name = str(_ref_value(ref, "name") or Path(path).name or f"attachment-{index}").strip()
        mime_type = str(_ref_value(ref, "mime_type") or "").strip() or mimetypes.guess_type(display_name)[0] or ""
        normalized_ref: dict[str, object] = {
            "path": path,
            "name": display_name,
            "mime_type": mime_type or None,
            "size_bytes": int(candidate.stat().st_size),
            "extraction_status": "pending",
        }

        lines.append(f"Attachment {index}: {display_name}")
        lines.append(f"Path: {path}")
        lines.append(f"MIME type: {mime_type or 'unknown'}")

        remaining_chars = _MAX_CHAT_ATTACHMENT_CHARS_TOTAL - total_chars
        if remaining_chars <= 0:
            lines.append("Content: omitted (chat attachment context limit reached).")
            normalized_ref["extraction_status"] = "skipped_limit"
            if path_key in message_ref_paths:
                processed_message_refs.append(normalized_ref)
            if path_key in session_ref_paths:
                processed_session_refs.append(normalized_ref)
            lines.append("")
            break

        max_chars_for_file = min(_MAX_CHAT_ATTACHMENT_CHARS_PER_FILE, remaining_chars)
        status_message: str | None = None
        if _is_text_attachment(file_name=display_name, mime_type=mime_type):
            snippet, truncated = _read_attachment_snippet(candidate, max_chars=max_chars_for_file)
        elif _is_docx_attachment(file_name=display_name, mime_type=mime_type):
            snippet, truncated, status_message = _extract_docx_text(candidate, max_chars=max_chars_for_file)
        elif _is_pdf_attachment(file_name=display_name, mime_type=mime_type):
            snippet, truncated, status_message = _extract_pdf_text(candidate, max_chars=max_chars_for_file)
        else:
            snippet, truncated = "", False
            status_message = "Content: omitted (unsupported binary file type)."

        if snippet:
            normalized_ref["extraction_status"] = "extracted" if not truncated else "truncated"
            normalized_ref["extracted_text"] = snippet
            lines.append("Content:")
            lines.append(snippet)
            if truncated:
                lines.append("[truncated]")
            total_chars += len(snippet)
        else:
            normalized_ref["extraction_status"] = "skipped"
            lines.append(status_message or "Content: omitted (empty or unreadable file).")
        if path_key in message_ref_paths:
            processed_message_refs.append(normalized_ref)
        if path_key in session_ref_paths:
            processed_session_refs.append(normalized_ref)
        lines.append("")

    for ref in refs[_MAX_CHAT_ATTACHMENT_FILES:]:
        path = str(_ref_value(ref, "path") or "").strip()
        if not path:
            continue
        path_key = path.lower()
        candidate = _resolve_attachment_candidate(payload.workspace_id, path)
        project_id = _project_id_from_path(path)
        if project_id:
            ensure_project_access(db, payload.workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        if payload.project_id and project_id and project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="Attachment project mismatch with selected chat project")
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Attachment not found: {path}")
        display_name = str(_ref_value(ref, "name") or Path(path).name or "attachment").strip()
        mime_type = str(_ref_value(ref, "mime_type") or "").strip() or mimetypes.guess_type(display_name)[0] or ""
        normalized_ref = {
            "path": path,
            "name": display_name,
            "mime_type": mime_type or None,
            "size_bytes": int(_ref_value(ref, "size_bytes") or 0)
            if isinstance(_ref_value(ref, "size_bytes"), int) and int(_ref_value(ref, "size_bytes")) >= 0
            else None,
            "extraction_status": "skipped_file_limit",
        }
        if path_key in message_ref_paths:
            processed_message_refs.append(normalized_ref)
        if path_key in session_ref_paths:
            processed_session_refs.append(normalized_ref)

    if not lines:
        return "", processed_message_refs, processed_session_refs
    return "Attached file context:\n" + "\n".join(lines).rstrip(), processed_message_refs, processed_session_refs


def _compose_chat_instruction(current_instruction: str, history: list[dict[str, str]]) -> str:
    normalized: list[str] = []
    for item in history[-12:]:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append(f"{role.upper()}: {content}")
    if not normalized:
        return current_instruction
    return (
        "Conversation history:\n"
        + "\n".join(normalized)
        + "\n\nLatest user instruction:\n"
        + current_instruction
    )


def _normalize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _resolve_chat_session_id(raw: str | None) -> str:
    session_id = str(raw or "").strip()
    if not session_id:
        return str(uuid.uuid4())
    if len(session_id) > 128:
        return session_id[:128]
    return session_id


def _command_id_with_suffix(command_id: str | None, suffix: str) -> str | None:
    normalized = str(command_id or "").strip()
    if not normalized:
        return None
    full = f"{normalized}:{suffix}"
    return full[:64]


def _assistant_text(summary: str | None, comment: str | None) -> str:
    return "\n\n".join(part for part in [str(summary or "").strip(), str(comment or "").strip()] if part).strip()


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 0:
            return False
        if value == 1:
            return True
        return None
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def _build_usage_with_resume_metadata(outcome: AutomationOutcome) -> dict[str, object]:
    usage_payload: dict[str, object] = dict(outcome.usage or {})
    usage_payload["codex_resume_attempted"] = bool(outcome.resume_attempted)
    usage_payload["codex_resume_succeeded"] = bool(outcome.resume_succeeded)
    usage_payload["codex_resume_fallback_used"] = bool(outcome.resume_fallback_used)
    return usage_payload


def _parse_event_key_aggregate_id(event_key: str | None) -> str | None:
    text = str(event_key or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    aggregate_id = str(parts[1] or "").strip()
    return aggregate_id or None


def _collect_created_resources(
    *,
    db: Session,
    workspace_id: str,
    project_id: str | None,
    actor_id: str,
    started_at: datetime,
    ended_at: datetime,
) -> list[dict[str, str]]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return []
    window_start = started_at - timedelta(seconds=2)
    window_end = ended_at + timedelta(seconds=2)
    query = (
        select(ActivityLog.action, ActivityLog.details)
        .where(
            ActivityLog.workspace_id == workspace_id,
            ActivityLog.project_id == normalized_project_id,
            ActivityLog.actor_id == actor_id,
            ActivityLog.action.in_(tuple(_CREATED_RESOURCE_ACTIONS.keys())),
            ActivityLog.created_at >= window_start,
            ActivityLog.created_at <= window_end,
        )
        .order_by(ActivityLog.created_at.asc(), ActivityLog.id.asc())
    )
    rows = db.execute(query).all()
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for action, details_raw in rows:
        resource_type = _CREATED_RESOURCE_ACTIONS.get(str(action or "").strip())
        if not resource_type:
            continue
        details: dict[str, object] = {}
        try:
            loaded = json.loads(str(details_raw or "{}"))
            if isinstance(loaded, dict):
                details = loaded
        except Exception:
            details = {}
        resource_id = _parse_event_key_aggregate_id(details.get("_event_key"))
        if not resource_id:
            continue
        key = (resource_type, resource_id)
        if key in seen:
            continue
        seen.add(key)
        out.append({"resource_type": resource_type, "resource_id": resource_id})
    return out


def _link_created_resources_to_chat_message(
    *,
    db: Session,
    user: User,
    command_id: str | None,
    workspace_id: str,
    project_id: str | None,
    session_id: str,
    message_id: str | None,
    resources: list[dict[str, str]],
) -> None:
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id or not resources:
        return
    for item in resources:
        resource_type = str(item.get("resource_type") or "").strip()
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_type or not resource_id:
            continue
        resource_key = hashlib.sha1(f"{resource_type}:{resource_id}".encode("utf-8")).hexdigest()[:10]
        try:
            ChatApplicationService(
                db,
                user,
                command_id=_command_id_with_suffix(command_id, f"chat-link-{resource_key}"),
            ).link_message_resource(
                LinkMessageResourcePayload(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    session_id=session_id,
                    message_id=normalized_message_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    relation="created",
                )
            )
        except Exception as exc:
            logger.warning(
                "Chat resource auto-link failed workspace_id=%s project_id=%s session_id=%s message_id=%s type=%s id=%s err=%s",
                workspace_id,
                project_id,
                session_id,
                normalized_message_id,
                resource_type,
                resource_id,
                exc,
            )


def _persist_assistant_message_with_links(
    *,
    db: Session,
    user: User,
    command_id: str | None,
    workspace_id: str,
    project_id: str | None,
    session_id: str,
    mcp_servers: list[str],
    content: str,
    usage: dict[str, object] | None,
    codex_session_id: str | None,
    run_started_at: datetime | None = None,
) -> str | None:
    assistant_content = str(content or "").strip()
    if not assistant_content:
        return None
    append_result = ChatApplicationService(
        db,
        user,
        command_id=_command_id_with_suffix(command_id, "chat-assistant"),
    ).append_assistant_message(
        AppendAssistantMessagePayload(
            workspace_id=workspace_id,
            project_id=project_id,
            session_id=session_id,
            message_id=None,
            content=assistant_content,
            usage=usage if isinstance(usage, dict) else {},
            codex_session_id=str(codex_session_id or "").strip() or None,
            mcp_servers=mcp_servers,
        )
    )
    message_id = str(append_result.get("message_id") or "").strip() or None
    if run_started_at and message_id:
        created_resources = _collect_created_resources(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_id=user.id,
            started_at=run_started_at,
            ended_at=datetime.now(timezone.utc),
        )
        _link_created_resources_to_chat_message(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=workspace_id,
            project_id=project_id,
            session_id=session_id,
            message_id=message_id,
            resources=created_resources,
        )
    return message_id


def _load_persisted_chat_history(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    session_id: str | None,
    max_turns: int = 120,
) -> list[dict[str, str]]:
    session_key = str(session_id or "").strip()
    if not session_key:
        return []
    session = db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.session_key == session_key,
            ChatSession.created_by == user.id,
        )
    ).scalar_one_or_none()
    if session is None:
        return []
    if session.project_id:
        ensure_project_access(db, workspace_id, session.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.is_deleted == False)
        .order_by(ChatMessage.order_index.desc(), ChatMessage.turn_created_at.desc(), ChatMessage.created_at.desc())
        .limit(max(1, int(max_turns)))
    ).scalars().all()
    out: list[dict[str, str]] = []
    for row in reversed(rows):
        role = "assistant" if str(row.role or "").strip().lower() == "assistant" else "user"
        content = str(row.content or "").strip()
        if not content:
            continue
        out.append({"role": role, "content": content})
    return out


def _load_chat_session_codex_state(
    *,
    db: Session,
    workspace_id: str,
    session_id: str | None,
) -> tuple[str | None, bool | None]:
    def _extract_resume_last_succeeded(usage_json_raw: str | None) -> bool | None:
        text_value = str(usage_json_raw or "").strip()
        if not text_value:
            return None
        try:
            usage_payload = json.loads(text_value)
        except Exception:
            return None
        if not isinstance(usage_payload, dict):
            return None
        resume_attempted = _coerce_bool(usage_payload.get("codex_resume_attempted"))
        resume_succeeded = _coerce_bool(usage_payload.get("codex_resume_succeeded"))
        if resume_attempted is True:
            return resume_succeeded
        return None

    session_key = str(session_id or "").strip()
    if not session_key:
        return None, None
    row = db.execute(
        select(ChatSession.id, ChatSession.codex_session_id, ChatSession.usage_json).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.session_key == session_key,
        )
    ).first()
    if row is None:
        return None, None
    session_db_id = str(row[0] or "").strip()
    codex_session_id = str(row[1] or "").strip() or None
    resume_last_succeeded = _extract_resume_last_succeeded(str(row[2] or ""))
    if resume_last_succeeded is not None:
        return codex_session_id, resume_last_succeeded
    if not session_db_id:
        return codex_session_id, None

    latest_assistant_usage_row = db.execute(
        select(ChatMessage.usage_json)
        .where(
            ChatMessage.session_id == session_db_id,
            ChatMessage.role == "assistant",
            ChatMessage.is_deleted == False,
        )
        .order_by(ChatMessage.order_index.desc(), ChatMessage.turn_created_at.desc(), ChatMessage.created_at.desc())
        .limit(1)
    ).first()
    if latest_assistant_usage_row is None:
        return codex_session_id, None
    return codex_session_id, _extract_resume_last_succeeded(str(latest_assistant_usage_row[0] or ""))


def _load_persisted_session_attachment_refs(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    session_id: str | None,
) -> list[dict[str, object]]:
    session_key = str(session_id or "").strip()
    if not session_key:
        return []
    session = db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.session_key == session_key,
            ChatSession.created_by == user.id,
        )
    ).scalar_one_or_none()
    if session is None:
        return []
    if session.project_id:
        ensure_project_access(db, workspace_id, session.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    try:
        raw = json.loads(session.session_attachment_refs or "[]")
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        dedupe_key = path.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized: dict[str, object] = {"path": path}
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
            normalized["checksum"] = checksum
        out.append(normalized)
    return out


def _parse_compact_command(instruction: str) -> tuple[bool, str]:
    raw = str(instruction or "").strip()
    if not raw:
        return False, ""
    marker = "/compact"
    if not raw.lower().startswith(marker):
        return False, raw
    remainder = raw[len(marker):].strip()
    return True, remainder


def _compact_history_with_codex(
    *,
    history: list[dict[str, str]],
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str | None,
) -> str | None:
    if not history:
        return None
    lines = [f"{item['role'].upper()}: {item['content']}" for item in history[-80:]]
    compact_instruction = (
        "Compact this conversation history for continuation in one concise summary.\n"
        "Include: current goals, decisions made, constraints, and open items.\n"
        "Do not call tools and do not mutate any data.\n"
        "Write plain text summary only."
        "\n\nConversation history:\n"
        + "\n".join(lines)
    )
    outcome = execute_task_automation(
        task_id="",
        title="General Codex Chat History Compaction",
        description=f"Compacting chat context. workspace_id={workspace_id}; project_id={project_id or ''}",
        status="To do",
        instruction=compact_instruction,
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        allow_mutations=False,
    )
    parts = [str(outcome.summary or "").strip(), str(outcome.comment or "").strip()]
    compacted = "\n\n".join(part for part in parts if part).strip()
    return compacted or None


def _maybe_compact_history(
    *,
    history: list[dict[str, str]],
    workspace_id: str,
    project_id: str | None,
    actor_user_id: str | None,
    force: bool = False,
) -> tuple[list[dict[str, str]], bool]:
    threshold = max(0, int(AGENT_CHAT_HISTORY_COMPACT_THRESHOLD))
    should_compact = force or (threshold > 0 and len(history) > threshold)
    if not should_compact:
        return history, False
    try:
        compacted = _compact_history_with_codex(
            history=history,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
        )
    except TimeoutError:
        logger.warning("Skipping chat history compaction due to timeout.")
        return history, False
    except Exception:
        logger.exception("Skipping chat history compaction due to failure.")
        return history, False
    if not compacted:
        return history, False
    recent_tail = max(0, int(AGENT_CHAT_HISTORY_RECENT_TAIL))
    tail = history[-recent_tail:] if recent_tail > 0 else []
    compact_turn = {
        "role": "assistant",
        "content": f"[Compacted conversation context]\n{compacted}",
    }
    return [compact_turn, *tail], True


def _prepare_chat_instruction(
    *,
    payload: AgentChatRun,
    db: Session,
    user: User,
    resume_codex_session_id: str | None = None,
    resume_last_succeeded: bool | None = None,
) -> tuple[str, list[dict[str, str]], bool, list[dict[str, object]], list[dict[str, object]]]:
    raw_instruction = (payload.instruction or "").strip()
    force_compact, instruction = _parse_compact_command(raw_instruction)
    if not raw_instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    history = _normalize_history(payload.history or [])
    if not history:
        history = _load_persisted_chat_history(
            db=db,
            user=user,
            workspace_id=payload.workspace_id,
            session_id=payload.session_id,
        )
    # Frontend includes the current user turn in `history`; when using /compact, avoid
    # compacting the command text itself.
    if force_compact and history and history[-1]["role"] == "user" and history[-1]["content"] == raw_instruction:
        history = history[:-1]
    persisted_session_attachment_refs: list[dict[str, object]] = []
    if not payload.session_attachment_refs:
        persisted_session_attachment_refs = _load_persisted_session_attachment_refs(
            db=db,
            user=user,
            workspace_id=payload.workspace_id,
            session_id=payload.session_id,
        )
    payload_for_attachments = payload
    if persisted_session_attachment_refs:
        payload_for_attachments = payload.model_copy(
            update={"session_attachment_refs": persisted_session_attachment_refs}
        )
    resume_active = bool(str(resume_codex_session_id or "").strip()) and resume_last_succeeded is not False
    if resume_active and not force_compact:
        compacted_history = history
        compacted_applied = False
    else:
        compacted_history, compacted_applied = _maybe_compact_history(
            history=history,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            actor_user_id=user.id,
            force=force_compact,
        )
    if force_compact and not instruction:
        if not history:
            summary = "No chat history to compact."
        elif compacted_applied:
            summary = "Chat history compacted."
        else:
            summary = "Chat history compaction skipped."
        return summary, compacted_history, True, [], []
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")

    attachment_context, prepared_attachment_refs, prepared_session_attachment_refs = _build_attachment_context(
        payload=payload_for_attachments,
        db=db,
        user=user,
    )
    instruction_with_context = instruction
    if attachment_context:
        instruction_with_context = f"{instruction}\n\n{attachment_context}"
    if resume_active:
        # For resumed Codex threads, avoid resending stitched history on every turn.
        effective_instruction = instruction_with_context
    else:
        effective_instruction = _compose_chat_instruction(instruction_with_context, compacted_history)
    return effective_instruction, compacted_history, False, prepared_attachment_refs, prepared_session_attachment_refs


@router.post("/api/agents/chat")
def agent_chat(
    payload: AgentChatRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    mcp_servers = _normalize_chat_mcp_servers(payload.mcp_servers)
    session_id = _resolve_chat_session_id(payload.session_id)
    existing_codex_session_id, resume_last_succeeded = _load_chat_session_codex_state(
        db=db,
        workspace_id=payload.workspace_id,
        session_id=session_id,
    )
    payload_with_session = payload.model_copy(update={"session_id": session_id})
    (
        effective_instruction,
        _,
        compact_only,
        prepared_attachment_refs,
        prepared_session_attachment_refs,
    ) = _prepare_chat_instruction(
        payload=payload_with_session,
        db=db,
        user=user,
        resume_codex_session_id=existing_codex_session_id,
        resume_last_succeeded=resume_last_succeeded,
    )

    attachment_refs = prepared_attachment_refs or [item.model_dump() for item in payload.attachment_refs or []]
    session_attachment_refs = (
        prepared_session_attachment_refs
        or [item.model_dump() for item in payload.session_attachment_refs or []]
    )
    ChatApplicationService(
        db,
        user,
        command_id=_command_id_with_suffix(command_id, "chat-user"),
    ).append_user_message(
        AppendUserMessagePayload(
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            message_id=None,
            content=(payload.instruction or "").strip(),
            mcp_servers=mcp_servers,
            attachment_refs=attachment_refs,
            session_attachment_refs=session_attachment_refs,
        )
    )

    if compact_only:
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=effective_instruction,
            usage={},
            codex_session_id=None,
        )
        return {
            "ok": True,
            "action": "comment",
            "summary": effective_instruction,
            "comment": None,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={payload.project_id or ''}"
    run_started_at = datetime.now(timezone.utc)
    try:
        outcome = execute_task_automation(
            task_id="",
            title="General Codex Chat",
            description=description,
            status="To do",
            instruction=effective_instruction,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            chat_session_id=session_id,
            codex_session_id=existing_codex_session_id,
            actor_user_id=user.id,
            allow_mutations=bool(payload.allow_mutations),
            mcp_servers=mcp_servers,
        )
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(outcome.summary, outcome.comment),
            usage=_build_usage_with_resume_metadata(outcome),
            codex_session_id=outcome.codex_session_id,
            run_started_at=run_started_at,
        )
        return {
            "ok": True,
            "action": outcome.action,
            "summary": outcome.summary,
            "comment": outcome.comment,
            "session_id": session_id,
            "codex_session_id": outcome.codex_session_id,
            "usage": outcome.usage,
            "resume_attempted": bool(outcome.resume_attempted),
            "resume_succeeded": bool(outcome.resume_succeeded),
            "resume_fallback_used": bool(outcome.resume_fallback_used),
        }
    except TimeoutError:
        timeout_summary = f"Codex timed out after {AGENT_EXECUTOR_TIMEOUT_SECONDS:.0f}s."
        timeout_comment = "Try a narrower request (e.g. one project at a time) or run again."
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(timeout_summary, timeout_comment),
            usage={},
            codex_session_id=None,
            run_started_at=run_started_at,
        )
        return {
            "ok": False,
            "action": "comment",
            "summary": timeout_summary,
            "comment": timeout_comment,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }
    except Exception as exc:
        # Avoid bubbling internal exceptions to the client as 500 errors.
        msg = str(exc)
        error_summary = "Codex failed to complete the request."
        error_comment = msg[:500]
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(error_summary, error_comment),
            usage={},
            codex_session_id=None,
            run_started_at=run_started_at,
        )
        return {
            "ok": False,
            "action": "comment",
            "summary": error_summary,
            "comment": error_comment,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }


@router.post("/api/agents/chat/stream")
def agent_chat_stream(
    payload: AgentChatRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    mcp_servers = _normalize_chat_mcp_servers(payload.mcp_servers)
    session_id = _resolve_chat_session_id(payload.session_id)
    existing_codex_session_id, resume_last_succeeded = _load_chat_session_codex_state(
        db=db,
        workspace_id=payload.workspace_id,
        session_id=session_id,
    )
    payload_with_session = payload.model_copy(update={"session_id": session_id})
    (
        effective_instruction,
        _,
        compact_only,
        prepared_attachment_refs,
        prepared_session_attachment_refs,
    ) = _prepare_chat_instruction(
        payload=payload_with_session,
        db=db,
        user=user,
        resume_codex_session_id=existing_codex_session_id,
        resume_last_succeeded=resume_last_succeeded,
    )

    attachment_refs = prepared_attachment_refs or [item.model_dump() for item in payload.attachment_refs or []]
    session_attachment_refs = (
        prepared_session_attachment_refs
        or [item.model_dump() for item in payload.session_attachment_refs or []]
    )
    ChatApplicationService(
        db,
        user,
        command_id=_command_id_with_suffix(command_id, "chat-user"),
    ).append_user_message(
        AppendUserMessagePayload(
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            message_id=None,
            content=(payload.instruction or "").strip(),
            mcp_servers=mcp_servers,
            attachment_refs=attachment_refs,
            session_attachment_refs=session_attachment_refs,
        )
    )

    if compact_only:
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=effective_instruction,
            usage={},
            codex_session_id=None,
        )
        compact_response = {
            "ok": True,
            "action": "comment",
            "summary": effective_instruction,
            "comment": None,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

        def _compact_stream():
            yield json.dumps({"type": "final", "response": compact_response}, ensure_ascii=True) + "\n"

        return StreamingResponse(_compact_stream(), media_type="application/x-ndjson")

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={payload.project_id or ''}"
    run_started_at = datetime.now(timezone.utc)

    def _stream() -> object:
        event_queue: queue.Queue[dict[str, object] | None] = queue.Queue()

        def _on_event(event: dict[str, object]) -> None:
            event_queue.put(event)

        def _worker() -> None:
            try:
                outcome = execute_task_automation_stream(
                    task_id="",
                    title="General Codex Chat",
                    description=description,
                    status="To do",
                    instruction=effective_instruction,
                    workspace_id=payload.workspace_id,
                    project_id=payload.project_id,
                    chat_session_id=session_id,
                    codex_session_id=existing_codex_session_id,
                    actor_user_id=user.id,
                    allow_mutations=bool(payload.allow_mutations),
                    mcp_servers=mcp_servers,
                    on_event=_on_event,
                )
                final_payload = {
                    "ok": True,
                    "action": outcome.action,
                    "summary": outcome.summary,
                    "comment": outcome.comment,
                    "session_id": session_id,
                    "codex_session_id": outcome.codex_session_id,
                    "usage": outcome.usage,
                    "resume_attempted": bool(outcome.resume_attempted),
                    "resume_succeeded": bool(outcome.resume_succeeded),
                    "resume_fallback_used": bool(outcome.resume_fallback_used),
                }
                event_queue.put({"type": "final", "response": final_payload})
            except TimeoutError:
                timeout_payload = {
                    "ok": False,
                    "action": "comment",
                    "summary": f"Codex timed out after {AGENT_EXECUTOR_TIMEOUT_SECONDS:.0f}s.",
                    "comment": "Try a narrower request (e.g. one project at a time) or run again.",
                    "session_id": session_id,
                    "codex_session_id": None,
                    "usage": None,
                    "resume_attempted": False,
                    "resume_succeeded": False,
                    "resume_fallback_used": False,
                }
                event_queue.put({"type": "final", "response": timeout_payload})
            except Exception as exc:
                error_payload = {
                    "ok": False,
                    "action": "comment",
                    "summary": "Codex failed to complete the request.",
                    "comment": str(exc)[:500],
                    "session_id": session_id,
                    "codex_session_id": None,
                    "usage": None,
                    "resume_attempted": False,
                    "resume_succeeded": False,
                    "resume_fallback_used": False,
                }
                event_queue.put({"type": "final", "response": error_payload})
            finally:
                event_queue.put(None)

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        streamed_assistant_text_parts: list[str] = []

        while True:
            item = event_queue.get()
            if item is None:
                break
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "assistant_text":
                streamed_assistant_text_parts.append(str(item.get("delta") or ""))
            if item_type == "final":
                response = item.get("response")
                if isinstance(response, dict):
                    assistant_content = "".join(streamed_assistant_text_parts).strip()
                    if not assistant_content:
                        assistant_content = _assistant_text(
                            str(response.get("summary") or ""),
                            str(response.get("comment") or ""),
                        )
                    _persist_assistant_message_with_links(
                        db=db,
                        user=user,
                        command_id=command_id,
                        workspace_id=payload.workspace_id,
                        project_id=payload.project_id,
                        session_id=session_id,
                        mcp_servers=mcp_servers,
                        content=assistant_content,
                        usage=(
                            {
                                **(response.get("usage") if isinstance(response.get("usage"), dict) else {}),
                                "codex_resume_attempted": bool(response.get("resume_attempted")),
                                "codex_resume_succeeded": bool(response.get("resume_succeeded")),
                                "codex_resume_fallback_used": bool(response.get("resume_fallback_used")),
                            }
                        ),
                        codex_session_id=str(response.get("codex_session_id") or "").strip() or None,
                        run_started_at=run_started_at,
                    )
            yield json.dumps(item, ensure_ascii=True) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
