from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading

from shared.settings import (
    AGENT_CHAT_CONTEXT_LIMIT_TOKENS,
    AGENT_CODEX_MCP_URL,
    AGENT_CODEX_MODEL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)


def _build_prompt(ctx: dict, *, structured_response: bool = True) -> str:
    task_id = ctx.get("task_id")
    title = ctx.get("title", "")
    description = ctx.get("description", "")
    status = ctx.get("status", "")
    instruction = ctx.get("instruction", "")
    workspace_id = ctx.get("workspace_id") or ""
    project_id = ctx.get("project_id") or ""
    actor_user_id = str(ctx.get("actor_user_id") or "").strip()
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
    response_header = (
        "Return ONLY JSON matching the schema.\n\n"
        if structured_response
        else "Return plain Markdown text for the end user.\nDo not output JSON wrappers.\n\n"
    )
    response_tail = (
        "- Return action=complete only if this task should be completed; otherwise return action=comment.\n"
        "- summary must state what was actually done.\n"
        "- comment should be concise and optional; use null when no extra runner comment is needed.\n"
        if structured_response
        else "- Respond directly to the user with clear, actionable text.\n"
    )
    return (
        "You are an automation agent for task management.\n"
        "Use available MCP tools to satisfy the instruction.\n"
        f"{response_header}"
        f"Task ID: {task_id}\n"
        f"Title: {title}\n"
        f"Status: {status}\n"
        f"Description: {description}\n"
        f"Workspace ID: {workspace_id}\n"
        f"Project ID: {project_id}\n"
        f"Current User ID: {actor_user_id}\n"
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
        "- For profile preference changes (theme/timezone/notifications), use MCP tools directly.\n"
        "- For chat theme changes, use set_user_theme(theme='light'|'dark').\n"
        "- set_user_theme targets the current app user profile.\n"
        "- Use toggle_my_theme only if the user explicitly asks to toggle (not set) theme.\n"
        "- Report the final theme based on set_user_theme tool output.\n"
        "- Use graph_* MCP tools when you need relation-aware lookup across project resources.\n"
        "- Prefer bulk tools when operating on many tasks (avoid per-task loops when possible).\n"
        "- Prefer archive_all_notes/archive_all_tasks for 'archive everything' requests.\n"
        "- For mutating MCP tool calls, always provide command_id.\n"
        "- If retrying the same mutation, reuse the exact same command_id.\n"
        "- If the user asks for a plan/spec/design doc, prefer creating a Note (Markdown) via MCP tools so it is visible in the UI.\n"
        "- When creating a plan note: use a clear title starting with 'Plan:' and include actionable steps.\n"
        "- If you are in task context, link the note to the task by setting task_id when creating the note.\n"
        "- For every request to create a new project, always use a strict interactive setup protocol.\n"
        "- Strict protocol is mandatory even if the user asks for immediate creation.\n"
        "- Ask one clarifying question at a time and track missing fields until they are resolved.\n"
        "- Discovery fields before creation: project goal/domain, setup strategy (template or manual), project name, and defaults/overrides (statuses, members, embeddings, context top K, template parameters when applicable).\n"
        "- Template strategy sequence: list_project_templates -> get_project_template -> collect template parameters -> preview_project_from_template -> explicit user confirmation -> create_project_from_template.\n"
        "- Manual strategy sequence: collect required fields -> explicit user confirmation -> create_project.\n"
        "- Never call create_project or create_project_from_template until the user explicitly confirms creation in the current conversation (for example: 'confirm create').\n"
        "- After successful creation, ask whether seeded tasks/specifications/rules should be adjusted for this specific project; if yes, apply the requested updates via MCP tools.\n"
        "- When mentioning created/updated entities in summary/comment, include clickable Markdown links (not raw IDs).\n"
        "- Never return generic phrases like 'open task' or 'open note' without a concrete link target.\n"
        "- For each created entity, include at least one explicit link that can be clicked in chat.\n"
        "- Link format in this app:\n"
        "  - Note: ?tab=notes&project=<project_id>&note=<note_id>\n"
        "  - Task: ?tab=tasks&project=<project_id>&task=<task_id>\n"
        "  - Specification: ?tab=specifications&project=<project_id>&specification=<specification_id>\n"
        "  - Project: ?tab=projects&project=<project_id>\n"
        f"{mutation_policy}"
        "- For recurring schedules, set task.recurring_rule explicitly using canonical format: every:<number><m|h|d> (example: every:1m).\n"
        "- After scheduling changes, verify by reading the task and confirming scheduled_at_utc + recurring_rule values.\n"
        f"{response_tail}"
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


def _emit_stream_event(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True), flush=True)


