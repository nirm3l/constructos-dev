from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict

from features.agents.mcp_registry import build_selected_mcp_config_text, normalize_chat_mcp_servers
from plugins import runner_policy as plugin_runner_policy
from shared.settings import (
    AGENT_CHAT_CONTEXT_LIMIT_TOKENS,
    AGENT_CODEX_MCP_URL,
    AGENT_CODEX_MODEL,
    AGENT_CODEX_REASONING_EFFORT,
    AGENT_ENABLED_PLUGINS,
    AGENT_EXECUTOR_TIMEOUT_SECONDS,
)
from shared.json_utils import parse_json_object

EMPTY_ASSISTANT_SUMMARY = "No assistant response content was returned."
_DEFAULT_CODEX_HOME_ROOT = "/tmp/codex-home"
_DEFAULT_CODEX_WORKDIR = "/home/app/workspace"
_DEFAULT_CODEX_HOME_RETENTION_DAYS = 14
_DEFAULT_CODEX_HOME_CLEANUP_INTERVAL_SECONDS = 3600
_DEFAULT_STRUCTURED_PROMPT_CACHE_MAX_ENTRIES = 256
_PROMPT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompt_templates" / "codex"
_ALLOWED_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
_STRUCTURED_PROMPT_CACHE_LOCK = threading.Lock()
_STRUCTURED_PROMPT_CACHE: OrderedDict[str, tuple[float, dict[str, object], dict[str, int] | None]] = OrderedDict()


def _strip_mcp_server_tables(config_text: str) -> str:
    lines = str(config_text or "").splitlines()
    if not lines:
        return ""
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        is_table_header = stripped.startswith("[") and stripped.endswith("]")
        if is_table_header:
            table_name = stripped[1:-1].strip().lower()
            if table_name == "mcp_servers" or table_name.startswith("mcp_servers."):
                skipping = True
                continue
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).strip()


@lru_cache(maxsize=16)
def _load_prompt_template(name: str) -> str:
    candidate_paths = [_PROMPT_TEMPLATES_DIR / name]
    candidate_paths.extend(base / name for base in _plugin_prompt_template_dirs())
    for template_path in candidate_paths:
        try:
            return template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
    raise RuntimeError(f"Prompt template file not found: {candidate_paths[0]}")


@lru_cache(maxsize=1)
def _plugin_prompt_template_dirs() -> tuple[Path, ...]:
    plugins_root = Path(__file__).resolve().parents[2] / "plugins"
    enabled = {str(item or "").strip().lower() for item in (AGENT_ENABLED_PLUGINS or []) if str(item or "").strip()}
    if not enabled:
        enabled = {"team_mode"}
    if enabled.intersection({"none", "off", "disabled"}):
        return tuple()
    out: list[Path] = []
    for key in sorted(enabled):
        candidate = plugins_root / key / "prompt_templates"
        if candidate.is_dir():
            out.append(candidate)
    return tuple(out)


@lru_cache(maxsize=16)
def _render_plugin_workflow_guidance(template_name: str) -> str:
    lines: list[str] = []
    for base in _plugin_prompt_template_dirs():
        path = base / template_name
        try:
            content = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if content:
            lines.append(content)
    return ("\n".join(lines)).strip()


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


def _resolve_codex_workdir() -> Path | None:
    raw = str(os.getenv("AGENT_CODEX_WORKDIR", _DEFAULT_CODEX_WORKDIR)).strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_task_workdir(workdir_hint: object) -> Path | None:
    hint = str(workdir_hint or "").strip()
    if not hint:
        return None
    try:
        path = Path(hint).expanduser().resolve()
    except Exception:
        return None
    if not path.exists() or not path.is_dir():
        return None
    return path


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


def _effective_timeout_seconds(value: object, *, fallback_seconds: float | int | None) -> float | None:
    candidate = fallback_seconds if value is None else value
    try:
        normalized = float(candidate or 0.0)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


