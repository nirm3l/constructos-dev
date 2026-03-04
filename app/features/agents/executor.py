from __future__ import annotations

import os
import json
import re
import shlex
import subprocess
import threading
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select

from plugins import executor_policy as plugin_executor_policy
from shared.context_frames import build_project_context_frame
from shared.models import Project, ProjectMember, ProjectRule, ProjectSkill, SessionLocal, Task
from shared.settings import AGENT_CODEX_COMMAND, AGENT_EXECUTOR_MODE, AGENT_EXECUTOR_TIMEOUT_SECONDS

_TIMEOUT_UNSET = object()
_DEFAULT_CODEX_WORKDIR = "/home/app/workspace"
_DEFAULT_CODEX_HOME_ROOT = "/tmp/codex-home"
_TASK_AUTOMATION_SESSION_PREFIX = "task-automation:"


@dataclass(frozen=True, slots=True)
class AutomationOutcome:
    action: str
    summary: str
    comment: str | None = None
    usage: dict[str, object] | None = None
    codex_session_id: str | None = None
    resume_attempted: bool = False
    resume_succeeded: bool = False
    resume_fallback_used: bool = False


def _effective_timeout_seconds(value: object) -> float | None:
    try:
        normalized = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _resolve_run_timeout_seconds(override: object = _TIMEOUT_UNSET) -> tuple[float | int | None, float | None]:
    raw_timeout = AGENT_EXECUTOR_TIMEOUT_SECONDS if override is _TIMEOUT_UNSET else override
    return raw_timeout, _effective_timeout_seconds(raw_timeout)


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


def _extract_gate_policy_context(project_rules: list[dict[str, str]]) -> tuple[str, str]:
    gate_rule = next(
        (
            item
            for item in project_rules
            if str(item.get("title") or "").strip().lower() == "gate policy"
        ),
        None,
    )
    if not isinstance(gate_rule, dict):
        return "_(Gate Policy not found)_", "_(none)_"
    raw_body = str(gate_rule.get("body") or "").strip()
    if not raw_body:
        return "_(Gate Policy body is empty)_", "_(none)_"
    body = raw_body
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_body, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        body = str(fenced_match.group(1) or "").strip()
    try:
        parsed = json.loads(body)
    except Exception:
        return raw_body, "_(required_checks unavailable)_"
    if not isinstance(parsed, dict):
        return raw_body, "_(required_checks unavailable)_"
    gate_policy_json = json.dumps(parsed, ensure_ascii=False, indent=2)
    required_checks = parsed.get("required_checks")
    if not isinstance(required_checks, dict):
        return gate_policy_json, "_(required_checks unavailable)_"
    lines: list[str] = []
    for scope, checks in required_checks.items():
        scope_name = str(scope or "").strip() or "unknown"
        check_names = [str(item or "").strip() for item in (checks if isinstance(checks, list) else []) if str(item or "").strip()]
        if not check_names:
            lines.append(f"- {scope_name}: _(none)_")
            continue
        lines.append(f"- {scope_name}: {', '.join(check_names)}")
    return gate_policy_json, ("\n".join(lines).strip() or "_(none)_")


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
    normalized_role = str(membership or "").strip()
    return normalized_role or None


def _resolve_task_assignee_project_role(*, task_id: str | None, project_id: str | None) -> str | None:
    normalized_task_id = str(task_id or "").strip()
    normalized_project_id = str(project_id or "").strip()
    if not normalized_task_id or not normalized_project_id:
        return None
    with SessionLocal() as db:
        assignee_id = db.execute(
            select(Task.assignee_id).where(
                Task.id == normalized_task_id,
                Task.project_id == normalized_project_id,
                Task.is_deleted == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        normalized_assignee_id = str(assignee_id or "").strip()
        if not normalized_assignee_id:
            return None
        membership = db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == normalized_project_id,
                ProjectMember.user_id == normalized_assignee_id,
            )
        ).scalar_one_or_none()
    normalized_role = str(membership or "").strip()
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


def _resolve_workspace_root() -> Path:
    raw = str(os.getenv("AGENT_CODEX_WORKDIR", _DEFAULT_CODEX_WORKDIR)).strip() or _DEFAULT_CODEX_WORKDIR
    path = Path(raw).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    root_raw = str(os.getenv("AGENT_CODEX_HOME_ROOT", _DEFAULT_CODEX_HOME_ROOT)).strip() or _DEFAULT_CODEX_HOME_ROOT
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
    code_add, _out_add, err_add = _run_git(cwd=repo_root, args=["add", "README.md"])
    if code_add != 0:
        raise RuntimeError(f"Failed to stage bootstrap files at {repo_root}: {err_add[:200]}")
    code_commit, _out_commit, err_commit = _run_git(
        cwd=repo_root,
        args=["commit", "-m", "chore: initialize project workspace"],
    )
    if code_commit != 0:
        raise RuntimeError(f"Failed to create bootstrap commit at {repo_root}: {err_commit[:200]}")


