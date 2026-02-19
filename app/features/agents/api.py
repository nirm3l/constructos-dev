from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.core import AgentChatRun, User, ensure_role, get_current_user, get_db
from shared.settings import (
    AGENT_CHAT_HISTORY_COMPACT_THRESHOLD,
    AGENT_CHAT_HISTORY_RECENT_TAIL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)

from .executor import execute_task_automation

router = APIRouter()
logger = logging.getLogger(__name__)


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
    effective_instruction = _compose_chat_instruction(instruction, compacted_history)

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
