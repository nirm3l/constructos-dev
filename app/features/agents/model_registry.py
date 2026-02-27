from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_CACHE_EXPIRES_AT = 0.0
_CACHE_MODELS: list[str] = []
_CACHE_DEFAULT_MODEL = ""


def _load_positive_float_env(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    if value <= 0:
        return default
    return value


def _load_positive_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    if value <= 0:
        return default
    return value


_CACHE_TTL_SECONDS = _load_positive_float_env("AGENT_CODEX_MODELS_CACHE_TTL_SECONDS", 300.0)
_MODEL_LIST_TIMEOUT_SECONDS = _load_positive_float_env("AGENT_CODEX_MODEL_LIST_TIMEOUT_SECONDS", 2.0)
_MODEL_LIST_LIMIT = _load_positive_int_env("AGENT_CODEX_MODEL_LIST_LIMIT", 200)


def _append_unique_model(out: list[str], seen: set[str], value: object) -> None:
    model = str(value or "").strip()
    if not model:
        return
    key = model.lower()
    if key in seen:
        return
    seen.add(key)
    out.append(model)


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


def _parse_model_list_result(result: object) -> tuple[list[str], str]:
    if not isinstance(result, dict):
        return [], ""
    out: list[str] = []
    seen: set[str] = set()
    default_model = ""
    data = result.get("data")
    if not isinstance(data, list):
        data = result.get("models")
    if not isinstance(data, list):
        return [], ""
    for item in data:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or item.get("id") or "").strip()
        if not model:
            continue
        _append_unique_model(out, seen, model)
        if not default_model and bool(item.get("isDefault")):
            default_model = model
    return out, default_model


def _read_model_list_from_codex() -> tuple[list[str], str]:
    proc = subprocess.Popen(
        ["codex", "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None:
        raise RuntimeError("codex app-server stdin unavailable")
    if proc.stdout is None:
        raise RuntimeError("codex app-server stdout unavailable")

    timed_out = False
    done = threading.Event()

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if done.wait(_MODEL_LIST_TIMEOUT_SECONDS):
            return
        if proc.poll() is None:
            timed_out = True
            proc.kill()

    threading.Thread(target=_timeout_watchdog, daemon=True).start()

    request_seq = 0
    pending_requests: dict[str, str] = {}
    final_models: list[str] = []
    final_default_model = ""
    model_list_received = False
    response_lines: list[str] = []

    def _send_message(payload: dict[str, object]) -> None:
        proc.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def _send_request(method: str, params: dict[str, object]) -> None:
        nonlocal request_seq
        request_seq += 1
        req_id = str(request_seq)
        pending_requests[req_id] = method
        _send_message({"method": method, "id": req_id, "params": params})

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
        response_lines.append(line)
        if line.startswith("WARNING:"):
            continue
        try:
            message = json.loads(line)
        except Exception:
            continue
        if not isinstance(message, dict):
            continue
        if "id" not in message:
            continue
        req_id = str(message.get("id") or "")
        req_method = pending_requests.pop(req_id, "")
        if req_method == "initialize":
            _send_message({"method": "initialized"})
            _send_request("model/list", {"includeHidden": False, "limit": _MODEL_LIST_LIMIT})
            continue
        if req_method != "model/list":
            continue
        error_payload = message.get("error")
        if isinstance(error_payload, dict):
            detail = _extract_error_message(error_payload) or "unknown error"
            raise RuntimeError(f"codex app-server model/list failed: {detail[:600]}")
        result = message.get("result")
        final_models, final_default_model = _parse_model_list_result(result)
        model_list_received = True
        break

    done.set()
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    proc.wait()

    if timed_out:
        raise TimeoutError(f"codex app-server model/list timed out after {_MODEL_LIST_TIMEOUT_SECONDS:.1f}s")
    if not model_list_received:
        detail = "\n".join(response_lines).strip()
        raise RuntimeError(f"codex app-server model/list returned no result: {detail[:600]}")
    return final_models, final_default_model


def _discover_models_uncached() -> tuple[list[str], str]:
    try:
        return _read_model_list_from_codex()
    except FileNotFoundError:
        logger.warning("codex binary not found; model discovery falls back to env values")
    except Exception as exc:
        logger.warning("Failed to discover Codex models from app-server: %s", exc)
    return [], ""


def list_available_codex_models(*, force_refresh: bool = False) -> tuple[list[str], str]:
    global _CACHE_MODELS, _CACHE_DEFAULT_MODEL, _CACHE_EXPIRES_AT
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force_refresh and now < _CACHE_EXPIRES_AT:
            return copy.deepcopy(_CACHE_MODELS), _CACHE_DEFAULT_MODEL

    models, default_model = _discover_models_uncached()
    with _CACHE_LOCK:
        _CACHE_MODELS = copy.deepcopy(models)
        _CACHE_DEFAULT_MODEL = str(default_model or "").strip()
        _CACHE_EXPIRES_AT = time.monotonic() + _CACHE_TTL_SECONDS
        return copy.deepcopy(_CACHE_MODELS), _CACHE_DEFAULT_MODEL
