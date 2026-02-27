from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from features.agents.mcp_registry import build_selected_mcp_config_text, normalize_chat_mcp_servers
from shared.settings import (
    AGENT_CHAT_CONTEXT_LIMIT_TOKENS,
    AGENT_CODEX_MCP_URL,
    AGENT_CODEX_MODEL,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)

EMPTY_ASSISTANT_SUMMARY = "No assistant response content was returned."
_DEFAULT_CODEX_HOME_ROOT = "/tmp/codex-home"
_DEFAULT_CODEX_HOME_RETENTION_DAYS = 14
_DEFAULT_CODEX_HOME_CLEANUP_INTERVAL_SECONDS = 3600
_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    template_path = _PROMPT_TEMPLATES_DIR / name
    try:
        return template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Prompt template file not found: {template_path}") from exc


def _render_prompt_template(name: str, values: dict[str, object]) -> str:
    rendered_values = {key: str(value) for key, value in values.items()}
    template = _load_prompt_template(name)
    try:
        return template.format(**rendered_values)
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise RuntimeError(f"Missing prompt template value '{missing_key}' for {name}") from exc


def _normalize_prompt_mcp_servers(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        name = str(raw or "").strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        out.append(name)
        seen.add(lowered)
    return out


def _normalize_path_component(value: object, *, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return fallback
    out_chars: list[str] = []
    for char in raw:
        if char.isalnum() or char in {"-", "_", "."}:
            out_chars.append(char)
        else:
            out_chars.append("_")
    normalized = "".join(out_chars).strip("._-")
    return normalized or fallback


def _resolve_codex_home_root() -> Path:
    root_raw = str(os.getenv("AGENT_CODEX_HOME_ROOT", _DEFAULT_CODEX_HOME_ROOT)).strip() or _DEFAULT_CODEX_HOME_ROOT
    return Path(root_raw).expanduser().resolve()


def _resolve_persistent_codex_home_path(*, workspace_id: str, chat_session_id: str) -> Path:
    root = _resolve_codex_home_root()
    workspace_part = _normalize_path_component(workspace_id, fallback="workspace")
    session_part = _normalize_path_component(chat_session_id, fallback="session")
    return root / "workspace" / workspace_part / "chat" / session_part


def _resolve_chat_session_lock_path(*, workspace_id: str, chat_session_id: str) -> Path:
    return _resolve_persistent_codex_home_path(
        workspace_id=workspace_id,
        chat_session_id=chat_session_id,
    ) / ".run.lock"


def _try_acquire_file_lock(lock_handle: object) -> bool:
    try:
        import fcntl
    except Exception:
        # Fallback for environments without fcntl (best-effort lock).
        return True
    try:
        fileno = getattr(lock_handle, "fileno")
        fcntl.flock(fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except Exception:
        return True
    return True


def _release_file_lock(lock_handle: object) -> None:
    try:
        import fcntl
    except Exception:
        return
    try:
        fileno = getattr(lock_handle, "fileno")
        fcntl.flock(fileno(), fcntl.LOCK_UN)
    except Exception:
        return


@contextmanager
def _chat_session_run_lock(
    *,
    workspace_id: str | None = None,
    chat_session_id: str | None = None,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.1,
):
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_chat_session_id = str(chat_session_id or "").strip()
    if not normalized_workspace_id or not normalized_chat_session_id:
        yield
        return

    lock_path = _resolve_chat_session_lock_path(
        workspace_id=normalized_workspace_id,
        chat_session_id=normalized_chat_session_id,
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+", encoding="utf-8")
    lock_acquired = False
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))

    try:
        while True:
            if _try_acquire_file_lock(lock_handle):
                lock_acquired = True
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for active chat run lock (workspace_id={normalized_workspace_id}, "
                    f"chat_session_id={normalized_chat_session_id})."
                )
            time.sleep(max(0.01, float(poll_interval_seconds)))
        yield
    finally:
        if lock_acquired:
            _release_file_lock(lock_handle)
        lock_handle.close()


def _parse_env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.getenv(name, str(default)) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    return parsed


def _iter_persistent_codex_session_dirs(root: Path) -> list[Path]:
    workspace_root = root / "workspace"
    if not workspace_root.exists() or not workspace_root.is_dir():
        return []
    out: list[Path] = []
    for workspace_dir in workspace_root.iterdir():
        if not workspace_dir.is_dir():
            continue
        chat_root = workspace_dir / "chat"
        if not chat_root.exists() or not chat_root.is_dir():
            continue
        for session_dir in chat_root.iterdir():
            if not session_dir.is_dir() or session_dir.is_symlink():
                continue
            out.append(session_dir)
    return out


def _cleanup_stale_persistent_codex_homes(*, root: Path, cutoff_unix_seconds: float) -> tuple[int, int]:
    removed = 0
    failures = 0
    for session_dir in _iter_persistent_codex_session_dirs(root):
        try:
            stat = session_dir.stat()
        except Exception:
            failures += 1
            continue
        if float(stat.st_mtime) >= cutoff_unix_seconds:
            continue
        try:
            shutil.rmtree(session_dir)
            removed += 1
        except Exception:
            failures += 1
    return removed, failures


def run_codex_home_cleanup_if_due(*, now_unix_seconds: float | None = None) -> dict[str, int | bool]:
    now_ts = float(now_unix_seconds if now_unix_seconds is not None else time.time())
    root = _resolve_codex_home_root()
    retention_days = _parse_env_int(
        "AGENT_CODEX_HOME_RETENTION_DAYS",
        _DEFAULT_CODEX_HOME_RETENTION_DAYS,
        minimum=1,
    )
    interval_seconds = _parse_env_int(
        "AGENT_CODEX_HOME_CLEANUP_INTERVAL_SECONDS",
        _DEFAULT_CODEX_HOME_CLEANUP_INTERVAL_SECONDS,
        minimum=0,
    )
    if retention_days <= 0:
        return {"ran": False, "removed": 0, "failures": 0}
    marker_path = root / ".cleanup-marker"
    if interval_seconds > 0:
        try:
            marker_stat = marker_path.stat()
            if now_ts - float(marker_stat.st_mtime) < float(interval_seconds):
                return {"ran": False, "removed": 0, "failures": 0}
        except Exception:
            pass

    cutoff = now_ts - (retention_days * 86400)
    try:
        removed, failures = _cleanup_stale_persistent_codex_homes(
            root=root,
            cutoff_unix_seconds=cutoff,
        )
    except Exception:
        return {"ran": False, "removed": 0, "failures": 1}
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.touch()
    except Exception:
        pass
    return {"ran": True, "removed": removed, "failures": failures}


def _prepare_codex_home(home_path: Path, *, mcp_config_text: str) -> None:
    codex_dir = home_path / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(str(mcp_config_text or ""), encoding="utf-8")

    target_auth_path = codex_dir / "auth.json"
    if target_auth_path.exists():
        return
    source_auth_path = Path.home() / ".codex" / "auth.json"
    if source_auth_path.exists() and source_auth_path.is_file():
        try:
            shutil.copy2(source_auth_path, target_auth_path)
        except Exception:
            # Authentication can still be resolved by other providers/environment in some setups.
            pass


@contextmanager
def _codex_home_env(
    *,
    mcp_config_text: str,
    workspace_id: str | None = None,
    chat_session_id: str | None = None,
):
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_chat_session_id = str(chat_session_id or "").strip()
    if normalized_workspace_id and normalized_chat_session_id:
        try:
            persistent_home = _resolve_persistent_codex_home_path(
                workspace_id=normalized_workspace_id,
                chat_session_id=normalized_chat_session_id,
            )
            _prepare_codex_home(persistent_home, mcp_config_text=mcp_config_text)
            env = os.environ.copy()
            env["HOME"] = str(persistent_home)
            yield env
            return
        except Exception:
            # Fall back to a temporary home so chat remains available even if persistent storage fails.
            pass

    with tempfile.TemporaryDirectory(prefix="codex-home-") as temp_home:
        temp_home_path = Path(temp_home)
        _prepare_codex_home(temp_home_path, mcp_config_text=mcp_config_text)
        env = os.environ.copy()
        env["HOME"] = str(temp_home_path)
        yield env


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
    project_skills = ctx.get("project_skills") or []
    graph_context_markdown = str(ctx.get("graph_context_markdown") or "").strip()
    graph_evidence_json = str(ctx.get("graph_evidence_json") or "").strip()
    graph_summary_markdown = str(ctx.get("graph_summary_markdown") or "").strip()
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mcp_servers = _normalize_prompt_mcp_servers(ctx.get("mcp_servers"))
    enabled_mcp_servers_text = ", ".join(mcp_servers)
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
    skills_md_lines: list[str] = []
    for item in project_skills:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        skill_key = str(item.get("skill_key") or "").strip()
        summary = str(item.get("summary") or "").strip()
        mode = str(item.get("mode") or "").strip().lower() or "advisory"
        trust_level = str(item.get("trust_level") or "").strip().lower() or "reviewed"
        source_locator = str(item.get("source_locator") or "").strip()
        if not name and not skill_key:
            continue
        label = name or skill_key
        key_text = f" ({skill_key})" if skill_key else ""
        source_text = f" source={source_locator}" if source_locator else ""
        suffix_parts = [f"mode={mode}", f"trust={trust_level}"]
        if summary:
            suffix_parts.append(summary)
        suffix_text = "; ".join(suffix_parts)
        skills_md_lines.append(f"- {label}{key_text}: {suffix_text}{source_text}")
    skills_md = "\n".join(skills_md_lines) if skills_md_lines else "_(no project skills)_"
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
    return _render_prompt_template(
        "full_prompt.md",
        {
            "response_header": response_header,
            "task_id": task_id,
            "title": title,
            "status": status,
            "description": description,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "actor_user_id": actor_user_id,
            "project_name": project_name,
            "instruction": instruction,
            "soul_md": soul_md,
            "rules_md": rules_md,
            "skills_md": skills_md,
            "graph_md": graph_md,
            "graph_evidence": graph_evidence,
            "graph_summary": graph_summary,
            "context_guidance": context_guidance,
            "enabled_mcp_servers_text": enabled_mcp_servers_text,
            "mutation_policy": mutation_policy,
            "response_tail": response_tail,
        },
    )


def _normalize_snapshot_text(value: object, *, max_chars: int) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max(0, max_chars - 3)]}..."


