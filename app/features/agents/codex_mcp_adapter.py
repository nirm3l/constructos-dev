from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from shared.settings import AGENT_CODEX_MCP_READONLY_URL, AGENT_CODEX_MCP_URL, AGENT_CODEX_MODEL, AGENT_EXECUTOR_TIMEOUT_SECONDS


def _build_prompt(ctx: dict) -> str:
    task_id = ctx.get("task_id")
    title = ctx.get("title", "")
    description = ctx.get("description", "")
    status = ctx.get("status", "")
    instruction = ctx.get("instruction", "")
    workspace_id = ctx.get("workspace_id") or ""
    project_id = ctx.get("project_id") or ""
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mutation_guidance = (
        "- Mutating tools are allowed for this request.\n"
        if allow_mutations
        else "- This request is read-only. Do not call mutating tools.\n"
    )
    has_task_context = bool(str(task_id or "").strip())
    context_guidance = (
        "- First call MCP tool get_task(task_id) to validate current task data.\n"
        if has_task_context
        else "- This is a general chat request (not bound to a single task). Use workspace/project context and MCP tools as needed.\n"
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
        f"Instruction: {instruction}\n\n"
        "Guidance:\n"
        f"{context_guidance}"
        "- You may call task-management MCP tools relevant to the request.\n"
        f"{mutation_guidance}"
        "- Apply requested changes via MCP tools directly when possible.\n"
        "- Return action=complete only if this task should be completed; otherwise return action=comment.\n"
        "- summary must state what was actually done.\n"
        "- comment should be concise and optional; use null when no extra runner comment is needed.\n"
    )


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"action": "comment", "summary": "No input context.", "comment": "No task context received."}))
        return 0

    ctx = json.loads(raw)
    prompt = _build_prompt(ctx)
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mcp_url = AGENT_CODEX_MCP_URL if allow_mutations else AGENT_CODEX_MCP_READONLY_URL
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
    print(json.dumps({"action": action, "summary": summary, "comment": comment}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
