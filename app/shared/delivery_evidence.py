from __future__ import annotations

import re
from typing import Any

_COMPOSE_MANIFEST_SUFFIXES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
_MERGE_TO_MAIN_REF_PREFIX = "merge:main:"
_DEPLOY_STACK_REF_PREFIX = "deploy:stack:"
_DEPLOY_COMMAND_REF_PREFIX = "deploy:command:"
_DEPLOY_COMPOSE_REF_PREFIX = "deploy:compose:"
_DEPLOY_RUNTIME_REF_PREFIX = "deploy:runtime:"
_DEPLOY_HEALTH_REF_PREFIX = "deploy:health:"
_LEGACY_COMPOSE_PREFIX = "compose:"
_LEGACY_RUNTIME_BASIS_PREFIX = "runtime-basis:"
_LEGACY_RUNTIME_DECISION_PREFIXES = ("decision:runtime_signal_", "runtime-decision://", "runtime_decision:")
_LEGACY_COMPOSE_DECISION_PREFIXES = ("compose_decision:", "compose-decision://")
_LEGACY_DEPLOY_COMMAND_PREFIXES = ("command:", "deploy-command://", "deploy:docker-compose:")
_LEGACY_HEALTH_PREFIXES = ("health:", "runtime-root:")
_TASK_BRANCH_RE = re.compile(r"\btask/[a-z0-9][a-z0-9._/-]*\b", re.IGNORECASE)
_HTTP_STATUS_RE = re.compile(r"http(?:[_=-])(\d{3})", re.IGNORECASE)
_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def parse_external_refs(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    refs: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or "").strip()
        refs.append({"url": url, "title": title})
    return refs


def has_merge_to_main_ref(raw: object) -> bool:
    for item in parse_external_refs(raw):
        if str(item.get("url") or "").strip().casefold().startswith(_MERGE_TO_MAIN_REF_PREFIX):
            return True
    return False


def extract_task_branches_from_refs(raw: object) -> set[str]:
    branches: set[str] = set()
    for item in parse_external_refs(raw):
        corpus = f"{item.get('url') or ''} {item.get('title') or ''}"
        for match in _TASK_BRANCH_RE.findall(corpus):
            branch = str(match or "").strip()
            if branch:
                branches.add(branch)
    return branches