def _build_resume_fresh_memory_snapshot(
    ctx: dict,
    *,
    max_summary_chars: int = 1100,
    max_evidence_items: int = 6,
    max_evidence_snippet_chars: int = 180,
    max_block_chars: int = 2400,
) -> str:
    blocks: list[str] = []

    summary_markdown = str(ctx.get("graph_summary_markdown") or "").strip()
    if summary_markdown:
        summary_text = _normalize_snapshot_text(summary_markdown, max_chars=max_summary_chars)
        if summary_text:
            blocks.append("Fresh Summary:\n" + summary_text)

    evidence_json = str(ctx.get("graph_evidence_json") or "").strip()
    evidence_lines: list[str] = []
    if evidence_json:
        try:
            parsed = json.loads(evidence_json)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                evidence_id = str(item.get("evidence_id") or "").strip()
                entity_type = str(item.get("entity_type") or "").strip() or "Entity"
                source_type = str(item.get("source_type") or "").strip() or "source"
                snippet = _normalize_snapshot_text(item.get("snippet"), max_chars=max_evidence_snippet_chars)
                if not snippet:
                    continue
                score_raw = item.get("final_score")
                score_text = ""
                try:
                    score_text = f"{float(score_raw):.3f}"
                except Exception:
                    score_text = ""
                evidence_prefix = f"[{evidence_id}] " if evidence_id else ""
                score_suffix = f" score={score_text}" if score_text else ""
                evidence_lines.append(
                    f"- {evidence_prefix}{entity_type} ({source_type}){score_suffix}: {snippet}"
                )
                if len(evidence_lines) >= max(1, int(max_evidence_items)):
                    break
    if evidence_lines:
        blocks.append("Fresh Evidence:\n" + "\n".join(evidence_lines))

    snapshot = "\n\n".join(blocks).strip()
    if not snapshot:
        return "_(fresh project snapshot unavailable)_"
    if len(snapshot) <= max_block_chars:
        return snapshot
    return _normalize_snapshot_text(snapshot, max_chars=max_block_chars)


