from __future__ import annotations

import os
import json
import re
import shlex
import subprocess
import threading
import signal
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select

from plugins import executor_policy as plugin_executor_policy
from plugins.team_mode.runtime_context import TeamModeProjectRuntimeContext
from plugins.team_mode.semantics import semantic_status_key
from plugins.team_mode.task_roles import canonicalize_role
from shared.context_frames import build_project_context_frame
from shared.models import Project, ProjectMember, ProjectPluginConfig, ProjectRule, ProjectSkill, SessionLocal, Task
from shared.project_repository import (
    ensure_project_repository_initialized,
    resolve_task_branch_name,
    resolve_task_worktree_path,
)
from shared.settings import AGENT_EXECUTION_COMMAND, AGENT_EXECUTOR_MODE, AGENT_EXECUTOR_TIMEOUT_SECONDS, AGENT_HOME_ROOT
from .workspace_runtime import (
    resolve_workspace_background_runtime_with_new_session,
    resolve_workspace_runtime_target_for_user,
)

_TIMEOUT_UNSET = object()
_DEFAULT_AGENT_HOME_ROOT = "/tmp/agent-home"
_TASK_AUTOMATION_SESSION_PREFIX = "task-automation:"
_APP_SOURCE_ROOT = str(Path(__file__).resolve().parents[2])
AGENT_CODEX_COMMAND = AGENT_EXECUTION_COMMAND


@dataclass(frozen=True, slots=True)
class AutomationOutcome:
    action: str
    summary: str
    comment: str | None = None
    execution_outcome_contract: dict[str, object] | None = None
    usage: dict[str, object] | None = None
    codex_session_id: str | None = None
    resume_attempted: bool = False
    resume_succeeded: bool = False
    resume_fallback_used: bool = False


def _is_completed_status(status: str | None) -> bool:
    normalized = str(status or "").strip()
    if not normalized:
        return False
    if normalized.casefold() in {"done", "completed"}:
        return True
    return semantic_status_key(status=normalized) == "completed"


def _effective_timeout_seconds(value: object) -> float | None:
    try:
        normalized = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _executor_command() -> str:
    return str(AGENT_EXECUTION_COMMAND or AGENT_CODEX_COMMAND or "").strip()


def _resolve_run_timeout_seconds(override: object = _TIMEOUT_UNSET) -> tuple[float | int | None, float | None]:
    raw_timeout = AGENT_EXECUTOR_TIMEOUT_SECONDS if override is _TIMEOUT_UNSET else override
    return raw_timeout, _effective_timeout_seconds(raw_timeout)


def _prepend_pythonpath_entry(existing: str | None, entry: str) -> str:
    normalized_entry = str(entry or "").strip()
    if not normalized_entry:
        return str(existing or "").strip()
    existing_value = str(existing or "").strip()
    if not existing_value:
        return normalized_entry
    parts = [segment.strip() for segment in existing_value.split(os.pathsep) if segment.strip()]
    if normalized_entry in parts:
        return existing_value
    return f"{normalized_entry}{os.pathsep}{existing_value}"