def _normalize_usage_payload(usage_raw: dict | None) -> dict[str, int] | None:
    if not isinstance(usage_raw, dict):
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


def _normalize_app_server_usage(token_usage_raw: dict | None) -> dict[str, int] | None:
    if not isinstance(token_usage_raw, dict):
        return None
    last = token_usage_raw.get("last")
    if not isinstance(last, dict):
        return None
    input_tokens = _safe_non_negative_int(last.get("inputTokens")) or 0
    cached_input_tokens = _safe_non_negative_int(last.get("cachedInputTokens")) or 0
    output_tokens = _safe_non_negative_int(last.get("outputTokens")) or 0
    usage = {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
    }
    context_limit = _safe_non_negative_int(token_usage_raw.get("modelContextWindow"))
    if context_limit and context_limit > 0:
        usage["context_limit_tokens"] = int(context_limit)
    elif AGENT_CHAT_CONTEXT_LIMIT_TOKENS > 0:
        usage["context_limit_tokens"] = int(AGENT_CHAT_CONTEXT_LIMIT_TOKENS)
    return usage


def _build_plain_text_result(message_text: str) -> dict[str, object]:
    text = str(message_text or "").strip()
    if not text:
        return {
            "action": "comment",
            "summary": "Codex execution completed.",
            "comment": None,
        }
    first_non_empty = next((line.strip() for line in text.splitlines() if line.strip()), "")
    summary = first_non_empty or "Codex execution completed."
    if len(summary) > 200:
        summary = f"{summary[:197]}..."
    return {
        "action": "comment",
        "summary": summary,
        "comment": text,
    }


