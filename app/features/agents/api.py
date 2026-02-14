from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.core import AgentChatRun, User, ensure_role, get_current_user, get_db

from .executor import execute_task_automation

router = APIRouter()


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


@router.post("/api/agents/chat")
def agent_chat(
    payload: AgentChatRun,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_role(db, payload.workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    instruction = (payload.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    effective_instruction = _compose_chat_instruction(instruction, payload.history or [])

    description = f"General Codex chat context. workspace_id={payload.workspace_id}; project_id={payload.project_id or ''}"
    outcome = execute_task_automation(
        task_id="",
        title="General Codex Chat",
        description=description,
        status="To do",
        instruction=effective_instruction,
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        allow_mutations=payload.allow_mutations,
    )
    return {
        "ok": True,
        "action": outcome.action,
        "summary": outcome.summary,
        "comment": outcome.comment,
        "session_id": payload.session_id,
    }