def derive_deploy_execution_snapshot(
    *,
    refs: object,
    current_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if isinstance(current_snapshot, dict):
        snapshot.update({key: value for key, value in current_snapshot.items() if value not in (None, "", [])})
    for item in parse_external_refs(refs):
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        url_lower = url.casefold()
        title_lower = title.casefold()

        if url_lower.startswith(_DEPLOY_STACK_REF_PREFIX):
            snapshot.setdefault("stack", url[len(_DEPLOY_STACK_REF_PREFIX):].strip())
            continue

        if url_lower.startswith(_DEPLOY_COMMAND_REF_PREFIX):
            command = url[len(_DEPLOY_COMMAND_REF_PREFIX):].strip()
            if command:
                snapshot.setdefault("command", command)
                _maybe_set_stack_from_command(snapshot, command)
            continue

        if url_lower.startswith(_DEPLOY_COMPOSE_REF_PREFIX):
            manifest_path = url[len(_DEPLOY_COMPOSE_REF_PREFIX):].strip()
            if manifest_path:
                snapshot.setdefault("manifest_path", manifest_path)
            continue

        if url_lower.startswith(_LEGACY_COMPOSE_PREFIX):
            manifest_path = url[len(_LEGACY_COMPOSE_PREFIX):].strip()
            if manifest_path:
                snapshot.setdefault("manifest_path", manifest_path)
            continue

        if url_lower.startswith(_DEPLOY_RUNTIME_REF_PREFIX):
            runtime_type = url[len(_DEPLOY_RUNTIME_REF_PREFIX):].strip()
            if runtime_type:
                snapshot.setdefault("runtime_type", runtime_type)
            continue

        if url_lower.startswith(_LEGACY_RUNTIME_BASIS_PREFIX):
            runtime_type = url[len(_LEGACY_RUNTIME_BASIS_PREFIX):].strip()
            if runtime_type:
                snapshot.setdefault("runtime_type", runtime_type)
            continue

        if url_lower.startswith(_LEGACY_COMPOSE_DECISION_PREFIXES):
            for prefix in _LEGACY_COMPOSE_DECISION_PREFIXES:
                if url_lower.startswith(prefix):
                    snapshot.setdefault("manifest_path", "docker-compose.yml")
                    break
            continue

        if url_lower.startswith("file:") and url_lower.endswith(_COMPOSE_MANIFEST_SUFFIXES):
            snapshot.setdefault("manifest_path", _strip_file_scheme(url))
            continue

        if url_lower.startswith(_LEGACY_RUNTIME_DECISION_PREFIXES):
            for prefix in _LEGACY_RUNTIME_DECISION_PREFIXES:
                if url_lower.startswith(prefix):
                    runtime_type = url[len(prefix):].strip()
                    if runtime_type:
                        snapshot.setdefault("runtime_type", runtime_type)
                    break
            continue

        if url_lower.startswith(_LEGACY_DEPLOY_COMMAND_PREFIXES):
            command = _normalize_legacy_command(url)
            if command:
                snapshot.setdefault("command", command)
                _maybe_set_stack_from_command(snapshot, command)
            continue

        if url_lower.startswith("deploy:docker compose "):
            command = _normalize_inline_deploy_command(url)
            if command:
                snapshot.setdefault("command", command)
                _maybe_set_stack_from_command(snapshot, command)
            continue

        health = _parse_health_signal(url=url, title=title)
        if health is not None:
            if health.get("http_url"):
                snapshot.setdefault("http_url", health["http_url"])
            if health.get("http_status") is not None:
                snapshot.setdefault("http_status", health["http_status"])
            if health.get("executed_at"):
                snapshot.setdefault("executed_at", health["executed_at"])
            if health.get("runtime_ok") is not None:
                snapshot["runtime_ok"] = bool(health["runtime_ok"])

    if "runtime_ok" in snapshot:
        snapshot["runtime_ok"] = bool(snapshot.get("runtime_ok"))
    return snapshot


def is_strict_deploy_success_snapshot(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    executed_at = str(snapshot.get("executed_at") or "").strip()
    stack = str(snapshot.get("stack") or "").strip()
    command = str(snapshot.get("command") or "").strip()
    manifest_path = str(snapshot.get("manifest_path") or "").strip()
    http_url = str(snapshot.get("http_url") or "").strip()
    http_status = snapshot.get("http_status")
    try:
        normalized_status = int(http_status) if http_status is not None else None
    except Exception:
        normalized_status = None
    return bool(
        executed_at
        and stack
        and command
        and manifest_path
        and http_url
        and normalized_status == 200
        and snapshot.get("runtime_ok") is True
    )


def _strip_file_scheme(value: str) -> str:
    if value.startswith("file://"):
        return value[len("file://"):]
    if value.startswith("file:"):
        return value[len("file:"):]
    return value


def _normalize_legacy_command(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    if lowered.startswith("command:"):
        return raw[len("command:"):].strip()
    if lowered.startswith("deploy-command://"):
        return raw[len("deploy-command://"):].strip()
    if lowered.startswith("deploy:docker-compose:"):
        compact = raw[len("deploy:docker-compose:"):].strip()
        if compact:
            return f"docker compose {compact.replace('-', ' ')}"
    return None


def _normalize_inline_deploy_command(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    if not lowered.startswith("deploy:docker compose "):
        return None
    command = raw[len("deploy:"):].strip()
    if ":exit=" in command:
        command = command.split(":exit=", 1)[0].strip()
    return command or None


def _maybe_set_stack_from_command(snapshot: dict[str, Any], command: str) -> None:
    if str(snapshot.get("stack") or "").strip():
        return
    match = re.search(r"(?:^|\s)-p\s+([a-zA-Z0-9_.-]+)\b", str(command or ""))
    if match:
        snapshot["stack"] = str(match.group(1) or "").strip()


def _parse_health_signal(*, url: str, title: str) -> dict[str, Any] | None:
    raw_url = str(url or "").strip()
    raw_title = str(title or "").strip()
    url_lower = raw_url.casefold()
    title_lower = raw_title.casefold()

    parsed_url = ""
    http_status: int | None = None
    executed_at = _extract_timestamp(f"{raw_url} {raw_title}")
    runtime_ok: bool | None = None

    if url_lower.startswith(_DEPLOY_HEALTH_REF_PREFIX):
        health_payload = raw_url[len(_DEPLOY_HEALTH_REF_PREFIX):].strip()
        parsed_url, http_status = _split_health_payload(health_payload)
        runtime_ok = http_status == 200 if http_status is not None else None
    elif url_lower.startswith("probe:postdeploy:"):
        probe_payload = raw_url[len("probe:postdeploy:"):].strip()
        parsed_url, http_status = _split_health_payload(probe_payload)
        runtime_ok = http_status == 200 if http_status is not None else None
    elif url_lower.startswith(_LEGACY_HEALTH_PREFIXES):
        for prefix in _LEGACY_HEALTH_PREFIXES:
            if url_lower.startswith(prefix):
                probe_payload = raw_url[len(prefix):].strip()
                parsed_url, http_status = _split_health_payload(probe_payload)
                if http_status is not None:
                    runtime_ok = http_status == 200
                break
    elif raw_url.startswith("http://") or raw_url.startswith("https://"):
        parsed_url = raw_url.split("#", 1)[0].strip()
        http_status = _extract_http_status(f"{raw_url} {raw_title}")
        if "deploy health" in title_lower or "post-deploy" in url_lower:
            if http_status is not None:
                runtime_ok = http_status == 200
            elif "fail" in title_lower:
                runtime_ok = False

    if not parsed_url:
        return None
    return {
        "http_url": parsed_url,
        "http_status": http_status,
        "executed_at": executed_at,
        "runtime_ok": runtime_ok,
    }


def _split_health_payload(value: str) -> tuple[str, int | None]:
    payload = str(value or "").strip()
    if not payload:
        return "", None
    match = re.search(r":http(?:[_=-])(\d{3})(?::|$)", payload, re.IGNORECASE)
    if match:
        url = payload[: match.start()].strip()
        return url, int(match.group(1))
    return payload, _extract_http_status(payload)


def _extract_http_status(value: str) -> int | None:
    match = _HTTP_STATUS_RE.search(str(value or ""))
    if match:
        return int(match.group(1))
    return None


def _extract_timestamp(value: str) -> str | None:
    match = _ISO_TIMESTAMP_RE.search(str(value or ""))
    if match:
        return str(match.group(0))
    return None
