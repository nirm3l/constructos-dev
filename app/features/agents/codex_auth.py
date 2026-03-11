from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import uuid

from shared.settings import AGENT_SYSTEM_USER_ID, AGENT_SYSTEM_USERNAME

_DEFAULT_CODEX_HOME_ROOT = "/tmp/codex-home"
_PLACEHOLDER_AUTH_SENTINEL_KEY = "constructos_placeholder"
_PLACEHOLDER_AUTH_SENTINEL_VALUE = "codex-auth-unconfigured"
_DEVICE_AUTH_OUTPUT_LIMIT = 24
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b")
_URL_RE = re.compile(r"https?://\S+")
_DEVICE_AUTH_LOCK = threading.RLock()


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
    root_raw = str(os.getenv("AGENT_CODEX_HOME_ROOT", _DEFAULT_CODEX_HOME_ROOT)).strip() or _DEFAULT_CODEX_HOME_ROOT
    return Path(root_raw).expanduser().resolve()


def _strip_ansi(value: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(value or ""))


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


def resolve_host_auth_path() -> Path | None:
    candidate = Path.home() / ".codex" / "auth.json"
    return candidate if is_usable_auth_file(candidate) else None


def resolve_host_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def resolve_system_override_home() -> Path:
    username_part = _normalize_path_component(AGENT_SYSTEM_USERNAME, fallback="codex-bot")
    return _resolve_codex_home_root() / "auth" / "system" / username_part


def resolve_system_override_auth_path() -> Path:
    return resolve_system_override_home() / ".codex" / "auth.json"


def resolve_system_override_config_path() -> Path:
    return resolve_system_override_home() / ".codex" / "config.toml"


def resolve_effective_auth_source(_actor_user_id: str | None = None) -> str:
    if is_usable_auth_file(resolve_system_override_auth_path()):
        return "system_override"
    if resolve_host_auth_path() is not None:
        return "host_mount"
    return "none"


def resolve_effective_auth_path(_actor_user_id: str | None = None) -> Path | None:
    override_path = resolve_system_override_auth_path()
    if is_usable_auth_file(override_path):
        return override_path
    return resolve_host_auth_path()


def ensure_system_override_home() -> Path:
    home_path = resolve_system_override_home()
    codex_dir = home_path / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")
    return home_path


@dataclass
class DeviceAuthSessionState:
    session_id: str
    status: str
    started_at: str
    updated_at: str
    requested_by_user_id: str | None = None
    verification_uri: str | None = None
    user_code: str | None = None
    error: str | None = None
    output_excerpt: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False


_DEVICE_AUTH_SESSION: DeviceAuthSessionState | None = None


def _append_output_line(session: DeviceAuthSessionState, line: str) -> None:
    text = _strip_ansi(line).strip()
    if not text:
        return
    session.output_excerpt.append(text[:600])
    if len(session.output_excerpt) > _DEVICE_AUTH_OUTPUT_LIMIT:
        session.output_excerpt = session.output_excerpt[-_DEVICE_AUTH_OUTPUT_LIMIT :]
    if session.verification_uri is None:
        url_match = _URL_RE.search(text)
        if url_match:
            session.verification_uri = url_match.group(0).rstrip(".,")
    if session.user_code is None:
        code_match = _DEVICE_CODE_RE.search(text)
        if code_match:
            session.user_code = code_match.group(0)


def _serialize_device_auth_session(session: DeviceAuthSessionState | None) -> dict[str, object] | None:
    if session is None:
        return None
    return {
        "id": session.session_id,
        "status": session.status,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "verification_uri": session.verification_uri,
        "user_code": session.user_code,
        "error": session.error,
        "output_excerpt": list(session.output_excerpt),
    }


