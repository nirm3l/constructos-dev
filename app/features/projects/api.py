import asyncio
import json
import subprocess
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from features.agents.gates import run_runtime_deploy_health_check
from features.agents.gates import plugin_check_catalog_by_scope
from features.agents.gateway import build_ui_gateway
from plugins.team_mode.runtime_snapshot import build_team_mode_runtime_snapshot
from plugins.team_mode.execution_sessions import (
    get_team_mode_execution_session,
    get_team_mode_execution_sessions_page,
    get_latest_team_mode_execution_session,
    serialize_team_mode_execution_session,
)
from features.agents.automation_session_logs import build_automation_session_log_from_row
from shared.core import (
    Project,
    ProjectCreate,
    ProjectMemberUpsert,
    ProjectPatch,
    ensure_project_access,
    get_command_id,
    get_current_user,
    get_current_user_detached,
    get_db,
)
from shared.models import ProjectPluginConfig
from shared.models import SessionLocal
from shared.knowledge_graph import (
    event_storming_set_link_review_status,
    event_storming_get_component_links,
    event_storming_get_entity_links,
    event_storming_get_project_overview,
    event_storming_get_project_subgraph,
    graph_generate_layout,
    graph_context_pack,
    graph_get_project_overview,
    graph_get_project_subgraph,
    require_graph_available,
    search_project_knowledge,
)
from shared.eventing_event_storming import enqueue_event_storming_project_backfill
from shared.project_repository import branch_is_merged_to_main, resolve_project_repository_path
from .task_dependency_graph import (
    get_project_task_dependency_event_detail,
    get_project_task_dependency_graph,
)
from .application import ProjectApplicationService
from .read_models import (
    get_project_activity_read_model,
    get_project_board_read_model,
    get_project_members_read_model,
    get_project_tags_read_model,
)
from features.tasks.read_models import get_task_automation_status_read_model
from shared.models import Task

router = APIRouter()
_GIT_FILE_PREVIEW_BYTES_LIMIT = 200_000
_GIT_DIFF_PATCH_BYTES_LIMIT = 350_000


def _parse_docker_compose_ps_payload(payload: str) -> list[dict[str, object]]:
    text = str(payload or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except Exception:
        pass
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed_line = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed_line, dict):
            rows.append(parsed_line)
    return rows


