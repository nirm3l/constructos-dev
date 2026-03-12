from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import queue
import re
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from plugins import api_policy as plugin_api_policy
from shared.core import (
    AgentChatRun,
    User,
    ensure_project_access,
    ensure_role,
    get_command_id,
    get_current_user,
    get_db,
)
from shared.models import (
    ActivityLog,
    ChatMessage,
    ChatSession,
    CommandExecution,
    Note,
    Project,
    ProjectPluginConfig,
    Task,
    WorkspaceMember,
)
from shared.in_memory_stream_broker import InMemoryStreamBroker
from shared.settings import (
    ATTACHMENTS_DIR,
    AGENT_CHAT_HISTORY_COMPACT_THRESHOLD,
    AGENT_CHAT_HISTORY_RECENT_TAIL,
    AGENT_ENABLED_PLUGINS,
    AGENT_SYSTEM_USER_ID,
)

from .executor import AutomationOutcome, execute_task_automation, execute_task_automation_stream
from .intent_classifier import classify_instruction_intent
from .mcp_registry import (
    filter_mcp_servers_for_project_plugins as filter_mcp_servers_for_project_plugins_registry,
    normalize_chat_mcp_servers as normalize_chat_mcp_servers_registry,
)
from .codex_auth import (
    cancel_device_auth_session,
    delete_system_override_auth,
    get_codex_auth_status,
    resolve_effective_auth_source,
    start_device_auth_session,
)
from .gateway import build_ui_gateway
from features.chat.application import ChatApplicationService
from features.chat.command_handlers import (
    AppendAssistantMessagePayload,
    AppendUserMessagePayload,
    LinkMessageResourcePayload,
)
from features.agents.gates import default_required_delivery_checks, normalize_delivery_required_checks

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
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_DEPLOY_STACK_RE = re.compile(r"\b(constructos-[a-z0-9_-]+)\b", re.IGNORECASE)
_DOCKER_COMPOSE_STACK_RE = re.compile(r"docker\s+compose\s+-p\s+([a-z0-9][a-z0-9_-]*)", re.IGNORECASE)
_DEPLOY_PORT_RE = re.compile(r"\bport\s*[:=]?\s*[`\"']?(\d{2,5})", re.IGNORECASE)
_HOST_PORT_RE = re.compile(r"(?:localhost|0\.0\.0\.0):(\d{2,5})\b", re.IGNORECASE)
_HEALTH_PATH_RE = re.compile(r"(/health[^\s\"'`]*)", re.IGNORECASE)
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
_MAX_CROSS_SESSION_DELTA_MESSAGES = 8
_MAX_CROSS_SESSION_DELTA_CHARS_PER_MESSAGE = 220
_ALLOWED_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"
_CREATED_RESOURCE_ACTIONS: dict[str, str] = {
    "TaskCreated": "task",
    "NoteCreated": "note",
    "SpecificationCreated": "specification",
    "ProjectRuleCreated": "project_rule",
}

_CHAT_STREAM_BROKER = InMemoryStreamBroker(max_events=1500)
_CHAT_STREAM_CANCEL_LOCK = threading.Lock()
_CHAT_STREAM_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CHAT_STREAM_CANCEL_BY_KEY: dict[str, tuple[str, threading.Event]] = {}
_CHAT_STREAM_STOP_REQUESTED_BY_KEY: dict[str, bool] = {}
_PROJECT_SETUP_STARTER_NEXT_QUESTION = "What should the new project be named?"
_CODEX_AUTH_REQUIRED_SUMMARY = "Codex authentication is not configured."
_CODEX_AUTH_REQUIRED_COMMENT = "Open Profile > Security to configure Codex, or ask a workspace admin to do it."


def _user_can_manage_codex_auth(db: Session, user_id: str) -> bool:
    membership = db.execute(
        select(WorkspaceMember.id).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role.in_(("Owner", "Admin")),
        ).limit(1)
    ).scalar_one_or_none()
    return membership is not None


def _ensure_codex_auth_manage_allowed(db: Session, user_id: str) -> None:
    if _user_can_manage_codex_auth(db, user_id):
        return
    raise HTTPException(status_code=403, detail="Only workspace owners and admins can configure Codex authentication.")


def _build_codex_auth_required_response(*, session_id: str) -> dict[str, object]:
    return {
        "ok": False,
        "action": "comment",
        "summary": _CODEX_AUTH_REQUIRED_SUMMARY,
        "comment": _CODEX_AUTH_REQUIRED_COMMENT,
        "session_id": session_id,
        "codex_session_id": None,
        "usage": None,
        "resume_attempted": False,
        "resume_succeeded": False,
        "resume_fallback_used": False,
    }


def _chat_stream_key(*, workspace_id: str, session_id: str) -> str:
    return f"{str(workspace_id or '').strip()}::{str(session_id or '').strip()}"


def _should_prompt_for_project_setup_name(*, intent_flags: dict[str, object], project_id: str | None) -> bool:
    _ = project_id
    if not bool(intent_flags.get("project_creation_intent")):
        return False
    return not bool(intent_flags.get("project_name_provided"))


def _create_chat_stream_run(*, stream_key: str, preferred_run_id: str | None = None) -> str:
    return _CHAT_STREAM_BROKER.create_run(key=stream_key, preferred_run_id=preferred_run_id)


def _publish_chat_stream_event(*, stream_key: str, event: dict[str, object]) -> dict[str, object] | None:
    return _CHAT_STREAM_BROKER.publish_event(key=stream_key, event=event)


def _finish_chat_stream_run(*, stream_key: str) -> None:
    _CHAT_STREAM_BROKER.finish_run(key=stream_key)


def _subscribe_chat_stream_run(
    *,
    stream_key: str,
    run_id: str,
    since_seq: int,
) -> tuple[queue.Queue[dict[str, object]], list[dict[str, object]], bool]:
    return _CHAT_STREAM_BROKER.subscribe_run(key=stream_key, run_id=run_id, since_seq=since_seq)


def _unsubscribe_chat_stream_run(*, stream_key: str, subscriber_queue: queue.Queue[dict[str, object]]) -> None:
    _CHAT_STREAM_BROKER.unsubscribe_run(key=stream_key, subscriber_queue=subscriber_queue)


def _chat_stream_cancel_key(*, stream_key: str, run_id: str) -> str:
    return f"{stream_key}::{str(run_id or '').strip()}"


def _register_chat_stream_cancel_event(*, stream_key: str, run_id: str) -> threading.Event:
    event = threading.Event()
    key = _chat_stream_cancel_key(stream_key=stream_key, run_id=run_id)
    with _CHAT_STREAM_CANCEL_LOCK:
        _CHAT_STREAM_CANCEL_EVENTS[key] = event
        _CHAT_STREAM_CANCEL_BY_KEY[stream_key] = (str(run_id or "").strip(), event)
    return event


def _request_chat_stream_cancel(*, stream_key: str, run_id: str) -> bool:
    normalized_run_id = str(run_id or "").strip()
    key = _chat_stream_cancel_key(stream_key=stream_key, run_id=normalized_run_id)
    with _CHAT_STREAM_CANCEL_LOCK:
        event = _CHAT_STREAM_CANCEL_EVENTS.get(key)
        if event is None:
            current = _CHAT_STREAM_CANCEL_BY_KEY.get(stream_key)
            if isinstance(current, tuple) and len(current) == 2:
                event = current[1]
    if event is None:
        return False
    event.set()
    return True


def _clear_chat_stream_cancel_event(*, stream_key: str, run_id: str) -> None:
    key = _chat_stream_cancel_key(stream_key=stream_key, run_id=run_id)
    with _CHAT_STREAM_CANCEL_LOCK:
        _CHAT_STREAM_CANCEL_EVENTS.pop(key, None)
        current = _CHAT_STREAM_CANCEL_BY_KEY.get(stream_key)
        if isinstance(current, tuple) and len(current) == 2:
            current_run_id = str(current[0] or "").strip()
            if current_run_id == str(run_id or "").strip():
                _CHAT_STREAM_CANCEL_BY_KEY.pop(stream_key, None)


def _set_chat_stream_stop_requested(*, stream_key: str, value: bool) -> None:
    with _CHAT_STREAM_CANCEL_LOCK:
        if value:
            _CHAT_STREAM_STOP_REQUESTED_BY_KEY[stream_key] = True
        else:
            _CHAT_STREAM_STOP_REQUESTED_BY_KEY.pop(stream_key, None)