def _build_device_auth_status() -> dict[str, object]:
    override_path = resolve_system_override_auth_path()
    override_available = is_usable_auth_file(override_path)
    host_path = resolve_host_auth_path()
    effective_source = resolve_effective_auth_source()
    login_session = _serialize_device_auth_session(_DEVICE_AUTH_SESSION)
    override_updated_at = None
    if override_available:
        try:
            override_updated_at = datetime.fromtimestamp(
                override_path.stat().st_mtime,
                tz=timezone.utc,
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            override_updated_at = None
    return {
        "configured": effective_source != "none",
        "effective_source": effective_source,
        "host_auth_available": host_path is not None,
        "override_available": override_available,
        "override_updated_at": override_updated_at,
        "scope": "system",
        "target_actor_user_id": AGENT_SYSTEM_USER_ID,
        "target_actor_username": AGENT_SYSTEM_USERNAME,
        "login_session": login_session,
    }


def get_codex_auth_status(_requested_by_user_id: str | None = None) -> dict[str, object]:
    with _DEVICE_AUTH_LOCK:
        return _build_device_auth_status()


def _finalize_device_auth_session(*, session_id: str, returncode: int) -> None:
    auth_path = resolve_system_override_auth_path()
    global _DEVICE_AUTH_SESSION
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSION
        if session is None or session.session_id != session_id:
            return
        session.process = None
        session.updated_at = _utcnow_iso()
        if session.cancel_requested:
            session.status = "cancelled"
            session.error = None
            return
        if returncode == 0 and is_usable_auth_file(auth_path):
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
            session.error = f"Codex login exited with status {returncode}."


def _monitor_device_auth_session(*, session_id: str, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for raw_line in process.stdout:
        with _DEVICE_AUTH_LOCK:
            session = _DEVICE_AUTH_SESSION
            if session is None or session.session_id != session_id:
                continue
            _append_output_line(session, raw_line)
            session.updated_at = _utcnow_iso()
    returncode = int(process.wait())
    _finalize_device_auth_session(session_id=session_id, returncode=returncode)


def start_device_auth_session(requested_by_user_id: str | None = None) -> dict[str, object]:
    global _DEVICE_AUTH_SESSION
    normalized_user_id = str(requested_by_user_id or "").strip() or None
    with _DEVICE_AUTH_LOCK:
        existing = _DEVICE_AUTH_SESSION
        if existing is not None and existing.status == "pending" and existing.process is not None and existing.process.poll() is None:
            return _build_device_auth_status()

        home_path = ensure_system_override_home()
        session = DeviceAuthSessionState(
            session_id=str(uuid.uuid4()),
            status="pending",
            started_at=_utcnow_iso(),
            updated_at=_utcnow_iso(),
            requested_by_user_id=normalized_user_id,
        )
        process = subprocess.Popen(
            ["codex", "login", "--device-auth", "-c", 'cli_auth_credentials_store="file"'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "HOME": str(home_path)},
            start_new_session=True,
        )
        session.process = process
        _DEVICE_AUTH_SESSION = session
        watcher = threading.Thread(
            target=_monitor_device_auth_session,
            kwargs={
                "session_id": session.session_id,
                "process": process,
            },
            daemon=True,
        )
        watcher.start()
        return _build_device_auth_status()


def cancel_device_auth_session(_requested_by_user_id: str | None = None) -> dict[str, object]:
    global _DEVICE_AUTH_SESSION
    with _DEVICE_AUTH_LOCK:
        session = _DEVICE_AUTH_SESSION
        if session is None:
            return _build_device_auth_status()
        process = session.process
        if process is None or process.poll() is not None:
            return _build_device_auth_status()
        session.cancel_requested = True
        session.status = "cancelled"
        session.error = None
        session.updated_at = _utcnow_iso()
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
    return get_codex_auth_status()


def delete_system_override_auth(_requested_by_user_id: str | None = None) -> dict[str, object]:
    global _DEVICE_AUTH_SESSION
    cancel_device_auth_session()
    override_home = resolve_system_override_home()
    try:
        shutil.rmtree(override_home)
    except FileNotFoundError:
        pass
    with _DEVICE_AUTH_LOCK:
        _DEVICE_AUTH_SESSION = None
        return _build_device_auth_status()