def _build_resume_prompt(ctx: dict, *, structured_response: bool = True) -> str:
    task_id = ctx.get("task_id")
    title = ctx.get("title", "")
    description = ctx.get("description", "")
    status = ctx.get("status", "")
    instruction = ctx.get("instruction", "")
    workspace_id = ctx.get("workspace_id") or ""
    project_id = ctx.get("project_id") or ""
    actor_user_id = str(ctx.get("actor_user_id") or "").strip()
    project_name = ctx.get("project_name") or ""
    fresh_memory_snapshot = _build_resume_fresh_memory_snapshot(ctx)
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mcp_servers = _normalize_prompt_mcp_servers(ctx.get("mcp_servers"))
    enabled_mcp_servers_text = ", ".join(mcp_servers) if mcp_servers else "_(none selected)_"
    has_task_context = bool(str(task_id or "").strip())
    task_guidance = (
        "- If task context is present, call get_task(task_id) before mutating state.\n"
        if has_task_context
        else "- This is a general chat request; use workspace/project context as needed.\n"
    )
    mutation_policy = (
        "- Mutating tools are allowed for this request.\n"
        if allow_mutations
        else "- Mutating tools are NOT allowed for this request.\n"
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
    return _render_prompt_template(
        "resume_prompt.md",
        {
            "response_header": response_header,
            "task_id": task_id,
            "title": title,
            "status": status,
            "description": description,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "actor_user_id": actor_user_id,
            "project_name": project_name,
            "instruction": instruction,
            "fresh_memory_snapshot": fresh_memory_snapshot,
            "task_guidance": task_guidance,
            "enabled_mcp_servers_text": enabled_mcp_servers_text,
            "mutation_policy": mutation_policy,
            "response_tail": response_tail,
        },
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


def _truncate_summary(text: str, *, limit: int = 200) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)]}..."


