from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

from sqlalchemy import select

from shared.knowledge_graph import build_graph_context_markdown
from shared.models import Project, ProjectRule, SessionLocal
from shared.settings import AGENT_CODEX_COMMAND, AGENT_EXECUTOR_MODE, AGENT_EXECUTOR_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class AutomationOutcome:
    action: str
    summary: str
    comment: str | None = None


def _load_project_context(project_id: str | None) -> tuple[str | None, str, list[dict[str, str]]]:
    if not project_id:
        return None, "", []
    with SessionLocal() as db:
        row = db.execute(
            select(Project.name, Project.description).where(Project.id == project_id, Project.is_deleted == False)
        ).first()
        rules = db.execute(
            select(ProjectRule.title, ProjectRule.body)
            .where(ProjectRule.project_id == project_id, ProjectRule.is_deleted == False)
            .order_by(ProjectRule.updated_at.desc())
        ).all()
    if not row:
        return None, "", []
    normalized_rules = [
        {
            "title": str(item[0] or "").strip(),
            "body": str(item[1] or ""),
        }
        for item in rules
    ]
    return str(row[0] or "").strip() or None, str(row[1] or ""), normalized_rules


def _placeholder_outcome(*, instruction: str, current_status: str) -> AutomationOutcome:
    lower_instruction = instruction.lower()
    should_complete = any(token in lower_instruction for token in ("#complete", "complete task", "mark done"))
    if should_complete and current_status != "Done":
        return AutomationOutcome(action="complete", summary="Automation runner marked task as completed.")
    comment = "Codex runner: request accepted, leaving progress note."
    if instruction:
        comment += f"\nInstruction: {instruction}"
    return AutomationOutcome(action="comment", summary="Automation runner left a task comment.", comment=comment)


def _parse_command_outcome(stdout: str) -> AutomationOutcome:
    text = (stdout or "").strip()
    if not text:
        raise RuntimeError("Executor returned empty output")
    try:
        payload = json.loads(text.splitlines()[-1])
    except Exception as exc:
        raise RuntimeError(f"Executor output is not valid JSON: {text[:200]}") from exc

    action = str(payload.get("action", "")).strip().lower()
    summary = str(payload.get("summary", "")).strip()
    comment = payload.get("comment")
    if action not in {"complete", "comment"}:
        raise RuntimeError('Executor JSON must include "action": "complete" or "comment"')
    if not summary:
        summary = "Automation run finished."
    if comment is not None:
        comment = str(comment)
    return AutomationOutcome(action=action, summary=summary, comment=comment)


def execute_task_automation(
    *,
    task_id: str,
    title: str,
    description: str,
    status: str,
    instruction: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    allow_mutations: bool = True,
) -> AutomationOutcome:
    # Deterministic shortcut: users can explicitly complete a task via "#complete".
    # This should work regardless of executor mode, and avoids reliance on the LLM for a simple directive.
    lower_instruction = (instruction or "").lower()
    should_complete = any(token in lower_instruction for token in ("#complete", "complete task", "mark done"))
    if str(task_id or "").strip() and should_complete and status != "Done" and allow_mutations:
        return AutomationOutcome(action="complete", summary="Automation runner marked task as completed.")

    if AGENT_EXECUTOR_MODE != "command":
        return _placeholder_outcome(instruction=instruction, current_status=status)
    if not AGENT_CODEX_COMMAND:
        raise RuntimeError("AGENT_EXECUTOR_MODE=command requires AGENT_CODEX_COMMAND")

    command = shlex.split(AGENT_CODEX_COMMAND)
    project_name, project_description, project_rules = _load_project_context(project_id)
    graph_context_markdown = build_graph_context_markdown(
        project_id=project_id,
        focus_entity_type="Task" if str(task_id or "").strip() else None,
        focus_entity_id=task_id if str(task_id or "").strip() else None,
    )
    context = {
        "task_id": task_id,
        "title": title,
        "description": description,
        "status": status,
        "instruction": instruction,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "project_name": project_name,
        "project_description": project_description,
        "project_rules": project_rules,
        "graph_context_markdown": graph_context_markdown,
        "allow_mutations": allow_mutations,
    }
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(context),
            text=True,
            capture_output=True,
            timeout=AGENT_EXECUTOR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Executor timed out after {AGENT_EXECUTOR_TIMEOUT_SECONDS:.1f}s") from exc

    if proc.returncode != 0:
        err_text = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Executor failed (exit={proc.returncode}): {err_text[:300]}")
    return _parse_command_outcome(proc.stdout)
