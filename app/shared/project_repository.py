from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

DEFAULT_CODEX_WORKDIR = "/home/app/workspace"
PROJECT_REPOSITORIES_DIR = ".constructos/repos"
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


def resolve_project_repository_path(
    *,
    project_name: str | None,
    project_id: str | None = None,
) -> Path:
    workspace_root = resolve_workspace_root()
    fallback_key = str(project_id or "").strip()[:8] or "project"
    project_slug = slugify_project_name(str(project_name or "").strip(), fallback=fallback_key)
    return workspace_root / PROJECT_REPOSITORIES_DIR / project_slug


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