def _ensure_task_worktree(
    *,
    project_name: str | None,
    task_id: str,
    title: str,
) -> tuple[Path, str, Path]:
    workspace_root = _resolve_workspace_root()
    project_slug = _slugify(str(project_name or "").strip(), fallback="project")
    repo_root = workspace_root / project_slug
    _ensure_git_repo_initialized(repo_root=repo_root)

    task_short = _slugify(task_id[:8], fallback="task")
    title_slug = _slugify(title, fallback="work")
    branch_name = f"task/{task_short}-{title_slug[:40]}".rstrip("-")
    if len(branch_name) > 120:
        branch_name = branch_name[:120].rstrip("-")
    worktree_root = repo_root / ".constructos" / "worktrees"
    worktree_root.mkdir(parents=True, exist_ok=True)
    task_worktree = worktree_root / task_short

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

    return task_worktree, branch_name, repo_root


def _placeholder_outcome(*, instruction: str, current_status: str) -> AutomationOutcome:
    lower_instruction = instruction.lower()
    should_complete = any(token in lower_instruction for token in ("#complete", "complete task", "mark done"))
    if should_complete and current_status != "Done":
        return AutomationOutcome(action="complete", summary="Automation runner marked task as completed.")
    comment = "Codex runner: request accepted, leaving progress note."
    if instruction:
        comment += f"\nInstruction: {instruction}"
    return AutomationOutcome(action="comment", summary="Automation runner left a task comment.", comment=comment)


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
        usage=usage_payload or None,
        codex_session_id=outcome.codex_session_id,
        resume_attempted=outcome.resume_attempted,
        resume_succeeded=outcome.resume_succeeded,
        resume_fallback_used=outcome.resume_fallback_used,
    )


