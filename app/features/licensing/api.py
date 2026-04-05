from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import User, get_current_user, get_current_user_detached, get_db
from shared.in_memory_stream_broker import InMemoryStreamBroker
from shared.models import SessionLocal, WorkspaceMember

from .read_models import license_status_read_model
from .sync import LicenseActivationError, activate_with_code_once

router = APIRouter()
_AUTO_UPDATE_LOCK = threading.Lock()
_AUTO_UPDATE_RUNNING = False
_AUTO_UPDATE_STARTED_AT: str | None = None
_AUTO_UPDATE_RUN_ID: str | None = None
_AUTO_UPDATE_LOG_PATH = "/tmp/constructos-auto-update.log"
_AUTO_UPDATE_STREAM_KEY = "license:auto-update"
_AUTO_UPDATE_STREAM_BROKER = InMemoryStreamBroker(max_events=3000)
_AUTO_UPDATE_DOCKER_BIN = os.getenv("AUTO_UPDATE_DOCKER_BIN", "/usr/bin/docker-real")
_AUTO_UPDATE_PROJECT_NAME = os.getenv("AUTO_UPDATE_PROJECT_NAME", "constructos-app").strip() or "constructos-app"
_AUTO_UPDATE_PROJECT_NETWORK = os.getenv("AUTO_UPDATE_PROJECT_NETWORK", "constructos-app_default").strip() or "constructos-app_default"
_AUTO_UPDATE_SERVICES = ("task-app", "mcp-tools")
_AUTO_UPDATE_TASK_APP_IMAGE_LOCAL = os.getenv("AUTO_UPDATE_TASK_APP_IMAGE_LOCAL", "task-management-task-app:local").strip() or "task-management-task-app:local"
_AUTO_UPDATE_MCP_TOOLS_IMAGE_LOCAL = os.getenv("AUTO_UPDATE_MCP_TOOLS_IMAGE_LOCAL", "task-management-mcp-tools:local").strip() or "task-management-mcp-tools:local"
_AUTO_UPDATE_TASK_APP_IMAGE_GHCR = os.getenv("AUTO_UPDATE_TASK_APP_IMAGE_GHCR", "ghcr.io/nirm3l/constructos-task-app:latest").strip() or "ghcr.io/nirm3l/constructos-task-app:latest"
_AUTO_UPDATE_MCP_TOOLS_IMAGE_GHCR = os.getenv("AUTO_UPDATE_MCP_TOOLS_IMAGE_GHCR", "ghcr.io/nirm3l/constructos-mcp-tools:latest").strip() or "ghcr.io/nirm3l/constructos-mcp-tools:latest"
_AUTO_UPDATE_HELPER_IMAGE = os.getenv("AUTO_UPDATE_HELPER_IMAGE", "docker:27-cli").strip() or "docker:27-cli"


class LicenseActivationRequest(BaseModel):
    activation_code: str = Field(min_length=8, max_length=128)


def _user_is_workspace_owner(db: Session, user_id: str) -> bool:
    membership = db.execute(
        select(WorkspaceMember.id).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role == "Owner",
        ).limit(1)
    ).scalar_one_or_none()
    return membership is not None


def _publish_auto_update_event(event: dict) -> dict | None:
    return _AUTO_UPDATE_STREAM_BROKER.publish_event(key=_AUTO_UPDATE_STREAM_KEY, event=event)


def _finish_auto_update_run() -> None:
    _AUTO_UPDATE_STREAM_BROKER.finish_run(key=_AUTO_UPDATE_STREAM_KEY)


def _docker_env_with_proxy() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = str(env.get("AGENT_DOCKER_PROXY_URL") or "tcp://docker-socket-proxy:2375").strip()
    env["DOCKER_HOST"] = proxy_url
    return env


def _resolve_task_app_host_binds(*, env: dict[str, str]) -> tuple[str, str, str, str]:
    inspect_cmd = [_AUTO_UPDATE_DOCKER_BIN, "inspect", "task-app", "--format", "{{json .Mounts}}"]
    inspect_output = subprocess.check_output(inspect_cmd, env=env, text=True).strip()
    mounts = json.loads(inspect_output or "[]")
    if not isinstance(mounts, list):
        raise RuntimeError("task-app mounts metadata is unavailable")

    by_destination: dict[str, str] = {}
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        destination = str(mount.get("Destination") or "").strip()
        source = str(mount.get("Source") or "").strip()
        if destination and source:
            by_destination[destination] = source

    code_config = by_destination.get("/home/app/.codex/config.toml", "").strip()
    code_auth = by_destination.get("/home/app/.codex/auth.json", "").strip()
    claude_auth = by_destination.get("/home/app/.claude.json", "").strip()
    workspace = by_destination.get("/home/app/workspace", "").strip()
    if not code_config or not code_auth or not claude_auth or not workspace:
        raise RuntimeError("required task-app bind mounts are missing (config/auth/claude-auth/workspace)")
    return code_config, code_auth, claude_auth, workspace