def _derive_summary_from_text(text: str) -> str:
    first_non_empty = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    return _truncate_summary(first_non_empty)


def _collect_message_text_parts(value: object, *, max_depth: int = 5) -> list[str]:
    if max_depth <= 0:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_collect_message_text_parts(item, max_depth=max_depth - 1))
        return parts
    if not isinstance(value, dict):
        return []

    parts: list[str] = []
    for key in ("text", "markdown", "value", "output_text"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            parts.append(raw)
    for key in ("delta", "content", "parts", "items", "message"):
        if key not in value:
            continue
        parts.extend(_collect_message_text_parts(value.get(key), max_depth=max_depth - 1))

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        deduped.append(part)
    return deduped


def _extract_message_text(item: object) -> str:
    if isinstance(item, dict):
        direct_text = item.get("text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()
        parts = _collect_message_text_parts(item.get("content"))
        if parts:
            return "".join(parts).strip()
    parts = _collect_message_text_parts(item)
    return "".join(parts).strip()


def _extract_delta_text(params: dict[str, object]) -> str:
    raw_delta = params.get("delta")
    if isinstance(raw_delta, str):
        return raw_delta
    if raw_delta is not None:
        extracted = _extract_message_text(raw_delta)
        if extracted:
            return extracted

    for key in ("text", "value", "output_text"):
        raw = params.get(key)
        if isinstance(raw, str):
            return raw
    item = params.get("item")
    if item is not None:
        extracted_item_text = _extract_message_text(item)
        if extracted_item_text:
            return extracted_item_text
    return ""


def _is_message_delta_method(method: str) -> bool:
    normalized = str(method or "").strip().lower()
    if not normalized.startswith("item/") or not normalized.endswith("/delta"):
        return False
    middle = normalized[len("item/") : -len("/delta")].replace("_", "").replace("-", "")
    return middle in {"agentmessage", "assistantmessage"}


def _is_assistant_message_item_type(item_type: str) -> bool:
    normalized = str(item_type or "").strip().lower().replace("_", "").replace("-", "")
    return normalized in {"agentmessage", "assistantmessage"}


def _extract_error_message(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    message = str(payload.get("message") or "").strip()
    additional = str(payload.get("additionalDetails") or payload.get("additional_details") or "").strip()
    if message and additional:
        return f"{message} | {additional}"
    if message:
        return message
    if additional:
        return additional
    return ""


def _build_plain_text_result(message_text: str) -> dict[str, object]:
    text = str(message_text or "").strip()
    if not text:
        return {
            "action": "comment",
            "summary": EMPTY_ASSISTANT_SUMMARY,
            "comment": None,
        }
    summary = _derive_summary_from_text(text) or EMPTY_ASSISTANT_SUMMARY
    return {
        "action": "comment",
        "summary": summary,
        "comment": text,
    }


def _run_codex_app_server_with_optional_stream(
    *,
    start_prompt: str,
    resume_prompt: str | None,
    timeout_seconds: float,
    stream_events: bool,
    model: str | None = None,
    output_schema: dict | None = None,
    preferred_thread_id: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, dict[str, int] | None, str | None, bool, bool]:
    cmd = [
        "codex",
        "app-server",
        "--listen",
        "stdio://",
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
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
    turn_failed = False
    turn_failure_message = ""
    last_error_message = ""
    usage: dict[str, int] | None = None
    final_message = ""
    delta_parts: list[str] = []
    stream_plain_text = output_schema is None
    lines: list[str] = []
    forced_shutdown = False
    resume_thread_id = str(preferred_thread_id or "").strip()
    resume_attempted = bool(resume_thread_id)
    resume_succeeded = False

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

    def _thread_request_params() -> dict[str, object]:
        params: dict[str, object] = {
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
        }
        if model:
            params["model"] = model
        return params

    def _request_thread_start() -> None:
        _send_request("thread/start", _thread_request_params())

    def _request_thread_resume(thread_id_value: str) -> None:
        params = _thread_request_params()
        params["threadId"] = thread_id_value
        _send_request("thread/resume", params)

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
                if resume_thread_id:
                    _request_thread_resume(resume_thread_id)
                else:
                    _request_thread_start()
            elif req_method in {"thread/start", "thread/resume"}:
                error_payload = message.get("error")
                if isinstance(error_payload, dict):
                    extracted = _extract_error_message(error_payload)
                    if extracted:
                        last_error_message = extracted
                    if req_method == "thread/resume":
                        resume_succeeded = False
                        _request_thread_start()
                        continue
                    detail = extracted or "unknown error"
                    raise RuntimeError(f"codex app-server thread/start failed: {detail[:600]}")
                result = message.get("result")
                thread = (result or {}).get("thread") if isinstance(result, dict) else None
                thread_id = str((thread or {}).get("id") if isinstance(thread, dict) else "").strip()
                if not thread_id:
                    if req_method == "thread/resume":
                        resume_succeeded = False
                        _request_thread_start()
                        continue
                    raise RuntimeError("codex app-server did not return thread id")
                if req_method == "thread/resume":
                    resume_succeeded = True
                selected_prompt = start_prompt
                if req_method == "thread/resume" and resume_prompt is not None:
                    selected_prompt = resume_prompt
                turn_params: dict[str, object] = {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": selected_prompt}],
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
        if _is_message_delta_method(method):
            delta = _extract_delta_text(params)
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
                if _is_assistant_message_item_type(item_type):
                    text = _extract_message_text(item)
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
        if method == "error":
            error_payload = params.get("error") if isinstance(params.get("error"), dict) else params
            extracted = _extract_error_message(error_payload)
            if extracted:
                last_error_message = extracted
            continue
        if method == "turn/completed":
            turn_payload = params.get("turn") if isinstance(params, dict) and isinstance(params.get("turn"), dict) else None
            turn_status = str((turn_payload or {}).get("status") if isinstance(turn_payload, dict) else "").strip().lower()
            if turn_status == "failed":
                turn_failed = True
                turn_error_payload = (turn_payload or {}).get("error") if isinstance(turn_payload, dict) else None
                turn_failure_message = _extract_error_message(turn_error_payload) or last_error_message
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
    if turn_failed:
        detail = turn_failure_message or "codex turn failed without error details"
        raise RuntimeError(f"codex app-server turn failed: {detail[:600]}")

    if not final_message:
        final_message = "".join(delta_parts).strip()
    if stream_events and not stream_plain_text and final_message:
        rendered = _render_stream_assistant_text(final_message)
        if rendered:
            _emit_stream_event({"type": "assistant_text", "delta": rendered})
    if stream_events and usage is not None:
        _emit_stream_event({"type": "usage", "usage": usage})
    return final_message, usage, (thread_id or None), resume_attempted, resume_succeeded


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
    env: dict[str, str] | None = None,
) -> str:
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
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
    workspace_id = str(ctx.get("workspace_id") or "").strip() or None
    chat_session_id = str(ctx.get("chat_session_id") or "").strip() or None
    preferred_codex_session_id = str(ctx.get("codex_session_id") or "").strip() or None
    mcp_url = AGENT_CODEX_MCP_URL
    selected_mcp_servers = normalize_chat_mcp_servers(
        ctx.get("mcp_servers"),
        strict=False,
    )
    mcp_config_text = build_selected_mcp_config_text(
        selected_servers=selected_mcp_servers,
        task_management_mcp_url=mcp_url,
    )
    stream_events = bool(ctx.get("stream_events"))
    stream_plain_text = bool(ctx.get("stream_plain_text"))
    structured_response = not (stream_events and stream_plain_text)
    start_prompt = _build_prompt(ctx, structured_response=structured_response)
    resume_prompt = _build_resume_prompt(ctx, structured_response=structured_response)
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
    codex_session_id: str | None = None
    resume_attempted = False
    resume_succeeded = False
    run_codex_home_cleanup_if_due()
    with _chat_session_run_lock(
        workspace_id=workspace_id,
        chat_session_id=chat_session_id,
        timeout_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
    ):
        with _codex_home_env(
            mcp_config_text=mcp_config_text,
            workspace_id=workspace_id,
            chat_session_id=chat_session_id,
        ) as codex_env:
            if stream_events:
                final_message, usage, codex_session_id, resume_attempted, resume_succeeded = _run_codex_app_server_with_optional_stream(
                    start_prompt=start_prompt,
                    resume_prompt=resume_prompt,
                    timeout_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
                    stream_events=True,
                    model=AGENT_CODEX_MODEL or None,
                    output_schema=schema if structured_response else None,
                    preferred_thread_id=preferred_codex_session_id,
                    env=codex_env,
                )
                if structured_response:
                    parsed_payload = _try_parse_structured_reply_text(final_message)
                    if parsed_payload is None:
                        raise RuntimeError("codex app-server returned a non-JSON response while JSON schema was required")
                    out = parsed_payload
                else:
                    out = _build_plain_text_result(final_message)
            else:
                final_message, usage, codex_session_id, resume_attempted, resume_succeeded = _run_codex_app_server_with_optional_stream(
                    start_prompt=start_prompt,
                    resume_prompt=resume_prompt,
                    timeout_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
                    stream_events=False,
                    model=AGENT_CODEX_MODEL or None,
                    output_schema=schema,
                    preferred_thread_id=preferred_codex_session_id,
                    env=codex_env,
                )
                parsed_payload = _try_parse_structured_reply_text(final_message)
                if parsed_payload is None:
                    raise RuntimeError("codex app-server returned a non-JSON response while JSON schema was required")
                out = parsed_payload

    action = str(out.get("action", "")).strip().lower()
    summary = str(out.get("summary", "")).strip()
    comment = out.get("comment")
    if action not in {"complete", "comment"}:
        raise RuntimeError("codex adapter received invalid action")
    if comment is not None:
        comment = str(comment)
    if not summary and comment:
        summary = _derive_summary_from_text(comment)
    if not summary:
        summary = EMPTY_ASSISTANT_SUMMARY
    print(
        json.dumps(
            {
                "action": action,
                "summary": summary,
                "comment": comment,
                "usage": usage,
                "codex_session_id": codex_session_id,
                "resume_attempted": resume_attempted,
                "resume_succeeded": resume_succeeded,
                "resume_fallback_used": bool(resume_attempted and not resume_succeeded),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
