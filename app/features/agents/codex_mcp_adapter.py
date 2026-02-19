from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from shared.settings import (
    AGENT_CHAT_CONTEXT_LIMIT_TOKENS,
    AGENT_CODEX_MCP_URL,
    AGENT_CODEX_MODEL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)


def _build_prompt(ctx: dict) -> str:
    task_id = ctx.get("task_id")
    title = ctx.get("title", "")
    description = ctx.get("description", "")
    status = ctx.get("status", "")
    instruction = ctx.get("instruction", "")
    workspace_id = ctx.get("workspace_id") or ""
    project_id = ctx.get("project_id") or ""
    project_name = ctx.get("project_name") or ""
    project_description = str(ctx.get("project_description") or "")
    project_rules = ctx.get("project_rules") or []
    graph_context_markdown = str(ctx.get("graph_context_markdown") or "").strip()
    graph_evidence_json = str(ctx.get("graph_evidence_json") or "").strip()
    graph_summary_markdown = str(ctx.get("graph_summary_markdown") or "").strip()
    allow_mutations = bool(ctx.get("allow_mutations", True))
    soul_md = project_description.strip() or "_(empty)_"
    graph_md = graph_context_markdown or "_(knowledge graph unavailable)_"
    graph_evidence = graph_evidence_json or "[]"
    graph_summary = graph_summary_markdown or "_(summary unavailable)_"
    rules_md_lines: list[str] = []
    for item in project_rules:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title and not body:
            continue
        label = title or "Untitled rule"
        if body:
            rules_md_lines.append(f"- {label}: {body}")
        else:
            rules_md_lines.append(f"- {label}")
    rules_md = "\n".join(rules_md_lines) if rules_md_lines else "_(no project rules)_"
    has_task_context = bool(str(task_id or "").strip())
    context_guidance = (
        "- First call MCP tool get_task(task_id) to validate current task data.\n"
        if has_task_context
        else "- This is a general chat request (not bound to a single task). Use workspace/project context and MCP tools as needed.\n"
    )
    mutation_policy = (
        "- Mutating tools are allowed for this request.\n"
        "- Apply requested changes via MCP tools directly when possible.\n"
        if allow_mutations
        else "- Mutating tools are NOT allowed for this request.\n"
        "- Do not create/update/delete/archive/complete entities.\n"
        "- Do not call mutating MCP tools; produce analysis/summary only.\n"
    )
    return (
        "You are an automation agent for task management.\n"
        "Use available MCP tools to satisfy the instruction.\n"
        "Return ONLY JSON matching the schema.\n\n"
        f"Task ID: {task_id}\n"
        f"Title: {title}\n"
        f"Status: {status}\n"
        f"Description: {description}\n"
        f"Workspace ID: {workspace_id}\n"
        f"Project ID: {project_id}\n"
        f"Project Name: {project_name}\n"
        f"Instruction: {instruction}\n\n"
        "Context Pack:\n"
        "File: Soul.md (source: project.description)\n"
        f"{soul_md}\n\n"
        "File: ProjectRules.md (source: project_rules)\n"
        f"{rules_md}\n\n"
        "File: GraphContext.md (source: knowledge_graph)\n"
        f"{graph_md}\n\n"
        "File: GraphEvidence.json (source: knowledge_graph.evidence)\n"
        f"{graph_evidence}\n\n"
        "File: GraphSummary.md (source: knowledge_graph.summary)\n"
        f"{graph_summary}\n\n"
        "Guidance:\n"
        f"{context_guidance}"
        "- Treat Soul.md, ProjectRules.md, GraphContext.md, GraphEvidence.json, and GraphSummary.md as durable project-level context.\n"
        "- ProjectRules.md defines how you should behave within this project.\n"
        "- GraphContext.md captures resource relations and should guide dependency-aware decisions.\n"
        "- GraphEvidence.json is the canonical evidence source for grounded claims.\n"
        "- GraphSummary.md can be used as a concise overview, but validate against GraphEvidence.json before acting.\n"
        "- Treat claims without an evidence_id as low confidence.\n"
        "- If project context conflicts with the latest explicit user instruction, follow the latest explicit user instruction.\n"
        "- You may call task-management MCP tools relevant to the request.\n"
        "- Use graph_* MCP tools when you need relation-aware lookup across project resources.\n"
        "- Prefer bulk tools when operating on many tasks (avoid per-task loops when possible).\n"
        "- Prefer archive_all_notes/archive_all_tasks for 'archive everything' requests.\n"
        "- For mutating MCP tool calls, always provide command_id.\n"
        "- If retrying the same mutation, reuse the exact same command_id.\n"
        "- If the user asks for a plan/spec/design doc, prefer creating a Note (Markdown) via MCP tools so it is visible in the UI.\n"
        "- When creating a plan note: use a clear title starting with 'Plan:' and include actionable steps.\n"
        "- If you are in task context, link the note to the task by setting task_id when creating the note.\n"
        "- When mentioning created/updated entities in summary/comment, include clickable Markdown links (not raw IDs).\n"
        "- Never return generic phrases like 'otvori task' or 'open note' without a concrete link target.\n"
        "- For each created entity, include at least one explicit link that can be clicked in chat.\n"
        "- Link format in this app:\n"
        "  - Note: ?tab=notes&project=<project_id>&note=<note_id>\n"
        "  - Task: ?tab=tasks&project=<project_id>&task=<task_id>\n"
        "  - Specification: ?tab=specifications&project=<project_id>&specification=<specification_id>\n"
        "  - Project: ?tab=projects&project=<project_id>\n"
        f"{mutation_policy}"
        "- For recurring schedules, set task.recurring_rule explicitly using canonical format: every:<number><m|h|d> (example: every:1m).\n"
        "- After scheduling changes, verify by reading the task and confirming scheduled_at_utc + recurring_rule values.\n"
        "- Return action=complete only if this task should be completed; otherwise return action=comment.\n"
        "- summary must state what was actually done.\n"
        "- comment should be concise and optional; use null when no extra runner comment is needed.\n"
    )