@contextmanager
def _chat_session_run_lock(
    *,
    workspace_id: str | None = None,
    chat_session_id: str | None = None,
    timeout_seconds: float | None,
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
    deadline = (time.monotonic() + max(0.0, float(timeout_seconds))) if timeout_seconds is not None else None

    try:
        while True:
            if _try_acquire_file_lock(lock_handle):
                lock_acquired = True
                break
            if deadline is not None and time.monotonic() >= deadline:
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


def _stable_json_dumps(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=True)


def _structured_prompt_cache_max_entries() -> int:
    return _parse_env_int(
        "AGENT_STRUCTURED_PROMPT_CACHE_MAX_ENTRIES",
        _DEFAULT_STRUCTURED_PROMPT_CACHE_MAX_ENTRIES,
        minimum=1,
    )


def _build_structured_prompt_cache_key(
    *,
    prompt: str,
    output_schema: dict[str, object],
    model: str | None,
    reasoning_effort: str | None,
    workspace_id: str | None,
    session_key: str | None,
    mcp_servers: list[str],
) -> str:
    material = {
        "prompt": str(prompt or ""),
        "output_schema": output_schema,
        "model": str(model or "").strip() or None,
        "reasoning_effort": str(reasoning_effort or "").strip() or None,
        "workspace_id": str(workspace_id or "").strip() or None,
        "session_key": str(session_key or "").strip() or None,
        "mcp_servers": list(mcp_servers),
    }
    digest = hashlib.sha256(_stable_json_dumps(material).encode("utf-8")).hexdigest()
    return f"structured:{digest}"


def _structured_prompt_cache_get(cache_key: str) -> tuple[dict[str, object], dict[str, int] | None] | None:
    with _STRUCTURED_PROMPT_CACHE_LOCK:
        row = _STRUCTURED_PROMPT_CACHE.get(cache_key)
        if row is None:
            return None
        _, payload, usage = row
        _STRUCTURED_PROMPT_CACHE.move_to_end(cache_key)
        return dict(payload), dict(usage) if isinstance(usage, dict) else None


def _structured_prompt_cache_put(
    cache_key: str,
    *,
    payload: dict[str, object],
    usage: dict[str, int] | None,
) -> None:
    now = time.time()
    cached_payload = dict(payload)
    cached_usage = dict(usage) if isinstance(usage, dict) else None
    max_entries = _structured_prompt_cache_max_entries()
    with _STRUCTURED_PROMPT_CACHE_LOCK:
        _STRUCTURED_PROMPT_CACHE[cache_key] = (now, cached_payload, cached_usage)
        _STRUCTURED_PROMPT_CACHE.move_to_end(cache_key)
        while len(_STRUCTURED_PROMPT_CACHE) > max_entries:
            _STRUCTURED_PROMPT_CACHE.popitem(last=False)


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


def _prepare_codex_home(
    home_path: Path,
    *,
    mcp_config_text: str,
    runtime_config_text: str = "",
) -> None:
    codex_dir = home_path / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    source_config_path = Path.home() / ".codex" / "config.toml"
    source_config_text = ""
    if source_config_path.exists() and source_config_path.is_file():
        try:
            source_config_text = source_config_path.read_text(encoding="utf-8")
        except Exception:
            source_config_text = ""
    base_config_text = _strip_mcp_server_tables(source_config_text)
    scoped_runtime_text = str(runtime_config_text or "").strip()
    selected_mcp_text = str(mcp_config_text or "").strip()
    sections = [text for text in [base_config_text, scoped_runtime_text, selected_mcp_text] if text]
    merged_config_text = "\n\n".join(sections).strip()
    config_path.write_text(f"{merged_config_text}\n" if merged_config_text else "", encoding="utf-8")

    target_auth_path = codex_dir / "auth.json"
    source_auth_path = Path.home() / ".codex" / "auth.json"
    if source_auth_path.exists() and source_auth_path.is_file():
        try:
            # Keep per-session auth.json in sync with the primary Codex auth source.
            shutil.copy2(source_auth_path, target_auth_path)
        except Exception as exc:
            # If OPENAI_API_KEY is present, Codex can still authenticate from env.
            if str(os.getenv("OPENAI_API_KEY") or "").strip():
                return
            raise RuntimeError(
                "Failed to prepare Codex auth.json for session home. "
                "No OPENAI_API_KEY fallback is available."
            ) from exc


@contextmanager
def _codex_home_env(
    *,
    mcp_config_text: str,
    runtime_config_text: str = "",
    workspace_id: str | None = None,
    chat_session_id: str | None = None,
):
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_chat_session_id = str(chat_session_id or "").strip()
    if normalized_workspace_id and normalized_chat_session_id:
        persistent_home: Path | None = None
        try:
            persistent_home = _resolve_persistent_codex_home_path(
                workspace_id=normalized_workspace_id,
                chat_session_id=normalized_chat_session_id,
            )
            _prepare_codex_home(
                persistent_home,
                mcp_config_text=mcp_config_text,
                runtime_config_text=runtime_config_text,
            )
        except Exception:
            # Fall back to a temporary home so chat remains available even if persistent storage fails.
            persistent_home = None
        if persistent_home is not None:
            env = os.environ.copy()
            env["HOME"] = str(persistent_home)
            yield env
            return

    with tempfile.TemporaryDirectory(prefix="codex-home-") as temp_home:
        temp_home_path = Path(temp_home)
        _prepare_codex_home(
            temp_home_path,
            mcp_config_text=mcp_config_text,
            runtime_config_text=runtime_config_text,
        )
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
    actor_project_role = str(ctx.get("actor_project_role") or "").strip() or "_(not available)_"
    task_workdir = str(ctx.get("task_workdir") or "").strip() or "_(not available)_"
    task_branch = str(ctx.get("task_branch") or "").strip() or "_(not available)_"
    repo_root = str(ctx.get("repo_root") or "").strip() or "_(not available)_"
    request_execution_kickoff_intent = bool(ctx.get("execution_kickoff_intent"))
    request_workflow_scope = str(ctx.get("workflow_scope") or "").strip().lower()
    request_execution_mode = str(ctx.get("execution_mode") or "").strip().lower()
    is_team_mode_kickoff = (
        plugin_runner_policy.is_lead_role(actor_project_role)
        and request_execution_kickoff_intent
        and request_workflow_scope == "team_mode"
        and request_execution_mode in {"kickoff_only", "setup_then_kickoff"}
    )
    project_name = ctx.get("project_name") or ""
    project_description = str(ctx.get("project_description") or "")
    project_rules = ctx.get("project_rules") or []
    project_skills = ctx.get("project_skills") or []
    graph_context_markdown = str(ctx.get("graph_context_markdown") or "").strip()
    graph_evidence_json = str(ctx.get("graph_evidence_json") or "").strip()
    graph_summary_markdown = str(ctx.get("graph_summary_markdown") or "").strip()
    plugin_policy_json = str(ctx.get("plugin_policy_json") or "").strip()
    plugin_required_checks = str(ctx.get("plugin_required_checks") or "").strip()
    trigger_task_id = str(ctx.get("trigger_task_id") or "").strip() or "_(not available)_"
    trigger_from_status = str(ctx.get("trigger_from_status") or "").strip() or "_(not available)_"
    trigger_to_status = str(ctx.get("trigger_to_status") or "").strip() or "_(not available)_"
    trigger_timestamp = str(ctx.get("trigger_timestamp") or "").strip() or "_(not available)_"
    status_change_trigger_context = (
        f"- Source task ID: {trigger_task_id}\n"
        f"- From status: {trigger_from_status}\n"
        f"- To status: {trigger_to_status}\n"
        f"- Triggered at: {trigger_timestamp}\n"
    )
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mcp_servers = _normalize_prompt_mcp_servers(ctx.get("mcp_servers"))
    enabled_mcp_servers_text = ", ".join(mcp_servers)
    stream_plain_text = bool(ctx.get("stream_plain_text"))
    soul_md = project_description.strip() or "_(empty)_"
    graph_md = graph_context_markdown or "_(knowledge graph unavailable)_"
    graph_evidence = graph_evidence_json or "[]"
    graph_summary = graph_summary_markdown or "_(summary unavailable)_"
    plugin_policy_md = plugin_policy_json or "_(Plugin Policy unavailable)_"
    plugin_required_checks_md = plugin_required_checks or "_(none)_"
    rules_md_lines: list[str] = []
    for item in project_rules:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title.lower() == "plugin policy":
            # Policy is rendered in a dedicated section below; skip duplicate copy here.
            continue
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
        "- If task context is present, validate current task data with get_task(task_id) before mutations.\n"
        "- Keep this internal; do not start responses by narrating tool checks.\n"
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
    interaction_mode_guidance = (
        "- This run is manual chat-like automation mode.\n"
        "- Default behavior: answer the instruction directly in Markdown.\n"
        "- Do not mutate tasks/projects or post task comments/notes unless explicitly requested by the instruction.\n"
        "- For greetings/questions (for example 'Hello'), reply conversationally with no side effects.\n"
        "- Do not describe internal planning/tool-call steps unless the user explicitly asks for them.\n"
        if (stream_plain_text and not structured_response)
        else "- This run is workflow automation mode; execute requested operations and persist evidence when appropriate.\n"
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
        "- execution_outcome_contract is mandatory and must be truthful to observed execution state.\n"
        "- execution_outcome_contract fields are strict: contract_version=1, files_changed[], commit_sha|null, branch|null, tests_run(bool), tests_passed(bool), artifacts[].\n"
        + (
            "- This is a Team Mode kickoff task: return action=comment only and keep task status unchanged (do not complete).\n"
            if is_team_mode_kickoff
            else ""
        )
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
            "actor_project_role": actor_project_role,
            "project_name": project_name,
            "instruction": instruction,
            "task_workdir": task_workdir,
            "task_branch": task_branch,
            "repo_root": repo_root,
            "status_change_trigger_context": status_change_trigger_context,
            "soul_md": soul_md,
            "rules_md": rules_md,
            "skills_md": skills_md,
            "plugin_policy_md": plugin_policy_md,
            "plugin_required_checks_md": plugin_required_checks_md,
            "graph_md": graph_md,
            "graph_evidence": graph_evidence,
            "graph_summary": graph_summary,
            "context_guidance": context_guidance,
            "interaction_mode_guidance": interaction_mode_guidance,
            "plugin_workflow_guidance": _render_plugin_workflow_guidance("full_prompt_workflow_guidance.md"),
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


def _render_rules_markdown_for_segments(project_rules: list[object]) -> str:
    lines: list[str] = []
    for item in project_rules:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title.lower() == "plugin policy":
            continue
        body = str(item.get("body") or "").strip()
        if not title and not body:
            continue
        label = title or "Untitled rule"
        lines.append(f"- {label}: {body}" if body else f"- {label}")
    return "\n".join(lines).strip()


def _render_skills_markdown_for_segments(project_skills: list[object]) -> str:
    lines: list[str] = []
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
        lines.append(f"- {label}{key_text}: {'; '.join(suffix_parts)}{source_text}")
    return "\n".join(lines).strip()


def _prompt_segment_char_stats(
    ctx: dict,
    *,
    mode: str,
) -> dict[str, int]:
    normalized_mode = str(mode or "").strip().lower()
    instruction = str(ctx.get("instruction") or "").strip()
    status_change = (
        f"- Source task ID: {str(ctx.get('trigger_task_id') or '').strip() or '_(not available)_'}\n"
        f"- From status: {str(ctx.get('trigger_from_status') or '').strip() or '_(not available)_'}\n"
        f"- To status: {str(ctx.get('trigger_to_status') or '').strip() or '_(not available)_'}\n"
        f"- Triggered at: {str(ctx.get('trigger_timestamp') or '').strip() or '_(not available)_'}\n"
    ).strip()
    plugin_policy = str(ctx.get("plugin_policy_json") or "").strip()
    plugin_required_checks = str(ctx.get("plugin_required_checks") or "").strip()

    stats: dict[str, int] = {
        "status_change_trigger_context": len(status_change),
        "plugin_policy": len(plugin_policy),
        "plugin_required_checks": len(plugin_required_checks),
    }
    instruction_breakdown = ctx.get("prompt_instruction_segments")
    instruction_parts: dict[str, int] = {}
    if isinstance(instruction_breakdown, dict):
        for key_raw, value_raw in instruction_breakdown.items():
            key = str(key_raw or "").strip()
            if not key:
                continue
            try:
                value = max(0, int(value_raw))
            except (TypeError, ValueError):
                continue
            instruction_parts[f"instruction_{key}"] = value
    if instruction_parts:
        stats.update(instruction_parts)
        stats["instruction"] = sum(instruction_parts.values())
    else:
        stats["instruction"] = len(instruction)
    if normalized_mode == "resume":
        stats["fresh_memory_snapshot"] = len(_build_resume_fresh_memory_snapshot(ctx))
    else:
        project_description = str(ctx.get("project_description") or "").strip()
        project_rules = ctx.get("project_rules") if isinstance(ctx.get("project_rules"), list) else []
        project_skills = ctx.get("project_skills") if isinstance(ctx.get("project_skills"), list) else []
        stats["soul"] = len(project_description)
        stats["project_rules"] = len(_render_rules_markdown_for_segments(project_rules))
        stats["project_skills"] = len(_render_skills_markdown_for_segments(project_skills))
        stats["graph_context"] = len(str(ctx.get("graph_context_markdown") or "").strip())
        stats["graph_evidence"] = len(str(ctx.get("graph_evidence_json") or "").strip())
        stats["graph_summary"] = len(str(ctx.get("graph_summary_markdown") or "").strip())

    return {key: value for key, value in stats.items() if isinstance(value, int) and value >= 0}


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
    actor_project_role = str(ctx.get("actor_project_role") or "").strip() or "_(not available)_"
    task_workdir = str(ctx.get("task_workdir") or "").strip() or "_(not available)_"
    task_branch = str(ctx.get("task_branch") or "").strip() or "_(not available)_"
    repo_root = str(ctx.get("repo_root") or "").strip() or "_(not available)_"
    request_execution_kickoff_intent = bool(ctx.get("execution_kickoff_intent"))
    request_workflow_scope = str(ctx.get("workflow_scope") or "").strip().lower()
    request_execution_mode = str(ctx.get("execution_mode") or "").strip().lower()
    is_team_mode_kickoff = (
        plugin_runner_policy.is_lead_role(actor_project_role)
        and request_execution_kickoff_intent
        and request_workflow_scope == "team_mode"
        and request_execution_mode in {"kickoff_only", "setup_then_kickoff"}
    )
    project_name = ctx.get("project_name") or ""
    plugin_policy_json = str(ctx.get("plugin_policy_json") or "").strip()
    plugin_required_checks = str(ctx.get("plugin_required_checks") or "").strip()
    trigger_task_id = str(ctx.get("trigger_task_id") or "").strip() or "_(not available)_"
    trigger_from_status = str(ctx.get("trigger_from_status") or "").strip() or "_(not available)_"
    trigger_to_status = str(ctx.get("trigger_to_status") or "").strip() or "_(not available)_"
    trigger_timestamp = str(ctx.get("trigger_timestamp") or "").strip() or "_(not available)_"
    status_change_trigger_context = (
        f"- Source task ID: {trigger_task_id}\n"
        f"- From status: {trigger_from_status}\n"
        f"- To status: {trigger_to_status}\n"
        f"- Triggered at: {trigger_timestamp}\n"
    )
    fresh_memory_snapshot = _build_resume_fresh_memory_snapshot(ctx)
    allow_mutations = bool(ctx.get("allow_mutations", True))
    mcp_servers = _normalize_prompt_mcp_servers(ctx.get("mcp_servers"))
    enabled_mcp_servers_text = ", ".join(mcp_servers) if mcp_servers else "_(none selected)_"
    stream_plain_text = bool(ctx.get("stream_plain_text"))
    has_task_context = bool(str(task_id or "").strip())
    task_guidance = (
        "- If task context is present, validate with get_task(task_id) before mutating state.\n"
        "- Keep validation/tool steps internal; do not prepend them to user-facing replies.\n"
        if has_task_context
        else "- This is a general chat request; use workspace/project context as needed.\n"
    )
    mutation_policy = (
        "- Mutating tools are allowed for this request.\n"
        if allow_mutations
        else "- Mutating tools are NOT allowed for this request.\n"
    )
    interaction_mode_guidance = (
        "- This run is manual chat-like automation mode.\n"
        "- Default behavior: answer the instruction directly in Markdown.\n"
        "- Do not mutate tasks/projects or post task comments/notes unless explicitly requested by the instruction.\n"
        "- For greetings/questions (for example 'Hello'), reply conversationally with no side effects.\n"
        "- Do not describe internal planning/tool-call steps unless the user explicitly asks for them.\n"
        if (stream_plain_text and not structured_response)
        else "- This run is workflow automation mode; execute requested operations and persist evidence when appropriate.\n"
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
        "- execution_outcome_contract is mandatory and must be truthful to observed execution state.\n"
        "- execution_outcome_contract fields are strict: contract_version=1, files_changed[], commit_sha|null, branch|null, tests_run(bool), tests_passed(bool), artifacts[].\n"
        + (
            "- This is a Team Mode kickoff task: return action=comment only and keep task status unchanged (do not complete).\n"
            if is_team_mode_kickoff
            else ""
        )
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
            "actor_project_role": actor_project_role,
            "project_name": project_name,
            "instruction": instruction,
            "task_workdir": task_workdir,
            "task_branch": task_branch,
            "repo_root": repo_root,
            "plugin_policy_md": plugin_policy_json or "_(Plugin Policy unavailable)_",
            "plugin_required_checks_md": plugin_required_checks or "_(none)_",
            "status_change_trigger_context": status_change_trigger_context,
            "fresh_memory_snapshot": fresh_memory_snapshot,
            "task_guidance": task_guidance,
            "interaction_mode_guidance": interaction_mode_guidance,
            "plugin_workflow_guidance": _render_plugin_workflow_guidance("resume_prompt_workflow_guidance.md"),
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


def _normalize_reasoning_effort(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    alias_map = {
        "very-high": "xhigh",
        "very_high": "xhigh",
        "very high": "xhigh",
    }
    canonical = alias_map.get(normalized, normalized)
    if canonical not in _ALLOWED_REASONING_EFFORTS:
        return None
    return canonical


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
    if not normalized:
        return False
    compact = normalized.replace("_", "").replace("-", "")
    if compact in {"item.delta", "item/delta"}:
        return True
    if compact.startswith("item/") and compact.endswith("/delta"):
        middle = compact[len("item/") : -len("/delta")]
        return middle in {"agentmessage", "assistantmessage", "message"}
    if compact.startswith("item.") and compact.endswith(".delta"):
        middle = compact[len("item.") : -len(".delta")]
        return middle in {"agentmessage", "assistantmessage", "message"}
    return False


def _is_assistant_message_item_type(item_type: str) -> bool:
    normalized = str(item_type or "").strip().lower().replace("_", "").replace("-", "")
    return normalized in {"agentmessage", "assistantmessage", "message"}


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
    timeout_seconds: float | None,
    stream_events: bool,
    model: str | None = None,
    reasoning_effort: str | None = None,
    output_schema: dict | None = None,
    preferred_thread_id: str | None = None,
    env: dict[str, str] | None = None,
    run_cwd: Path | None = None,
) -> tuple[str, dict[str, int] | None, str | None, bool, bool]:
    effective_run_cwd = run_cwd or _resolve_codex_workdir()
    cmd = ["codex"]
    cmd.extend(
        [
            "app-server",
            "--listen",
            "stdio://",
        ]
    )
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(effective_run_cwd) if effective_run_cwd is not None else None,
    )
    timed_out = False
    done = threading.Event()
    timeout_error_message = "codex app-server timed out"
    if timeout_seconds is not None:
        timeout_error_message = f"codex app-server timed out after {timeout_seconds:.1f}s"

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if timeout_seconds is None:
            return
        if done.wait(timeout_seconds):
            return
        if proc.poll() is None:
            timed_out = True
            proc.kill()

    if timeout_seconds is not None:
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
        if reasoning_effort:
            params["reasoningEffort"] = reasoning_effort
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
            if not delta and isinstance(params.get("item"), dict):
                item_payload = params.get("item")
                item_type = str((item_payload or {}).get("type") or "").strip()
                if _is_assistant_message_item_type(item_type):
                    delta = _extract_message_text(item_payload)
            if not delta:
                continue
            delta_parts.append(delta)
            if stream_events and stream_plain_text:
                _emit_stream_event({"type": "assistant_text", "delta": delta})
            continue
        if method in {"item/updated", "item.updated"}:
            item_payload = params.get("item") if isinstance(params.get("item"), dict) else None
            item_type = str((item_payload or {}).get("type") if isinstance(item_payload, dict) else "").strip()
            if not _is_assistant_message_item_type(item_type):
                continue
            delta = _extract_delta_text(params)
            if not delta and isinstance(item_payload, dict):
                delta = _extract_message_text(item_payload)
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
                        if stream_events and stream_plain_text and not "".join(delta_parts).strip():
                            rendered = _render_stream_assistant_text(text)
                            if rendered:
                                _emit_stream_event({"type": "assistant_text", "delta": rendered})
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
        raise TimeoutError(timeout_error_message)

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
    timeout_seconds: float | None,
    stream_events: bool,
    env: dict[str, str] | None = None,
) -> str:
    run_cwd = _resolve_codex_workdir()
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(run_cwd) if run_cwd is not None else None,
    )
    timed_out = False
    done = threading.Event()
    timeout_error_message = "codex exec timed out"
    if timeout_seconds is not None:
        timeout_error_message = f"codex exec timed out after {timeout_seconds:.1f}s"

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if timeout_seconds is None:
            return
        if done.wait(timeout_seconds):
            return
        if proc.poll() is None:
            timed_out = True
            proc.kill()

    if timeout_seconds is not None:
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
        raise TimeoutError(timeout_error_message)
    if return_code != 0:
        err_text = "\n".join(lines).strip()
        raise RuntimeError(f"codex exec failed (exit={return_code}): {err_text[:600]}")
    return "\n".join(lines)