def _ensure_executor_pythonpath() -> None:
    os.environ["PYTHONPATH"] = _prepend_pythonpath_entry(
        os.environ.get("PYTHONPATH"),
        _APP_SOURCE_ROOT,
    )


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 0:
            return False
        if value == 1:
            return True
        return None
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def _resolve_background_runtime_preferences(
    *,
    workspace_id: str | None,
    task_id: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> tuple[str | None, str | None]:
    effective_model = str(model or "").strip() or None
    effective_reasoning_effort = str(reasoning_effort or "").strip().lower() or None
    if not workspace_id:
        return effective_model, effective_reasoning_effort
    if effective_model is not None and effective_reasoning_effort is not None:
        return effective_model, effective_reasoning_effort
    runtime_target = _resolve_task_assignee_runtime_target(
        workspace_id=workspace_id,
        task_id=task_id,
    )
    if runtime_target is None:
        runtime_target = resolve_workspace_background_runtime_with_new_session(workspace_id)
    if runtime_target is None:
        return effective_model, effective_reasoning_effort
    if effective_model is None:
        effective_model = str(runtime_target.model or "").strip() or None
    if effective_reasoning_effort is None:
        effective_reasoning_effort = str(runtime_target.reasoning_effort or "").strip().lower() or None
    return effective_model, effective_reasoning_effort


def _resolve_task_assignee_runtime_target(
    *,
    workspace_id: str | None,
    task_id: str | None,
):
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_task_id = str(task_id or "").strip()
    if not normalized_workspace_id or not normalized_task_id:
        return None
    with SessionLocal() as db:
        assignee_id = db.execute(
            select(Task.assignee_id).where(
                Task.id == normalized_task_id,
                Task.workspace_id == normalized_workspace_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        return resolve_workspace_runtime_target_for_user(
            db,
            normalized_workspace_id,
            user_id=str(assignee_id or "").strip() or None,
        )


def _graph_summary_to_markdown(summary: dict[str, object] | None) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    lines: list[str] = []
    executive = str(summary.get("executive") or "").strip()
    if executive:
        lines.append("# Grounded Summary")
        lines.append("")
        lines.append(executive)
    key_points = summary.get("key_points")
    if isinstance(key_points, list) and key_points:
        if lines:
            lines.append("")
        lines.append("## Key Points")
        for item in key_points:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            evidence_ids = [str(raw).strip() for raw in (item.get("evidence_ids") or []) if str(raw).strip()]
            if not claim:
                continue
            suffix = f" [{', '.join(evidence_ids)}]" if evidence_ids else ""
            lines.append(f"- {claim}{suffix}")
    gaps = summary.get("gaps")
    if isinstance(gaps, list) and gaps:
        if lines:
            lines.append("")
        lines.append("## Gaps")
        for gap in gaps:
            text = str(gap or "").strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines).strip()


def _load_project_context(
    project_id: str | None,
) -> tuple[str | None, str, list[dict[str, str]], list[dict[str, object]]]:
    if not project_id:
        return None, "", [], []
    with SessionLocal() as db:
        row = db.execute(
            select(Project.name, Project.description).where(Project.id == project_id, Project.is_deleted == False)
        ).first()
        rules = db.execute(
            select(ProjectRule.title, ProjectRule.body)
            .where(ProjectRule.project_id == project_id, ProjectRule.is_deleted == False)
            .order_by(ProjectRule.updated_at.desc())
        ).all()
        skills = db.execute(
            select(
                ProjectSkill.id,
                ProjectSkill.skill_key,
                ProjectSkill.name,
                ProjectSkill.summary,
                ProjectSkill.mode,
                ProjectSkill.trust_level,
                ProjectSkill.source_locator,
                ProjectSkill.generated_rule_id,
            )
            .where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.is_deleted == False,
            )
            .order_by(ProjectSkill.updated_at.desc())
        ).all()
    if not row:
        return None, "", [], []
    normalized_rules = [
        {
            "title": str(item[0] or "").strip(),
            "body": str(item[1] or ""),
        }
        for item in rules
    ]
    normalized_skills = [
        {
            "id": str(item[0] or "").strip(),
            "skill_key": str(item[1] or "").strip(),
            "name": str(item[2] or "").strip(),
            "summary": str(item[3] or "").strip(),
            "mode": str(item[4] or "").strip(),
            "trust_level": str(item[5] or "").strip(),
            "source_locator": str(item[6] or "").strip(),
            "generated_rule_id": str(item[7] or "").strip(),
        }
        for item in skills
    ]
    return str(row[0] or "").strip() or None, str(row[1] or ""), normalized_rules, normalized_skills


def _deep_merge_dicts(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


def _team_mode_runtime_context_for_project(*, db, project_id: str | None, workspace_id: str | None = None) -> TeamModeProjectRuntimeContext | None:
    normalized_project_id = str(project_id or "").strip()
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_project_id:
        return None
    if not normalized_workspace_id:
        normalized_workspace_id = str(
            db.execute(
                select(Project.workspace_id).where(
                    Project.id == normalized_project_id,
                    Project.is_deleted == False,  # noqa: E712
                )
            ).scalar_one_or_none()
            or ""
        ).strip()
    if not normalized_workspace_id:
        return None
    return TeamModeProjectRuntimeContext(
        db=db,
        workspace_id=normalized_workspace_id,
        project_id=normalized_project_id,
    )


def _load_project_plugin_runtime(
    project_id: str | None,
) -> tuple[bool, bool, str, str]:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return False, False, "_(Plugin Policy unavailable)_", "_(none)_"
    with SessionLocal() as db:
        runtime_context = _team_mode_runtime_context_for_project(db=db, project_id=normalized_project_id)
        rows = db.execute(
            select(
                ProjectPluginConfig.plugin_key,
                ProjectPluginConfig.enabled,
                ProjectPluginConfig.compiled_policy_json,
            ).where(
                ProjectPluginConfig.project_id == normalized_project_id,
                ProjectPluginConfig.plugin_key.in_(["team_mode", "git_delivery"]),
                ProjectPluginConfig.is_deleted == False,  # noqa: E712
            )
        ).all()

    policy: dict[str, object] = {}
    team_mode_enabled = bool(runtime_context.enabled) if runtime_context is not None else False
    git_delivery_enabled = False
    for plugin_key_raw, enabled_raw, compiled_policy_raw in rows:
        plugin_key = str(plugin_key_raw or "").strip().lower()
        enabled = bool(enabled_raw)
        if plugin_key == "git_delivery":
            git_delivery_enabled = enabled
        compiled_text = str(compiled_policy_raw or "").strip()
        if not compiled_text:
            continue
        try:
            parsed = json.loads(compiled_text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            policy = _deep_merge_dicts(policy, parsed)

    plugin_policy_json = json.dumps(policy, ensure_ascii=False, indent=2) if policy else "_(Plugin Policy unavailable)_"
    required_checks = policy.get("required_checks")
    if not isinstance(required_checks, dict):
        return team_mode_enabled, (git_delivery_enabled or team_mode_enabled), plugin_policy_json, "_(required_checks unavailable)_"
    lines: list[str] = []
    for scope, checks in required_checks.items():
        scope_name = str(scope or "").strip() or "unknown"
        check_names = [str(item or "").strip() for item in (checks if isinstance(checks, list) else []) if str(item or "").strip()]
        if not check_names:
            lines.append(f"- {scope_name}: _(none)_")
            continue
        lines.append(f"- {scope_name}: {', '.join(check_names)}")
    return (
        team_mode_enabled,
        (git_delivery_enabled or team_mode_enabled),
        plugin_policy_json,
        ("\n".join(lines).strip() or "_(none)_"),
    )


def _resolve_actor_project_role(*, actor_user_id: str | None, project_id: str | None) -> str | None:
    normalized_actor_user_id = str(actor_user_id or "").strip()
    normalized_project_id = str(project_id or "").strip()
    if not normalized_actor_user_id or not normalized_project_id:
        return None
    with SessionLocal() as db:
        membership = db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == normalized_project_id,
                ProjectMember.user_id == normalized_actor_user_id,
            )
        ).scalar_one_or_none()
    normalized_role = canonicalize_role(membership)
    return normalized_role or None


def _resolve_task_assignee_project_role(*, task_id: str | None, project_id: str | None) -> str | None:
    normalized_task_id = str(task_id or "").strip()
    normalized_project_id = str(project_id or "").strip()
    if not normalized_task_id or not normalized_project_id:
        return None
    with SessionLocal() as db:
        task_row = db.execute(
            select(Task.workspace_id, Task.assignee_id, Task.assigned_agent_code, Task.status, Task.labels).where(
                Task.id == normalized_task_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).first()
        if task_row is None:
            return None
        workspace_id, assignee_id, assigned_agent_code, status, labels = task_row
        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_assignee_id = str(assignee_id or "").strip()
        normalized_assigned_agent_code = str(assigned_agent_code or "").strip()
        if normalized_workspace_id:
            runtime_context = _team_mode_runtime_context_for_project(
                db=db,
                workspace_id=normalized_workspace_id,
                project_id=normalized_project_id,
            )
            if runtime_context.enabled:
                workflow_role = runtime_context.derive_workflow_role(
                    task_like={
                        "assignee_id": normalized_assignee_id,
                        "assigned_agent_code": normalized_assigned_agent_code,
                        "labels": labels,
                        "status": str(status or "").strip(),
                    }
                )
                if workflow_role:
                    return workflow_role
        if not normalized_assignee_id:
            return None
        membership = db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == normalized_project_id,
                ProjectMember.user_id == normalized_assignee_id,
            )
        ).scalar_one_or_none()
    normalized_role = canonicalize_role(membership)
    return normalized_role or None


def _should_prepare_task_worktree(
    *,
    team_mode_enabled: bool,
    git_delivery_enabled: bool,
    task_status: str,
    actor_project_role: str | None,
    assignee_project_role: str | None,
) -> bool:
    return plugin_executor_policy.should_prepare_task_worktree(
        plugin_enabled=team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        task_status=task_status,
        actor_project_role=actor_project_role,
        assignee_project_role=assignee_project_role,
    )


def _require_task_scoped_git_worktree(
    *,
    task_id: str | None,
    project_team_mode_enabled: bool,
    git_delivery_enabled: bool,
    team_mode_enabled: bool,
) -> None:
    if not str(task_id or "").strip():
        return
    if not project_team_mode_enabled or not git_delivery_enabled:
        return
    if team_mode_enabled:
        return
    raise RuntimeError(
        "[EXECUTOR_WORKTREE_SCOPE_REQUIRED] Executor refused repo-root execution: Team Mode task with Git Delivery requires a task-scoped role and worktree."
    )


def _is_task_scoped_team_mode_context_enabled(
    *,
    project_team_mode_enabled: bool,
    assignee_project_role: str | None,
) -> bool:
    return plugin_executor_policy.is_task_scoped_context_enabled(
        project_plugin_enabled=project_team_mode_enabled,
        assignee_project_role=assignee_project_role,
    )