def _load_docker_compose_runtime_config(db: Session, project_id: str) -> dict[str, object]:
    row = db.execute(
        select(ProjectPluginConfig).where(
            ProjectPluginConfig.project_id == project_id,
            ProjectPluginConfig.plugin_key == "docker_compose",
            ProjectPluginConfig.is_deleted == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    config: dict[str, object] = {}
    enabled = False
    if row is not None:
        enabled = bool(getattr(row, "enabled", False))
        try:
            parsed = json.loads(str(getattr(row, "config_json", "") or "").strip() or "{}")
            if isinstance(parsed, dict):
                config = dict(parsed)
        except Exception:
            config = {}
    runtime_cfg = config.get("runtime_deploy_health")
    runtime = dict(runtime_cfg) if isinstance(runtime_cfg, dict) else {}
    stack = str(runtime.get("stack") or config.get("compose_project_name") or "constructos-ws-default").strip()
    port_raw = runtime.get("port")
    try:
        port = int(port_raw) if port_raw is not None else None
    except Exception:
        port = None
    health_path = str(runtime.get("health_path") or "/health").strip() or "/health"
    require_http_200 = bool(runtime.get("require_http_200", True))
    host = str(runtime.get("host") or "gateway").strip() or "gateway"
    return {
        "enabled": enabled,
        "stack": stack,
        "host": host,
        "port": port,
        "health_path": health_path,
        "require_http_200": require_http_200,
    }


def _load_project_runtime_snapshot(*, db: Session, project_id: str) -> dict[str, object]:
    runtime = _load_docker_compose_runtime_config(db, project_id)
    stack = str(runtime.get("stack") or "").strip()
    result: dict[str, object] = {
        "stack": stack,
        "port": runtime.get("port"),
        "health_path": runtime.get("health_path"),
        "require_http_200": bool(runtime.get("require_http_200")),
        "enabled": bool(runtime.get("enabled")),
        "containers": [],
        "has_runtime": False,
    }
    if not stack:
        return result
    try:
        proc = subprocess.run(
            ["docker", "compose", "-p", stack, "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        result["error"] = "docker_cli_missing"
        return result
    except subprocess.TimeoutExpired:
        result["error"] = "docker_compose_timeout"
        return result
    if proc.returncode != 0:
        result["error"] = f"docker_compose_ps_failed:{proc.returncode}"
        result["stderr"] = str(proc.stderr or "").strip()
        return result
    rows = _parse_docker_compose_ps_payload(str(proc.stdout or ""))
    containers: list[dict[str, object]] = []
    for item in rows:
        publishers = item.get("Publishers")
        normalized_publishers: list[dict[str, object]] = []
        if isinstance(publishers, list):
            for publisher in publishers:
                if not isinstance(publisher, dict):
                    continue
                normalized_publishers.append(
                    {
                        "url": publisher.get("URL"),
                        "target_port": publisher.get("TargetPort"),
                        "published_port": publisher.get("PublishedPort"),
                        "protocol": publisher.get("Protocol"),
                    }
                )
        containers.append(
            {
                "name": str(item.get("Name") or "").strip(),
                "service": str(item.get("Service") or "").strip(),
                "state": str(item.get("State") or "").strip(),
                "status": str(item.get("Status") or "").strip(),
                "health": str(item.get("Health") or "").strip() or None,
                "image": str(item.get("Image") or "").strip() or None,
                "command": str(item.get("Command") or "").strip() or None,
                "exit_code": item.get("ExitCode"),
                "publishers": normalized_publishers,
            }
        )
    health = run_runtime_deploy_health_check(
        stack=stack,
        port=runtime.get("port") if isinstance(runtime.get("port"), int) else None,
        health_path=str(runtime.get("health_path") or "/health"),
        require_http_200=bool(runtime.get("require_http_200")),
        host=str(runtime.get("host") or "gateway").strip() or "gateway",
    )
    result["containers"] = containers
    result["has_runtime"] = bool(containers)
    result["health"] = health
    return result


def _project_execution_gate_snapshot(*, db: Session, user, project_id: str) -> dict[str, object]:
    rows = db.execute(
        select(Task.id, Task.title, Task.status)
        .where(
            Task.project_id == project_id,
            Task.is_deleted == False,  # noqa: E712
            Task.archived == False,  # noqa: E712
        )
        .order_by(Task.created_at.asc())
        .limit(300)
    ).all()
    tasks: list[dict[str, object]] = []
    communication_events: list[dict[str, object]] = []
    totals = {
        "tasks_with_gates": 0,
        "gates_total": 0,
        "blocking_total": 0,
        "pass": 0,
        "fail": 0,
        "waiting": 0,
        "not_applicable": 0,
    }
    communication_totals: dict[str, int] = {}
    for task_id, title, status in rows:
        task_id_text = str(task_id or "").strip()
        if not task_id_text:
            continue
        try:
            automation_status = get_task_automation_status_read_model(db, user, task_id_text)
        except Exception:
            continue
        requested_source = str(automation_status.get("last_requested_source") or "").strip()
        if requested_source:
            requested_at = (
                str(automation_status.get("last_requested_triggered_at") or "").strip()
                or str(automation_status.get("last_agent_run_at") or "").strip()
                or None
            )
            communication_events.append(
                {
                    "delivery": "requested",
                    "task_id": task_id_text,
                    "title": str(title or "").strip(),
                    "status": str(status or "").strip(),
                    "source": requested_source,
                    "source_task_id": str(automation_status.get("last_requested_source_task_id") or "").strip() or None,
                    "reason": str(automation_status.get("last_requested_reason") or "").strip() or None,
                    "trigger_link": str(automation_status.get("last_requested_trigger_link") or "").strip() or None,
                    "correlation_id": str(automation_status.get("last_requested_correlation_id") or "").strip() or None,
                    "lead_handoff_token": str(automation_status.get("last_lead_handoff_token") or "").strip() or None,
                    "dispatch_decision": (
                        automation_status.get("last_dispatch_decision")
                        if isinstance(automation_status.get("last_dispatch_decision"), dict)
                        else None
                    ),
                    "requested_at": requested_at,
                }
            )
            communication_totals[requested_source] = int(communication_totals.get(requested_source) or 0) + 1
        ignored_source = str(automation_status.get("last_ignored_request_source") or "").strip()
        if ignored_source:
            ignored_at = str(automation_status.get("last_ignored_request_triggered_at") or "").strip() or None
            communication_events.append(
                {
                    "delivery": "ignored",
                    "task_id": task_id_text,
                    "title": str(title or "").strip(),
                    "status": str(status or "").strip(),
                    "source": ignored_source,
                    "source_task_id": str(automation_status.get("last_ignored_request_source_task_id") or "").strip() or None,
                    "reason": str(automation_status.get("last_ignored_request_reason") or "").strip() or None,
                    "trigger_link": str(automation_status.get("last_ignored_request_trigger_link") or "").strip() or None,
                    "correlation_id": str(automation_status.get("last_ignored_request_correlation_id") or "").strip() or None,
                    "lead_handoff_token": None,
                    "dispatch_decision": (
                        automation_status.get("last_dispatch_decision")
                        if isinstance(automation_status.get("last_dispatch_decision"), dict)
                        else None
                    ),
                    "requested_at": ignored_at,
                }
            )
            communication_totals[f"ignored:{ignored_source}"] = int(
                communication_totals.get(f"ignored:{ignored_source}") or 0
            ) + 1
        execution_gates = list(automation_status.get("execution_gates") or [])
        if not execution_gates:
            continue
        totals["tasks_with_gates"] = int(totals["tasks_with_gates"]) + 1
        per_task = {
            "task_id": task_id_text,
            "title": str(title or "").strip(),
            "status": str(status or "").strip(),
            "gates_total": 0,
            "blocking_total": 0,
            "pass": 0,
            "fail": 0,
            "waiting": 0,
            "not_applicable": 0,
        }
        for gate in execution_gates:
            if not isinstance(gate, dict):
                continue
            gate_status = str(gate.get("status") or "").strip().lower()
            blocking = bool(gate.get("blocking"))
            per_task["gates_total"] = int(per_task["gates_total"]) + 1
            totals["gates_total"] = int(totals["gates_total"]) + 1
            if blocking:
                per_task["blocking_total"] = int(per_task["blocking_total"]) + 1
                totals["blocking_total"] = int(totals["blocking_total"]) + 1
            if gate_status in {"pass", "fail", "waiting", "not_applicable"}:
                per_task[gate_status] = int(per_task[gate_status]) + 1
                totals[gate_status] = int(totals[gate_status]) + 1
        tasks.append(per_task)
    communication_events.sort(
        key=lambda event: (
            str(event.get("requested_at") or ""),
            str(event.get("task_id") or ""),
        ),
        reverse=True,
    )
    return {
        "team_mode_runtime": build_team_mode_runtime_snapshot(db=db, user=user, project_id=project_id),
        "execution_gates": {
            "tasks": tasks,
            "totals": totals,
        },
        "workflow_communication": {
            "events": communication_events,
            "totals": communication_totals,
            "events_total": len(communication_events),
        },
    }


class EventStormingLinkReviewPatch(BaseModel):
    entity_type: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    component_id: str = Field(min_length=1)
    review_status: str = Field(min_length=1)
    confidence: float | None = None


class EventStormingBulkLinkReviewPatch(BaseModel):
    items: list[EventStormingLinkReviewPatch] = Field(default_factory=list)


class GraphLayoutNodeIn(BaseModel):
    entity_id: str = Field(min_length=1)
    entity_type: str = Field(default="Entity")
    title: str = Field(default="")
    degree: int = Field(default=0)


class GraphLayoutEdgeIn(BaseModel):
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    relationship: str = Field(default="RELATED")


class GraphAiLayoutRequest(BaseModel):
    nodes: list[GraphLayoutNodeIn] = Field(default_factory=list)
    edges: list[GraphLayoutEdgeIn] = Field(default_factory=list)
    node_width: int = Field(default=220, ge=120, le=420)
    node_height: int = Field(default=74, ge=48, le=280)


class ProjectPluginConfigValidateRequest(BaseModel):
    draft_config: dict[str, object] = Field(default_factory=dict)


class ProjectPluginConfigApplyRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class ProjectPluginEnabledPatch(BaseModel):
    enabled: bool


class ProjectPluginConfigDiffRequest(BaseModel):
    draft_config: dict[str, object] = Field(default_factory=dict)


def _load_project_with_access(db: Session, user, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_access(db, project.workspace_id, project.id, user.id, {"Owner", "Admin", "Member", "Guest"})
    return project


def _load_project_git_repo_root(*, project: Project) -> Path:
    repo_root = resolve_project_repository_path(project_name=project.name, project_id=project.id)
    if not repo_root.exists() or not repo_root.is_dir() or not (repo_root / ".git").exists():
        raise HTTPException(status_code=404, detail="Project repository is not available")
    return repo_root


def _normalize_git_ref(value: str | None) -> str:
    ref = str(value or "").strip()
    if not ref:
        return "HEAD"
    if any(char.isspace() for char in ref) or ".." in ref or ref.startswith("-") or ":" in ref:
        raise HTTPException(status_code=400, detail="Invalid git ref")
    return ref


def _normalize_repo_relative_path(value: str | None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    try:
        normalized = PurePosixPath(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid repository path") from exc
    if normalized.is_absolute() or any(part in {"..", ""} for part in normalized.parts):
        raise HTTPException(status_code=400, detail="Invalid repository path")
    return normalized.as_posix()


def _run_git_text(*, repo_root: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _git_current_branch(*, repo_root: Path) -> str | None:
    code, out, _err = _run_git_text(repo_root=repo_root, args=["branch", "--show-current"])
    branch = str(out or "").strip()
    return branch if code == 0 and branch else None


def _git_default_branch(*, repo_root: Path) -> str:
    current_branch = _git_current_branch(repo_root=repo_root)
    code, out, _err = _run_git_text(
        repo_root=repo_root,
        args=["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
    )
    if code == 0:
        remote_head = str(out or "").strip()
        if remote_head.startswith("origin/") and remote_head[7:]:
            return remote_head[7:]
    for candidate in ("main", "master"):
        code, _out, _err = _run_git_text(repo_root=repo_root, args=["rev-parse", "--verify", f"refs/heads/{candidate}"])
        if code == 0:
            return candidate
    return current_branch or "HEAD"


def _git_branch_rows(*, repo_root: Path, project: Project) -> list[dict[str, object]]:
    current_branch = _git_current_branch(repo_root=repo_root)
    default_branch = _git_default_branch(repo_root=repo_root)
    code, out, err = _run_git_text(
        repo_root=repo_root,
        args=[
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)\t%(objectname)\t%(committerdate:iso8601)\t%(authorname)\t%(subject)",
            "refs/heads",
        ],
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=f"Unable to read git branches: {err or 'unknown error'}")
    rows: list[dict[str, object]] = []
    for line in out.splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        name = str(parts[0] or "").strip()
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "commit_sha": str(parts[1] or "").strip() or None,
                "committed_at": str(parts[2] or "").strip() or None,
                "author_name": str(parts[3] or "").strip() or None,
                "subject": str(parts[4] or "").strip() or None,
                "is_current": name == current_branch,
                "is_default": name == default_branch,
                "merged_to_main": branch_is_merged_to_main(
                    project_name=project.name,
                    project_id=project.id,
                    branch_name=name,
                ),
            }
        )
    return rows


def _git_repository_summary(*, project: Project) -> dict[str, object]:
    repo_root = _load_project_git_repo_root(project=project)
    branches = _git_branch_rows(repo_root=repo_root, project=project)
    current_branch = next((str(item.get("name")) for item in branches if item.get("is_current")), None)
    default_branch = next((str(item.get("name")) for item in branches if item.get("is_default")), None) or _git_default_branch(repo_root=repo_root)
    return {
        "available": True,
        "repo_root": str(repo_root),
        "current_branch": current_branch,
        "default_branch": default_branch,
        "branch_count": len(branches),
        "branches_preview": branches[:8],
    }


def _git_tree_entries(*, repo_root: Path, ref: str, relative_path: str) -> list[dict[str, object]]:
    spec = f"{ref}:{relative_path}" if relative_path else ref
    code, out, err = _run_git_text(repo_root=repo_root, args=["ls-tree", spec])
    if code != 0:
        raise HTTPException(status_code=404, detail=f"Repository path not found: {relative_path or '/'}")
    entries: list[dict[str, object]] = []
    for line in out.splitlines():
        meta, sep, name = line.partition("\t")
        if not sep:
            continue
        meta_parts = meta.split()
        if len(meta_parts) < 3:
            continue
        mode, kind, object_id = meta_parts[:3]
        item_name = str(name or "").strip()
        if not item_name:
            continue
        item_path = f"{relative_path}/{item_name}".strip("/") if relative_path else item_name
        entries.append(
            {
                "name": item_name,
                "path": item_path,
                "kind": "directory" if kind == "tree" else "file",
                "object_id": object_id,
                "mode": mode,
            }
        )
    entries.sort(key=lambda item: (0 if item.get("kind") == "directory" else 1, str(item.get("name") or "").lower()))
    return entries


def _git_file_preview(*, repo_root: Path, ref: str, relative_path: str) -> dict[str, object]:
    spec = f"{ref}:{relative_path}"
    type_proc = subprocess.run(
        ["git", "cat-file", "-t", spec],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if type_proc.returncode != 0 or str(type_proc.stdout or "").strip() != "blob":
        raise HTTPException(status_code=404, detail="Repository file not found")
    size_proc = subprocess.run(
        ["git", "cat-file", "-s", spec],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    size_text = str(size_proc.stdout or "").strip()
    try:
        size_bytes = int(size_text)
    except Exception:
        size_bytes = None
    previewable = size_bytes is None or size_bytes <= _GIT_FILE_PREVIEW_BYTES_LIMIT
    if not previewable:
        return {
            "path": relative_path,
            "size_bytes": size_bytes,
            "encoding": "utf-8",
            "previewable": False,
            "truncated": False,
            "binary": False,
            "content": None,
        }
    content_proc = subprocess.run(
        ["git", "show", spec],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if content_proc.returncode != 0:
        raise HTTPException(status_code=404, detail="Repository file not found")
    payload = bytes(content_proc.stdout or b"")
    is_binary = b"\x00" in payload
    if is_binary:
        return {
            "path": relative_path,
            "size_bytes": size_bytes if size_bytes is not None else len(payload),
            "encoding": "utf-8",
            "previewable": False,
            "truncated": False,
            "binary": True,
            "content": None,
        }
    text = payload.decode("utf-8", errors="replace")
    return {
        "path": relative_path,
        "size_bytes": size_bytes if size_bytes is not None else len(payload),
        "encoding": "utf-8",
        "previewable": True,
        "truncated": False,
        "binary": False,
        "content": text,
    }


def _parse_git_numstat_line(line: str) -> dict[str, object] | None:
    parts = str(line or "").split("\t")
    if len(parts) < 3:
        return None
    additions_raw, deletions_raw = parts[0], parts[1]
    path_part = "\t".join(parts[2:]).strip()
    if not path_part:
        return None
    old_path: str | None = None
    path = path_part
    if "\t" in path:
        old_path, path = path.split("\t", 1)
    elif " => " in path and "{" not in path:
        old_path, path = path.split(" => ", 1)
    additions = None if additions_raw == "-" else int(additions_raw or "0")
    deletions = None if deletions_raw == "-" else int(deletions_raw or "0")
    return {
        "path": path.strip(),
        "old_path": old_path.strip() if old_path else None,
        "additions": additions,
        "deletions": deletions,
        "binary": additions is None or deletions is None,
    }


def _parse_git_name_status_line(line: str) -> dict[str, object] | None:
    parts = str(line or "").split("\t")
    if len(parts) < 2:
        return None
    status_token = str(parts[0] or "").strip().upper()
    if not status_token:
        return None
    status = status_token[:1]
    path = str(parts[-1] or "").strip()
    old_path = str(parts[1] or "").strip() if status in {"R", "C"} and len(parts) >= 3 else None
    status_map = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type_changed",
        "U": "unmerged",
    }
    return {
        "path": path,
        "old_path": old_path or None,
        "status": status_map.get(status, "modified"),
        "status_code": status_token,
    }


def _git_repository_diff(
    *,
    repo_root: Path,
    base_ref: str,
    head_ref: str,
    relative_path: str = "",
    context_lines: int = 3,
) -> dict[str, object]:
    diff_args = [
        "diff",
        "--find-renames",
        "--find-copies",
        f"--unified={max(0, int(context_lines))}",
        f"{base_ref}...{head_ref}",
    ]
    if relative_path:
        diff_args.extend(["--", relative_path])
    code_patch, patch_out, patch_err = _run_git_text(repo_root=repo_root, args=diff_args)
    if code_patch != 0:
        raise HTTPException(status_code=404, detail=f"Unable to load repository diff: {patch_err or 'unknown error'}")

    numstat_args = ["diff", "--find-renames", "--find-copies", "--numstat", f"{base_ref}...{head_ref}"]
    if relative_path:
        numstat_args.extend(["--", relative_path])
    code_numstat, numstat_out, numstat_err = _run_git_text(repo_root=repo_root, args=numstat_args)
    if code_numstat != 0:
        raise HTTPException(status_code=404, detail=f"Unable to summarize repository diff: {numstat_err or 'unknown error'}")

    name_status_args = ["diff", "--find-renames", "--find-copies", "--name-status", f"{base_ref}...{head_ref}"]
    if relative_path:
        name_status_args.extend(["--", relative_path])
    code_name_status, name_status_out, name_status_err = _run_git_text(repo_root=repo_root, args=name_status_args)
    if code_name_status != 0:
        raise HTTPException(
            status_code=404,
            detail=f"Unable to read repository diff files: {name_status_err or 'unknown error'}",
        )

    merge_base_code, merge_base_out, _merge_base_err = _run_git_text(
        repo_root=repo_root,
        args=["merge-base", base_ref, head_ref],
    )
    file_rows: dict[str, dict[str, object]] = {}
    for line in numstat_out.splitlines():
        parsed = _parse_git_numstat_line(line)
        if not parsed:
            continue
        file_rows[str(parsed["path"])] = parsed
    for line in name_status_out.splitlines():
        parsed = _parse_git_name_status_line(line)
        if not parsed:
            continue
        current_path = str(parsed["path"])
        existing = file_rows.get(current_path, {"path": current_path})
        existing.update(parsed)
        file_rows[current_path] = existing

    files = sorted(file_rows.values(), key=lambda item: str(item.get("path") or "").lower())
    insertions = 0
    deletions = 0
    for row in files:
        additions = row.get("additions")
        removals = row.get("deletions")
        if isinstance(additions, int):
            insertions += additions
        if isinstance(removals, int):
            deletions += removals

    patch_text = str(patch_out or "")
    patch_truncated = False
    if len(patch_text.encode("utf-8")) > _GIT_DIFF_PATCH_BYTES_LIMIT:
        patch_text = ""
        patch_truncated = True

    return {
        "base_ref": base_ref,
        "head_ref": head_ref,
        "compare_mode": "merge_base",
        "merge_base": merge_base_out if merge_base_code == 0 and merge_base_out else None,
        "path": relative_path,
        "context_lines": max(0, int(context_lines)),
        "files_changed": len(files),
        "insertions": insertions,
        "deletions": deletions,
        "patch": patch_text,
        "patch_truncated": patch_truncated,
        "files": files,
    }


@router.post("/api/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.create_project(
        name=payload.name,
        workspace_id=payload.workspace_id,
        description=payload.description,
        custom_statuses=payload.custom_statuses,
        external_refs=[item.model_dump() for item in payload.external_refs],
        attachment_refs=[item.model_dump() for item in payload.attachment_refs],
        embedding_enabled=payload.embedding_enabled,
        embedding_model=payload.embedding_model,
        context_pack_evidence_top_k=payload.context_pack_evidence_top_k,
        automation_max_parallel_tasks=payload.automation_max_parallel_tasks,
        chat_index_mode=payload.chat_index_mode,
        chat_attachment_ingestion_mode=payload.chat_attachment_ingestion_mode,
        vector_index_distill_enabled=payload.vector_index_distill_enabled,
        event_storming_enabled=payload.event_storming_enabled,
        member_user_ids=payload.member_user_ids,
        command_id=command_id,
    )


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).delete_project(project_id)


@router.patch("/api/projects/{project_id}")
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    project = _load_project_with_access(db, user, project_id)
    was_enabled = bool(getattr(project, "event_storming_enabled", True))
    updated = ProjectApplicationService(db, user, command_id=command_id).patch_project(project_id, payload)
    requested = payload.model_dump(exclude_unset=True)
    now_enabled = bool(updated.get("event_storming_enabled", was_enabled))
    if "event_storming_enabled" in requested and requested.get("event_storming_enabled") is True and not was_enabled and now_enabled:
        enqueue_event_storming_project_backfill(project_id=project_id, workspace_id=str(project.workspace_id))
    return updated


@router.get("/api/projects/{project_id}/board")
def project_board(
    project_id: str,
    tags: str | None = None,
    user=Depends(get_current_user_detached),
):
    parsed_tags = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else None
    with SessionLocal() as db:
        return get_project_board_read_model(db, user, project_id, tags=parsed_tags)


@router.get("/api/projects/{project_id}/activity")
def project_activity(project_id: str, user=Depends(get_current_user_detached)):
    with SessionLocal() as db:
        return get_project_activity_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/tags")
def project_tags(project_id: str, user=Depends(get_current_user_detached)):
    with SessionLocal() as db:
        return get_project_tags_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/members")
def project_members(project_id: str, user=Depends(get_current_user_detached)):
    with SessionLocal() as db:
        return get_project_members_read_model(db, user, project_id)


@router.get("/api/projects/{project_id}/checks/verify")
def project_checks_verify(
    project_id: str,
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        project_execution_snapshot = _project_execution_gate_snapshot(db=db, user=user, project_id=project_id)
        latest_session_row = get_latest_team_mode_execution_session(db=db, project_id=project_id)
        latest_execution_session = serialize_team_mode_execution_session(latest_session_row)
        latest_automation_session_log = (
            build_automation_session_log_from_row(session=latest_session_row)
            if latest_session_row is not None
            else None
        )
    gateway = build_ui_gateway(actor_user_id=user.id)
    team_mode = gateway.verify_team_mode_workflow(project_id=project_id)
    delivery = gateway.verify_delivery_workflow(project_id=project_id)
    return {
        "project_id": project_id,
        "team_mode": team_mode,
        "team_mode_runtime": project_execution_snapshot.get("team_mode_runtime") or {"active": False, "agents": [], "tasks": [], "summary": {}},
        "delivery": delivery,
        "team_mode_execution_session": latest_execution_session,
        "team_mode_automation_session_log": latest_automation_session_log,
        "execution_gates": project_execution_snapshot.get("execution_gates") or {"tasks": [], "totals": {}},
        "workflow_communication": project_execution_snapshot.get("workflow_communication")
        or {"events": [], "totals": {}, "events_total": 0},
        "catalog": plugin_check_catalog_by_scope(),
        "ok": bool(team_mode.get("ok")) and bool(delivery.get("ok")),
    }


@router.get("/api/projects/{project_id}/team-mode/execution-sessions")
def project_team_mode_execution_sessions(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        _load_project_with_access(db, user, project_id)
        rows, total = get_team_mode_execution_sessions_page(
            db=db,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        items = [
            {
                "execution_session": serialize_team_mode_execution_session(row),
                "automation_session_log": build_automation_session_log_from_row(session=row),
            }
            for row in rows
        ]
    return {
        "project_id": project_id,
        "items": items,
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
    }


@router.get("/api/projects/{project_id}/team-mode/execution-sessions/{session_id}")
def project_team_mode_execution_session_get(
    project_id: str,
    session_id: str,
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        _load_project_with_access(db, user, project_id)
        row = get_team_mode_execution_session(
            db=db,
            project_id=project_id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Team Mode execution session not found")
    return {
        "project_id": project_id,
        "execution_session": serialize_team_mode_execution_session(row),
        "automation_session_log": build_automation_session_log_from_row(session=row),
    }


@router.get("/api/projects/{project_id}/team-mode/automation-session-logs")
def project_team_mode_automation_session_logs(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        _load_project_with_access(db, user, project_id)
        rows, total = get_team_mode_execution_sessions_page(
            db=db,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        items = [build_automation_session_log_from_row(session=row) for row in rows]
    return {
        "project_id": project_id,
        "items": items,
        "total": int(total),
        "limit": int(limit),
        "offset": int(offset),
    }


@router.get("/api/projects/{project_id}/team-mode/automation-session-logs/{session_id}")
def project_team_mode_automation_session_log_get(
    project_id: str,
    session_id: str,
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        _load_project_with_access(db, user, project_id)
        row = get_team_mode_execution_session(
            db=db,
            project_id=project_id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Team Mode automation session log not found")
    return {
        "project_id": project_id,
        "session_id": str(session_id or "").strip(),
        "automation_session_log": build_automation_session_log_from_row(session=row),
    }


@router.get("/api/projects/{project_id}/plugins/{plugin_key}")
def project_plugin_config_get(
    project_id: str,
    plugin_key: str,
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/validate")
def project_plugin_config_validate(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigValidateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.validate_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        draft_config=payload.draft_config,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/apply")
def project_plugin_config_apply(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigApplyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.apply_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        config=payload.config,
        expected_version=payload.expected_version,
        enabled=payload.enabled,
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/enabled")
def project_plugin_enabled_patch(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginEnabledPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.set_project_plugin_enabled(
        project_id=project_id,
        plugin_key=plugin_key,
        enabled=bool(payload.enabled),
    )


@router.post("/api/projects/{project_id}/plugins/{plugin_key}/diff")
def project_plugin_config_diff(
    project_id: str,
    plugin_key: str,
    payload: ProjectPluginConfigDiffRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.diff_project_plugin_config(
        project_id=project_id,
        plugin_key=plugin_key,
        draft_config=payload.draft_config,
    )


@router.get("/api/projects/{project_id}/capabilities")
def project_capabilities_get(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _load_project_with_access(db, user, project_id)
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_capabilities(
        project_id=project_id,
    )


@router.get("/api/projects/{project_id}/knowledge-graph/overview")
def project_knowledge_graph_overview(
    project_id: str,
    top_limit: int = Query(default=8, ge=1, le=30),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.graph_get_project_overview(project_id=project_id, top_limit=top_limit)


@router.get("/api/projects/{project_id}/knowledge-graph/context-pack")
def project_knowledge_graph_context_pack(
    project_id: str,
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=60),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.graph_context_pack(
        project_id=project_id,
        focus_entity_type=focus_entity_type,
        focus_entity_id=focus_entity_id,
        limit=limit,
    )


@router.get("/api/projects/{project_id}/knowledge-graph/subgraph")
def project_knowledge_graph_subgraph(
    project_id: str,
    limit_nodes: int = Query(default=48, ge=8, le=120),
    limit_edges: int = Query(default=160, ge=8, le=320),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return graph_get_project_subgraph(
            project_id=project.id,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Knowledge graph is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/task-dependency-graph")
def project_task_dependency_graph(
    project_id: str,
    limit_nodes: int = Query(default=240, ge=8, le=600),
    limit_edges: int = Query(default=1600, ge=8, le=4000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    return get_project_task_dependency_graph(
        db=db,
        project_id=project.id,
        limit_nodes=limit_nodes,
        limit_edges=limit_edges,
    )


@router.get("/api/projects/{project_id}/task-dependency-graph/event-detail")
def project_task_dependency_graph_event_detail(
    project_id: str,
    source_task_id: str = Query(min_length=1),
    target_task_id: str = Query(min_length=1),
    source: str = Query(min_length=1),
    at: str | None = None,
    correlation_id: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    payload = get_project_task_dependency_event_detail(
        db=db,
        project_id=project.id,
        source_task_id=source_task_id,
        target_task_id=target_task_id,
        runtime_source=source,
        occurred_at=at,
        correlation_id=correlation_id,
    )
    if not bool(payload.get("found")):
        raise HTTPException(status_code=404, detail=str(payload.get("detail") or "Task flow event detail not found"))
    return payload


@router.get("/api/projects/{project_id}/docker-compose/runtime")
def project_docker_compose_runtime(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    snapshot = _load_project_runtime_snapshot(db=db, project_id=project.id)
    return {
        "project_id": project.id,
        "project_name": project.name,
        **snapshot,
    }


@router.get("/api/projects/{project_id}/git-delivery/repository")
def project_git_delivery_repository_summary(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    return {
        "project_id": project.id,
        "project_name": project.name,
        **_git_repository_summary(project=project),
    }


@router.get("/api/projects/{project_id}/git-delivery/repository/branches")
def project_git_delivery_repository_branches(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    repo_root = _load_project_git_repo_root(project=project)
    branches = _git_branch_rows(repo_root=repo_root, project=project)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "branches": branches,
    }


@router.get("/api/projects/{project_id}/git-delivery/repository/tree")
def project_git_delivery_repository_tree(
    project_id: str,
    ref: str | None = Query(default=None),
    path: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    repo_root = _load_project_git_repo_root(project=project)
    normalized_ref = _normalize_git_ref(ref)
    normalized_path = _normalize_repo_relative_path(path)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "ref": normalized_ref,
        "path": normalized_path,
        "entries": _git_tree_entries(repo_root=repo_root, ref=normalized_ref, relative_path=normalized_path),
    }


@router.get("/api/projects/{project_id}/git-delivery/repository/file")
def project_git_delivery_repository_file(
    project_id: str,
    ref: str | None = Query(default=None),
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    repo_root = _load_project_git_repo_root(project=project)
    normalized_ref = _normalize_git_ref(ref)
    normalized_path = _normalize_repo_relative_path(path)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "ref": normalized_ref,
        **_git_file_preview(repo_root=repo_root, ref=normalized_ref, relative_path=normalized_path),
    }


@router.get("/api/projects/{project_id}/git-delivery/repository/diff")
def project_git_delivery_repository_diff(
    project_id: str,
    base_ref: str | None = Query(default=None),
    head_ref: str | None = Query(default=None),
    path: str | None = Query(default=None),
    context_lines: int = Query(default=3, ge=0, le=20),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    repo_root = _load_project_git_repo_root(project=project)
    default_branch = _git_default_branch(repo_root=repo_root)
    normalized_base_ref = _normalize_git_ref(base_ref or default_branch)
    normalized_head_ref = _normalize_git_ref(head_ref or "HEAD")
    normalized_path = _normalize_repo_relative_path(path)
    return {
        "project_id": project.id,
        "project_name": project.name,
        **_git_repository_diff(
            repo_root=repo_root,
            base_ref=normalized_base_ref,
            head_ref=normalized_head_ref,
            relative_path=normalized_path,
            context_lines=context_lines,
        ),
    }


@router.get("/api/projects/{project_id}/docker-compose/runtime/logs/stream")
async def project_docker_compose_runtime_logs_stream(
    project_id: str,
    request: Request,
    container_name: str = Query(..., min_length=1),
    tail: int = Query(200, ge=1, le=2000),
    user=Depends(get_current_user_detached),
):
    with SessionLocal() as db:
        project = _load_project_with_access(db, user, project_id)
        snapshot = _load_project_runtime_snapshot(db=db, project_id=project.id)
        containers = snapshot.get("containers")
        if not isinstance(containers, list):
            raise HTTPException(status_code=404, detail="Runtime is not available")
        requested_container = str(container_name or "").strip()
        allowed = next(
            (
                item for item in containers
                if isinstance(item, dict) and str(item.get("name") or "").strip() == requested_container
            ),
            None,
        )
        if allowed is None:
            raise HTTPException(status_code=404, detail="Runtime container not found")

    async def event_generator():
        process = await asyncio.create_subprocess_exec(
            "docker",
            "logs",
            "--timestamps",
            "--tail",
            str(int(tail)),
            "-f",
            requested_container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert process.stdout is not None
            while True:
                if await request.is_disconnected():
                    process.terminate()
                    break
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if not line:
                    if process.returncode is not None:
                        break
                    await asyncio.sleep(0.1)
                    continue
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                timestamp = None
                message = text
                if " " in text:
                    first, remainder = text.split(" ", 1)
                    if "T" in first:
                        timestamp = first
                        message = remainder
                payload = {
                    "project_id": project.id,
                    "project_name": project.name,
                    "container_name": requested_container,
                    "timestamp": timestamp,
                    "message": message,
                }
                yield f"event: log\ndata: {json.dumps(payload)}\n\n"
            return_code = await process.wait()
            yield f"event: end\ndata: {json.dumps({'container_name': requested_container, 'return_code': return_code})}\n\n"
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except Exception:
                    process.kill()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/api/projects/{project_id}/knowledge-graph/layout")
def project_knowledge_graph_layout(
    project_id: str,
    payload: GraphAiLayoutRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        return graph_generate_layout(
            project_id=project.id,
            project_name=str(project.name or project.id),
            nodes=[row.model_dump() for row in payload.nodes],
            edges=[row.model_dump() for row in payload.edges],
            node_width=payload.node_width,
            node_height=payload.node_height,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"AI layout is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/knowledge/search")
def project_knowledge_search(
    project_id: str,
    q: str = Query(min_length=1),
    focus_entity_type: str | None = None,
    focus_entity_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.search_project_knowledge(
        project_id=project_id,
        query=q,
        focus_entity_type=focus_entity_type,
        focus_entity_id=focus_entity_id,
        limit=limit,
    )


@router.get("/api/projects/{project_id}/event-storming/overview")
def project_event_storming_overview(
    project_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_project_overview(project.id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/subgraph")
def project_event_storming_subgraph(
    project_id: str,
    limit_nodes: int = Query(default=120, ge=16, le=300),
    limit_edges: int = Query(default=220, ge=16, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_project_subgraph(
            project_id=project.id,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/entity-links")
def project_event_storming_entity_links(
    project_id: str,
    entity_type: str = Query(..., min_length=1),
    entity_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_entity_links(
            project_id=project.id,
            entity_type=entity_type,
            entity_id=entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.get("/api/projects/{project_id}/event-storming/component-links")
def project_event_storming_component_links(
    project_id: str,
    component_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_get_component_links(
            project_id=project.id,
            component_id=component_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.post("/api/projects/{project_id}/event-storming/review-link")
def project_event_storming_review_link(
    project_id: str,
    payload: EventStormingLinkReviewPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    try:
        require_graph_available()
        return event_storming_set_link_review_status(
            project_id=project.id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            component_id=payload.component_id,
            review_status=payload.review_status,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.post("/api/projects/{project_id}/event-storming/review-links")
def project_event_storming_review_links(
    project_id: str,
    payload: EventStormingBulkLinkReviewPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    project = _load_project_with_access(db, user, project_id)
    if not payload.items:
        return {"project_id": project.id, "updated": [], "errors": []}
    updated: list[dict] = []
    errors: list[dict] = []
    try:
        require_graph_available()
        for idx, item in enumerate(payload.items):
            try:
                updated.append(
                    event_storming_set_link_review_status(
                        project_id=project.id,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        component_id=item.component_id,
                        review_status=item.review_status,
                        confidence=item.confidence,
                    )
                )
            except Exception as exc:
                errors.append({"index": idx, "entity_id": item.entity_id, "component_id": item.component_id, "detail": str(exc)})
        return {"project_id": project.id, "updated": updated, "errors": errors}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Event storming projection is unavailable: {exc}") from exc


@router.post("/api/projects/{project_id}/members")
def add_project_member(
    project_id: str,
    payload: ProjectMemberUpsert,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).add_project_member(
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
    )


@router.post("/api/projects/{project_id}/members/{member_user_id}/remove")
def remove_project_member(
    project_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return ProjectApplicationService(db, user, command_id=command_id).remove_project_member(
        project_id=project_id,
        user_id=member_user_id,
    )