def _is_chat_stream_stop_requested(*, stream_key: str) -> bool:
    with _CHAT_STREAM_CANCEL_LOCK:
        return bool(_CHAT_STREAM_STOP_REQUESTED_BY_KEY.get(stream_key))


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    candidate_paths = [_PROMPT_TEMPLATES_DIR / name]
    candidate_paths.extend(base / name for base in _plugin_prompt_template_dirs())
    for template_path in candidate_paths:
        try:
            return template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
    raise RuntimeError(f"Prompt template file not found: {candidate_paths[0]}")


@lru_cache(maxsize=1)
def _plugin_prompt_template_dirs() -> tuple[Path, ...]:
    plugins_root = Path(__file__).resolve().parents[2] / "plugins"
    enabled = {str(item or "").strip().lower() for item in (AGENT_ENABLED_PLUGINS or []) if str(item or "").strip()}
    if not enabled:
        enabled = {"team_mode"}
    if enabled.intersection({"none", "off", "disabled"}):
        return tuple()
    out: list[Path] = []
    for key in sorted(enabled):
        candidate = plugins_root / key / "prompt_templates"
        if candidate.is_dir():
            out.append(candidate)
    return tuple(out)


def _render_prompt_template(name: str, values: dict[str, object]) -> str:
    rendered_values = {key: str(value) for key, value in values.items()}
    template = _load_prompt_template(name)
    try:
        return template.format(**rendered_values)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise RuntimeError(f"Missing prompt template value '{missing_key}' for {name}") from exc