def _slugify(value: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or fallback


def _resolve_effective_chat_session_id(
    *,
    chat_session_id: str | None,
    task_id: str | None,
) -> str | None:
    explicit = str(chat_session_id or "").strip()
    if explicit:
        return explicit
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    return f"{_TASK_AUTOMATION_SESSION_PREFIX}{normalized_task_id}"


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
    root_raw = str(AGENT_HOME_ROOT or os.getenv("AGENT_CODEX_HOME_ROOT", _DEFAULT_AGENT_HOME_ROOT)).strip() or _DEFAULT_AGENT_HOME_ROOT
    return Path(root_raw).expanduser().resolve()


def _resolve_codex_session_home_path(*, workspace_id: str, chat_session_id: str) -> Path:
    root = _resolve_codex_home_root()
    workspace_part = _normalize_path_component(workspace_id, fallback="workspace")
    session_part = _normalize_path_component(chat_session_id, fallback="session")
    return root / "workspace" / workspace_part / "chat" / session_part


def _is_codex_auth_401_failure(error_text: str) -> bool:
    hay = str(error_text or "")
    return (
        "401 Unauthorized" in hay
        and "Missing bearer or basic authentication" in hay
    )


def _purge_codex_session_home(
    *,
    workspace_id: str | None,
    chat_session_id: str | None,
) -> None:
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_chat_session_id = str(chat_session_id or "").strip()
    if not normalized_workspace_id or not normalized_chat_session_id:
        return
    session_home = _resolve_codex_session_home_path(
        workspace_id=normalized_workspace_id,
        chat_session_id=normalized_chat_session_id,
    )
    if not session_home.exists():
        return
    try:
        import shutil

        shutil.rmtree(session_home, ignore_errors=True)
    except Exception:
        return


def _run_git(*, cwd: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _collect_git_snapshot(*, cwd: Path | None, task_branch: str | None) -> dict[str, object] | None:
    if cwd is None:
        return None
    if not cwd.exists():
        return None
    code_sha, head_sha, _err_sha = _run_git(cwd=cwd, args=["rev-parse", "HEAD"])
    if code_sha != 0 or not str(head_sha or "").strip():
        return None
    code_branch, branch_name, _err_branch = _run_git(cwd=cwd, args=["branch", "--show-current"])
    normalized_branch = str(branch_name or "").strip() if code_branch == 0 else ""
    code_status, status_out, _err_status = _run_git(cwd=cwd, args=["status", "--porcelain"])
    is_dirty = bool(str(status_out or "").strip()) if code_status == 0 else False
    status_entries = [
        line
        for line in str(status_out or "").splitlines()
        if str(line or "").strip()
        and not str(line or "").strip().endswith(" .constructos/")
        and " .constructos/" not in str(line or "").strip()
    ] if code_status == 0 else []
    normalized_task_branch = str(task_branch or "").strip()
    return {
        "head_sha": str(head_sha or "").strip().lower(),
        "branch": normalized_branch or normalized_task_branch or None,
        "on_task_branch": bool(normalized_task_branch and normalized_branch == normalized_task_branch),
        "is_dirty": bool(is_dirty),
        "status_entries": status_entries,
    }


def _repo_root_changed_outside_task_worktree(
    *,
    repo_root_before: dict[str, object] | None,
    repo_root_after: dict[str, object] | None,
) -> bool:
    def _ignored_repo_root_entry(entry: object) -> bool:
        text = str(entry or "").strip()
        if not text:
            return True
        path = text[3:].strip() if len(text) > 3 else text
        if not path:
            return True
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return (
            normalized == ".constructos.host.compose.yml"
            or normalized.startswith(".constructos/")
            or normalized == ".constructos"
        )

    before = repo_root_before if isinstance(repo_root_before, dict) else {}
    after = repo_root_after if isinstance(repo_root_after, dict) else {}
    before_entries = tuple(
        str(item or "").strip()
        for item in (before.get("status_entries") or [])
        if str(item or "").strip() and not _ignored_repo_root_entry(item)
    )
    after_entries = tuple(
        str(item or "").strip()
        for item in (after.get("status_entries") or [])
        if str(item or "").strip() and not _ignored_repo_root_entry(item)
    )
    return before_entries != after_entries


def _attach_git_evidence_usage(
    outcome: AutomationOutcome,
    *,
    task_workdir: str | None,
    repo_root: str | None,
    task_branch: str | None,
    git_before: dict[str, object] | None,
    git_after: dict[str, object] | None,
) -> AutomationOutcome:
    usage_payload: dict[str, object] = dict(outcome.usage or {})
    usage_payload["git_evidence"] = {
        "task_workdir": str(task_workdir or "").strip() or None,
        "repo_root": str(repo_root or "").strip() or None,
        "task_branch": str(task_branch or "").strip() or None,
        "before": dict(git_before or {}),
        "after": dict(git_after or {}),
    }
    return AutomationOutcome(
        action=outcome.action,
        summary=outcome.summary,
        comment=outcome.comment,
        execution_outcome_contract=outcome.execution_outcome_contract,
        usage=usage_payload,
        codex_session_id=outcome.codex_session_id,
        resume_attempted=outcome.resume_attempted,
        resume_succeeded=outcome.resume_succeeded,
        resume_fallback_used=outcome.resume_fallback_used,
    )


def _ensure_task_worktree(
    *,
    project_name: str | None,
    project_id: str | None,
    task_id: str,
    title: str,
) -> tuple[Path, str, Path]:
    repo_root = ensure_project_repository_initialized(
        project_name=project_name,
        project_id=project_id,
    )
    branch_name = resolve_task_branch_name(task_id=task_id, title=title)
    task_worktree = resolve_task_worktree_path(
        project_name=project_name,
        project_id=project_id,
        task_id=task_id,
    )
    task_worktree.parent.mkdir(parents=True, exist_ok=True)

    code, _out, _err = _run_git(cwd=repo_root, args=["show-ref", "--verify", f"refs/heads/{branch_name}"])
    branch_exists = code == 0

    if not task_worktree.exists():
        if branch_exists:
            code, _out, err = _run_git(cwd=repo_root, args=["worktree", "add", str(task_worktree), branch_name])
        else:
            base_ref = "main"
            code_main, _out_main, _err_main = _run_git(cwd=repo_root, args=["show-ref", "--verify", "refs/heads/main"])
            if code_main != 0:
                base_ref = "HEAD"
            code, _out, err = _run_git(
                cwd=repo_root,
                args=["worktree", "add", "-b", branch_name, str(task_worktree), base_ref],
            )
        if code != 0:
            raise RuntimeError(f"Failed to prepare worktree for {task_id}: {err[:220]}")
    else:
        code, _out, err = _run_git(cwd=task_worktree, args=["checkout", branch_name])
        if code != 0:
            if not branch_exists:
                base_ref = "main"
                code_main, _out_main, _err_main = _run_git(cwd=repo_root, args=["show-ref", "--verify", "refs/heads/main"])
                if code_main != 0:
                    base_ref = "HEAD"
                code_b, _out_b, err_b = _run_git(cwd=repo_root, args=["branch", branch_name, base_ref])
                if code_b != 0:
                    raise RuntimeError(f"Failed to create branch {branch_name}: {err_b[:220]}")
            code_retry, _out_retry, err_retry = _run_git(cwd=task_worktree, args=["checkout", branch_name])
            if code_retry != 0:
                raise RuntimeError(f"Failed to checkout branch {branch_name}: {err_retry[:220]}")

    _sync_task_branch_with_main_if_safe(
        repo_root=repo_root,
        task_worktree=task_worktree,
        branch_name=branch_name,
    )

    return task_worktree, branch_name, repo_root


def _sync_task_branch_with_main_if_safe(
    *,
    repo_root: Path,
    task_worktree: Path,
    branch_name: str,
) -> None:
    if not branch_name:
        return
    code_main, _out_main, _err_main = _run_git(cwd=repo_root, args=["show-ref", "--verify", "refs/heads/main"])
    if code_main != 0:
        return
    code_contains_main, _out_contains_main, _err_contains_main = _run_git(
        cwd=repo_root,
        args=["merge-base", "--is-ancestor", "main", branch_name],
    )
    if code_contains_main == 0:
        return
    code_status, status_out, _err_status = _run_git(cwd=task_worktree, args=["status", "--porcelain"])
    if code_status == 0 and str(status_out or "").strip():
        return
    code_merge, out_merge, err_merge = _run_git(cwd=task_worktree, args=["merge", "--no-edit", "main"])
    if code_merge == 0:
        return
    _run_git(cwd=task_worktree, args=["merge", "--abort"])
    merge_stdout = str(out_merge or "").strip()
    merge_stderr = str(err_merge or "").strip()
    failure_preview = merge_stderr or merge_stdout
    if not failure_preview:
        # Non-diagnostic merge failures should not hard-block execution:
        # let the task reconcile flow handle merge explicitly.
        return
    normalized_failure = failure_preview.casefold()
    if (
        "automatic merge failed" in normalized_failure
        or "conflict (" in normalized_failure
        or "merge conflict" in normalized_failure
        or "local changes" in normalized_failure
        or "would be overwritten by merge" in normalized_failure
    ):
        # Conflict-like failures are expected during parallel branch evolution.
        # Abort the in-progress merge and continue so reconcile instructions
        # can be executed by the task automation run itself.
        return
    raise RuntimeError(
        "Failed to auto-reconcile latest main into "
        f"{branch_name} before execution: {failure_preview[:220]}"
    )


def _resolve_project_repo_root_and_branch(
    *,
    project_name: str | None,
    project_id: str | None,
) -> tuple[Path, str]:
    repo_root = ensure_project_repository_initialized(
        project_name=project_name,
        project_id=project_id,
    )
    code, branch_out, _err = _run_git(cwd=repo_root, args=["branch", "--show-current"])
    if code == 0 and str(branch_out or "").strip():
        return repo_root, str(branch_out or "").strip()
    return repo_root, "main"


def _placeholder_outcome(*, instruction: str, current_status: str) -> AutomationOutcome:
    should_complete = False
    if should_complete and not _is_completed_status(current_status):
        return AutomationOutcome(
            action="complete",
            summary="Automation runner marked task as completed.",
            execution_outcome_contract={
                "contract_version": 1,
                "files_changed": [],
                "commit_sha": None,
                "branch": None,
                "tests_run": False,
                "tests_passed": False,
                "artifacts": [],
            },
        )
    comment = "Agent runner: request accepted, leaving progress note."
    if instruction:
        comment += f"\nInstruction: {instruction}"
    return AutomationOutcome(
        action="comment",
        summary="Automation runner left a task comment.",
        comment=comment,
        execution_outcome_contract={
            "contract_version": 1,
            "files_changed": [],
            "commit_sha": None,
            "branch": None,
            "tests_run": False,
            "tests_passed": False,
            "artifacts": [],
        },
    )


def _normalize_execution_outcome_contract(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RuntimeError('Executor JSON must include object field "execution_outcome_contract"')
    contract_version = raw.get("contract_version")
    try:
        normalized_version = int(contract_version)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("execution_outcome_contract.contract_version must be integer 1") from exc
    if normalized_version != 1:
        raise RuntimeError("execution_outcome_contract.contract_version must be 1")

    files_changed_raw = raw.get("files_changed")
    if not isinstance(files_changed_raw, list):
        raise RuntimeError("execution_outcome_contract.files_changed must be an array")
    files_changed: list[str] = []
    for item in files_changed_raw:
        value = str(item or "").strip()
        if not value:
            continue
        files_changed.append(value)

    commit_sha_raw = raw.get("commit_sha")
    commit_sha: str | None = None
    if commit_sha_raw is not None:
        normalized_sha = str(commit_sha_raw or "").strip().lower()
        if normalized_sha:
            commit_sha = normalized_sha

    branch_raw = raw.get("branch")
    branch: str | None = None
    if branch_raw is not None:
        normalized_branch = str(branch_raw or "").strip()
        if normalized_branch:
            branch = normalized_branch

    tests_run_raw = raw.get("tests_run")
    tests_passed_raw = raw.get("tests_passed")
    if not isinstance(tests_run_raw, bool):
        raise RuntimeError("execution_outcome_contract.tests_run must be boolean")
    if not isinstance(tests_passed_raw, bool):
        raise RuntimeError("execution_outcome_contract.tests_passed must be boolean")

    artifacts_raw = raw.get("artifacts")
    if not isinstance(artifacts_raw, list):
        raise RuntimeError("execution_outcome_contract.artifacts must be an array")
    artifacts: list[dict[str, object]] = []
    for item in artifacts_raw:
        if not isinstance(item, dict):
            raise RuntimeError("execution_outcome_contract.artifacts items must be objects")
        kind = str(item.get("kind") or "").strip()
        ref = str(item.get("ref") or "").strip()
        if not kind or not ref:
            raise RuntimeError("execution_outcome_contract.artifacts items require non-empty kind and ref")
        description_raw = item.get("description")
        description: str | None = None
        if description_raw is not None:
            description = str(description_raw)
        artifacts.append({"kind": kind, "ref": ref, "description": description})

    return {
        "contract_version": 1,
        "files_changed": files_changed,
        "commit_sha": commit_sha,
        "branch": branch,
        "tests_run": tests_run_raw,
        "tests_passed": tests_passed_raw,
        "artifacts": artifacts,
    }


def _parse_command_outcome(stdout: str) -> AutomationOutcome:
    text = (stdout or "").strip()
    if not text:
        raise RuntimeError("Executor returned empty output")
    try:
        payload = json.loads(text.splitlines()[-1])
    except Exception as exc:
        raise RuntimeError(f"Executor output is not valid JSON: {text[:200]}") from exc

    action = str(payload.get("action", "")).strip().lower()
    summary = str(payload.get("summary", "")).strip()
    comment = payload.get("comment")
    execution_outcome_contract = _normalize_execution_outcome_contract(payload.get("execution_outcome_contract"))
    usage_raw = payload.get("usage")
    codex_session_id_raw = str(payload.get("codex_session_id") or "").strip()
    codex_session_id = codex_session_id_raw or None
    resume_attempted = _coerce_bool(payload.get("resume_attempted"))
    resume_succeeded = _coerce_bool(payload.get("resume_succeeded"))
    resume_fallback_used = _coerce_bool(payload.get("resume_fallback_used"))
    usage: dict[str, object] | None = None
    if isinstance(usage_raw, dict):
        usage = {}
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "context_limit_tokens"):
            raw_value = usage_raw.get(key)
            if raw_value is None:
                continue
            try:
                usage[key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                continue
        frame_mode_raw = str(usage_raw.get("graph_context_frame_mode") or "").strip().lower()
        if frame_mode_raw in {"full", "delta"}:
            usage["graph_context_frame_mode"] = frame_mode_raw
        frame_revision = str(usage_raw.get("graph_context_frame_revision") or "").strip()
        if frame_revision:
            usage["graph_context_frame_revision"] = frame_revision
        prompt_mode = str(usage_raw.get("prompt_mode") or "").strip().lower()
        if prompt_mode in {"full", "resume"}:
            usage["prompt_mode"] = prompt_mode
        segment_chars_raw = usage_raw.get("prompt_segment_chars")
        if isinstance(segment_chars_raw, dict):
            segment_chars: dict[str, int] = {}
            for key, raw_value in segment_chars_raw.items():
                normalized_key = str(key or "").strip()
                if not normalized_key:
                    continue
                try:
                    segment_chars[normalized_key] = max(0, int(raw_value))
                except (TypeError, ValueError):
                    continue
            if segment_chars:
                usage["prompt_segment_chars"] = segment_chars
        if not usage:
            usage = None
    if action not in {"complete", "comment"}:
        raise RuntimeError('Executor JSON must include "action": "complete" or "comment"')
    if not summary:
        summary = "Automation run finished."
    if comment is not None:
        comment = str(comment)
    return AutomationOutcome(
        action=action,
        summary=summary,
        comment=comment,
        execution_outcome_contract=execution_outcome_contract,
        usage=usage,
        codex_session_id=codex_session_id,
        resume_attempted=bool(resume_attempted),
        resume_succeeded=bool(resume_succeeded),
        resume_fallback_used=bool(resume_fallback_used),
    )


def _attach_context_frame_usage(
    outcome: AutomationOutcome,
    *,
    frame_mode: str,
    frame_revision: str,
) -> AutomationOutcome:
    usage_payload: dict[str, object] = dict(outcome.usage or {})
    normalized_mode = str(frame_mode or "").strip().lower()
    normalized_revision = str(frame_revision or "").strip()
    if normalized_mode in {"full", "delta"}:
        usage_payload["graph_context_frame_mode"] = normalized_mode
    if normalized_revision:
        usage_payload["graph_context_frame_revision"] = normalized_revision
    return AutomationOutcome(
        action=outcome.action,
        summary=outcome.summary,
        comment=outcome.comment,
        execution_outcome_contract=outcome.execution_outcome_contract,
        usage=usage_payload or None,
        codex_session_id=outcome.codex_session_id,
        resume_attempted=outcome.resume_attempted,
        resume_succeeded=outcome.resume_succeeded,
        resume_fallback_used=outcome.resume_fallback_used,
    )


def _sanitize_prompt_segment_chars(raw_value: object) -> dict[str, int]:
    if not isinstance(raw_value, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw_value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        try:
            out[normalized_key] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return out


def _sanitize_skill_trace(raw_value: object) -> list[dict[str, str]]:
    if not isinstance(raw_value, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        skill_key = str(item.get("skill_key") or "").strip()
        name = str(item.get("name") or "").strip()
        mode = str(item.get("mode") or "").strip().lower()
        trust_level = str(item.get("trust_level") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        source_locator = str(item.get("source_locator") or "").strip()
        if not skill_key and not name:
            continue
        out.append(
            {
                "skill_key": skill_key,
                "name": name or skill_key,
                "mode": mode,
                "trust_level": trust_level,
                "reason": reason,
                "source_locator": source_locator,
            }
        )
    return out


def _sanitize_non_negative_float(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return None
    return numeric


@lru_cache(maxsize=1)
def _load_usage_cost_rate_card() -> dict[str, object]:
    raw = str(os.getenv("AGENT_USAGE_COST_RATE_CARD_JSON", "")).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _estimate_usage_cost_usd_from_rate_card(
    *,
    usage_raw: dict[str, object],
    provider: str,
    model: str,
) -> float | None:
    rate_card = _load_usage_cost_rate_card()
    provider_table_raw = rate_card.get(provider) if isinstance(rate_card, dict) else None
    provider_table = dict(provider_table_raw) if isinstance(provider_table_raw, dict) else {}
    model_key = str(model or "").strip()
    rate_row_raw = provider_table.get(model_key) if model_key else None
    if not isinstance(rate_row_raw, dict):
        rate_row_raw = provider_table.get("*")
    rate_row = dict(rate_row_raw) if isinstance(rate_row_raw, dict) else {}
    if not rate_row:
        return None

    input_rate = _sanitize_non_negative_float(rate_row.get("input_per_1k"))
    cached_input_rate = _sanitize_non_negative_float(rate_row.get("cached_input_per_1k"))
    output_rate = _sanitize_non_negative_float(rate_row.get("output_per_1k"))
    if input_rate is None and cached_input_rate is None and output_rate is None:
        return None

    input_tokens = max(0, int(usage_raw.get("input_tokens") or 0))
    cached_input_tokens = max(0, int(usage_raw.get("cached_input_tokens") or 0))
    output_tokens = max(0, int(usage_raw.get("output_tokens") or 0))
    billable_input_tokens = max(0, input_tokens - cached_input_tokens)

    estimated = 0.0
    if input_rate is not None:
        estimated += (float(billable_input_tokens) / 1000.0) * float(input_rate)
    if cached_input_rate is not None:
        estimated += (float(cached_input_tokens) / 1000.0) * float(cached_input_rate)
    if output_rate is not None:
        estimated += (float(output_tokens) / 1000.0) * float(output_rate)
    if estimated <= 0:
        return None
    return round(estimated, 8)


def build_automation_usage_metadata(outcome: AutomationOutcome) -> dict[str, object]:
    usage_raw = outcome.usage if isinstance(outcome.usage, dict) else {}
    usage: dict[str, object] = {}
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "context_limit_tokens"):
        raw_value = usage_raw.get(key)
        if raw_value is None:
            continue
        try:
            usage[key] = max(0, int(raw_value))
        except (TypeError, ValueError):
            continue

    prompt_mode_raw = str(usage_raw.get("prompt_mode") or "").strip().lower()
    prompt_mode = prompt_mode_raw if prompt_mode_raw in {"full", "resume"} else None
    if prompt_mode:
        usage["prompt_mode"] = prompt_mode

    prompt_segment_chars = _sanitize_prompt_segment_chars(usage_raw.get("prompt_segment_chars"))
    if prompt_segment_chars:
        usage["prompt_segment_chars"] = prompt_segment_chars

    frame_mode_raw = str(usage_raw.get("graph_context_frame_mode") or "").strip().lower()
    frame_mode = frame_mode_raw if frame_mode_raw in {"full", "delta"} else None
    if frame_mode:
        usage["graph_context_frame_mode"] = frame_mode
    frame_revision = str(usage_raw.get("graph_context_frame_revision") or "").strip()
    if frame_revision:
        usage["graph_context_frame_revision"] = frame_revision
    execution_provider = str(usage_raw.get("execution_provider") or "").strip().lower()
    if execution_provider:
        usage["execution_provider"] = execution_provider
    execution_model = str(usage_raw.get("execution_model") or "").strip()
    if execution_model:
        usage["execution_model"] = execution_model
    reasoning_effort_raw = str(usage_raw.get("reasoning_effort") or "").strip().lower()
    if reasoning_effort_raw in {"low", "medium", "high", "xhigh"}:
        usage["reasoning_effort"] = reasoning_effort_raw
    cost_usd = _sanitize_non_negative_float(
        usage_raw.get("total_cost_usd")
        if usage_raw.get("total_cost_usd") is not None
        else usage_raw.get("cost_usd")
    )
    cost_estimated = False
    if cost_usd is None and execution_provider:
        estimated_cost = _estimate_usage_cost_usd_from_rate_card(
            usage_raw=usage_raw,
            provider=execution_provider,
            model=execution_model,
        )
        if estimated_cost is not None:
            cost_usd = estimated_cost
            cost_estimated = True
    if cost_usd is not None:
        usage["cost_usd"] = cost_usd
        usage["cost_estimated_from_rate_card"] = bool(cost_estimated)
    skill_trace = _sanitize_skill_trace(usage_raw.get("project_skill_trace"))
    if skill_trace:
        usage["project_skill_trace"] = skill_trace
        usage["project_skill_trace_count"] = len(skill_trace)

    codex_session_id = str(outcome.codex_session_id or "").strip() or None
    payload: dict[str, object] = {
        "last_agent_usage": usage if usage else None,
        "last_agent_execution_outcome_contract": (
            dict(outcome.execution_outcome_contract)
            if isinstance(outcome.execution_outcome_contract, dict)
            else None
        ),
        "last_agent_prompt_mode": prompt_mode,
        "last_agent_prompt_segment_chars": prompt_segment_chars or None,
        "last_agent_codex_session_id": codex_session_id,
        "last_agent_codex_resume_attempted": bool(outcome.resume_attempted),
        "last_agent_codex_resume_succeeded": bool(outcome.resume_succeeded),
        "last_agent_codex_resume_fallback_used": bool(outcome.resume_fallback_used),
    }
    return payload


def _run_command_streaming(
    *,
    command: list[str],
    context: dict[str, object],
    cwd: str | None,
    timeout_seconds: float | None,
    cancel_event: threading.Event | None = None,
    on_event: Callable[[dict[str, object]], None] | None = None,
) -> str:
    _ensure_executor_pythonpath()
    run_cwd = str(cwd or "").strip() or None
    proc = subprocess.Popen(
        command,
        cwd=run_cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    timed_out = False
    cancelled = False
    done = threading.Event()
    timeout_error_message = "Executor timed out."
    if timeout_seconds is not None:
        timeout_error_message = f"Executor timed out after {timeout_seconds:.1f}s"

    def _timeout_watchdog() -> None:
        nonlocal timed_out
        if timeout_seconds is None:
            return
        if done.wait(timeout_seconds):
            return
        if proc.poll() is None:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()

    if timeout_seconds is not None:
        watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
        watchdog.start()

    def _cancel_watchdog() -> None:
        nonlocal cancelled
        if cancel_event is None:
            return
        if done.wait(0):
            return
        cancel_event.wait()
        if done.is_set():
            return
        if proc.poll() is None:
            cancelled = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()

    if cancel_event is not None:
        cancel_thread = threading.Thread(target=_cancel_watchdog, daemon=True)
        cancel_thread.start()

    input_payload = json.dumps(context)
    if proc.stdin is None:
        raise RuntimeError("Executor stdin is unavailable")
    proc.stdin.write(input_payload)
    proc.stdin.close()

    lines: list[str] = []
    if proc.stdout is None:
        raise RuntimeError("Executor stdout is unavailable")
    for raw_line in proc.stdout:
        line = str(raw_line or "").strip()
        if not line:
            continue
        lines.append(line)
        if on_event is None:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        event_type = str(parsed.get("type") or "").strip()
        if event_type in {"assistant_text", "status", "usage"}:
            on_event(parsed)

    return_code = proc.wait()
    done.set()
    if timed_out:
        raise TimeoutError(timeout_error_message)
    if cancelled:
        raise InterruptedError("Execution cancelled by user.")
    if return_code != 0:
        err_text = "\n".join(lines).strip()
        raise RuntimeError(f"Executor failed (exit={return_code}): {err_text[:2000]}")
    return "\n".join(lines)


def execute_task_automation(
    *,
    task_id: str,
    title: str,
    description: str,
    status: str,
    instruction: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    trigger_task_id: str | None = None,
    trigger_from_status: str | None = None,
    trigger_to_status: str | None = None,
    trigger_timestamp: str | None = None,
    execution_kickoff_intent: bool = False,
    workflow_scope: str | None = None,
    execution_mode: str | None = None,
    task_completion_requested: bool = False,
    chat_session_id: str | None = None,
    codex_session_id: str | None = None,
    actor_user_id: str | None = None,
    allow_mutations: bool = True,
    mcp_servers: list[str] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    command_id: str | None = None,
    prompt_instruction_segments: dict[str, int] | None = None,
    timeout_seconds: float | int | None | object = _TIMEOUT_UNSET,
) -> AutomationOutcome:
    _ensure_executor_pythonpath()
    should_complete = bool(task_completion_requested)
    if str(task_id or "").strip() and should_complete and not _is_completed_status(status) and allow_mutations:
        return AutomationOutcome(
            action="complete",
            summary="Automation runner marked task as completed.",
            execution_outcome_contract={
                "contract_version": 1,
                "files_changed": [],
                "commit_sha": None,
                "branch": None,
                "tests_run": False,
                "tests_passed": False,
                "artifacts": [],
            },
        )

    if AGENT_EXECUTOR_MODE != "command":
        return _placeholder_outcome(instruction=instruction, current_status=status)
    executor_command = _executor_command()
    if not executor_command:
        return _placeholder_outcome(instruction=instruction, current_status=status)
    effective_model, effective_reasoning_effort = _resolve_background_runtime_preferences(
        workspace_id=workspace_id,
        task_id=task_id,
        model=model,
        reasoning_effort=reasoning_effort,
    )

    effective_chat_session_id = _resolve_effective_chat_session_id(
        chat_session_id=chat_session_id,
        task_id=task_id,
    )
    command = shlex.split(executor_command)
    project_name, project_description, project_rules, project_skills = _load_project_context(project_id)
    (
        project_team_mode_enabled,
        project_git_delivery_enabled,
        plugin_policy_json,
        plugin_policy_required_checks,
    ) = _load_project_plugin_runtime(project_id)
    actor_project_role = _resolve_actor_project_role(actor_user_id=actor_user_id, project_id=project_id)
    assignee_project_role = (
        _resolve_task_assignee_project_role(task_id=task_id, project_id=project_id)
        or actor_project_role
    )
    team_mode_enabled = _is_task_scoped_team_mode_context_enabled(
        project_team_mode_enabled=project_team_mode_enabled,
        assignee_project_role=assignee_project_role,
    )
    git_delivery_enabled = bool(project_git_delivery_enabled)
    _require_task_scoped_git_worktree(
        task_id=task_id,
        project_team_mode_enabled=project_team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        team_mode_enabled=team_mode_enabled,
    )
    effective_plugin_policy_required_checks = plugin_policy_required_checks if team_mode_enabled else []
    task_workdir: str | None = None
    task_branch: str | None = None
    repo_root: str | None = None
    if _should_prepare_task_worktree(
        team_mode_enabled=team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        task_status=status,
        actor_project_role=actor_project_role,
        assignee_project_role=assignee_project_role,
    ) and str(task_id or "").strip():
        workdir_path, branch_name, repo_root_path = _ensure_task_worktree(
            project_name=project_name,
            project_id=project_id,
            task_id=str(task_id),
            title=title,
        )
        task_workdir = str(workdir_path)
        task_branch = branch_name
        repo_root = str(repo_root_path)
    context_scope_type = "chat_session" if str(effective_chat_session_id or "").strip() else "task_automation"
    context_scope_id = str(effective_chat_session_id or "").strip() or str(task_id or "").strip() or "general"
    context_frame = build_project_context_frame(
        workspace_id=workspace_id,
        project_id=project_id,
        scope_type=context_scope_type,
        scope_id=context_scope_id,
        focus_entity_type="Task" if str(task_id or "").strip() else None,
        focus_entity_id=task_id if str(task_id or "").strip() else None,
        limit=20,
    )
    graph_context_markdown = str(context_frame.get("markdown") or "").strip()
    if not graph_context_markdown:
        graph_context_markdown = "_(knowledge graph unavailable)_"
    graph_evidence_json = json.dumps(context_frame.get("evidence") or [], ensure_ascii=True)
    graph_summary_markdown = str(context_frame.get("summary_markdown") or "").strip()
    frame_mode = str(context_frame.get("mode") or "full").strip().lower()
    frame_revision = str(context_frame.get("revision") or "").strip()
    raw_timeout, run_timeout_seconds = _resolve_run_timeout_seconds(timeout_seconds)
    context = {
        "task_id": task_id,
        "title": title,
        "description": description,
        "status": status,
        "instruction": instruction,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "trigger_task_id": trigger_task_id,
        "trigger_from_status": trigger_from_status,
        "trigger_to_status": trigger_to_status,
        "trigger_timestamp": trigger_timestamp,
        "execution_kickoff_intent": bool(execution_kickoff_intent),
        "workflow_scope": str(workflow_scope or "").strip() or None,
        "execution_mode": str(execution_mode or "").strip() or None,
        "task_completion_requested": bool(task_completion_requested),
        "chat_session_id": effective_chat_session_id,
        "codex_session_id": codex_session_id,
        "actor_user_id": actor_user_id,
        "actor_project_role": actor_project_role,
        "assignee_project_role": assignee_project_role,
        "project_name": project_name,
        "project_description": project_description,
        "project_rules": project_rules,
        "project_skills": project_skills,
        "team_mode_enabled": team_mode_enabled,
        "git_delivery_enabled": git_delivery_enabled,
        "plugin_policy_json": plugin_policy_json,
        "plugin_required_checks": effective_plugin_policy_required_checks,
        "graph_context_markdown": graph_context_markdown,
        "graph_evidence_json": graph_evidence_json,
        "graph_summary_markdown": graph_summary_markdown,
        "graph_context_frame_mode": frame_mode,
        "graph_context_frame_revision": frame_revision,
        "allow_mutations": allow_mutations,
        "mcp_servers": mcp_servers,
        "model": effective_model,
        "reasoning_effort": effective_reasoning_effort,
        "command_id": str(command_id or "").strip() or None,
        "prompt_instruction_segments": prompt_instruction_segments,
        "executor_timeout_seconds": raw_timeout,
        "task_workdir": task_workdir,
        "task_branch": task_branch,
        "repo_root": repo_root,
    }
    def _run_once() -> AutomationOutcome:
        workdir_path = Path(task_workdir) if str(task_workdir or "").strip() else None
        git_before = _collect_git_snapshot(cwd=workdir_path, task_branch=task_branch)
        repo_root_path = Path(repo_root) if str(repo_root or "").strip() else None
        repo_root_before = None
        if repo_root_path is not None and workdir_path is not None and repo_root_path != workdir_path:
            repo_root_before = _collect_git_snapshot(cwd=repo_root_path, task_branch=None)
        try:
            proc = subprocess.run(
                command,
                cwd=str(task_workdir or "").strip() or None,
                input=json.dumps(context),
                text=True,
                capture_output=True,
                timeout=run_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if run_timeout_seconds is None:
                raise TimeoutError("Executor timed out.") from exc
            raise TimeoutError(f"Executor timed out after {run_timeout_seconds:.1f}s") from exc
        if proc.returncode != 0:
            err_text = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Executor failed (exit={proc.returncode}): {err_text[:2000]}")
        parsed_outcome = _parse_command_outcome(proc.stdout)
        git_after = _collect_git_snapshot(cwd=workdir_path, task_branch=task_branch)
        repo_root_after = None
        if repo_root_path is not None and workdir_path is not None and repo_root_path != workdir_path:
            repo_root_after = _collect_git_snapshot(cwd=repo_root_path, task_branch=None)
            if _repo_root_changed_outside_task_worktree(
                repo_root_before=repo_root_before,
                repo_root_after=repo_root_after,
            ):
                raise RuntimeError(
                    "[EXECUTOR_WORKTREE_ROOT_MUTATION] Executor modified the repository root outside the task worktree. "
                    "Task automation must only edit files inside the assigned task worktree and task branch."
                )
        parsed_outcome = _attach_git_evidence_usage(
            parsed_outcome,
            task_workdir=task_workdir,
            repo_root=repo_root,
            task_branch=task_branch,
            git_before=git_before,
            git_after=git_after,
        )
        return _attach_context_frame_usage(
            parsed_outcome,
            frame_mode=frame_mode,
            frame_revision=frame_revision,
        )

    try:
        return _run_once()
    except RuntimeError as exc:
        session_id = str(effective_chat_session_id or "").strip()
        if (
            str(task_id or "").strip()
            and session_id.startswith(_TASK_AUTOMATION_SESSION_PREFIX)
            and _is_codex_auth_401_failure(str(exc))
        ):
            _purge_codex_session_home(
                workspace_id=workspace_id,
                chat_session_id=session_id,
            )
            return _run_once()
        raise


def execute_task_automation_stream(
    *,
    task_id: str,
    title: str,
    description: str,
    status: str,
    instruction: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    trigger_task_id: str | None = None,
    trigger_from_status: str | None = None,
    trigger_to_status: str | None = None,
    trigger_timestamp: str | None = None,
    execution_kickoff_intent: bool = False,
    workflow_scope: str | None = None,
    execution_mode: str | None = None,
    task_completion_requested: bool = False,
    chat_session_id: str | None = None,
    codex_session_id: str | None = None,
    actor_user_id: str | None = None,
    allow_mutations: bool = True,
    mcp_servers: list[str] | None = None,
    on_event: Callable[[dict[str, object]], None] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    command_id: str | None = None,
    prompt_instruction_segments: dict[str, int] | None = None,
    timeout_seconds: float | int | None | object = _TIMEOUT_UNSET,
    stream_plain_text: bool = False,
    cancel_event: threading.Event | None = None,
) -> AutomationOutcome:
    _ensure_executor_pythonpath()
    should_complete = bool(task_completion_requested)
    if str(task_id or "").strip() and should_complete and not _is_completed_status(status) and allow_mutations:
        return AutomationOutcome(
            action="complete",
            summary="Automation runner marked task as completed.",
            execution_outcome_contract={
                "contract_version": 1,
                "files_changed": [],
                "commit_sha": None,
                "branch": None,
                "tests_run": False,
                "tests_passed": False,
                "artifacts": [],
            },
        )

    if AGENT_EXECUTOR_MODE != "command":
        return _placeholder_outcome(instruction=instruction, current_status=status)
    executor_command = _executor_command()
    if not executor_command:
        return _placeholder_outcome(instruction=instruction, current_status=status)
    effective_model, effective_reasoning_effort = _resolve_background_runtime_preferences(
        workspace_id=workspace_id,
        task_id=task_id,
        model=model,
        reasoning_effort=reasoning_effort,
    )

    effective_chat_session_id = _resolve_effective_chat_session_id(
        chat_session_id=chat_session_id,
        task_id=task_id,
    )
    command = shlex.split(executor_command)
    project_name, project_description, project_rules, project_skills = _load_project_context(project_id)
    (
        project_team_mode_enabled,
        project_git_delivery_enabled,
        plugin_policy_json,
        plugin_policy_required_checks,
    ) = _load_project_plugin_runtime(project_id)
    actor_project_role = _resolve_actor_project_role(actor_user_id=actor_user_id, project_id=project_id)
    assignee_project_role = (
        _resolve_task_assignee_project_role(task_id=task_id, project_id=project_id)
        or actor_project_role
    )
    team_mode_enabled = _is_task_scoped_team_mode_context_enabled(
        project_team_mode_enabled=project_team_mode_enabled,
        assignee_project_role=assignee_project_role,
    )
    git_delivery_enabled = bool(project_git_delivery_enabled)
    _require_task_scoped_git_worktree(
        task_id=task_id,
        project_team_mode_enabled=project_team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        team_mode_enabled=team_mode_enabled,
    )
    effective_plugin_policy_required_checks = plugin_policy_required_checks if team_mode_enabled else []
    task_workdir: str | None = None
    task_branch: str | None = None
    repo_root: str | None = None
    if _should_prepare_task_worktree(
        team_mode_enabled=team_mode_enabled,
        git_delivery_enabled=git_delivery_enabled,
        task_status=status,
        actor_project_role=actor_project_role,
        assignee_project_role=assignee_project_role,
    ) and str(task_id or "").strip():
        workdir_path, branch_name, repo_root_path = _ensure_task_worktree(
            project_name=project_name,
            project_id=project_id,
            task_id=str(task_id),
            title=title,
        )
        task_workdir = str(workdir_path)
        task_branch = branch_name
        repo_root = str(repo_root_path)
    context_scope_type = "chat_session" if str(effective_chat_session_id or "").strip() else "task_automation"
    context_scope_id = str(effective_chat_session_id or "").strip() or str(task_id or "").strip() or "general"
    context_frame = build_project_context_frame(
        workspace_id=workspace_id,
        project_id=project_id,
        scope_type=context_scope_type,
        scope_id=context_scope_id,
        focus_entity_type="Task" if str(task_id or "").strip() else None,
        focus_entity_id=task_id if str(task_id or "").strip() else None,
        limit=20,
    )
    graph_context_markdown = str(context_frame.get("markdown") or "").strip()
    if not graph_context_markdown:
        graph_context_markdown = "_(knowledge graph unavailable)_"
    graph_evidence_json = json.dumps(context_frame.get("evidence") or [], ensure_ascii=True)
    graph_summary_markdown = str(context_frame.get("summary_markdown") or "").strip()
    frame_mode = str(context_frame.get("mode") or "full").strip().lower()
    frame_revision = str(context_frame.get("revision") or "").strip()
    raw_timeout, run_timeout_seconds = _resolve_run_timeout_seconds(timeout_seconds)
    # Chat-mode runs (no task_id) should always stream plain text deltas to the UI.
    effective_stream_plain_text = bool(stream_plain_text or not str(task_id or "").strip())

    context = {
        "task_id": task_id,
        "title": title,
        "description": description,
        "status": status,
        "instruction": instruction,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "trigger_task_id": trigger_task_id,
        "trigger_from_status": trigger_from_status,
        "trigger_to_status": trigger_to_status,
        "trigger_timestamp": trigger_timestamp,
        "execution_kickoff_intent": bool(execution_kickoff_intent),
        "workflow_scope": str(workflow_scope or "").strip() or None,
        "execution_mode": str(execution_mode or "").strip() or None,
        "task_completion_requested": bool(task_completion_requested),
        "chat_session_id": effective_chat_session_id,
        "codex_session_id": codex_session_id,
        "actor_user_id": actor_user_id,
        "actor_project_role": actor_project_role,
        "assignee_project_role": assignee_project_role,
        "project_name": project_name,
        "project_description": project_description,
        "project_rules": project_rules,
        "project_skills": project_skills,
        "team_mode_enabled": team_mode_enabled,
        "git_delivery_enabled": git_delivery_enabled,
        "plugin_policy_json": plugin_policy_json,
        "plugin_required_checks": effective_plugin_policy_required_checks,
        "graph_context_markdown": graph_context_markdown,
        "graph_evidence_json": graph_evidence_json,
        "graph_summary_markdown": graph_summary_markdown,
        "graph_context_frame_mode": frame_mode,
        "graph_context_frame_revision": frame_revision,
        "allow_mutations": allow_mutations,
        "mcp_servers": mcp_servers,
        "model": effective_model,
        "reasoning_effort": effective_reasoning_effort,
        "command_id": str(command_id or "").strip() or None,
        "prompt_instruction_segments": prompt_instruction_segments,
        "executor_timeout_seconds": raw_timeout,
        "task_workdir": task_workdir,
        "task_branch": task_branch,
        "repo_root": repo_root,
        "stream_events": True,
        "stream_plain_text": effective_stream_plain_text,
    }
    def _run_once() -> AutomationOutcome:
        workdir_path = Path(task_workdir) if str(task_workdir or "").strip() else None
        git_before = _collect_git_snapshot(cwd=workdir_path, task_branch=task_branch)
        repo_root_path = Path(repo_root) if str(repo_root or "").strip() else None
        repo_root_before = None
        if repo_root_path is not None and workdir_path is not None and repo_root_path != workdir_path:
            repo_root_before = _collect_git_snapshot(cwd=repo_root_path, task_branch=None)
        try:
            stdout = _run_command_streaming(
                command=command,
                context=context,
                cwd=str(task_workdir or "").strip() or None,
                timeout_seconds=run_timeout_seconds,
                cancel_event=cancel_event,
                on_event=on_event,
            )
        except InterruptedError:
            if on_event is not None:
                on_event({"type": "status", "message": "Run cancelled by user."})
            return AutomationOutcome(
                action="comment",
                summary="Stopped.",
                comment="Run cancelled by user.",
                execution_outcome_contract={
                    "contract_version": 1,
                    "files_changed": [],
                    "commit_sha": None,
                    "branch": None,
                    "tests_run": False,
                    "tests_passed": False,
                    "artifacts": [],
                },
            )
        parsed_outcome = _parse_command_outcome(stdout)
        git_after = _collect_git_snapshot(cwd=workdir_path, task_branch=task_branch)
        repo_root_after = None
        if repo_root_path is not None and workdir_path is not None and repo_root_path != workdir_path:
            repo_root_after = _collect_git_snapshot(cwd=repo_root_path, task_branch=None)
            if _repo_root_changed_outside_task_worktree(
                repo_root_before=repo_root_before,
                repo_root_after=repo_root_after,
            ):
                raise RuntimeError(
                    "[EXECUTOR_WORKTREE_ROOT_MUTATION] Executor modified the repository root outside the task worktree. "
                    "Task automation must only edit files inside the assigned task worktree and task branch."
                )
        parsed_outcome = _attach_git_evidence_usage(
            parsed_outcome,
            task_workdir=task_workdir,
            repo_root=repo_root,
            task_branch=task_branch,
            git_before=git_before,
            git_after=git_after,
        )
        return _attach_context_frame_usage(
            parsed_outcome,
            frame_mode=frame_mode,
            frame_revision=frame_revision,
        )

    try:
        return _run_once()
    except RuntimeError as exc:
        session_id = str(effective_chat_session_id or "").strip()
        if (
            str(task_id or "").strip()
            and session_id.startswith(_TASK_AUTOMATION_SESSION_PREFIX)
            and _is_codex_auth_401_failure(str(exc))
        ):
            _purge_codex_session_home(
                workspace_id=workspace_id,
                chat_session_id=session_id,
            )
            return _run_once()
        raise