def _run_codex_app_server_with_optional_stream(
    *,
    prompt: str,
    mcp_url: str,
    timeout_seconds: float,
    stream_events: bool,
    model: str | None = None,
    output_schema: dict | None = None,
) -> tuple[str, dict[str, int] | None]:
    cmd = [
        "codex",
        "app-server",
        "--listen",
        "stdio://",
        "-c",
        f'mcp_servers.task_management_tools.url="{mcp_url}"',
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    timed_out = False
    done = threading.Event()

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if done.wait(timeout_seconds):
            return
        if proc.poll() is None:
            timed_out = True
            proc.kill()

    watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
    watchdog.start()

    if proc.stdin is None:
        raise RuntimeError("codex app-server stdin unavailable")
    if proc.stdout is None:
        raise RuntimeError("codex app-server stdout unavailable")

    request_seq = 0
    pending_requests: dict[str, str] = {}
    thread_id = ""
    turn_completed = False
    usage: dict[str, int] | None = None
    final_message = ""
    delta_parts: list[str] = []
    stream_plain_text = output_schema is None
    lines: list[str] = []
    forced_shutdown = False

    def _send_message(payload: dict[str, object]) -> None:
        proc.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def _send_request(method: str, params: dict[str, object]) -> str:
        nonlocal request_seq
        request_seq += 1
        req_id = str(request_seq)
        pending_requests[req_id] = method
        _send_message({"method": method, "id": req_id, "params": params})
        return req_id

    _send_request(
        "initialize",
        {
            "clientInfo": {"name": "task-management-agent", "title": "task-management-agent", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True, "optOutNotificationMethods": None},
        },
    )

    for raw_line in proc.stdout:
        line = str(raw_line or "").strip()
        if not line:
            continue
        lines.append(line)
        if line.startswith("WARNING:"):
            continue
        try:
            message = json.loads(line)
        except Exception:
            continue
        if not isinstance(message, dict):
            continue

        if "id" in message:
            req_id = str(message.get("id") or "")
            req_method = pending_requests.pop(req_id, "")
            if req_method == "initialize":
                _send_message({"method": "initialized"})
                thread_params: dict[str, object] = {
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                }
                if model:
                    thread_params["model"] = model
                _send_request("thread/start", thread_params)
            elif req_method == "thread/start":
                result = message.get("result")
                thread = (result or {}).get("thread") if isinstance(result, dict) else None
                thread_id = str((thread or {}).get("id") if isinstance(thread, dict) else "").strip()
                if not thread_id:
                    raise RuntimeError("codex app-server did not return thread id")
                turn_params: dict[str, object] = {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                }
                if output_schema is not None:
                    turn_params["outputSchema"] = output_schema
                _send_request("turn/start", turn_params)
            continue

        method = str(message.get("method") or "").strip()
        params = message.get("params") if isinstance(message.get("params"), dict) else {}

        if method == "turn/started":
            if stream_events:
                _emit_stream_event({"type": "status", "message": "Codex started processing the request."})
            continue
        if method == "item/agentMessage/delta":
            delta = str(params.get("delta") or "")
            if not delta:
                continue
            delta_parts.append(delta)
            if stream_events and stream_plain_text:
                _emit_stream_event({"type": "assistant_text", "delta": delta})
            continue
        if method == "item/completed":
            item = params.get("item") if isinstance(params, dict) else None
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip().lower()
                if item_type == "agent_message":
                    text = str(item.get("text") or "").strip()
                    if text:
                        final_message = text
                elif item_type == "reasoning" and stream_events:
                    _emit_stream_event({"type": "status", "message": "Reasoning step completed."})
            continue
        if method == "thread/tokenUsage/updated":
            usage_candidate = _normalize_app_server_usage(params.get("tokenUsage") if isinstance(params, dict) else None)
            if usage_candidate is not None:
                usage = usage_candidate
            continue
        if method == "turn/completed":
            turn_completed = True
            break

    done.set()
    if timed_out:
        raise TimeoutError(f"codex app-server timed out after {timeout_seconds:.1f}s")

    if proc.poll() is None:
        # codex app-server is long-lived; after turn/completed we stop it ourselves.
        forced_shutdown = True
        proc.terminate()
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return_code = proc.wait()
    if return_code != 0 and not (turn_completed and forced_shutdown):
        err_text = "\n".join(lines).strip()
        raise RuntimeError(f"codex app-server failed (exit={return_code}): {err_text[:600]}")
    if not turn_completed:
        err_text = "\n".join(lines).strip()
        raise RuntimeError(f"codex app-server did not emit turn/completed: {err_text[:600]}")

    if not final_message:
        final_message = "".join(delta_parts).strip()
    if stream_events and not stream_plain_text and final_message:
        rendered = _render_stream_assistant_text(final_message)
        if rendered:
            _emit_stream_event({"type": "assistant_text", "delta": rendered})
    if stream_events and usage is not None:
        _emit_stream_event({"type": "usage", "usage": usage})
    return final_message, usage


def _coerce_structured_reply_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    summary_raw = value.get("summary")
    action_raw = value.get("action")
    has_comment_key = "comment" in value
    if summary_raw is None and action_raw is None and not has_comment_key:
        return None
    return value


def _try_parse_structured_reply_text(text: str) -> dict[str, object] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]

    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            fenced_inner = "\n".join(lines[1:-1]).strip()
            if fenced_inner:
                candidates.append(fenced_inner)

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        bracket_slice = raw[start : end + 1].strip()
        if bracket_slice and bracket_slice not in candidates:
            candidates.append(bracket_slice)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        payload = _coerce_structured_reply_payload(parsed)
        if payload is not None:
            return payload
    return None


