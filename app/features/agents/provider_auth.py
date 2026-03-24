from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pty
import re
import shutil
import signal
import subprocess
import threading
import time
from urllib.parse import parse_qsl, urlparse
import uuid

from shared.realtime import realtime_hub
from shared.settings import (
    AGENT_HOME_ROOT,
    CLAUDE_SYSTEM_FULL_NAME,
    CLAUDE_SYSTEM_USER_ID,
    CLAUDE_SYSTEM_USERNAME,
    CODEX_SYSTEM_FULL_NAME,
    CODEX_SYSTEM_USER_ID,
    CODEX_SYSTEM_USERNAME,
    OPENCODE_SYSTEM_FULL_NAME,
    OPENCODE_SYSTEM_USER_ID,
    OPENCODE_SYSTEM_USERNAME,
)

_DEFAULT_AGENT_HOME_ROOT = "/tmp/agent-home"
_PLACEHOLDER_AUTH_SENTINEL_KEY = "constructos_placeholder"
_PLACEHOLDER_AUTH_SENTINEL_VALUE = "codex-auth-unconfigured"
_DEVICE_AUTH_OUTPUT_LIMIT = 24
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b")
_URL_RE = re.compile(r"https?://\S+")
_CODEX_OAUTH_URL_RE = re.compile(
    r"https://auth\.openai\.com/oauth/authorize\?[^\s]+"
)
_CLAUDE_OAUTH_URL_RE = re.compile(
    r"https://platform\.claude\.com/oauth/authorize\?[^\s]+?&state=[A-Za-z0-9._~-]+"
)
_URL_CONTINUATION_RE = re.compile(r"^[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$")
_CLAUDE_URL_STOP_PREFIXES = (
    "Loginmethodpre-selected",
    "Pastecodehereifprompted",
    "Browserdidn'topen",
)
_DEVICE_AUTH_LOCK = threading.RLock()
_CLAUDE_LOGIN_METHODS = ("claudeai", "console")
_CODEX_LOGIN_METHODS = ("browser", "device_code")
_DEVICE_AUTH_START_WAIT_SECONDS = 1.5
_CLAUDE_DEVICE_AUTH_START_WAIT_SECONDS = 6.0
_CLAUDE_DEVICE_AUTH_SUBMIT_WAIT_SECONDS = 12.0
_DEVICE_AUTH_START_WAIT_STEP_SECONDS = 0.05
_AUTH_REALTIME_CHANNEL = "agent-auth"
_AUTH_REALTIME_REASON_PREFIX = "agent-auth:"


@dataclass(frozen=True)
class AuthProviderSpec:
    provider: str
    display_name: str
    system_user_id: str
    system_username: str
    system_full_name: str
    host_auth_relative_path: tuple[str, ...]
    override_auth_relative_path: tuple[str, ...]
    login_command: tuple[str, ...]


_AUTH_PROVIDER_SPECS: dict[str, AuthProviderSpec] = {
    "codex": AuthProviderSpec(
        provider="codex",
        display_name="Codex",
        system_user_id=CODEX_SYSTEM_USER_ID,
        system_username=CODEX_SYSTEM_USERNAME,
        system_full_name=CODEX_SYSTEM_FULL_NAME,
        host_auth_relative_path=(".codex", "auth.json"),
        override_auth_relative_path=(".codex", "auth.json"),
        login_command=("codex", "login", "-c", 'cli_auth_credentials_store="file"'),
    ),
    "claude": AuthProviderSpec(
        provider="claude",
        display_name="Claude",
        system_user_id=CLAUDE_SYSTEM_USER_ID,
        system_username=CLAUDE_SYSTEM_USERNAME,
        system_full_name=CLAUDE_SYSTEM_FULL_NAME,
        host_auth_relative_path=(".claude.json",),
        override_auth_relative_path=(".claude.json",),
        login_command=("claude",),
    ),
    "opencode": AuthProviderSpec(
        provider="opencode",
        display_name="OpenCode",
        system_user_id=OPENCODE_SYSTEM_USER_ID,
        system_username=OPENCODE_SYSTEM_USERNAME,
        system_full_name=OPENCODE_SYSTEM_FULL_NAME,
        host_auth_relative_path=(".opencode", "auth.json"),
        override_auth_relative_path=(".opencode", "auth.json"),
        login_command=(),
    ),
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    root_raw = str(AGENT_HOME_ROOT or "").strip() or _DEFAULT_AGENT_HOME_ROOT
    return Path(root_raw).expanduser().resolve()


def _strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(value or ""))