def _normalize_reasoning_effort(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    alias_map = {
        "very-high": "xhigh",
        "very_high": "xhigh",
        "very high": "xhigh",
    }
    canonical = alias_map.get(normalized, normalized)
    if canonical not in _ALLOWED_REASONING_EFFORTS:
        return None
    return canonical


def _resolve_chat_execution_preferences(payload: AgentChatRun, user: User) -> tuple[str | None, str | None]:
    payload_model = str(payload.model or "").strip()
    user_model = str(getattr(user, "agent_chat_model", "") or "").strip()
    model = payload_model or user_model or None

    payload_reasoning = _normalize_reasoning_effort(payload.reasoning_effort)
    user_reasoning = _normalize_reasoning_effort(getattr(user, "agent_chat_reasoning_effort", None))
    reasoning_effort = payload_reasoning or user_reasoning
    return model, reasoning_effort


def _chat_timeout_summary() -> str:
    return "Codex execution timed out."


def _normalize_chat_mcp_servers(
    raw_servers: list[str] | None,
    *,
    project_id: str | None = None,
) -> list[str]:
    try:
        normalized = normalize_chat_mcp_servers_registry(raw_servers, strict=True)
        return filter_mcp_servers_for_project_plugins_registry(
            project_id=project_id,
            selected_servers=normalized,
        )
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


def _attachment_checksum(*, path: str, mime_type: str, size_bytes: int, snippet: str) -> str:
    payload = {
        "path": path,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "snippet": _truncate_chat_delta_text(snippet, max_chars=2048),
    }
    material = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _build_attachment_context(
    *,
    payload: AgentChatRun,
    db: Session,
    user: User,
    reuse_session_extracted_context: bool = False,
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
        size_bytes = int(candidate.stat().st_size)
        normalized_ref: dict[str, object] = {
            "path": path,
            "name": display_name,
            "mime_type": mime_type or None,
            "size_bytes": size_bytes,
            "extraction_status": "pending",
        }
        ref_checksum = str(_ref_value(ref, "checksum") or "").strip()
        if ref_checksum:
            normalized_ref["checksum"] = ref_checksum

        is_message_ref = path_key in message_ref_paths
        is_session_ref = path_key in session_ref_paths
        prior_status = str(_ref_value(ref, "extraction_status") or "").strip().lower()
        prior_extracted_text = str(_ref_value(ref, "extracted_text") or "").strip()
        can_reuse_session_context = (
            reuse_session_extracted_context
            and is_session_ref
            and not is_message_ref
            and (prior_status in {"extracted", "truncated", "reused"} or bool(prior_extracted_text))
        )
        if can_reuse_session_context:
            normalized_ref["extraction_status"] = "reused"
            if not ref_checksum:
                normalized_ref["checksum"] = _attachment_checksum(
                    path=path,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    snippet=prior_extracted_text,
                )
            short_checksum = str(normalized_ref.get("checksum") or "").strip()[:10]
            checksum_text = f"; checksum={short_checksum}" if short_checksum else ""
            lines.append(f"Attachment {index}: {display_name} (reused from session memory{checksum_text})")
            if is_message_ref:
                processed_message_refs.append(normalized_ref)
            if is_session_ref:
                processed_session_refs.append(normalized_ref)
            lines.append("")
            continue

        lines.append(f"Attachment {index}: {display_name}")
        lines.append(f"Path: {path}")
        lines.append(f"MIME type: {mime_type or 'unknown'}")

        remaining_chars = _MAX_CHAT_ATTACHMENT_CHARS_TOTAL - total_chars
        if remaining_chars <= 0:
            lines.append("Content: omitted (chat attachment context limit reached).")
            normalized_ref["extraction_status"] = "skipped_limit"
            if is_message_ref:
                processed_message_refs.append(normalized_ref)
            if is_session_ref:
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
            normalized_ref["checksum"] = _attachment_checksum(
                path=path,
                mime_type=mime_type,
                size_bytes=size_bytes,
                snippet=snippet,
            )
            lines.append("Content:")
            lines.append(snippet)
            if truncated:
                lines.append("[truncated]")
            total_chars += len(snippet)
        else:
            normalized_ref["extraction_status"] = "skipped"
            lines.append(status_message or "Content: omitted (empty or unreadable file).")
            if not ref_checksum:
                normalized_ref["checksum"] = _attachment_checksum(
                    path=path,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    snippet="",
                )
        if is_message_ref:
            processed_message_refs.append(normalized_ref)
        if is_session_ref:
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
        checksum = str(_ref_value(ref, "checksum") or "").strip()
        if checksum:
            normalized_ref["checksum"] = checksum
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


def _build_usage_with_resume_metadata(
    outcome: AutomationOutcome,
    *,
    extra_usage: dict[str, object] | None = None,
) -> dict[str, object]:
    usage_payload: dict[str, object] = dict(outcome.usage or {})
    if isinstance(extra_usage, dict):
        usage_payload.update(extra_usage)
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
    actor_ids = {str(actor_id or "").strip()}
    actor_ids.add(str(AGENT_SYSTEM_USER_ID or "").strip())
    normalized_actor_ids = [item for item in actor_ids if item]
    query = (
        select(ActivityLog.action, ActivityLog.details)
        .where(
            ActivityLog.workspace_id == workspace_id,
            ActivityLog.project_id == normalized_project_id,
            ActivityLog.actor_id.in_(tuple(normalized_actor_ids)),
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


def _truncate_chat_delta_text(content: str, *, max_chars: int = _MAX_CROSS_SESSION_DELTA_CHARS_PER_MESSAGE) -> str:
    normalized = " ".join(str(content or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max(0, max_chars - 3)]}..."


def _load_cross_session_recent_updates(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
    max_messages: int = _MAX_CROSS_SESSION_DELTA_MESSAGES,
) -> list[dict[str, str]]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return []

    session_key = str(session_id or "").strip()
    current_session_row = db.execute(
        select(ChatSession.id, ChatSession.last_message_at)
        .where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.project_id == normalized_project_id,
            ChatSession.session_key == session_key,
            ChatSession.created_by == user.id,
        )
    ).first()
    current_session_db_id = str(current_session_row[0] or "").strip() if current_session_row else ""
    current_last_message_at = current_session_row[1] if current_session_row else None

    message_time = func.coalesce(ChatMessage.turn_created_at, ChatMessage.created_at)
    base_query = (
        select(
            ChatMessage.id,
            ChatMessage.role,
            ChatMessage.content,
            ChatSession.session_key,
            message_time.label("message_time"),
        )
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.project_id == normalized_project_id,
            ChatSession.created_by == user.id,
            ChatSession.is_archived == False,
            ChatMessage.is_deleted == False,
        )
        .order_by(message_time.desc(), ChatMessage.order_index.desc(), ChatMessage.created_at.desc())
    )
    query = base_query.limit(max(8, int(max_messages) * 4))
    if current_session_db_id:
        query = query.where(ChatMessage.session_id != current_session_db_id)
    if current_last_message_at is not None:
        # Include same-timestamp messages from other sessions to avoid dropping
        # user turns when requests are processed nearly simultaneously.
        query = query.where(message_time >= current_last_message_at)

    rows = db.execute(query).all()
    if not rows and current_last_message_at is not None:
        # Fallback for near-simultaneous timestamps: still provide most recent cross-session context.
        fallback_query = base_query.limit(max(8, int(max_messages) * 4))
        if current_session_db_id:
            fallback_query = fallback_query.where(ChatMessage.session_id != current_session_db_id)
        rows = db.execute(fallback_query).all()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for message_id_raw, role_raw, content_raw, source_session_key, _ in rows:
        content = _truncate_chat_delta_text(str(content_raw or ""))
        if not content:
            continue
        normalized_role = "assistant" if str(role_raw or "").strip().lower() == "assistant" else "user"
        source_key = str(source_session_key or "").strip()
        message_id = str(message_id_raw or "").strip()
        update_id = hashlib.sha256(
            f"{message_id}|{source_key}|{normalized_role}|{content}".encode("utf-8")
        ).hexdigest()[:24]
        dedupe_key = f"{source_key}|{normalized_role}|{content}".lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(
            {
                "update_id": update_id,
                "role": normalized_role,
                "content": content,
                "source_session_key": source_key,
            }
        )
        if len(out) >= max(1, int(max_messages)):
            break
    out.reverse()
    return out


def _compose_cross_session_updates_text(updates: list[dict[str, str]]) -> str:
    if not updates:
        return ""
    lines = []
    for item in updates:
        role = str(item.get("role") or "user").strip().lower()
        role_label = "ASSISTANT" if role == "assistant" else "USER"
        source_key = str(item.get("source_session_key") or "").strip()
        source_label = f"[{source_key}] " if source_key else ""
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        update_id = str(item.get("update_id") or "").strip()
        update_prefix = f"[{update_id}] " if update_id else ""
        lines.append(f"- {update_prefix}{source_label}{role_label}: {content}")
    if not lines:
        return ""
    return (
        "Recent updates from other project chat sessions (new since this session was last active):\n"
        + "\n".join(lines)
    )


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
        extraction_status = str(item.get("extraction_status") or "").strip().lower()
        if extraction_status in {"extracted", "truncated", "reused", "skipped", "skipped_limit", "skipped_file_limit"}:
            normalized["extraction_status"] = extraction_status
        extracted_text = str(item.get("extracted_text") or "").strip()
        if extracted_text:
            normalized["extracted_text"] = extracted_text
        out.append(normalized)
    return out


def _load_chat_session_usage_metadata(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    session_id: str | None,
) -> dict[str, object]:
    session_key = str(session_id or "").strip()
    if not session_key:
        return {}
    session = db.execute(
        select(ChatSession).where(
            ChatSession.workspace_id == workspace_id,
            ChatSession.session_key == session_key,
            ChatSession.created_by == user.id,
        )
    ).scalar_one_or_none()
    if session is None:
        return {}
    if session.project_id:
        ensure_project_access(db, workspace_id, session.project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    try:
        payload = json.loads(session.usage_json or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_sent_cross_session_update_ids(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    session_id: str | None,
    max_items: int = 160,
) -> list[str]:
    usage = _load_chat_session_usage_metadata(
        db=db,
        user=user,
        workspace_id=workspace_id,
        session_id=session_id,
    )
    raw = usage.get("sent_cross_session_update_ids")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        update_id = str(item or "").strip()
        if not update_id or update_id in seen:
            continue
        seen.add(update_id)
        out.append(update_id)
    return out[-max(1, int(max_items)) :]


def _parse_compact_command(instruction: str) -> tuple[bool, str]:
    raw = str(instruction or "").strip()
    if not raw:
        return False, ""
    marker = "/compact"
    if not raw.lower().startswith(marker):
        return False, raw
    remainder = raw[len(marker):].strip()
    return True, remainder


def _classify_chat_instruction_intents(
    *,
    instruction: str,
    workspace_id: str,
    project_id: str | None,
    session_id: str | None,
    actor_user_id: str | None,
) -> dict[str, object]:
    return classify_instruction_intent(
        instruction=instruction,
        workspace_id=workspace_id,
        project_id=project_id,
        session_id=session_id,
        actor_user_id=actor_user_id,
    )


def _build_execution_intent_mandate() -> str:
    return _render_prompt_template("chat_execution_intent_mandate.md", {})


def _build_chat_history_compaction_instruction(*, history_lines: str) -> str:
    return _render_prompt_template(
        "chat_history_compaction_instruction.md",
        {"history_lines": history_lines},
    )


def _build_chat_history_compaction_description(*, workspace_id: str, project_id: str | None) -> str:
    return _render_prompt_template(
        "chat_history_compaction_description.md",
        {
            "workspace_id": workspace_id,
            "project_id": project_id or "",
        },
    )


def _build_execution_evidence_contract_comment(*, existing_comment: str | None, details: str) -> str:
    existing = str(existing_comment or "").strip()
    body = _render_prompt_template(
        "chat_execution_evidence_contract_comment.md",
        {"details": details},
    )
    if existing:
        return f"{existing}\n\n{body}"
    return body


def _build_chat_timeout_comment() -> str:
    return _render_prompt_template("chat_timeout_comment.md", {}).strip()


def _build_chat_error_summary() -> str:
    return _render_prompt_template("chat_error_summary.md", {}).strip()


def _extract_missing_setup_question(error_text: str) -> str | None:
    raw = str(error_text or "").strip()
    if not raw:
        return None

    def _extract_from_dict(payload: dict[str, object]) -> str | None:
        code = str(payload.get("code") or "").strip().lower()
        if code != "missing_setup_inputs":
            return None
        question = str(payload.get("next_question") or "").strip()
        if question:
            return question
        missing = payload.get("missing_inputs")
        if isinstance(missing, list):
            for item in missing:
                if not isinstance(item, dict):
                    continue
                question_text = str(item.get("question") or "").strip()
                if question_text:
                    return question_text
        return None

    try:
        parsed_direct = json.loads(raw)
    except Exception:
        parsed_direct = None
    if isinstance(parsed_direct, dict):
        extracted = _extract_from_dict(parsed_direct)
        if extracted:
            return extracted

    decoder = json.JSONDecoder()
    for index in range(len(raw)):
        if raw[index] != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(raw[index:])
        except Exception:
            continue
        if isinstance(candidate, dict):
            extracted = _extract_from_dict(candidate)
            if extracted:
                return extracted

    match = re.search(r'"next_question"\s*:\s*"([^"]+)"', raw)
    if match:
        fallback_question = str(match.group(1) or "").strip()
        if fallback_question:
            return fallback_question
    return None


def _map_chat_exception_to_response(exc: Exception) -> tuple[bool, str, str | None]:
    missing_setup_question = _extract_missing_setup_question(str(exc))
    if missing_setup_question:
        return True, missing_setup_question, None
    return False, _build_chat_error_summary(), str(exc).strip()[:500]


def _build_team_lead_kickoff_instruction(*, project_id: str, requester_user_id: str) -> str:
    return _render_prompt_template(
        "team_mode_kickoff_instruction.md",
        {
            "project_id": project_id,
            "requester_user_id": requester_user_id,
        },
    )


def _extract_runtime_deploy_target_from_text(text: str) -> tuple[str | None, int | None, str | None]:
    normalized = str(text or "").strip()
    if not normalized:
        return None, None, None

    stack_match = _DOCKER_COMPOSE_STACK_RE.search(normalized) or _DEPLOY_STACK_RE.search(normalized)
    stack = str(stack_match.group(1) or "").strip() if stack_match else None

    port: int | None = None
    port_match = _DEPLOY_PORT_RE.search(normalized) or _HOST_PORT_RE.search(normalized)
    if port_match:
        try:
            candidate = int(str(port_match.group(1) or "").strip())
            if 1 <= candidate <= 65535:
                port = candidate
        except Exception:
            port = None

    health_path_match = _HEALTH_PATH_RE.search(normalized)
    health_path = str(health_path_match.group(1) or "").strip() if health_path_match else None
    if health_path and not health_path.startswith("/"):
        health_path = f"/{health_path}"
    return stack, port, health_path


def _resolve_runtime_deploy_target_from_project_artifacts(
    *,
    db: Session,
    workspace_id: str,
    project_id: str,
) -> tuple[str | None, int | None, str | None]:
    tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()
    deploy_tasks = [task for task in tasks if "deploy" in str(task.title or "").strip().lower()]
    if not deploy_tasks:
        return None, None, None

    task_ids = [str(task.id) for task in deploy_tasks if str(task.id or "").strip()]
    notes_by_task: dict[str, list[Note]] = {}
    comments_by_task: dict[str, list[ActivityLog]] = {}
    if task_ids:
        notes = db.execute(
            select(Note).where(
                Note.workspace_id == workspace_id,
                Note.project_id == project_id,
                Note.is_deleted == False,  # noqa: E712
                Note.task_id.in_(task_ids),
            )
        ).scalars().all()
        for note in notes:
            key = str(note.task_id or "").strip()
            if not key:
                continue
            notes_by_task.setdefault(key, []).append(note)

        comments = db.execute(
            select(ActivityLog).where(
                ActivityLog.workspace_id == workspace_id,
                ActivityLog.project_id == project_id,
                ActivityLog.task_id.in_(task_ids),
            )
        ).scalars().all()
        for comment in comments:
            key = str(comment.task_id or "").strip()
            if not key:
                continue
            comments_by_task.setdefault(key, []).append(comment)

    project_notes = db.execute(
        select(Note).where(
            Note.workspace_id == workspace_id,
            Note.project_id == project_id,
            Note.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()

    resolved_stack: str | None = None
    resolved_port: int | None = None
    resolved_health_path: str | None = None

    for task in deploy_tasks:
        task_id = str(task.id or "").strip()
        corpus_parts = [str(task.title or ""), str(task.description or ""), str(task.instruction or "")]
        for note in notes_by_task.get(task_id, []):
            corpus_parts.extend([str(note.title or ""), str(note.body or "")])
        for comment in comments_by_task.get(task_id, []):
            corpus_parts.append(str(comment.details or ""))
        corpus = "\n".join(corpus_parts)
        stack, port, health_path = _extract_runtime_deploy_target_from_text(corpus)
        if not resolved_stack and stack:
            resolved_stack = stack
        if resolved_port is None and port is not None:
            resolved_port = port
        if not resolved_health_path and health_path:
            resolved_health_path = health_path
        if resolved_stack and resolved_port is not None and resolved_health_path:
            break

    if not (resolved_stack and resolved_port is not None and resolved_health_path):
        for note in project_notes:
            corpus = "\n".join([str(note.title or ""), str(note.body or "")])
            stack, port, health_path = _extract_runtime_deploy_target_from_text(corpus)
            if not resolved_stack and stack:
                resolved_stack = stack
            if resolved_port is None and port is not None:
                resolved_port = port
            if not resolved_health_path and health_path:
                resolved_health_path = health_path
            if resolved_stack and resolved_port is not None and resolved_health_path:
                break

    return resolved_stack, resolved_port, resolved_health_path


def _promote_plugin_policy_to_execution_mode_if_needed(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    project_id: str,
    command_id: str | None,
) -> None:
    plugin_rows = db.execute(
        select(ProjectPluginConfig).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key.in_(["team_mode", "git_delivery", "docker_compose"]),
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalars().all()
    row_by_key = {
        str(getattr(row, "plugin_key", "") or "").strip().lower(): row
        for row in plugin_rows
        if str(getattr(row, "plugin_key", "") or "").strip()
    }
    team_mode_enabled = bool(getattr(row_by_key.get("team_mode"), "enabled", False))
    git_delivery_enabled = bool(getattr(row_by_key.get("git_delivery"), "enabled", False))
    if not (team_mode_enabled or git_delivery_enabled):
        return

    git_delivery_config: dict[str, object] = {}
    git_delivery_row = row_by_key.get("git_delivery")
    if git_delivery_row is not None:
        try:
            parsed = json.loads(str(getattr(git_delivery_row, "config_json", "") or "").strip() or "{}")
            if isinstance(parsed, dict):
                git_delivery_config = dict(parsed)
        except Exception:
            git_delivery_config = {}

    detected_stack, detected_port, detected_health_path = _resolve_runtime_deploy_target_from_project_artifacts(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    required_checks_cfg = (
        dict(git_delivery_config.get("required_checks"))
        if isinstance(git_delivery_config.get("required_checks"), dict)
        else {}
    )
    delivery_checks_raw = required_checks_cfg.get("delivery")
    delivery_checks = (
        [str(item or "").strip() for item in delivery_checks_raw if str(item or "").strip()]
        if isinstance(delivery_checks_raw, list)
        else []
    )
    normalized_delivery_checks = normalize_delivery_required_checks(
        delivery_checks if delivery_checks else default_required_delivery_checks(team_mode_enabled=team_mode_enabled),
        team_mode_enabled=team_mode_enabled,
    )
    required_checks_cfg["delivery"] = normalized_delivery_checks
    git_delivery_config["required_checks"] = required_checks_cfg
    build_ui_gateway(actor_user_id=user.id).apply_project_plugin_config(
        project_id=project_id,
        workspace_id=workspace_id,
        plugin_key="git_delivery",
        config=git_delivery_config,
        enabled=True,
    )

    docker_compose_config: dict[str, object] = {}
    docker_compose_row = row_by_key.get("docker_compose")
    if docker_compose_row is not None:
        try:
            parsed = json.loads(str(getattr(docker_compose_row, "config_json", "") or "").strip() or "{}")
            if isinstance(parsed, dict):
                docker_compose_config = dict(parsed)
        except Exception:
            docker_compose_config = {}
    runtime_cfg = (
        dict(docker_compose_config.get("runtime_deploy_health"))
        if isinstance(docker_compose_config.get("runtime_deploy_health"), dict)
        else {}
    )
    if "required" not in runtime_cfg:
        runtime_cfg["required"] = bool(team_mode_enabled)
    if not str(runtime_cfg.get("stack") or "").strip() and detected_stack:
        runtime_cfg["stack"] = detected_stack
    runtime_port_raw = runtime_cfg.get("port")
    has_valid_port = isinstance(runtime_port_raw, int) and 1 <= int(runtime_port_raw) <= 65535
    if not has_valid_port and detected_port is not None:
        runtime_cfg["port"] = int(detected_port)
    if not str(runtime_cfg.get("health_path") or "").strip() and detected_health_path:
        runtime_cfg["health_path"] = detected_health_path
    docker_compose_config["runtime_deploy_health"] = runtime_cfg
    build_ui_gateway(actor_user_id=user.id).apply_project_plugin_config(
        project_id=project_id,
        workspace_id=workspace_id,
        plugin_key="docker_compose",
        config=docker_compose_config,
        enabled=True,
    )


def _sync_plugin_runtime_target_if_needed(
    *,
    db: Session,
    user: User,
    workspace_id: str,
    project_id: str,
    command_id: str | None,
) -> bool:
    row = db.execute(
        select(ProjectPluginConfig).where(
            ProjectPluginConfig.workspace_id == workspace_id,
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == "docker_compose",
            ProjectPluginConfig.enabled == True,  # noqa: E712
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    config: dict[str, object] = {}
    try:
        parsed = json.loads(str(getattr(row, "config_json", "") or "").strip() or "{}")
        if isinstance(parsed, dict):
            config = dict(parsed)
    except Exception:
        config = {}

    runtime_cfg = dict(config.get("runtime_deploy_health")) if isinstance(config.get("runtime_deploy_health"), dict) else {}
    runtime_stack = str(runtime_cfg.get("stack") or "").strip() or None
    runtime_port_raw = runtime_cfg.get("port")
    runtime_health_path = str(runtime_cfg.get("health_path") or "").strip() or None
    has_valid_port = isinstance(runtime_port_raw, int) and 1 <= int(runtime_port_raw) <= 65535

    detected_stack, detected_port, detected_health_path = _resolve_runtime_deploy_target_from_project_artifacts(
        db=db,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    changed = False
    if not runtime_stack and detected_stack:
        runtime_cfg["stack"] = detected_stack
        changed = True
    if not has_valid_port and detected_port is not None:
        runtime_cfg["port"] = int(detected_port)
        changed = True
    if not runtime_health_path and detected_health_path:
        runtime_cfg["health_path"] = detected_health_path
        changed = True
    if not changed:
        return False

    config["runtime_deploy_health"] = runtime_cfg
    build_ui_gateway(actor_user_id=user.id).apply_project_plugin_config(
        project_id=project_id,
        workspace_id=workspace_id,
        plugin_key="docker_compose",
        config=config,
        enabled=True,
    )
    return True


def _resolve_effective_chat_project_id(
    *,
    db: Session,
    workspace_id: str,
    user_id: str,
    project_id: str | None,
    session_id: str | None,
    instruction: str,
) -> str | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_project_id and normalized_session_id:
        session = db.execute(
            select(ChatSession).where(
                ChatSession.workspace_id == workspace_id,
                ChatSession.session_key == normalized_session_id,
                ChatSession.created_by == str(user_id),
            )
        ).scalar_one_or_none()
        session_project_id = str(getattr(session, "project_id", "") or "").strip()
        if session_project_id:
            normalized_project_id = session_project_id
    if not normalized_project_id:
        return None
    exists = db.execute(
        select(Project.id).where(
            Project.id == normalized_project_id,
            Project.workspace_id == workspace_id,
            Project.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if exists is not None:
        return normalized_project_id
    intent_flags = _classify_chat_instruction_intents(
        instruction=instruction,
        workspace_id=workspace_id,
        project_id=None,
        session_id=None,
    )
    if bool(intent_flags.get("project_creation_intent")):
        return None
    raise HTTPException(status_code=404, detail="Project not found")


def _collect_execution_evidence_violations(
    *,
    db: Session,
    user_id: str,
    project_id: str,
    run_started_at: datetime,
) -> list[dict[str, str]]:
    rows = db.execute(
        select(CommandExecution.response_json)
        .where(
            CommandExecution.user_id == str(user_id),
            CommandExecution.command_name.in_(("Task.Patch", "Task.Create")),
            CommandExecution.created_at >= run_started_at,
        )
        .order_by(CommandExecution.created_at.asc())
    ).all()
    latest_by_task: dict[str, dict[str, object]] = {}
    for (response_json,) in rows:
        try:
            payload = json.loads(str(response_json or "{}"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("project_id") or "").strip() != str(project_id):
            continue
        task_id = str(payload.get("id") or "").strip()
        if not task_id:
            continue
        latest_by_task[task_id] = payload

    violations: list[dict[str, str]] = []
    task_ids = list(latest_by_task.keys())
    note_task_ids: set[str] = set()
    if task_ids:
        note_rows = db.execute(
            select(Note.task_id).where(
                Note.task_id.in_(task_ids),
                Note.is_deleted == False,  # noqa: E712
            )
        ).all()
        note_task_ids = {
            str(task_id).strip()
            for (task_id,) in note_rows
            if str(task_id or "").strip()
        }

    def _has_valid_external_ref(external_refs: object) -> bool:
        if not isinstance(external_refs, list):
            return False
        for item in external_refs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            lower_url = url.lower()
            if lower_url.startswith("http://") or lower_url.startswith("https://"):
                return True
            text_blob = f"{url} {title}".strip()
            if _COMMIT_SHA_RE.search(text_blob):
                return True
        return False

    for task_id, payload in latest_by_task.items():
        status = str(payload.get("status") or "").strip()
        if status not in {"QA", "Lead", "Done"}:
            continue
        external_refs = payload.get("external_refs") or []
        has_note_evidence = task_id in note_task_ids
        has_external_evidence = _has_valid_external_ref(external_refs)
        if has_note_evidence or has_external_evidence:
            continue
        violations.append(
            {
                "task_id": task_id,
                "title": str(payload.get("title") or "").strip() or task_id,
                "status": status,
            }
        )
    return violations


def _apply_execution_evidence_contract(
    *,
    db: Session,
    user_id: str,
    project_id: str | None,
    execution_intent: bool,
    allow_mutations: bool,
    run_started_at: datetime,
    summary: str,
    comment: str | None,
) -> tuple[bool, str, str | None]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id or not allow_mutations:
        return True, summary, comment
    if not bool(execution_intent):
        return True, summary, comment
    violations = _collect_execution_evidence_violations(
        db=db,
        user_id=user_id,
        project_id=normalized_project_id,
        run_started_at=run_started_at,
    )
    if not violations:
        return True, summary, comment
    details = "\n".join(
        f"- {item['title']} ({item['task_id']}) -> status `{item['status']}` has no external links"
        for item in violations
    )
    contract_summary = "Execution incomplete: task evidence is missing."
    contract_comment = _build_execution_evidence_contract_comment(
        existing_comment=comment,
        details=details,
    )
    return False, contract_summary, contract_comment


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
    compact_instruction = _build_chat_history_compaction_instruction(
        history_lines="\n".join(lines),
    )
    outcome = execute_task_automation(
        task_id="",
        title="General Codex Chat History Compaction",
        description=_build_chat_history_compaction_description(
            workspace_id=workspace_id,
            project_id=project_id,
        ),
        status="To do",
        instruction=compact_instruction,
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        allow_mutations=False,
        timeout_seconds=0,
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
) -> tuple[
    str,
    list[dict[str, str]],
    bool,
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, bool],
    dict[str, object],
]:
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
        return (
            summary,
            compacted_history,
            True,
            [],
            [],
            {
                "execution_intent": False,
                "execution_kickoff_intent": False,
                "project_creation_intent": False,
                "workflow_scope": "unknown",
                "execution_mode": "unknown",
                "deploy_requested": False,
                "docker_compose_requested": False,
                "requested_port": None,
                "exact_task_count": None,
                "project_name_provided": False,
                "task_completion_requested": False,
            },
            {"prompt_instruction_segments": {"user_instruction": len(instruction)}},
        )
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")

    attachment_context, prepared_attachment_refs, prepared_session_attachment_refs = _build_attachment_context(
        payload=payload_for_attachments,
        db=db,
        user=user,
        reuse_session_extracted_context=resume_active,
    )
    instruction_with_context = instruction
    instruction_segments: dict[str, int] = {"user_instruction": len(instruction)}
    if attachment_context:
        instruction_with_context = f"{instruction}\n\n{attachment_context}"
        instruction_segments["attachment_context"] = len(attachment_context)
    intent_flags = {
        "execution_intent": False,
        "execution_kickoff_intent": False,
        "project_creation_intent": False,
        "workflow_scope": "unknown",
        "execution_mode": "unknown",
        "deploy_requested": False,
        "docker_compose_requested": False,
        "requested_port": None,
        "exact_task_count": None,
        "project_name_provided": False,
        "task_completion_requested": False,
    }
    mandate_text = ""
    if payload.allow_mutations:
        intent_flags = _classify_chat_instruction_intents(
            instruction=instruction,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=payload.session_id,
            actor_user_id=user.id,
        )
        if bool(intent_flags.get("execution_intent")) and str(payload.project_id or "").strip():
            mandate_text = _build_execution_intent_mandate()
            instruction_with_context = f"{instruction_with_context}\n\n{mandate_text}"
            instruction_segments["intent_mandate"] = len(mandate_text)
    usage_metadata: dict[str, object] = {"prompt_instruction_segments": instruction_segments}
    if resume_active:
        # For resumed Codex threads, avoid resending stitched history on every turn.
        # Instead, inject only small fresh deltas from other project chat sessions so stale
        # thread memory can pick up newly introduced facts.
        cross_session_updates = _load_cross_session_recent_updates(
            db=db,
            user=user,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            session_id=payload.session_id,
        )
        already_sent_update_ids_list = _load_sent_cross_session_update_ids(
            db=db,
            user=user,
            workspace_id=payload.workspace_id,
            session_id=payload.session_id,
        )
        already_sent_update_ids = set(already_sent_update_ids_list)
        if already_sent_update_ids_list:
            # Preserve dedupe memory across turns even when there are no new
            # cross-session updates in the current turn.
            usage_metadata["sent_cross_session_update_ids"] = already_sent_update_ids_list[-160:]
        cross_session_updates_filtered = [
            item
            for item in cross_session_updates
            if str(item.get("update_id") or "").strip() not in already_sent_update_ids
        ]
        cross_session_updates_text = _compose_cross_session_updates_text(cross_session_updates_filtered)
        if cross_session_updates_text:
            instruction_segments["cross_session_updates"] = len(cross_session_updates_text)
        if cross_session_updates_filtered:
            combined_ids = [
                *list(already_sent_update_ids),
                *[str(item.get("update_id") or "").strip() for item in cross_session_updates_filtered],
            ]
            deduped_ids: list[str] = []
            seen_ids: set[str] = set()
            for update_id in combined_ids:
                if not update_id or update_id in seen_ids:
                    continue
                seen_ids.add(update_id)
                deduped_ids.append(update_id)
            usage_metadata["sent_cross_session_update_ids"] = deduped_ids[-160:]
        effective_instruction = (
            f"{instruction_with_context}\n\n{cross_session_updates_text}"
            if cross_session_updates_text
            else instruction_with_context
        )
    else:
        effective_instruction = _compose_chat_instruction(instruction_with_context, compacted_history)
        history_stitch_chars = max(0, len(effective_instruction) - len(instruction_with_context))
        if history_stitch_chars > 0:
            instruction_segments["history_stitch"] = history_stitch_chars
    return (
        effective_instruction,
        compacted_history,
        False,
        prepared_attachment_refs,
        prepared_session_attachment_refs,
        intent_flags,
        usage_metadata,
    )


@router.get("/api/agents/codex-auth")
def codex_auth_status(
    user: User = Depends(get_current_user),
):
    return get_codex_auth_status(user.id)


@router.post("/api/agents/codex-auth/device/start")
def codex_auth_device_start(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_codex_auth_manage_allowed(db, user.id)
    try:
        return start_device_auth_session(user.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Failed to start Codex authentication.") from exc


@router.post("/api/agents/codex-auth/device/cancel")
def codex_auth_device_cancel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_codex_auth_manage_allowed(db, user.id)
    return cancel_device_auth_session(user.id)


@router.delete("/api/agents/codex-auth/override")
def codex_auth_override_delete(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_codex_auth_manage_allowed(db, user.id)
    return delete_system_override_auth(user.id)


@router.post("/api/agents/chat")
def agent_chat(
    payload: AgentChatRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    session_id = _resolve_chat_session_id(payload.session_id)
    effective_project_id = _resolve_effective_chat_project_id(
        db=db,
        workspace_id=payload.workspace_id,
        user_id=user.id,
        project_id=payload.project_id,
        session_id=session_id,
        instruction=payload.instruction,
    )
    mcp_servers = _normalize_chat_mcp_servers(
        payload.mcp_servers,
        project_id=effective_project_id,
    )
    if resolve_effective_auth_source() == "none":
        attachment_refs = [item.model_dump() for item in payload.attachment_refs or []]
        session_attachment_refs = [item.model_dump() for item in payload.session_attachment_refs or []]
        ChatApplicationService(
            db,
            user,
            command_id=_command_id_with_suffix(command_id, "chat-user"),
        ).append_user_message(
            AppendUserMessagePayload(
                workspace_id=payload.workspace_id,
                project_id=effective_project_id,
                session_id=session_id,
                message_id=None,
                content=(payload.instruction or "").strip(),
                usage={},
                mcp_servers=mcp_servers,
                attachment_refs=attachment_refs,
                session_attachment_refs=session_attachment_refs,
            )
        )
        response = _build_codex_auth_required_response(session_id=session_id)
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(
                str(response.get("summary") or ""),
                str(response.get("comment") or ""),
            ),
            usage={},
            codex_session_id=None,
        )
        return response
    model, reasoning_effort = _resolve_chat_execution_preferences(payload, user)
    existing_codex_session_id, resume_last_succeeded = _load_chat_session_codex_state(
        db=db,
        workspace_id=payload.workspace_id,
        session_id=session_id,
    )
    payload_with_session = payload.model_copy(update={"session_id": session_id, "project_id": effective_project_id})
    (
        effective_instruction,
        _,
        compact_only,
        prepared_attachment_refs,
        prepared_session_attachment_refs,
        intent_flags,
        chat_usage_metadata,
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
            project_id=effective_project_id,
            session_id=session_id,
            message_id=None,
            content=(payload.instruction or "").strip(),
            usage={"intent_flags": intent_flags},
            mcp_servers=mcp_servers,
            attachment_refs=attachment_refs,
            session_attachment_refs=session_attachment_refs,
        )
    )

    if _should_prompt_for_project_setup_name(intent_flags=intent_flags, project_id=effective_project_id):
        summary = _PROJECT_SETUP_STARTER_NEXT_QUESTION
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=summary,
            usage={},
            codex_session_id=None,
        )
        return {
            "ok": True,
            "action": "comment",
            "summary": summary,
            "comment": None,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

    if compact_only:
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=effective_instruction,
            usage=dict(chat_usage_metadata or {}),
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

    kickoff_result = plugin_api_policy.maybe_dispatch_execution_kickoff(
        db=db,
        user=user,
        workspace_id=payload.workspace_id,
        project_id=effective_project_id,
        intent_flags=intent_flags,
        allow_mutations=bool(payload.allow_mutations),
        command_id=command_id,
        promote_plugin_policy_to_execution_mode_if_needed=_promote_plugin_policy_to_execution_mode_if_needed,
        build_team_lead_kickoff_instruction=_build_team_lead_kickoff_instruction,
        command_id_with_suffix=_command_id_with_suffix,
    )
    if bool(payload.allow_mutations) and str(effective_project_id or "").strip():
        try:
            _sync_plugin_runtime_target_if_needed(
                db=db,
                user=user,
                workspace_id=payload.workspace_id,
                project_id=str(effective_project_id),
                command_id=command_id,
            )
        except Exception:
            logger.exception("Failed to sync plugin runtime deploy target for project %s", effective_project_id)
    if kickoff_result is not None:
        summary = str(kickoff_result.get("summary") or "").strip() or "Team Mode kickoff dispatched."
        comment = str(kickoff_result.get("comment") or "").strip() or None
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(summary, comment),
            usage={},
            codex_session_id=None,
        )
        return {
            "ok": bool(kickoff_result.get("ok")),
            "action": "comment",
            "summary": summary,
            "comment": comment,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={effective_project_id or ''}"
    run_started_at = datetime.now(timezone.utc)
    try:
        outcome = execute_task_automation(
            task_id="",
            title="General Codex Chat",
            description=description,
            status="To do",
            instruction=effective_instruction,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            chat_session_id=session_id,
            codex_session_id=existing_codex_session_id,
            actor_user_id=user.id,
            allow_mutations=bool(payload.allow_mutations),
            mcp_servers=mcp_servers,
            model=model,
            reasoning_effort=reasoning_effort,
            prompt_instruction_segments=(
                chat_usage_metadata.get("prompt_instruction_segments")
                if isinstance(chat_usage_metadata, dict)
                else None
            ),
            timeout_seconds=0,
        )
        ok_by_contract, final_summary, final_comment = _apply_execution_evidence_contract(
            db=db,
            user_id=user.id,
            project_id=effective_project_id,
            execution_intent=bool(intent_flags.get("execution_intent")),
            allow_mutations=bool(payload.allow_mutations),
            run_started_at=run_started_at,
            summary=outcome.summary,
            comment=outcome.comment,
        )
        if bool(payload.allow_mutations) and str(effective_project_id or "").strip():
            try:
                _sync_plugin_runtime_target_if_needed(
                    db=db,
                    user=user,
                    workspace_id=payload.workspace_id,
                    project_id=str(effective_project_id),
                    command_id=command_id,
                )
            except Exception:
                logger.exception("Failed to sync plugin runtime deploy target for project %s", effective_project_id)
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(final_summary, final_comment),
            usage=_build_usage_with_resume_metadata(
                outcome,
                extra_usage=(chat_usage_metadata if isinstance(chat_usage_metadata, dict) else None),
            ),
            codex_session_id=outcome.codex_session_id,
            run_started_at=run_started_at,
        )
        return {
            "ok": bool(ok_by_contract),
            "action": outcome.action,
            "summary": final_summary,
            "comment": final_comment,
            "session_id": session_id,
            "codex_session_id": outcome.codex_session_id,
            "usage": outcome.usage,
            "resume_attempted": bool(outcome.resume_attempted),
            "resume_succeeded": bool(outcome.resume_succeeded),
            "resume_fallback_used": bool(outcome.resume_fallback_used),
        }
    except TimeoutError:
        timeout_summary = _chat_timeout_summary()
        timeout_comment = _build_chat_timeout_comment()
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
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
        mapped_ok, mapped_summary, mapped_comment = _map_chat_exception_to_response(exc)
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(mapped_summary, mapped_comment),
            usage={},
            codex_session_id=None,
            run_started_at=run_started_at,
        )
        return {
            "ok": bool(mapped_ok),
            "action": "comment",
            "summary": mapped_summary,
            "comment": mapped_comment,
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
    session_id = _resolve_chat_session_id(payload.session_id)
    effective_project_id = _resolve_effective_chat_project_id(
        db=db,
        workspace_id=payload.workspace_id,
        user_id=user.id,
        project_id=payload.project_id,
        session_id=session_id,
        instruction=payload.instruction,
    )
    mcp_servers = _normalize_chat_mcp_servers(
        payload.mcp_servers,
        project_id=effective_project_id,
    )
    stream_headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    if resolve_effective_auth_source() == "none":
        attachment_refs = [item.model_dump() for item in payload.attachment_refs or []]
        session_attachment_refs = [item.model_dump() for item in payload.session_attachment_refs or []]
        ChatApplicationService(
            db,
            user,
            command_id=_command_id_with_suffix(command_id, "chat-user"),
        ).append_user_message(
            AppendUserMessagePayload(
                workspace_id=payload.workspace_id,
                project_id=effective_project_id,
                session_id=session_id,
                message_id=None,
                content=(payload.instruction or "").strip(),
                usage={},
                mcp_servers=mcp_servers,
                attachment_refs=attachment_refs,
                session_attachment_refs=session_attachment_refs,
            )
        )
        response = _build_codex_auth_required_response(session_id=session_id)
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(
                str(response.get("summary") or ""),
                str(response.get("comment") or ""),
            ),
            usage={},
            codex_session_id=None,
        )

        def _auth_required_stream():
            yield json.dumps({"type": "final", "response": response}, ensure_ascii=True) + "\n"

        return StreamingResponse(_auth_required_stream(), media_type="application/x-ndjson", headers=stream_headers)
    model, reasoning_effort = _resolve_chat_execution_preferences(payload, user)
    existing_codex_session_id, resume_last_succeeded = _load_chat_session_codex_state(
        db=db,
        workspace_id=payload.workspace_id,
        session_id=session_id,
    )
    payload_with_session = payload.model_copy(update={"session_id": session_id, "project_id": effective_project_id})
    (
        effective_instruction,
        _,
        compact_only,
        prepared_attachment_refs,
        prepared_session_attachment_refs,
        intent_flags,
        chat_usage_metadata,
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
            project_id=effective_project_id,
            session_id=session_id,
            message_id=None,
            content=(payload.instruction or "").strip(),
            usage={"intent_flags": intent_flags},
            mcp_servers=mcp_servers,
            attachment_refs=attachment_refs,
            session_attachment_refs=session_attachment_refs,
        )
    )

    if _should_prompt_for_project_setup_name(intent_flags=intent_flags, project_id=effective_project_id):
        summary = _PROJECT_SETUP_STARTER_NEXT_QUESTION
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=summary,
            usage={},
            codex_session_id=None,
        )
        starter_response = {
            "ok": True,
            "action": "comment",
            "summary": summary,
            "comment": None,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

        def _starter_stream():
            yield json.dumps({"type": "final", "response": starter_response}, ensure_ascii=True) + "\n"

        return StreamingResponse(_starter_stream(), media_type="application/x-ndjson", headers=stream_headers)

    if compact_only:
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=effective_instruction,
            usage=dict(chat_usage_metadata or {}),
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

        return StreamingResponse(_compact_stream(), media_type="application/x-ndjson", headers=stream_headers)

    kickoff_result = plugin_api_policy.maybe_dispatch_execution_kickoff(
        db=db,
        user=user,
        workspace_id=payload.workspace_id,
        project_id=effective_project_id,
        intent_flags=intent_flags,
        allow_mutations=bool(payload.allow_mutations),
        command_id=command_id,
        promote_plugin_policy_to_execution_mode_if_needed=_promote_plugin_policy_to_execution_mode_if_needed,
        build_team_lead_kickoff_instruction=_build_team_lead_kickoff_instruction,
        command_id_with_suffix=_command_id_with_suffix,
    )
    if kickoff_result is not None:
        summary = str(kickoff_result.get("summary") or "").strip() or "Team Mode kickoff dispatched."
        comment = str(kickoff_result.get("comment") or "").strip() or None
        _persist_assistant_message_with_links(
            db=db,
            user=user,
            command_id=command_id,
            workspace_id=payload.workspace_id,
            project_id=effective_project_id,
            session_id=session_id,
            mcp_servers=mcp_servers,
            content=_assistant_text(summary, comment),
            usage={},
            codex_session_id=None,
        )
        kickoff_response = {
            "ok": bool(kickoff_result.get("ok")),
            "action": "comment",
            "summary": summary,
            "comment": comment,
            "session_id": session_id,
            "codex_session_id": None,
            "usage": None,
            "resume_attempted": False,
            "resume_succeeded": False,
            "resume_fallback_used": False,
        }

        def _kickoff_stream():
            yield json.dumps({"type": "final", "response": kickoff_response}, ensure_ascii=True) + "\n"

        return StreamingResponse(_kickoff_stream(), media_type="application/x-ndjson", headers=stream_headers)

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={effective_project_id or ''}"
    run_started_at = datetime.now(timezone.utc)
    stream_key = _chat_stream_key(workspace_id=payload.workspace_id, session_id=session_id)
    run_id = _create_chat_stream_run(
        stream_key=stream_key,
        preferred_run_id=str(command_id or "").strip() or None,
    )
    _set_chat_stream_stop_requested(stream_key=stream_key, value=False)
    cancel_event = _register_chat_stream_cancel_event(stream_key=stream_key, run_id=run_id)

    def _stream() -> object:
        subscriber_queue, replay_events, _ = _subscribe_chat_stream_run(
            stream_key=stream_key,
            run_id=run_id,
            since_seq=0,
        )
        done_event = threading.Event()
        outcome_holder: dict[str, object] = {}
        error_holder: dict[str, Exception] = {}
        finalize_lock = threading.Lock()
        finalized_response: dict[str, object] = {}
        streamed_assistant_text_parts: list[str] = []
        streamed_parts_lock = threading.Lock()

        _publish_chat_stream_event(
            stream_key=stream_key,
            event={"type": "stream_run", "run_id": run_id},
        )
        _publish_chat_stream_event(
            stream_key=stream_key,
            event={"type": "status", "message": "Codex started processing the request."},
        )

        def _on_event(event: dict[str, object]) -> None:
            if cancel_event.is_set() or _is_chat_stream_stop_requested(stream_key=stream_key):
                return
            item_type = str(event.get("type") or "").strip().lower()
            if item_type == "assistant_text":
                delta = str(event.get("delta") or "")
                if delta:
                    with streamed_parts_lock:
                        streamed_assistant_text_parts.append(delta)
            _publish_chat_stream_event(stream_key=stream_key, event=dict(event))

        def _worker() -> None:
            try:
                outcome = execute_task_automation_stream(
                    task_id="",
                    title="General Codex Chat",
                    description=description,
                    status="To do",
                    instruction=effective_instruction,
                    workspace_id=payload.workspace_id,
                    project_id=effective_project_id,
                    chat_session_id=session_id,
                    codex_session_id=existing_codex_session_id,
                    actor_user_id=user.id,
                    allow_mutations=bool(payload.allow_mutations),
                    mcp_servers=mcp_servers,
                    on_event=_on_event,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    prompt_instruction_segments=(
                        chat_usage_metadata.get("prompt_instruction_segments")
                        if isinstance(chat_usage_metadata, dict)
                        else None
                    ),
                    timeout_seconds=0,
                    stream_plain_text=True,
                    cancel_event=cancel_event,
                )
                outcome_holder["value"] = outcome
            except TimeoutError:
                error_holder["value"] = TimeoutError(_chat_timeout_summary())
            except Exception as exc:
                logger.exception("Agent chat stream worker failed.")
                error_holder["value"] = exc
            finally:
                done_event.set()

        def _finalize_once() -> dict[str, object]:
            with finalize_lock:
                existing = finalized_response.get("value")
                if isinstance(existing, dict):
                    return existing

                if "value" in error_holder:
                    exc = error_holder["value"]
                    if isinstance(exc, TimeoutError):
                        response = {
                            "ok": False,
                            "action": "comment",
                            "summary": _chat_timeout_summary(),
                            "comment": _build_chat_timeout_comment(),
                            "session_id": session_id,
                            "codex_session_id": None,
                            "usage": None,
                            "resume_attempted": False,
                            "resume_succeeded": False,
                            "resume_fallback_used": False,
                        }
                    else:
                        mapped_ok, mapped_summary, mapped_comment = _map_chat_exception_to_response(exc)
                        response = {
                            "ok": bool(mapped_ok),
                            "action": "comment",
                            "summary": mapped_summary,
                            "comment": mapped_comment,
                            "session_id": session_id,
                            "codex_session_id": None,
                            "usage": None,
                            "resume_attempted": False,
                            "resume_succeeded": False,
                            "resume_fallback_used": False,
                            "_force_summary_only": bool(mapped_ok and mapped_comment is None),
                        }
                else:
                    outcome = outcome_holder.get("value")
                    if outcome is None:
                        response = {
                            "ok": False,
                            "action": "comment",
                            "summary": _build_chat_error_summary(),
                            "comment": "Missing automation outcome.",
                            "session_id": session_id,
                            "codex_session_id": None,
                            "usage": None,
                            "resume_attempted": False,
                            "resume_succeeded": False,
                            "resume_fallback_used": False,
                        }
                    else:
                        outcome_obj = outcome  # type: ignore[assignment]
                        response = {
                            "ok": True,
                            "action": getattr(outcome_obj, "action", "comment"),
                            "summary": getattr(outcome_obj, "summary", ""),
                            "comment": getattr(outcome_obj, "comment", ""),
                            "session_id": session_id,
                            "codex_session_id": getattr(outcome_obj, "codex_session_id", None),
                            "usage": getattr(outcome_obj, "usage", None),
                            "resume_attempted": bool(getattr(outcome_obj, "resume_attempted", False)),
                            "resume_succeeded": bool(getattr(outcome_obj, "resume_succeeded", False)),
                            "resume_fallback_used": bool(getattr(outcome_obj, "resume_fallback_used", False)),
                        }

                if cancel_event.is_set() or _is_chat_stream_stop_requested(stream_key=stream_key):
                    response = {
                        "ok": True,
                        "action": "comment",
                        "summary": "Stopped.",
                        "comment": "Run cancelled by user.",
                        "session_id": session_id,
                        "codex_session_id": None,
                        "usage": None,
                        "resume_attempted": False,
                        "resume_succeeded": False,
                        "resume_fallback_used": False,
                    }

                if isinstance(chat_usage_metadata, dict):
                    merged_usage = {
                        **(response.get("usage") if isinstance(response.get("usage"), dict) else {}),
                        **chat_usage_metadata,
                    }
                    response["usage"] = merged_usage

                ok_by_contract, final_summary, final_comment = _apply_execution_evidence_contract(
                    db=db,
                    user_id=user.id,
                    project_id=effective_project_id,
                    execution_intent=bool(intent_flags.get("execution_intent")),
                    allow_mutations=bool(payload.allow_mutations),
                    run_started_at=run_started_at,
                    summary=str(response.get("summary") or ""),
                    comment=str(response.get("comment") or "") or None,
                )
                response["ok"] = bool(ok_by_contract) and bool(response.get("ok"))
                response["summary"] = final_summary
                response["comment"] = final_comment

                with streamed_parts_lock:
                    assistant_content = "".join(streamed_assistant_text_parts).strip()
                if bool(response.get("_force_summary_only")):
                    assistant_content = str(response.get("summary") or "").strip()
                if assistant_content and not bool(response.get("ok")):
                    assistant_content = _assistant_text(
                        assistant_content,
                        _assistant_text(final_summary, str(final_comment or "")),
                    )
                elif not assistant_content:
                    assistant_content = _assistant_text(
                        final_summary,
                        str(final_comment or ""),
                    )

                _persist_assistant_message_with_links(
                    db=db,
                    user=user,
                    command_id=command_id,
                    workspace_id=payload.workspace_id,
                    project_id=effective_project_id,
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

                _publish_chat_stream_event(
                    stream_key=stream_key,
                    event={"type": "final", "response": response},
                )
                _finish_chat_stream_run(stream_key=stream_key)
                _clear_chat_stream_cancel_event(stream_key=stream_key, run_id=run_id)
                _set_chat_stream_stop_requested(stream_key=stream_key, value=False)
                response.pop("_force_summary_only", None)
                finalized_response["value"] = response
                return response

        def _background_finalize() -> None:
            done_event.wait()
            _finalize_once()

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        finalizer = threading.Thread(target=_background_finalize, daemon=True)
        finalizer.start()

        try:
            saw_final = False
            for event in replay_events:
                yield json.dumps(event, ensure_ascii=True) + "\n"
                if str(event.get("type") or "").strip().lower() == "final":
                    saw_final = True
            while True:
                try:
                    event = subscriber_queue.get(timeout=0.25)
                except queue.Empty:
                    if done_event.is_set():
                        break
                    continue
                if not isinstance(event, dict):
                    continue
                yield json.dumps(event, ensure_ascii=True) + "\n"
                if str(event.get("type") or "").strip().lower() == "final":
                    saw_final = True
                    break
            response = _finalize_once()
            if not saw_final and bool(response):
                yield json.dumps({"type": "final", "response": response}, ensure_ascii=True) + "\n"
        finally:
            _unsubscribe_chat_stream_run(stream_key=stream_key, subscriber_queue=subscriber_queue)
            if done_event.is_set():
                _clear_chat_stream_cancel_event(stream_key=stream_key, run_id=run_id)
                _set_chat_stream_stop_requested(stream_key=stream_key, value=False)

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers=stream_headers)


@router.get("/api/agents/chat/stream")
def resume_agent_chat_stream(
    workspace_id: str,
    session_id: str,
    run_id: str,
    since_seq: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    normalized_session_id = _resolve_chat_session_id(session_id)
    stream_key = _chat_stream_key(workspace_id=workspace_id, session_id=normalized_session_id)
    subscriber_queue, replay_events, done = _subscribe_chat_stream_run(
        stream_key=stream_key,
        run_id=run_id,
        since_seq=since_seq,
    )
    if not replay_events and done:
        raise HTTPException(status_code=404, detail="Chat stream run is not available")

    headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    }

    def _stream():
        try:
            for event in replay_events:
                yield json.dumps(event, ensure_ascii=True) + "\n"
            if done:
                return
            while True:
                try:
                    event = subscriber_queue.get(timeout=0.5)
                except queue.Empty:
                    broker = _CHAT_STREAM_BROKER.current_state(key=stream_key)
                    if not isinstance(broker, dict):
                        break
                    if str(broker.get("run_id") or "").strip() != str(run_id).strip():
                        break
                    if bool(broker.get("done")):
                        break
                    continue
                if not isinstance(event, dict):
                    continue
                yield json.dumps(event, ensure_ascii=True) + "\n"
                if str(event.get("type") or "").strip().lower() == "final":
                    break
        finally:
            _unsubscribe_chat_stream_run(stream_key=stream_key, subscriber_queue=subscriber_queue)

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers=headers)


@router.post("/api/agents/chat/stop")
def stop_agent_chat_stream(
    payload: dict[str, object] = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    workspace_id = str(payload.get("workspace_id") or "").strip()
    session_id = str(payload.get("session_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if not workspace_id or not session_id:
        raise HTTPException(status_code=400, detail="workspace_id and session_id are required")
    ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    stream_key = _chat_stream_key(workspace_id=workspace_id, session_id=_resolve_chat_session_id(session_id))
    _set_chat_stream_stop_requested(stream_key=stream_key, value=True)
    effective_run_id = run_id
    if not effective_run_id:
        state = _CHAT_STREAM_BROKER.current_state(key=stream_key)
        if isinstance(state, dict):
            effective_run_id = str(state.get("run_id") or "").strip()
    cancelled = _request_chat_stream_cancel(stream_key=stream_key, run_id=effective_run_id)
    if cancelled:
        _publish_chat_stream_event(
            stream_key=stream_key,
            event={"type": "status", "message": "Stop requested."},
        )
    return {"ok": True, "cancel_requested": bool(cancelled), "run_id": effective_run_id}
