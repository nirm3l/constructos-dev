from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

from sqlalchemy import select

from shared.knowledge_graph import build_graph_context_markdown, build_graph_context_pack
from shared.models import Project, ProjectRule, SessionLocal
from shared.settings import AGENT_CODEX_COMMAND, AGENT_EXECUTOR_MODE, AGENT_EXECUTOR_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class AutomationOutcome:
    action: str
    summary: str
    comment: str | None = None
    usage: dict[str, int] | None = None


def _graph_summary_to_markdown(summary: dict[str, object] | None) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    lines: list[str] = []
    executive = str(summary.get("executive") or "").strip()
    if executive:
        lines.append("# Grounded Summary")
        lines.append("")
        lines.append(executive)
    key_points = summary.get("key_points")
    if isinstance(key_points, list) and key_points:
        if lines:
            lines.append("")
        lines.append("## Key Points")
        for item in key_points:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            evidence_ids = [str(raw).strip() for raw in (item.get("evidence_ids") or []) if str(raw).strip()]
            if not claim:
                continue
            suffix = f" [{', '.join(evidence_ids)}]" if evidence_ids else ""
            lines.append(f"- {claim}{suffix}")
    gaps = summary.get("gaps")
    if isinstance(gaps, list) and gaps:
        if lines:
            lines.append("")
        lines.append("## Gaps")
        for gap in gaps:
            text = str(gap or "").strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines).strip()


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
    usage_raw = payload.get("usage")
    usage: dict[str, int] | None = None
    if isinstance(usage_raw, dict):
        usage = {}
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "context_limit_tokens"):
            raw_value = usage_raw.get(key)
            if raw_value is None:
                continue
            try:
                usage[key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                continue
        if not usage:
            usage = None
    if action not in {"complete", "comment"}:
        raise RuntimeError('Executor JSON must include "action": "complete" or "comment"')
    if not summary:
        summary = "Automation run finished."
    if comment is not None:
        comment = str(comment)
    return AutomationOutcome(action=action, summary=summary, comment=comment, usage=usage)


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
    graph_context_pack = build_graph_context_pack(
        project_id=project_id,
        focus_entity_type="Task" if str(task_id or "").strip() else None,
        focus_entity_id=task_id if str(task_id or "").strip() else None,
    )
    graph_context_markdown = str(graph_context_pack.get("markdown") or "").strip() if graph_context_pack else ""
    if not graph_context_markdown:
        graph_context_markdown = build_graph_context_markdown(
            project_id=project_id,
            focus_entity_type="Task" if str(task_id or "").strip() else None,
            focus_entity_id=task_id if str(task_id or "").strip() else None,
        )
    graph_evidence_json = json.dumps(graph_context_pack.get("evidence") or [], ensure_ascii=True) if graph_context_pack else "[]"
    graph_summary_markdown = _graph_summary_to_markdown(graph_context_pack.get("summary")) if graph_context_pack else ""
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
        "graph_evidence_json": graph_evidence_json,
        "graph_summary_markdown": graph_summary_markdown,
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
