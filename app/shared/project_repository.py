from __future__ import annotations

import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

DEFAULT_CODEX_WORKDIR = "/home/app/workspace"
PROJECT_REPOSITORIES_DIR = ".constructos/repos"
DEFAULT_TASK_APP_CONTAINER_NAME = "task-app"
DEFAULT_DOCKER_BIN = "/usr/bin/docker-real"
DEFAULT_DOCKER_PROXY_URL = "tcp://docker-socket-proxy:2375"
_COMPOSE_MANIFEST_CANDIDATES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)


def slugify_project_name(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def resolve_workspace_root() -> Path:
    raw = str(os.getenv("AGENT_CODEX_WORKDIR", DEFAULT_CODEX_WORKDIR)).strip() or DEFAULT_CODEX_WORKDIR
    path = Path(raw).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_workspace_root_for_host_docker() -> Path:
    workspace_root = resolve_workspace_root()
    container_name = (
        str(os.getenv("TASK_APP_CONTAINER_NAME") or DEFAULT_TASK_APP_CONTAINER_NAME).strip()
        or DEFAULT_TASK_APP_CONTAINER_NAME
    )
    bind_source = _resolve_container_bind_source(container_name=container_name, destination=str(workspace_root))
    if not bind_source:
        return workspace_root
    return Path(bind_source).expanduser()


def resolve_path_for_host_docker(*, path: Path) -> Path:
    normalized_path = Path(path).expanduser().resolve(strict=False)
    workspace_root = resolve_workspace_root()
    try:
        relative_path = normalized_path.relative_to(workspace_root)
    except ValueError:
        return normalized_path
    return resolve_workspace_root_for_host_docker() / relative_path


def resolve_project_repository_path(
    *,
    project_name: str | None,
    project_id: str | None = None,
) -> Path:
    workspace_root = resolve_workspace_root()
    fallback_key = str(project_id or "").strip()[:8] or "project"
    project_slug = slugify_project_name(str(project_name or "").strip(), fallback=fallback_key)
    return workspace_root / PROJECT_REPOSITORIES_DIR / project_slug


def resolve_project_repository_host_path(
    *,
    project_name: str | None,
    project_id: str | None = None,
) -> Path:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    return resolve_path_for_host_docker(path=repo_root)


def branch_is_merged_to_main(
    *,
    project_name: str | None,
    project_id: str | None = None,
    branch_name: str,
) -> bool:
    branch = str(branch_name or "").strip()
    if not branch:
        return False
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists():
        return False
    code_branch, _out_branch, _err_branch = _run_git(
        cwd=repo_root,
        args=["rev-parse", "--verify", f"refs/heads/{branch}"],
    )
    if code_branch != 0:
        return False
    code_main, _out_main, _err_main = _run_git(
        cwd=repo_root,
        args=["rev-parse", "--verify", "refs/heads/main"],
    )
    if code_main != 0:
        return False
    code_ancestor, _out_ancestor, _err_ancestor = _run_git(
        cwd=repo_root,
        args=["merge-base", "--is-ancestor", branch, "main"],
    )
    return code_ancestor == 0


def resolve_task_branch_name(*, task_id: str, title: str | None) -> str:
    task_short = slugify_project_name(str(task_id or "").strip()[:8], fallback="task")
    title_slug = slugify_project_name(str(title or "").strip(), fallback="work")
    branch_name = f"task/{task_short}-{title_slug[:40]}".rstrip("-")
    if len(branch_name) > 120:
        branch_name = branch_name[:120].rstrip("-")
    return branch_name


def resolve_task_worktree_path(
    *,
    project_name: str | None,
    project_id: str | None = None,
    task_id: str,
) -> Path:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    task_short = slugify_project_name(str(task_id or "").strip()[:8], fallback="task")
    return repo_root / ".constructos" / "worktrees" / task_short


def ensure_project_repository_initialized(
    *,
    project_name: str | None,
    project_id: str | None = None,
) -> Path:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    _ensure_git_repo_initialized(repo_root=repo_root)
    return repo_root


def find_project_compose_manifest(
    *,
    project_name: str | None,
    project_id: str | None = None,
) -> Path | None:
    repo_root = resolve_project_repository_path(project_name=project_name, project_id=project_id)
    if not repo_root.exists():
        return None
    for name in _COMPOSE_MANIFEST_CANDIDATES:
        candidate = repo_root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _run_git(*, cwd: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _docker_env_with_proxy() -> dict[str, str]:
    env = os.environ.copy()
    proxy_url = str(env.get("AGENT_DOCKER_PROXY_URL") or DEFAULT_DOCKER_PROXY_URL).strip()
    if proxy_url:
        env["DOCKER_HOST"] = proxy_url
    return env


@lru_cache(maxsize=8)
def _resolve_container_bind_source(*, container_name: str, destination: str) -> str | None:
    docker_bin = str(os.getenv("PROJECT_REPOSITORY_DOCKER_BIN") or DEFAULT_DOCKER_BIN).strip() or DEFAULT_DOCKER_BIN
    if not container_name or not destination:
        return None
    try:
        inspect_output = subprocess.check_output(
            [docker_bin, "inspect", container_name, "--format", "{{json .Mounts}}"],
            env=_docker_env_with_proxy(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        mounts = json.loads(inspect_output or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(mounts, list):
        return None
    normalized_destination = str(destination).strip()
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        mount_destination = str(mount.get("Destination") or "").strip()
        mount_source = str(mount.get("Source") or "").strip()
        if mount_destination == normalized_destination and mount_source:
            return mount_source
    return None


def _ensure_git_repo_initialized(*, repo_root: Path) -> None:
    if not (repo_root / ".git").exists():
        repo_root.mkdir(parents=True, exist_ok=True)
        code, _out, err = _run_git(cwd=repo_root, args=["init", "-b", "main"])
        if code != 0:
            raise RuntimeError(f"Failed to initialize repository at {repo_root}: {err[:200]}")
    code_head, _out_head, _err_head = _run_git(cwd=repo_root, args=["rev-parse", "--verify", "HEAD"])
    if code_head == 0:
        return
    _run_git(cwd=repo_root, args=["config", "user.name", "Constructos Automation"])
    _run_git(cwd=repo_root, args=["config", "user.email", "automation@constructos.local"])
    readme_path = repo_root / "README.md"
    if not readme_path.exists():
        readme_path.write_text("# Project Workspace\n", encoding="utf-8")
    code_add, _out_add, err_add = _run_git(cwd=repo_root, args=["add", "-A"])
    if code_add != 0:
        raise RuntimeError(f"Failed to stage bootstrap files at {repo_root}: {err_add[:200]}")
    code_commit, _out_commit, err_commit = _run_git(
        cwd=repo_root,
        args=["commit", "--allow-empty", "-m", "chore: initialize project workspace"],
    )
    if code_commit != 0:
        raise RuntimeError(f"Failed to create bootstrap commit at {repo_root}: {err_commit[:200]}")