def _stream_process_lines(*, cmd: list[str], env: dict[str, str], log_file) -> int:
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = str(raw_line or "").rstrip()
        if not line:
            continue
        log_file.write(line + "\n")
        log_file.flush()
        _publish_auto_update_event({"type": "progress", "message": line[:1200]})
    return int(process.wait())


def _docker_image_exists(*, image_ref: str, env: dict[str, str]) -> bool:
    ref = str(image_ref or "").strip()
    if not ref:
        return False
    cmd = [_AUTO_UPDATE_DOCKER_BIN, "image", "inspect", ref]
    result = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, check=False)
    return int(result.returncode) == 0


def _resolve_update_images(*, env: dict[str, str]) -> tuple[str, str]:
    local_task = _AUTO_UPDATE_TASK_APP_IMAGE_LOCAL
    local_mcp = _AUTO_UPDATE_MCP_TOOLS_IMAGE_LOCAL
    if _docker_image_exists(image_ref=local_task, env=env) and _docker_image_exists(image_ref=local_mcp, env=env):
        return local_task, local_mcp
    return _AUTO_UPDATE_TASK_APP_IMAGE_GHCR, _AUTO_UPDATE_MCP_TOOLS_IMAGE_GHCR


def _is_local_image_ref(image_ref: str) -> bool:
    ref = str(image_ref or "").strip().lower()
    if not ref:
        return False
    if ref.endswith(":local"):
        return True
    return ref.startswith("task-management-")


def _run_auto_update_background(*, run_id: str) -> None:
    global _AUTO_UPDATE_RUNNING, _AUTO_UPDATE_STARTED_AT, _AUTO_UPDATE_RUN_ID
    started_at = datetime.now(timezone.utc).isoformat()
    with _AUTO_UPDATE_LOCK:
        _AUTO_UPDATE_RUNNING = True
        _AUTO_UPDATE_STARTED_AT = started_at
        _AUTO_UPDATE_RUN_ID = run_id
    _publish_auto_update_event({"type": "status", "message": "Auto-update started.", "started_at": started_at})
    _publish_auto_update_event({"type": "status", "message": "Pulling latest images for task-app and mcp-tools."})
    try:
        env = _docker_env_with_proxy()
        code_config_file, code_auth_file, claude_auth_file, workspace_mount = _resolve_task_app_host_binds(env=env)
        repo_mount_host = str(Path(code_config_file).resolve().parent).strip()
        if not repo_mount_host:
            raise RuntimeError("unable to derive repository host path from CODEX_CONFIG_FILE mount")
        task_app_image, mcp_tools_image = _resolve_update_images(env=env)

        helper_script_lines = ["set -euo pipefail"]
        with open(_AUTO_UPDATE_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"\n[{started_at}] Auto-update started "
                f"(task-app={task_app_image}, mcp-tools={mcp_tools_image}).\n"
            )
            log_file.flush()
            both_local = _is_local_image_ref(task_app_image) and _is_local_image_ref(mcp_tools_image)
            if both_local:
                _publish_auto_update_event({"type": "status", "message": "Local images detected; skipping pull and redeploying services."})
            else:
                _publish_auto_update_event({"type": "status", "message": f"Pulling images for: {', '.join(_AUTO_UPDATE_SERVICES)}"})
                helper_script_lines.append(
                    "docker compose -p \"$AUTO_UPDATE_PROJECT_NAME\" -f /repo/docker-compose.yml --env-file /repo/.env "
                    f"pull {' '.join(_AUTO_UPDATE_SERVICES)}"
                )
            helper_script_lines.append(
                "docker compose -p \"$AUTO_UPDATE_PROJECT_NAME\" -f /repo/docker-compose.yml --env-file /repo/.env "
                f"up -d --no-build {' '.join(_AUTO_UPDATE_SERVICES)}"
            )
            helper_script = "\n".join(helper_script_lines)

            helper_name = f"constructos-app-updater-{run_id.split('-')[-1][:12]}"
            helper_cmd = [
                _AUTO_UPDATE_DOCKER_BIN,
                "run",
                "-d",
                "--rm",
                "--name",
                helper_name,
                "--network",
                _AUTO_UPDATE_PROJECT_NETWORK,
                "-e",
                "DOCKER_HOST=tcp://docker-socket-proxy:2375",
                "-e",
                f"AUTO_UPDATE_PROJECT_NAME={_AUTO_UPDATE_PROJECT_NAME}",
                "-e",
                f"CODEX_CONFIG_FILE={code_config_file}",
                "-e",
                f"CODEX_AUTH_FILE={code_auth_file}",
                "-e",
                f"CLAUDE_AUTH_FILE={claude_auth_file}",
                "-e",
                f"AGENT_WORKSPACE_MOUNT={workspace_mount}",
                "-e",
                f"AGENT_CODEX_WORKSPACE_MOUNT={workspace_mount}",
                "-e",
                f"TASK_APP_IMAGE={task_app_image}",
                "-e",
                f"MCP_TOOLS_IMAGE={mcp_tools_image}",
                "-e",
                "APP_VERSION=latest",
                "-e",
                "APP_BUILD=auto-update-latest",
                "-e",
                f"APP_DEPLOYED_AT_UTC={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "-v",
                f"{repo_mount_host}:/repo:ro",
                _AUTO_UPDATE_HELPER_IMAGE,
                "sh",
                "-lc",
                helper_script,
            ]
            helper_container_id = subprocess.check_output(helper_cmd, env=env, text=True).strip()
            log_file.write(f"Started auto-update helper container: {helper_container_id}\n")
            log_file.flush()
            _publish_auto_update_event(
                {
                    "type": "final",
                    "result": {
                        "ok": True,
                        "exit_code": 0,
                        "message": "Auto-update dispatched. Services are being redeployed in background.",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "refresh_recommended": True,
                        "helper_container": helper_container_id,
                    },
                }
            )
            _finish_auto_update_run()
    except Exception as exc:
        _publish_auto_update_event(
            {
                "type": "final",
                "result": {
                    "ok": False,
                    "exit_code": -1,
                    "message": f"Auto-update failed: {exc}",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "refresh_recommended": False,
                },
            }
        )
        _finish_auto_update_run()
    finally:
        with _AUTO_UPDATE_LOCK:
            _AUTO_UPDATE_RUNNING = False