def run_structured_codex_prompt(
    *,
    prompt: str,
    output_schema: dict[str, object],
    workspace_id: str | None = None,
    session_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float | None = None,
    mcp_servers: list[str] | None = None,
    preferred_thread_id: str | None = None,
    use_cache: bool = True,
) -> dict[str, object]:
    parsed_payload, _ = run_structured_codex_prompt_with_usage(
        prompt=prompt,
        output_schema=output_schema,
        workspace_id=workspace_id,
        session_key=session_key,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        mcp_servers=mcp_servers,
        preferred_thread_id=preferred_thread_id,
        use_cache=use_cache,
    )
    return parsed_payload


def run_structured_codex_prompt_with_usage(
    *,
    prompt: str,
    output_schema: dict[str, object],
    workspace_id: str | None = None,
    session_key: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float | None = None,
    mcp_servers: list[str] | None = None,
    preferred_thread_id: str | None = None,
    use_cache: bool = True,
) -> tuple[dict[str, object], dict[str, int] | None]:
    normalized_workspace_id = str(workspace_id or "").strip() or None
    normalized_session_key = str(session_key or "").strip() or None
    selected_mcp_servers = normalize_chat_mcp_servers(mcp_servers, strict=False)
    mcp_config_text = build_selected_mcp_config_text(
        selected_servers=selected_mcp_servers,
        task_management_mcp_url=AGENT_CODEX_MCP_URL,
    )
    preferred_model = str(model or "").strip() or AGENT_CODEX_MODEL or None
    preferred_reasoning_effort = _normalize_reasoning_effort(reasoning_effort) or _normalize_reasoning_effort(
        AGENT_CODEX_REASONING_EFFORT
    )
    cache_key = _build_structured_prompt_cache_key(
        prompt=prompt,
        output_schema=output_schema,
        model=preferred_model,
        reasoning_effort=preferred_reasoning_effort,
        workspace_id=normalized_workspace_id,
        session_key=normalized_session_key,
        mcp_servers=selected_mcp_servers,
    )
    if use_cache:
        cached = _structured_prompt_cache_get(cache_key)
        if cached is not None:
            return cached
    runtime_timeout_seconds = _effective_timeout_seconds(
        timeout_seconds,
        fallback_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
    )
    run_codex_home_cleanup_if_due()
    with _chat_session_run_lock(
        workspace_id=normalized_workspace_id,
        chat_session_id=normalized_session_key,
        timeout_seconds=runtime_timeout_seconds,
    ):
        with _codex_home_env(
            mcp_config_text=mcp_config_text,
            runtime_config_text="",
            workspace_id=normalized_workspace_id,
            chat_session_id=normalized_session_key,
        ) as codex_env:
            final_message, usage, _, _, _ = _run_codex_app_server_with_optional_stream(
                start_prompt=prompt,
                resume_prompt=prompt,
                timeout_seconds=runtime_timeout_seconds,
                stream_events=False,
                model=preferred_model,
                reasoning_effort=preferred_reasoning_effort,
                output_schema=output_schema,
                preferred_thread_id=str(preferred_thread_id or "").strip() or None,
                env=codex_env,
            )
    try:
        parsed_generic = parse_json_object(
            final_message,
            empty_error="codex app-server returned an empty response while JSON schema was required",
            invalid_error="codex app-server returned a non-JSON response while JSON schema was required",
        )
    except ValueError as exc:
        snippet = str(final_message or "").strip().replace("\n", " ")[:320]
        detail = f"{exc} | response_snippet={snippet}" if snippet else str(exc)
        raise RuntimeError(detail) from exc
    normalized_payload = {str(key): value for key, value in parsed_generic.items()}
    if use_cache:
        _structured_prompt_cache_put(cache_key, payload=normalized_payload, usage=usage)
    return normalized_payload, usage


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
    preferred_model = str(ctx.get("model") or "").strip() or AGENT_CODEX_MODEL or None
    preferred_reasoning_effort = (
        _normalize_reasoning_effort(ctx.get("reasoning_effort"))
        or _normalize_reasoning_effort(AGENT_CODEX_REASONING_EFFORT)
    )
    runtime_timeout_seconds = _effective_timeout_seconds(
        ctx.get("executor_timeout_seconds"),
        fallback_seconds=AGENT_EXECUTOR_TIMEOUT_SECONDS,
    )
    task_run_cwd = _resolve_task_workdir(ctx.get("task_workdir"))
    structured_response = not (stream_events and stream_plain_text)
    start_prompt = _build_prompt(ctx, structured_response=structured_response)
    resume_prompt = _build_resume_prompt(ctx, structured_response=structured_response)
    full_prompt_segments = _prompt_segment_char_stats(ctx, mode="full")
    resume_prompt_segments = _prompt_segment_char_stats(ctx, mode="resume")
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["complete", "comment"]},
            "summary": {"type": "string"},
            "comment": {"type": ["string", "null"]},
            "execution_outcome_contract": {
                "type": "object",
                "properties": {
                    "contract_version": {"type": "integer", "enum": [1]},
                    "files_changed": {"type": "array", "items": {"type": "string"}},
                    "commit_sha": {"type": ["string", "null"]},
                    "branch": {"type": ["string", "null"]},
                    "tests_run": {"type": "boolean"},
                    "tests_passed": {"type": "boolean"},
                    "artifacts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string"},
                                "ref": {"type": "string"},
                                "description": {"type": ["string", "null"]},
                            },
                            "required": ["kind", "ref", "description"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "contract_version",
                    "files_changed",
                    "commit_sha",
                    "branch",
                    "tests_run",
                    "tests_passed",
                    "artifacts",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["action", "summary", "comment", "execution_outcome_contract"],
        "additionalProperties": False,
    }
    codex_session_id: str | None = None
    resume_attempted = False
    resume_succeeded = False
    run_codex_home_cleanup_if_due()
    with _chat_session_run_lock(
        workspace_id=workspace_id,
        chat_session_id=chat_session_id,
        timeout_seconds=runtime_timeout_seconds,
    ):
        with _codex_home_env(
            mcp_config_text=mcp_config_text,
            workspace_id=workspace_id,
            chat_session_id=chat_session_id,
        ) as codex_env:
            if stream_events:
                run_kwargs = {
                    "start_prompt": start_prompt,
                    "resume_prompt": resume_prompt,
                    "timeout_seconds": runtime_timeout_seconds,
                    "stream_events": True,
                    "model": preferred_model,
                    "reasoning_effort": preferred_reasoning_effort,
                    "output_schema": schema if structured_response else None,
                    "preferred_thread_id": preferred_codex_session_id,
                    "env": codex_env,
                }
                if task_run_cwd is not None:
                    run_kwargs["run_cwd"] = task_run_cwd
                final_message, usage, codex_session_id, resume_attempted, resume_succeeded = _run_codex_app_server_with_optional_stream(
                    **run_kwargs,
                )
                if structured_response:
                    parsed_payload = _try_parse_structured_reply_text(final_message)
                    if parsed_payload is None:
                        raise RuntimeError("codex app-server returned a non-JSON response while JSON schema was required")
                    out = parsed_payload
                else:
                    out = _build_plain_text_result(final_message)
            else:
                run_kwargs = {
                    "start_prompt": start_prompt,
                    "resume_prompt": resume_prompt,
                    "timeout_seconds": runtime_timeout_seconds,
                    "stream_events": False,
                    "model": preferred_model,
                    "reasoning_effort": preferred_reasoning_effort,
                    "output_schema": schema,
                    "preferred_thread_id": preferred_codex_session_id,
                    "env": codex_env,
                }
                if task_run_cwd is not None:
                    run_kwargs["run_cwd"] = task_run_cwd
                final_message, usage, codex_session_id, resume_attempted, resume_succeeded = _run_codex_app_server_with_optional_stream(
                    **run_kwargs,
                )
                parsed_payload = _try_parse_structured_reply_text(final_message)
                if parsed_payload is None:
                    raise RuntimeError("codex app-server returned a non-JSON response while JSON schema was required")
                out = parsed_payload

    action = str(out.get("action", "")).strip().lower()
    summary = str(out.get("summary", "")).strip()
    comment = out.get("comment")
    execution_outcome_contract = out.get("execution_outcome_contract")
    if not isinstance(execution_outcome_contract, dict):
        execution_outcome_contract = {
            "contract_version": 1,
            "files_changed": [],
            "commit_sha": None,
            "branch": None,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [],
        }
    if action not in {"complete", "comment"}:
        raise RuntimeError("codex adapter received invalid action")
    if comment is not None:
        comment = str(comment)
    if not summary and comment:
        summary = _derive_summary_from_text(comment)
    if not summary:
        summary = EMPTY_ASSISTANT_SUMMARY
    effective_prompt_mode = "resume" if (resume_attempted and resume_succeeded) else "full"
    effective_prompt_segments = resume_prompt_segments if effective_prompt_mode == "resume" else full_prompt_segments
    usage_payload: dict[str, object] | None = dict(usage or {})
    usage_payload["prompt_mode"] = effective_prompt_mode
    usage_payload["prompt_segment_chars"] = effective_prompt_segments
    print(
        json.dumps(
            {
                "action": action,
                "summary": summary,
                "comment": comment,
                "execution_outcome_contract": execution_outcome_contract,
                "usage": usage_payload,
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