def _normalize_terminal_text_for_matching(value: str) -> str:
    stripped = _strip_ansi(value)
    out_chars: list[str] = []
    for char in stripped:
        codepoint = ord(char)
        if char in "\n\r\t":
            out_chars.append(" ")
            continue
        if codepoint < 32 or codepoint == 127:
            out_chars.append(" ")
            continue
        out_chars.append(char)
    return " ".join("".join(out_chars).split())


def _normalize_terminal_text_compact(value: str) -> str:
    normalized = _normalize_terminal_text_for_matching(value).lower()
    return "".join(char for char in normalized if char.isalnum())


def _read_json_file(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in parsed.items()}


def _provider_spec(provider: str) -> AuthProviderSpec:
    normalized = str(provider or "").strip().lower()
    spec = _AUTH_PROVIDER_SPECS.get(normalized)
    if spec is None:
        raise ValueError(f"Unsupported auth provider: {provider}")
    return spec


def _publish_auth_realtime_signal(provider: str) -> None:
    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider:
        return
    try:
        realtime_hub.publish(
            _AUTH_REALTIME_CHANNEL,
            reason=f"{_AUTH_REALTIME_REASON_PREFIX}{normalized_provider}",
        )
    except Exception:
        pass


def _normalize_claude_login_method(value: object | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return normalized if normalized in _CLAUDE_LOGIN_METHODS else None


def _normalize_codex_login_method(value: object | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return normalized if normalized in _CODEX_LOGIN_METHODS else None


def _resolve_provider_settings_path(provider: str, home_path: Path) -> Path | None:
    spec = _provider_spec(provider)
    if spec.provider == "claude":
        return home_path / ".claude" / "settings.json"
    return None


def _resolve_provider_configured_login_method(provider: str, home_path: Path | None = None) -> str | None:
    spec = _provider_spec(provider)
    if spec.provider != "claude":
        return None
    effective_home = home_path or resolve_provider_system_override_home(spec.provider)
    settings_path = _resolve_provider_settings_path(spec.provider, effective_home)
    if settings_path is None or not settings_path.exists() or not settings_path.is_file():
        return None
    payload = _read_json_file(settings_path)
    if not isinstance(payload, dict):
        return None
    return _normalize_claude_login_method(payload.get("forceLoginMethod"))


def _persist_provider_login_settings(provider: str, home_path: Path, login_method: str | None) -> None:
    spec = _provider_spec(provider)
    if spec.provider != "claude":
        return
    settings_path = _resolve_provider_settings_path(spec.provider, home_path)
    if settings_path is None:
        return
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_json_file(settings_path) or {}
    payload["forceLoginMethod"] = _normalize_claude_login_method(login_method) or "claudeai"
    settings_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _resolve_provider_login_method(provider: str, requested_login_method: object | None = None) -> str | None:
    spec = _provider_spec(provider)
    if spec.provider == "claude":
        normalized = _normalize_claude_login_method(requested_login_method)
        if normalized is not None:
            return normalized
        return _resolve_provider_configured_login_method(spec.provider) or "claudeai"
    if spec.provider == "codex":
        return _normalize_codex_login_method(requested_login_method) or "device_code"
    return None


def _provider_uses_interactive_login(provider: str) -> bool:
    return _provider_spec(provider).provider == "claude"


def _provider_device_auth_start_wait_seconds(provider: str) -> float:
    return _CLAUDE_DEVICE_AUTH_START_WAIT_SECONDS if _provider_spec(provider).provider == "claude" else _DEVICE_AUTH_START_WAIT_SECONDS


def _build_provider_login_command(spec: AuthProviderSpec, *, login_method: str | None) -> tuple[str, ...]:
    if spec.provider != "codex":
        return spec.login_command
    normalized_login_method = _normalize_codex_login_method(login_method) or "device_code"
    base_command = list(spec.login_command)
    if normalized_login_method == "device_code":
        base_command.insert(2, "--device-auth")
    return tuple(base_command)


def _launch_provider_device_auth_process(
    spec: AuthProviderSpec,
    *,
    home_path: Path,
    login_method: str | None,
) -> tuple[subprocess.Popen[str], int | None]:
    env = {
        **os.environ,
        "HOME": str(home_path),
    }
    command = _build_provider_login_command(spec, login_method=login_method)
    if _provider_uses_interactive_login(spec.provider):
        env["TERM"] = str(os.environ.get("TERM") or "xterm-256color")
        master_fd, slave_fd = pty.openpty()
        try:
            process = subprocess.Popen(
                list(command),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                text=False,
                bufsize=0,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            try:
                os.close(slave_fd)
            except Exception:
                pass
        return process, master_fd
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        start_new_session=True,
    )
    return process, None


def is_placeholder_auth_file(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    payload = _read_json_file(path)
    if payload is None:
        return False
    return str(payload.get(_PLACEHOLDER_AUTH_SENTINEL_KEY) or "").strip() == _PLACEHOLDER_AUTH_SENTINEL_VALUE


def is_usable_auth_file(path: Path | None) -> bool:
    if path is None or not path.exists() or not path.is_file():
        return False
    return not is_placeholder_auth_file(path)


def _read_claude_auth_status(home_path: Path) -> dict[str, object] | None:
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "HOME": str(home_path),
            },
            check=False,
            timeout=10,
        )
    except Exception:
        return None
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    try:
        payload = json.loads(output)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _provider_auth_home_ready(provider: str, home_path: Path | None) -> bool:
    spec = _provider_spec(provider)
    if spec.provider == "opencode":
        return shutil.which("opencode") is not None
    if home_path is None:
        return False
    auth_path = home_path.joinpath(*spec.override_auth_relative_path)
    if not is_usable_auth_file(auth_path):
        return False
    if spec.provider != "claude":
        return True
    status_payload = _read_claude_auth_status(home_path)
    return bool(status_payload and status_payload.get("loggedIn") is True)


def _provider_home_from_auth_path(provider: str, auth_path: Path | None) -> Path | None:
    if auth_path is None:
        return None
    depth = len(_provider_spec(provider).override_auth_relative_path)
    home_path = auth_path
    for _ in range(depth):
        home_path = home_path.parent
    return home_path


def resolve_provider_host_auth_path(provider: str) -> Path | None:
    spec = _provider_spec(provider)
    candidate = Path.home().joinpath(*spec.host_auth_relative_path)
    return candidate if _provider_auth_home_ready(provider, Path.home()) else None


def resolve_provider_system_override_home(provider: str) -> Path:
    spec = _provider_spec(provider)
    username_part = _normalize_path_component(spec.system_username, fallback=f"{spec.provider}-bot")
    return _resolve_codex_home_root() / "auth" / "system" / username_part


def resolve_provider_system_override_auth_path(provider: str) -> Path:
    return resolve_provider_system_override_home(provider).joinpath(*_provider_spec(provider).override_auth_relative_path)


def resolve_provider_effective_auth_source(provider: str, _actor_user_id: str | None = None) -> str:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "opencode":
        return "runtime_builtin" if shutil.which("opencode") is not None else "none"
    if _provider_auth_home_ready(provider, resolve_provider_system_override_home(provider)):
        return "system_override"
    if resolve_provider_host_auth_path(provider) is not None:
        return "host_mount"
    return "none"


def resolve_provider_effective_auth_path(provider: str, _actor_user_id: str | None = None) -> Path | None:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "opencode":
        return None
    override_path = resolve_provider_system_override_auth_path(provider)
    if _provider_auth_home_ready(provider, _provider_home_from_auth_path(provider, override_path)):
        return override_path
    return resolve_provider_host_auth_path(provider)


def ensure_provider_system_override_home(provider: str) -> Path:
    spec = _provider_spec(provider)
    home_path = resolve_provider_system_override_home(provider)
    if spec.provider == "opencode":
        home_path.mkdir(parents=True, exist_ok=True)
        (home_path / ".opencode").mkdir(parents=True, exist_ok=True)
        return home_path
    if spec.provider == "codex":
        codex_dir = home_path / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")
        return home_path
    home_path.mkdir(parents=True, exist_ok=True)
    (home_path / ".claude").mkdir(parents=True, exist_ok=True)
    (home_path / ".codex").mkdir(parents=True, exist_ok=True)
    return home_path


@dataclass
class DeviceAuthSessionState:
    session_id: str
    status: str
    started_at: str
    updated_at: str
    requested_by_user_id: str | None = None
    login_method: str | None = None
    verification_uri: str | None = None
    local_callback_url: str | None = None
    user_code: str | None = None
    error: str | None = None
    output_excerpt: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None
    pty_master_fd: int | None = None
    cancel_requested: bool = False
    theme_prompt_confirmed: bool = False
    slash_login_sent: bool = False
    login_method_choice_sent: bool = False
    login_method_choice_scheduled: bool = False
    completion_prompt_confirmed: bool = False
    trust_prompt_confirmed: bool = False


_DEVICE_AUTH_SESSIONS: dict[str, DeviceAuthSessionState | None] = {provider: None for provider in _AUTH_PROVIDER_SPECS}


def _schedule_interactive_auth_write(*, provider: str, session_id: str, master_fd: int, data: bytes, delay_seconds: float) -> None:
    def _writer() -> None:
        with _DEVICE_AUTH_LOCK:
            session = _DEVICE_AUTH_SESSIONS.get(provider)
            if session is None or session.session_id != session_id or session.cancel_requested:
                return
        try:
            os.write(master_fd, data)
        except Exception:
            return

    timer = threading.Timer(max(0.0, delay_seconds), _writer)
    timer.daemon = True
    timer.start()


def _refresh_verification_uri_from_output(session: DeviceAuthSessionState) -> None:
    existing_verification_uri = str(session.verification_uri or "").strip()
    existing_local_callback_url = str(session.local_callback_url or "").strip()
    preserve_codex_oauth_uri = bool(_CODEX_OAUTH_URL_RE.fullmatch(existing_verification_uri))
    preserve_claude_oauth_uri = bool(_CLAUDE_OAUTH_URL_RE.fullmatch(existing_verification_uri))
    lines = [str(line or "").strip() for line in session.output_excerpt if str(line or "").strip()]
    if not lines:
        return
    generic_candidates: list[str] = []
    for index, line in enumerate(lines):
        if "http://" not in line and "https://" not in line:
            continue
        candidate_parts = [line]
        for continuation in lines[index + 1 :]:
            if continuation.startswith(_CLAUDE_URL_STOP_PREFIXES):
                break
            if not _URL_CONTINUATION_RE.fullmatch(continuation):
                break
            candidate_parts.append(continuation)
        candidate = "".join(candidate_parts).rstrip(".,")
        codex_match = _CODEX_OAUTH_URL_RE.search(candidate)
        if codex_match:
            codex_url = codex_match.group(0).rstrip(".,")
            session.verification_uri = codex_url
            redirect_uri = dict(parse_qsl(urlparse(codex_url).query, keep_blank_values=True)).get("redirect_uri")
            redirect_uri = str(redirect_uri or "").strip()
            if redirect_uri:
                session.local_callback_url = redirect_uri
            return
        if not existing_local_callback_url:
            callback_match = _URL_RE.search(candidate)
            if callback_match:
                callback_url = callback_match.group(0).rstrip(".,")
                parsed_callback_url = urlparse(callback_url)
                if (
                    parsed_callback_url.scheme == "http"
                    and str(parsed_callback_url.hostname or "").strip().lower() in {"localhost", "127.0.0.1"}
                    and parsed_callback_url.port is not None
                ):
                    session.local_callback_url = callback_url
        claude_match = _CLAUDE_OAUTH_URL_RE.search(candidate)
        if claude_match:
            session.verification_uri = claude_match.group(0).rstrip(".,")
            return
        if preserve_codex_oauth_uri or preserve_claude_oauth_uri:
            continue
        generic_candidates.append(candidate)
    for candidate in generic_candidates:
        match = _URL_RE.search(candidate)
        if match:
            session.verification_uri = match.group(0).rstrip(".,")
            return


def _append_output_line(
    provider_or_session: str | DeviceAuthSessionState,
    session_or_line: DeviceAuthSessionState | str,
    line: str | None = None,
) -> None:
    if isinstance(provider_or_session, DeviceAuthSessionState):
        provider = ""
        session = provider_or_session
        text_input = str(session_or_line or "")
    else:
        provider = str(provider_or_session or "").strip().lower()
        session = session_or_line if isinstance(session_or_line, DeviceAuthSessionState) else None
        text_input = str(line or "")
    if session is None:
        return
    text = _strip_ansi(text_input).strip()
    if not text:
        return
    previous_verification_uri = str(session.verification_uri or "").strip()
    previous_user_code = str(session.user_code or "").strip()
    previous_error = str(session.error or "").strip()
    session.output_excerpt.append(text[:600])
    if len(session.output_excerpt) > _DEVICE_AUTH_OUTPUT_LIMIT:
        session.output_excerpt = session.output_excerpt[-_DEVICE_AUTH_OUTPUT_LIMIT :]
    _refresh_verification_uri_from_output(session)
    if session.user_code is None:
        code_match = _DEVICE_CODE_RE.search(text)
        if code_match:
            session.user_code = code_match.group(0)
    if (
        str(session.verification_uri or "").strip() != previous_verification_uri
        or str(session.user_code or "").strip() != previous_user_code
        or str(session.error or "").strip() != previous_error
    ):
        if provider:
            _publish_auth_realtime_signal(provider)


def _serialize_device_auth_session(session: DeviceAuthSessionState | None) -> dict[str, object] | None:
    if session is None:
        return None
    return {
        "id": session.session_id,
        "status": session.status,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "login_method": session.login_method,
        "verification_uri": session.verification_uri,
        "local_callback_url": session.local_callback_url,
        "user_code": session.user_code,
        "error": session.error,
        "output_excerpt": list(session.output_excerpt),
    }


def _build_provider_auth_status(provider: str) -> dict[str, object]:
    spec = _provider_spec(provider)
    override_path = resolve_provider_system_override_auth_path(provider)
    override_available = _provider_auth_home_ready(provider, _provider_home_from_auth_path(provider, override_path))
    host_path = resolve_provider_host_auth_path(provider)
    effective_source = resolve_provider_effective_auth_source(provider)
    login_session = _serialize_device_auth_session(_DEVICE_AUTH_SESSIONS.get(spec.provider))
    override_updated_at = None
    if override_available:
        try:
            override_updated_at = datetime.fromtimestamp(
                override_path.stat().st_mtime,
                tz=timezone.utc,
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            override_updated_at = None
    selected_login_method = None
    if isinstance(login_session, dict):
        selected_login_method = (
            _normalize_claude_login_method(login_session.get("login_method"))
            if spec.provider == "claude"
            else _normalize_codex_login_method(login_session.get("login_method"))
        )
    if selected_login_method is None:
        selected_login_method = (
            _resolve_provider_configured_login_method(spec.provider)
            if spec.provider == "claude"
            else _resolve_provider_login_method(spec.provider)
        )
    return {
        "provider": spec.provider,
        "provider_label": spec.display_name,
        "configured": effective_source != "none",
        "effective_source": effective_source,
        "host_auth_available": host_path is not None,
        "override_available": override_available,
        "override_updated_at": override_updated_at,
        "scope": "system",
        "target_actor_user_id": spec.system_user_id,
        "target_actor_username": spec.system_username,
        "target_actor_full_name": spec.system_full_name,
        "selected_login_method": selected_login_method,
        "supported_login_methods": (
            list(_CLAUDE_LOGIN_METHODS)
            if spec.provider == "claude"
            else list(_CODEX_LOGIN_METHODS) if spec.provider == "codex" else []
        ),
        "login_session": login_session,
    }


def get_provider_auth_status(provider: str, _requested_by_user_id: str | None = None) -> dict[str, object]:
    with _DEVICE_AUTH_LOCK:
        return _build_provider_auth_status(provider)


def get_provider_device_auth_session(provider: str, session_id: str) -> dict[str, object] | None:
    spec = _provider_spec(provider)
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(spec.provider)
        if session is None or session.session_id != normalized_session_id:
            return None
        return _serialize_device_auth_session(session)


def _finalize_device_auth_session(*, provider: str, session_id: str, returncode: int) -> None:
    spec = _provider_spec(provider)
    home_path = resolve_provider_system_override_home(provider)
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(spec.provider)
        if session is None or session.session_id != session_id:
            return
        session.process = None
        session.updated_at = _utcnow_iso()
        if session.cancel_requested:
            session.status = "cancelled"
            session.error = None
            return
        if _provider_auth_home_ready(spec.provider, home_path):
            session.status = "succeeded"
            session.error = None
            return
        session.status = "failed"
        if session.error:
            return
        detail = session.output_excerpt[-1] if session.output_excerpt else ""
        if detail:
            session.error = detail
        else:
            session.error = f"{spec.display_name} login exited with status {returncode}."
    _publish_auth_realtime_signal(provider)


def _handle_interactive_device_auth_output(
    *,
    provider: str,
    session_id: str,
    chunk_text: str,
    master_fd: int,
) -> None:
    normalized = _strip_ansi(chunk_text).replace("\r", "\n")
    normalized_for_matching = _normalize_terminal_text_for_matching(chunk_text)
    normalized_compact = _normalize_terminal_text_compact(chunk_text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    should_confirm_theme = False
    should_schedule_login_command = False
    login_method_choice: bytes | None = None
    schedule_login_method_choice = False
    should_confirm_completion = False
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(provider)
        if session is None or session.session_id != session_id:
            return
        for line in lines:
            _append_output_line(provider, session, line)
        if (
            not session.theme_prompt_confirmed
            and (
                "Choose the text style" in normalized_for_matching
                or "choosethetextstylethatlooksbestwithyourterminal" in normalized_compact
            )
        ):
            session.theme_prompt_confirmed = True
            should_confirm_theme = True
        if (
            provider == "claude"
            and session.theme_prompt_confirmed
            and not session.slash_login_sent
            and (
                "Syntax highlighting available only in native build" in normalized_for_matching
                or "syntaxhighlightingavailableonlyinnativebuild" in normalized_compact
                or "syntaxtheme" in normalized_compact
            )
        ):
            session.slash_login_sent = True
            should_schedule_login_command = True
            if not session.login_method_choice_scheduled:
                session.login_method_choice_scheduled = True
                schedule_login_method_choice = True
        if (
            provider == "claude"
            and session.slash_login_sent
            and not session.login_method_choice_sent
            and (
                "Select login method:" in normalized_for_matching
                or "selectloginmethod" in normalized_compact
            )
        ):
            session.login_method_choice_sent = True
            selected = _normalize_claude_login_method(session.login_method) or "claudeai"
            login_method_choice = b"\x1b[B\r" if selected == "console" else b"\r"
        if (
            provider == "claude"
            and (
                "Press Enter to continue" in normalized_for_matching
                or "pressentertocontinue" in normalized_compact
            )
        ):
            session.completion_prompt_confirmed = True
            should_confirm_completion = True
        if (
            provider == "claude"
            and not session.trust_prompt_confirmed
            and (
                "Yes, I trust this folder" in normalized_for_matching
                or "yesitrustthisfolder" in normalized_compact
            )
        ):
            session.trust_prompt_confirmed = True
            should_confirm_completion = True
        session.updated_at = _utcnow_iso()
    if should_confirm_theme:
        try:
            os.write(master_fd, b"\r")
        except Exception:
            pass
    if should_schedule_login_command:
        _schedule_interactive_auth_write(
            provider=provider,
            session_id=session_id,
            master_fd=master_fd,
            data=b"/login\r",
            delay_seconds=0.6,
        )
    if schedule_login_method_choice:
        selected = _normalize_claude_login_method(session.login_method) or "claudeai"
        delayed_choice = b"\x1b[B\r" if selected == "console" else b"\r"
        _schedule_interactive_auth_write(
            provider=provider,
            session_id=session_id,
            master_fd=master_fd,
            data=delayed_choice,
            delay_seconds=1.8,
        )
    if login_method_choice is not None:
        try:
            os.write(master_fd, login_method_choice.replace(b"\r", b"\r\n"))
        except Exception:
            pass
    if should_confirm_completion:
        try:
            os.write(master_fd, b"\r")
        except Exception:
            pass


def _monitor_interactive_device_auth_session(
    *,
    provider: str,
    session_id: str,
    process: subprocess.Popen[str],
    master_fd: int,
) -> None:
    try:
        while True:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            _handle_interactive_device_auth_output(
                provider=provider,
                session_id=session_id,
                chunk_text=chunk.decode("utf-8", errors="ignore"),
                master_fd=master_fd,
            )
            if provider != "claude" and _provider_auth_home_ready(provider, resolve_provider_system_override_home(provider)) and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except Exception:
                    try:
                        process.terminate()
                    except Exception:
                        pass
    finally:
        try:
            os.close(master_fd)
        except Exception:
            pass
    returncode = int(process.wait())
    _finalize_device_auth_session(provider=provider, session_id=session_id, returncode=returncode)


def _monitor_device_auth_session(*, provider: str, session_id: str, process: subprocess.Popen[str]) -> None:
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(provider)
        master_fd = None
        if session is not None and session.session_id == session_id:
            master_fd = session.pty_master_fd
    if master_fd is not None:
        _monitor_interactive_device_auth_session(
            provider=provider,
            session_id=session_id,
            process=process,
            master_fd=master_fd,
        )
        return
    assert process.stdout is not None
    for raw_line in process.stdout:
        should_terminate = False
        with _DEVICE_AUTH_LOCK:
            session = _DEVICE_AUTH_SESSIONS.get(provider)
            if session is None or session.session_id != session_id:
                continue
            _append_output_line(provider, session, raw_line)
            session.updated_at = _utcnow_iso()
            if provider != "claude" and _provider_auth_home_ready(provider, resolve_provider_system_override_home(provider)):
                session.status = "succeeded"
                session.error = None
                should_terminate = True
        if should_terminate:
            _publish_auth_realtime_signal(provider)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except Exception:
                    try:
                        process.terminate()
                    except Exception:
                        pass
            break
    returncode = int(process.wait())
    _finalize_device_auth_session(provider=provider, session_id=session_id, returncode=returncode)


def start_provider_device_auth_session(
    provider: str,
    requested_by_user_id: str | None = None,
    *,
    login_method: str | None = None,
) -> dict[str, object]:
    spec = _provider_spec(provider)
    if spec.provider not in {"codex", "claude"}:
        raise ValueError(f"{spec.display_name} does not require device authentication.")
    normalized_user_id = str(requested_by_user_id or "").strip() or None
    resolved_login_method = _resolve_provider_login_method(spec.provider, login_method)
    if spec.provider == "claude" and resolved_login_method is None:
        raise ValueError("Unsupported Claude login method.")
    if spec.provider == "codex" and resolved_login_method is None:
        raise ValueError("Unsupported Codex login method.")
    with _DEVICE_AUTH_LOCK:
        existing = _DEVICE_AUTH_SESSIONS.get(spec.provider)
        if existing is not None and existing.status == "pending" and existing.process is not None and existing.process.poll() is None:
            return _build_provider_auth_status(spec.provider)

        home_path = ensure_provider_system_override_home(spec.provider)
        _persist_provider_login_settings(spec.provider, home_path, resolved_login_method)
        session = DeviceAuthSessionState(
            session_id=str(uuid.uuid4()),
            status="pending",
            started_at=_utcnow_iso(),
            updated_at=_utcnow_iso(),
            requested_by_user_id=normalized_user_id,
            login_method=resolved_login_method,
        )
        process, pty_master_fd = _launch_provider_device_auth_process(
            spec,
            home_path=home_path,
            login_method=resolved_login_method,
        )
        session.process = process
        session.pty_master_fd = pty_master_fd
        _DEVICE_AUTH_SESSIONS[spec.provider] = session
        watcher = threading.Thread(
            target=_monitor_device_auth_session,
            kwargs={
                "provider": spec.provider,
                "session_id": session.session_id,
                "process": process,
            },
            daemon=True,
        )
        watcher.start()
    _publish_auth_realtime_signal(spec.provider)
    deadline = time.monotonic() + _provider_device_auth_start_wait_seconds(spec.provider)
    while time.monotonic() < deadline:
        with _DEVICE_AUTH_LOCK:
            current = _DEVICE_AUTH_SESSIONS.get(spec.provider)
            if current is None:
                break
            if current.status != "pending":
                return _build_provider_auth_status(spec.provider)
            if current.verification_uri or current.user_code or current.error:
                return _build_provider_auth_status(spec.provider)
        time.sleep(_DEVICE_AUTH_START_WAIT_STEP_SECONDS)
    with _DEVICE_AUTH_LOCK:
        return _build_provider_auth_status(spec.provider)


def cancel_provider_device_auth_session(provider: str, _requested_by_user_id: str | None = None) -> dict[str, object]:
    spec = _provider_spec(provider)
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(spec.provider)
        if session is None:
            return _build_provider_auth_status(spec.provider)
        process = session.process
        if process is None or process.poll() is not None:
            return _build_provider_auth_status(spec.provider)
        session.cancel_requested = True
        session.status = "cancelled"
        session.error = None
        session.updated_at = _utcnow_iso()
    _publish_auth_realtime_signal(spec.provider)
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
    return get_provider_auth_status(spec.provider)


def submit_provider_device_auth_code(
    provider: str,
    code: str,
    _requested_by_user_id: str | None = None,
) -> dict[str, object]:
    spec = _provider_spec(provider)
    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise ValueError("Authentication code is required.")
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSIONS.get(spec.provider)
        if session is None or session.status != "pending" or session.process is None or session.process.poll() is not None:
            raise ValueError(f"No active {spec.display_name} authentication session.")
        master_fd = session.pty_master_fd
        if master_fd is None:
            raise ValueError(f"{spec.display_name} authentication does not accept manual code entry.")
        session.updated_at = _utcnow_iso()
    try:
        os.write(master_fd, normalized_code.encode("utf-8", errors="ignore") + b"\r")
    except Exception as exc:
        raise ValueError(f"Failed to submit {spec.display_name} authentication code.") from exc
    if spec.provider == "claude":
        deadline = time.monotonic() + _CLAUDE_DEVICE_AUTH_SUBMIT_WAIT_SECONDS
        while time.monotonic() < deadline:
            payload = get_provider_auth_status(spec.provider)
            login_session = payload.get("login_session") if isinstance(payload, dict) else None
            status = ""
            if isinstance(login_session, dict):
                status = str(login_session.get("status") or "").strip().lower()
            if payload.get("configured") or status in {"succeeded", "failed", "cancelled"}:
                return payload
            time.sleep(_DEVICE_AUTH_START_WAIT_STEP_SECONDS)
    return get_provider_auth_status(spec.provider)


def delete_provider_system_override_auth(provider: str, _requested_by_user_id: str | None = None) -> dict[str, object]:
    spec = _provider_spec(provider)
    cancel_provider_device_auth_session(spec.provider)
    override_home = resolve_provider_system_override_home(spec.provider)
    try:
        shutil.rmtree(override_home)
    except FileNotFoundError:
        pass
    with _DEVICE_AUTH_LOCK:
        _DEVICE_AUTH_SESSIONS[spec.provider] = None
        payload = _build_provider_auth_status(spec.provider)
    _publish_auth_realtime_signal(spec.provider)
    return payload
