from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.core import AgentChatRun, User, ensure_project_access, ensure_role, get_current_user, get_db
from shared.settings import (
    ATTACHMENTS_DIR,
    AGENT_CHAT_HISTORY_COMPACT_THRESHOLD,
    AGENT_CHAT_HISTORY_RECENT_TAIL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)

from .executor import execute_task_automation

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
) -> str:
    refs = payload.attachment_refs or []
    if not refs:
        return ""

    lines: list[str] = []
    total_chars = 0
    for index, ref in enumerate(refs[:_MAX_CHAT_ATTACHMENT_FILES], start=1):
        path = str(ref.path or "").strip()
        if not path:
            continue
        candidate = _resolve_attachment_candidate(payload.workspace_id, path)
        project_id = _project_id_from_path(path)
        if project_id:
            ensure_project_access(db, payload.workspace_id, project_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        if payload.project_id and project_id and project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="Attachment project mismatch with selected chat project")
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Attachment not found: {path}")

        display_name = str(ref.name or Path(path).name or f"attachment-{index}").strip()
        mime_type = str(ref.mime_type or "").strip() or mimetypes.guess_type(display_name)[0] or ""

        lines.append(f"Attachment {index}: {display_name}")
        lines.append(f"Path: {path}")
        lines.append(f"MIME type: {mime_type or 'unknown'}")

        remaining_chars = _MAX_CHAT_ATTACHMENT_CHARS_TOTAL - total_chars
        if remaining_chars <= 0:
            lines.append("Content: omitted (chat attachment context limit reached).")
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
            lines.append("Content:")
            lines.append(snippet)
            if truncated:
                lines.append("[truncated]")
            total_chars += len(snippet)
        else:
            lines.append(status_message or "Content: omitted (empty or unreadable file).")
        lines.append("")

    if not lines:
        return ""
    return "Attached file context:\n" + "\n".join(lines).rstrip()


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


def _parse_compact_command(instruction: str) -> tuple[bool, str]:
    raw = str(instruction or "").strip()
    if not raw:
        return False, ""
    marker = "/compact"
    if not raw.lower().startswith(marker):
        return False, raw
    remainder = raw[len(marker):].strip()
    return True, remainder


def _compact_history_with_codex(*, history: list[dict[str, str]], workspace_id: str, project_id: str | None) -> str | None:
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
    force: bool = False,
) -> tuple[list[dict[str, str]], bool]:
    threshold = max(0, int(AGENT_CHAT_HISTORY_COMPACT_THRESHOLD))
    should_compact = force or (threshold > 0 and len(history) > threshold)
    if not should_compact:
        return history, False
    try:
        compacted = _compact_history_with_codex(history=history, workspace_id=workspace_id, project_id=project_id)
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


@router.post("/api/agents/chat")
def agent_chat(
    payload: AgentChatRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    raw_instruction = (payload.instruction or "").strip()
    force_compact, instruction = _parse_compact_command(raw_instruction)
    if not raw_instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    history = _normalize_history(payload.history or [])
    # Frontend includes the current user turn in `history`; when using /compact, avoid
    # compacting the command text itself.
    if force_compact and history and history[-1]["role"] == "user" and history[-1]["content"] == raw_instruction:
        history = history[:-1]
    compacted_history, compacted_applied = _maybe_compact_history(
        history=history,
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        force=force_compact,
    )
    if force_compact and not instruction:
        if not history:
            summary = "No chat history to compact."
        elif compacted_applied:
            summary = "Chat history compacted."
        else:
            summary = "Chat history compaction skipped."
        return {
            "ok": True,
            "action": "comment",
            "summary": summary,
            "comment": None,
            "session_id": payload.session_id,
            "usage": None,
        }
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    attachment_context = _build_attachment_context(payload=payload, db=db, user=user)
    instruction_with_context = instruction
    if attachment_context:
        instruction_with_context = f"{instruction}\n\n{attachment_context}"
    effective_instruction = _compose_chat_instruction(instruction_with_context, compacted_history)

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={payload.project_id or ''}"
    try:
        outcome = execute_task_automation(
            task_id="",
            title="General Codex Chat",
            description=description,
            status="To do",
            instruction=effective_instruction,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            allow_mutations=bool(payload.allow_mutations),
        )
        return {
            "ok": True,
            "action": outcome.action,
            "summary": outcome.summary,
            "comment": outcome.comment,
            "session_id": payload.session_id,
            "usage": outcome.usage,
        }
    except TimeoutError:
        return {
            "ok": False,
            "action": "comment",
            "summary": f"Codex timed out after {AGENT_EXECUTOR_TIMEOUT_SECONDS:.0f}s.",
            "comment": "Try a narrower request (e.g. one project at a time) or run again.",
            "session_id": payload.session_id,
            "usage": None,
        }
    except Exception as exc:
        # Avoid bubbling internal exceptions to the client as 500 errors.
        msg = str(exc)
        return {
            "ok": False,
            "action": "comment",
            "summary": "Codex failed to complete the request.",
            "comment": msg[:500],
            "session_id": payload.session_id,
            "usage": None,
        }