def _render_stream_assistant_text(message_text: str) -> str:
    raw = str(message_text or "").strip()
    if not raw:
        return ""
    structured = _try_parse_structured_reply_text(raw)
    if structured is None:
        return raw

    summary = str(structured.get("summary") or "").strip()
    comment_value = structured.get("comment")
    comment = str(comment_value).strip() if comment_value is not None else ""
    if summary and comment:
        return f"{summary}\n\n{comment}"
    if summary:
        return summary
    if comment:
        return comment
    return raw


def _run_codex_json_with_optional_stream(
    *,
    command: list[str],
    timeout_seconds: float,
    stream_events: bool,
) -> str:
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    timed_out = False
    done = threading.Event()

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if done.wait(timeout_seconds):
            return
        if proc.poll() is None:
            timed_out = True
            proc.kill()

    watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
    watchdog.start()

    lines: list[str] = []
    emitted_message_count = 0
    if proc.stdout is None:
        raise RuntimeError("codex exec stdout unavailable")
    for raw_line in proc.stdout:
        line = str(raw_line or "").strip()
        if not line:
            continue
        lines.append(line)
        if not stream_events:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "").strip()
        if event_type == "item.completed":
            item = event.get("item")
            if isinstance(item, dict):
                item_type = str(item.get("type") or "").strip()
                if item_type == "agent_message":
                    text = _render_stream_assistant_text(str(item.get("text") or ""))
                    if text:
                        if emitted_message_count > 0:
                            _emit_stream_event({"type": "assistant_text", "delta": "\n\n"})
                        _emit_stream_event({"type": "assistant_text", "delta": text})
                        emitted_message_count += 1
                elif item_type == "reasoning":
                    _emit_stream_event({"type": "status", "message": "Reasoning step completed."})
        elif event_type == "turn.started":
            _emit_stream_event({"type": "status", "message": "Codex started processing the request."})
        elif event_type == "turn.completed":
            usage_payload = _normalize_usage_payload(event.get("usage") if isinstance(event, dict) else None)
            if usage_payload is not None:
                _emit_stream_event({"type": "usage", "usage": usage_payload})

    return_code = proc.wait()
    done.set()
    if timed_out:
        raise TimeoutError(f"codex exec timed out after {timeout_seconds:.1f}s")
    if return_code != 0:
        err_text = "\n".join(lines).strip()
        raise RuntimeError(f"codex exec failed (exit={return_code}): {err_text[:600]}")
    return "\n".join(lines)


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"action": "comment", "summary": "No input context.", "comment": "No task context received."}))
        return 0

    ctx = json.loads(raw)
    mcp_url = AGENT_CODEX_MCP_URL
    stream_events = bool(ctx.get("stream_events"))
    stream_plain_text = bool(ctx.get("stream_plain_text"))
    structured_response = not (stream_events and stream_plain_text)
    prompt = _build_prompt(ctx, structured_response=structured_response)
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
    if stream_events:
        final_message, usage = _run_codex_app_server_with_optional_stream(
            prompt=prompt,
            mcp_url=mcp_url,
            timeout_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
            stream_events=True,
            model=AGENT_CODEX_MODEL or None,
            output_schema=schema if structured_response else None,
        )
        if structured_response:
            parsed_payload = _try_parse_structured_reply_text(final_message)
            if parsed_payload is None:
                raise RuntimeError("codex app-server returned a non-JSON response while JSON schema was required")
            out = parsed_payload
        else:
            out = _build_plain_text_result(final_message)
    else:
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

            stdout = _run_codex_json_with_optional_stream(
                command=cmd,
                timeout_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
                stream_events=False,
            )
            usage = _extract_turn_usage(stdout or "")

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