@router.get("/api/license/status")
def get_license_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return {"ok": True, "license": license_status_read_model(db)}


@router.post("/api/license/activate")
def activate_license(
    payload: LicenseActivationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _user_is_workspace_owner(db, str(user.id)):
        raise HTTPException(status_code=403, detail="Only workspace owners can activate a license.")
    try:
        result = activate_with_code_once(payload.activation_code)
    except Exception as exc:
        # Test/runtime module reloads can produce a distinct LicenseActivationError
        # class object with the same contract; handle both robustly.
        if not (
            isinstance(exc, LicenseActivationError)
            or (
                str(exc.__class__.__name__ or "").strip() == "LicenseActivationError"
                and hasattr(exc, "status_code")
                and hasattr(exc, "detail")
            )
        ):
            raise
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"ok": True, **result}


@router.post("/api/license/auto-update")
def auto_update_app_images(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _user_is_workspace_owner(db, str(user.id)):
        raise HTTPException(status_code=403, detail="Only workspace owners can trigger application auto-update.")

    with _AUTO_UPDATE_LOCK:
        if _AUTO_UPDATE_RUNNING:
            return {
                "ok": True,
                "queued": False,
                "running": True,
                "run_id": _AUTO_UPDATE_RUN_ID,
                "started_at": _AUTO_UPDATE_STARTED_AT,
                "log_path": _AUTO_UPDATE_LOG_PATH,
            }
        run_id = f"run-{uuid.uuid4()}"
        _AUTO_UPDATE_STREAM_BROKER.create_run(key=_AUTO_UPDATE_STREAM_KEY, preferred_run_id=run_id)
        thread = threading.Thread(
            target=_run_auto_update_background,
            kwargs={"run_id": run_id},
            daemon=True,
        )
        thread.start()
    return {
        "ok": True,
        "queued": True,
        "running": True,
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": _AUTO_UPDATE_LOG_PATH,
    }


@router.get("/api/license/auto-update/stream")
def auto_update_stream(
    run_id: str,
    since_seq: int = 0,
    user: User = Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        if not _user_is_workspace_owner(db, str(user.id)):
            raise HTTPException(status_code=403, detail="Only workspace owners can read application auto-update stream.")

    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise HTTPException(status_code=400, detail="run_id is required.")

    subscriber_queue, replay_events, done = _AUTO_UPDATE_STREAM_BROKER.subscribe_run(
        key=_AUTO_UPDATE_STREAM_KEY,
        run_id=normalized_run_id,
        since_seq=max(0, int(since_seq)),
    )
    if not replay_events and done:
        raise HTTPException(status_code=404, detail="Auto-update stream run is not available")

    headers = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    def _to_sse(event: dict) -> str:
        seq = int(event.get("seq") or 0)
        event_type = str(event.get("type") or "message")
        payload = json.dumps(event, ensure_ascii=True)
        return f"id: {seq}\nevent: {event_type}\ndata: {payload}\n\n"

    def _stream():
        try:
            for event in replay_events:
                if isinstance(event, dict):
                    yield _to_sse(event)
            if done:
                return
            while True:
                try:
                    event = subscriber_queue.get(timeout=0.5)
                except queue.Empty:
                    broker = _AUTO_UPDATE_STREAM_BROKER.current_state(key=_AUTO_UPDATE_STREAM_KEY)
                    if not isinstance(broker, dict):
                        break
                    if str(broker.get("run_id") or "").strip() != normalized_run_id:
                        break
                    if bool(broker.get("done")):
                        break
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if not isinstance(event, dict):
                    continue
                yield _to_sse(event)
                if str(event.get("type") or "").strip() == "final":
                    break
        finally:
            _AUTO_UPDATE_STREAM_BROKER.unsubscribe_run(key=_AUTO_UPDATE_STREAM_KEY, subscriber_queue=subscriber_queue)

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=headers)
