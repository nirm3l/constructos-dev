from __future__ import annotations

from pathlib import Path
import sys


def load_text_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Failed to read system prompt file '{path}': {exc}") from exc


def resolve_user_prompt(raw_prompt: str, *, allow_stdin: bool) -> str:
    text = str(raw_prompt or "")
    if text == "-" and allow_stdin:
        return sys.stdin.read().strip()
    return text.strip()


def build_hidden_instruction(
    *,
    app_mcp_name: str,
    app_mcp_url: str,
    extra_system_prompt: str,
    has_user_prompt: bool,
    runtime_workspace_id: str = "",
) -> str:
    base = (
        "COS wrapper runtime instructions:\n"
        "- The application MCP server is preconfigured and available in this session.\n"
        f"- Server name: {app_mcp_name}\n"
        f"- Server URL: {app_mcp_url}\n"
        "- Use this MCP when the request touches workspace/project/task/specification/note/rule data.\n"
        "- The workspace context below is auto-detected from the active application runtime.\n"
        "- Unless the user explicitly asks for a different workspace, use the detected workspace_id directly in MCP calls.\n"
        "- For coding requests, implement directly in the current repository: edit files, run commands, run tests, and report concrete results.\n"
        "- Do not ask the user to manually configure or enable this MCP server.\n"
    )
    blocks: list[str] = [base]
    if runtime_workspace_id:
        blocks.append(f"Detected application workspace:\n- Active workspace_id: {runtime_workspace_id}")

    if extra_system_prompt:
        blocks.append(f"Additional COS system instructions:\n{extra_system_prompt}")
    if not has_user_prompt:
        blocks.append("No initial user request was provided. Reply with one short readiness message and wait.")
    return "\n\n".join(blocks).strip()


def compose_prompt(hidden_instruction: str, user_prompt: str) -> str:
    user_text = str(user_prompt or "").strip()
    if not user_text:
        return hidden_instruction
    return f"{hidden_instruction}\n\nUser request:\n{user_text}".strip()