def _safe_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _extract_turn_usage(stdout: str) -> dict[str, int] | None:
    usage_raw: dict | None = None
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") != "turn.completed":
            continue
        maybe_usage = event.get("usage")
        if isinstance(maybe_usage, dict):
            usage_raw = maybe_usage
    if usage_raw is None:
        return None
    input_tokens = _safe_non_negative_int(usage_raw.get("input_tokens")) or 0
    cached_input_tokens = _safe_non_negative_int(usage_raw.get("cached_input_tokens")) or 0
    output_tokens = _safe_non_negative_int(usage_raw.get("output_tokens")) or 0
    usage = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
    }
    if AGENT_CHAT_CONTEXT_LIMIT_TOKENS > 0:
        usage["context_limit_tokens"] = int(AGENT_CHAT_CONTEXT_LIMIT_TOKENS)
    return usage


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"action": "comment", "summary": "No input context.", "comment": "No task context received."}))
        return 0

    ctx = json.loads(raw)
    prompt = _build_prompt(ctx)
    mcp_url = AGENT_CODEX_MCP_URL
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["complete", "comment"]},
            "summary": {"type": "string"},
            "comment": {"type": ["string", "null"]},
        },
        "required": ["action", "summary", "comment"],
        "additionalProperties": False,
    }

    with tempfile.TemporaryDirectory() as td:
        schema_path = os.path.join(td, "schema.json")
        output_path = os.path.join(td, "last_message.json")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f)

        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--output-schema",
            schema_path,
            "--output-last-message",
            output_path,
            "-c",
            f'mcp_servers.task_management_tools.url="{mcp_url}"',
        ]
        if AGENT_CODEX_MODEL:
            cmd.extend(["-m", AGENT_CODEX_MODEL])
        cmd.append(prompt)

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=AGENT_EXECUTOR_TIMEOUT_SECONDS,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"codex exec failed (exit={proc.returncode}): {err[:600]}")
        usage = _extract_turn_usage(proc.stdout or "")

        with open(output_path, "r", encoding="utf-8") as f:
            out = json.loads(f.read().strip() or "{}")

    action = str(out.get("action", "")).strip().lower()
    summary = str(out.get("summary", "")).strip()
    comment = out.get("comment")
    if action not in {"complete", "comment"}:
        raise RuntimeError("codex adapter received invalid action")
    if not summary:
        summary = "Codex execution completed."
    if comment is not None:
        comment = str(comment)
    print(json.dumps({"action": action, "summary": summary, "comment": comment, "usage": usage}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