def _run_command_streaming(
    *,
    command: list[str],
    context: dict[str, object],
    timeout_seconds: float | None,
    on_event: Callable[[dict[str, object]], None] | None = None,
) -> str:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    timed_out = False
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
            proc.kill()

    if timeout_seconds is not None:
        watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
        watchdog.start()

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
    chat_session_id: str | None = None,
    codex_session_id: str | None = None,
    actor_user_id: str | None = None,
    allow_mutations: bool = True,
    mcp_servers: list[str] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float | int | None | object = _TIMEOUT_UNSET,
) -> AutomationOutcome:
    # Deterministic shortcut: users can explicitly complete a task via "#complete".
    # This should work regardless of executor mode, and avoids reliance on the LLM for a simple directive.
    lower_instruction = (instruction or "").lower()
    should_complete = any(token in lower_instruction for token in ("#complete", "complete task", "mark done"))
    if str(task_id or "").strip() and should_complete and status != "Done" and allow_mutations:
        return AutomationOutcome(action="complete", summary="Automation runner marked task as completed.")

    if AGENT_EXECUTOR_MODE != "command":
        return _placeholder_outcome(instruction=instruction, current_status=status)
    if not AGENT_CODEX_COMMAND:
        return _placeholder_outcome(instruction=instruction, current_status=status)

    effective_chat_session_id = _resolve_effective_chat_session_id(
        chat_session_id=chat_session_id,
        task_id=task_id,
    )
    command = shlex.split(AGENT_CODEX_COMMAND)
    project_name, project_description, project_rules, project_skills = _load_project_context(project_id)
    gate_policy_json, gate_policy_required_checks = _extract_gate_policy_context(project_rules)
    actor_project_role = _resolve_actor_project_role(actor_user_id=actor_user_id, project_id=project_id)
    assignee_project_role = (
        _resolve_task_assignee_project_role(task_id=task_id, project_id=project_id)
        or actor_project_role
    )
    workflow_skill_keys = plugin_executor_policy.workflow_plugin_skill_keys()
    project_team_mode_enabled = any(
        str(item.get("skill_key") or "").strip().lower() in workflow_skill_keys for item in project_skills
    )
    project_git_delivery_enabled = any(
        str(item.get("skill_key") or "").strip().lower() == "git_delivery" for item in project_skills
    ) or any(str(item.get("skill_key") or "").strip().lower() == "team_mode" for item in project_skills)
    team_mode_enabled = _is_task_scoped_team_mode_context_enabled(
        project_team_mode_enabled=project_team_mode_enabled,
        assignee_project_role=assignee_project_role,
    )
    git_delivery_enabled = bool(project_git_delivery_enabled and team_mode_enabled)
    effective_gate_policy_required_checks = gate_policy_required_checks if team_mode_enabled else []
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
        "gate_policy_json": gate_policy_json,
        "gate_policy_required_checks": effective_gate_policy_required_checks,
        "graph_context_markdown": graph_context_markdown,
        "graph_evidence_json": graph_evidence_json,
        "graph_summary_markdown": graph_summary_markdown,
        "graph_context_frame_mode": frame_mode,
        "graph_context_frame_revision": frame_revision,
        "allow_mutations": allow_mutations,
        "mcp_servers": mcp_servers,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "executor_timeout_seconds": raw_timeout,
        "task_workdir": task_workdir,
        "task_branch": task_branch,
        "repo_root": repo_root,
    }
    def _run_once() -> AutomationOutcome:
        try:
            proc = subprocess.run(
                command,
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
        return _attach_context_frame_usage(
            _parse_command_outcome(proc.stdout),
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
    chat_session_id: str | None = None,
    codex_session_id: str | None = None,
    actor_user_id: str | None = None,
    allow_mutations: bool = True,
    mcp_servers: list[str] | None = None,
    on_event: Callable[[dict[str, object]], None] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float | int | None | object = _TIMEOUT_UNSET,
    stream_plain_text: bool = False,
) -> AutomationOutcome:
    # Deterministic shortcut for explicit completion requests.
    lower_instruction = (instruction or "").lower()
    should_complete = any(token in lower_instruction for token in ("#complete", "complete task", "mark done"))
    if str(task_id or "").strip() and should_complete and status != "Done" and allow_mutations:
        return AutomationOutcome(action="complete", summary="Automation runner marked task as completed.")

    if AGENT_EXECUTOR_MODE != "command":
        return _placeholder_outcome(instruction=instruction, current_status=status)
    if not AGENT_CODEX_COMMAND:
        return _placeholder_outcome(instruction=instruction, current_status=status)

    effective_chat_session_id = _resolve_effective_chat_session_id(
        chat_session_id=chat_session_id,
        task_id=task_id,
    )
    command = shlex.split(AGENT_CODEX_COMMAND)
    project_name, project_description, project_rules, project_skills = _load_project_context(project_id)
    gate_policy_json, gate_policy_required_checks = _extract_gate_policy_context(project_rules)
    actor_project_role = _resolve_actor_project_role(actor_user_id=actor_user_id, project_id=project_id)
    assignee_project_role = (
        _resolve_task_assignee_project_role(task_id=task_id, project_id=project_id)
        or actor_project_role
    )
    workflow_skill_keys = plugin_executor_policy.workflow_plugin_skill_keys()
    project_team_mode_enabled = any(
        str(item.get("skill_key") or "").strip().lower() in workflow_skill_keys for item in project_skills
    )
    project_git_delivery_enabled = any(
        str(item.get("skill_key") or "").strip().lower() == "git_delivery" for item in project_skills
    ) or any(str(item.get("skill_key") or "").strip().lower() == "team_mode" for item in project_skills)
    team_mode_enabled = _is_task_scoped_team_mode_context_enabled(
        project_team_mode_enabled=project_team_mode_enabled,
        assignee_project_role=assignee_project_role,
    )
    git_delivery_enabled = bool(project_git_delivery_enabled and team_mode_enabled)
    effective_gate_policy_required_checks = gate_policy_required_checks if team_mode_enabled else []
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
        "gate_policy_json": gate_policy_json,
        "gate_policy_required_checks": effective_gate_policy_required_checks,
        "graph_context_markdown": graph_context_markdown,
        "graph_evidence_json": graph_evidence_json,
        "graph_summary_markdown": graph_summary_markdown,
        "graph_context_frame_mode": frame_mode,
        "graph_context_frame_revision": frame_revision,
        "allow_mutations": allow_mutations,
        "mcp_servers": mcp_servers,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "executor_timeout_seconds": raw_timeout,
        "task_workdir": task_workdir,
        "task_branch": task_branch,
        "repo_root": repo_root,
        "stream_events": True,
        "stream_plain_text": bool(stream_plain_text),
    }
    def _run_once() -> AutomationOutcome:
        stdout = _run_command_streaming(
            command=command,
            context=context,
            timeout_seconds=run_timeout_seconds,
            on_event=on_event,
        )
        return _attach_context_frame_usage(
            _parse_command_outcome(stdout),
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
