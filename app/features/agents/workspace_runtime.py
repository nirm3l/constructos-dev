from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import SessionLocal, User, WorkspaceAgentRuntime, WorkspaceMember
from shared.settings import (
    AGENT_DEFAULT_EXECUTION_PROVIDER,
    CLAUDE_SYSTEM_USER_ID,
    CODEX_SYSTEM_USER_ID,
    agent_default_model_for_provider,
    agent_default_reasoning_effort_for_provider,
    agent_system_user_id_for_provider,
    agent_system_username_for_provider,
)

from .execution_provider import encode_execution_model, normalize_execution_provider, parse_execution_model
from .provider_auth import resolve_provider_effective_auth_source

_ALLOWED_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
_CODEX_DEFAULT_REASONING = "medium"


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeTarget:
    workspace_id: str
    user_id: str
    username: str
    provider: str
    model: str
    reasoning_effort: str | None
    is_background_default: bool
    model_is_fallback: bool
    reasoning_is_fallback: bool


def _normalize_reasoning_effort(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    alias_map = {
        "very-high": "xhigh",
        "very_high": "xhigh",
        "very high": "xhigh",
    }
    canonical = alias_map.get(normalized, normalized)
    if canonical not in _ALLOWED_REASONING_EFFORTS:
        return None
    return canonical


def system_user_id_for_provider(provider: str) -> str:
    return agent_system_user_id_for_provider(provider)


def provider_for_system_user(*, user_id: str | None = None, username: str | None = None) -> str | None:
    normalized_user_id = str(user_id or "").strip()
    normalized_username = str(username or "").strip().lower()
    if normalized_user_id == CLAUDE_SYSTEM_USER_ID or normalized_username == agent_system_username_for_provider("claude").lower():
        return "claude"
    if normalized_user_id == CODEX_SYSTEM_USER_ID or normalized_username == agent_system_username_for_provider("codex").lower():
        return "codex"
    return None


def _fallback_model(provider: str) -> str:
    normalized_provider = normalize_execution_provider(provider)
    configured = str(agent_default_model_for_provider(normalized_provider) or "").strip()
    if normalized_provider == "claude":
        return encode_execution_model(provider="claude", model=configured or "sonnet")
    if configured:
        return encode_execution_model(provider="codex", model=configured)
    return ""


def _fallback_reasoning(provider: str) -> str | None:
    normalized_provider = normalize_execution_provider(provider)
    configured = _normalize_reasoning_effort(agent_default_reasoning_effort_for_provider(normalized_provider))
    if normalized_provider == "claude":
        return configured
    return configured or _CODEX_DEFAULT_REASONING


def normalize_workspace_runtime_model(*, provider: str, value: object) -> str:
    normalized_provider = normalize_execution_provider(provider)
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed_provider, model = parse_execution_model(raw)
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return ""
    if normalize_execution_provider(parsed_provider) != normalized_provider:
        raise ValueError(f"{normalized_provider}_bot runtime model must belong to the {normalized_provider} provider")
    return encode_execution_model(provider=normalized_provider, model=normalized_model)


def normalize_workspace_runtime_reasoning(*, provider: str, value: object) -> str:
    normalized_provider = normalize_execution_provider(provider)
    raw = str(value or "").strip()
    normalized = _normalize_reasoning_effort(value)
    if raw and normalized is None:
        raise ValueError(f"{normalized_provider}_bot reasoning_effort must be one of: {', '.join(sorted(_ALLOWED_REASONING_EFFORTS))}")
    if normalized_provider == "claude":
        return normalized or ""
    return normalized or ""


def _resolve_default_provider() -> str:
    return normalize_execution_provider(AGENT_DEFAULT_EXECUTION_PROVIDER)


def _resolve_available_default_provider() -> str:
    if resolve_provider_effective_auth_source("codex") != "none":
        return "codex"
    if resolve_provider_effective_auth_source("claude") != "none":
        return "claude"
    return _resolve_default_provider()


def _load_runtime_rows(db: Session, workspace_id: str) -> dict[str, WorkspaceAgentRuntime]:
    rows = db.execute(
        select(WorkspaceAgentRuntime).where(WorkspaceAgentRuntime.workspace_id == workspace_id)
    ).scalars().all()
    return {str(row.user_id): row for row in rows}


def _load_runtime_user_map(db: Session, workspace_id: str) -> dict[str, User]:
    rows = db.execute(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            User.id.in_([CODEX_SYSTEM_USER_ID, CLAUDE_SYSTEM_USER_ID]),
        )
    ).scalars().all()
    return {str(row.id): row for row in rows}


def list_workspace_runtime_targets(db: Session, workspace_id: str) -> dict[str, WorkspaceRuntimeTarget]:
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return {}
    runtime_rows = _load_runtime_rows(db, normalized_workspace_id)
    runtime_users = _load_runtime_user_map(db, normalized_workspace_id)
    default_provider = _resolve_default_provider()
    selected_user_id = next(
        (
            str(row.user_id)
            for row in runtime_rows.values()
            if bool(getattr(row, "is_background_default", False))
        ),
        "",
    )
    if not selected_user_id:
        selected_user_id = system_user_id_for_provider(_resolve_available_default_provider())
    out: dict[str, WorkspaceRuntimeTarget] = {}
    for provider in ("codex", "claude"):
        user_id = system_user_id_for_provider(provider)
        user = runtime_users.get(user_id)
        username = str(getattr(user, "username", "") or "").strip() or agent_system_username_for_provider(provider)
        runtime_row = runtime_rows.get(user_id)
        model = str(getattr(runtime_row, "model", "") or "").strip() or _fallback_model(provider)
        reasoning = (
            _normalize_reasoning_effort(getattr(runtime_row, "reasoning_effort", None))
            if runtime_row is not None
            else None
        )
        if reasoning is None:
            reasoning = _fallback_reasoning(provider)
        out[user_id] = WorkspaceRuntimeTarget(
            workspace_id=normalized_workspace_id,
            user_id=user_id,
            username=username,
            provider=provider,
            model=model,
            reasoning_effort=reasoning,
            is_background_default=(user_id == selected_user_id),
            model_is_fallback=not bool(str(getattr(runtime_row, "model", "") or "").strip()),
            reasoning_is_fallback=not bool(_normalize_reasoning_effort(getattr(runtime_row, "reasoning_effort", None)))
            if runtime_row is not None
            else True,
        )
    return out


def resolve_workspace_runtime_target_for_user(
    db: Session,
    workspace_id: str | None,
    *,
    user_id: str | None = None,
    username: str | None = None,
) -> WorkspaceRuntimeTarget | None:
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return None
    provider = provider_for_system_user(user_id=user_id, username=username)
    if provider is None:
        return None
    targets = list_workspace_runtime_targets(db, normalized_workspace_id)
    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id:
        target = targets.get(normalized_user_id)
        if target is not None:
            return target
    normalized_username = str(username or "").strip().lower()
    if normalized_username:
        for target in targets.values():
            if str(target.username or "").strip().lower() == normalized_username:
                return target
    fallback_user_id = system_user_id_for_provider(provider)
    target = targets.get(fallback_user_id)
    if target is not None:
        return target
        return WorkspaceRuntimeTarget(
            workspace_id=normalized_workspace_id,
            user_id=fallback_user_id,
        username=agent_system_username_for_provider(provider),
            provider=provider,
            model=_fallback_model(provider),
            reasoning_effort=_fallback_reasoning(provider),
            is_background_default=(provider == _resolve_default_provider()),
        model_is_fallback=True,
        reasoning_is_fallback=True,
    )


def resolve_workspace_background_runtime(db: Session, workspace_id: str | None) -> WorkspaceRuntimeTarget | None:
    normalized_workspace_id = str(workspace_id or "").strip()
    if not normalized_workspace_id:
        return None
    targets = list_workspace_runtime_targets(db, normalized_workspace_id)
    if not targets:
        provider = _resolve_available_default_provider()
        user_id = system_user_id_for_provider(provider)
        return WorkspaceRuntimeTarget(
            workspace_id=normalized_workspace_id,
            user_id=user_id,
            username=agent_system_username_for_provider(provider),
            provider=provider,
            model=_fallback_model(provider),
            reasoning_effort=_fallback_reasoning(provider),
            is_background_default=True,
            model_is_fallback=True,
            reasoning_is_fallback=True,
        )
    selected = next((item for item in targets.values() if item.is_background_default), None)
    if selected is not None:
        return selected
    fallback_user_id = system_user_id_for_provider(_resolve_available_default_provider())
    return targets.get(fallback_user_id) or next(iter(targets.values()))


def resolve_workspace_background_runtime_with_new_session(workspace_id: str | None) -> WorkspaceRuntimeTarget | None:
    with SessionLocal() as db:
        return resolve_workspace_background_runtime(db, workspace_id)


def resolve_workspace_runtime_target_for_user_with_new_session(
    workspace_id: str | None,
    *,
    user_id: str | None = None,
    username: str | None = None,
) -> WorkspaceRuntimeTarget | None:
    with SessionLocal() as db:
        return resolve_workspace_runtime_target_for_user(
            db,
            workspace_id,
            user_id=user_id,
            username=username,
        )


def upsert_workspace_runtime_target(
    *,
    db: Session,
    workspace_id: str,
    target_user_id: str,
    model: object | None = None,
    reasoning_effort: object | None = None,
    set_as_background_default: bool | None = None,
) -> WorkspaceRuntimeTarget:
    normalized_workspace_id = str(workspace_id or "").strip()
    normalized_user_id = str(target_user_id or "").strip()
    if not normalized_workspace_id or not normalized_user_id:
        raise ValueError("workspace_id and target_user_id are required")
    user = db.execute(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.workspace_id == normalized_workspace_id,
            User.id == normalized_user_id,
        )
    ).scalar_one_or_none()
    if user is None:
        raise ValueError("Target user is not a member of this workspace")
    provider = provider_for_system_user(user_id=normalized_user_id, username=str(user.username or ""))
    if provider is None:
        raise ValueError("Only system bot users can have workspace agent runtime settings")
    runtime = db.execute(
        select(WorkspaceAgentRuntime).where(
            WorkspaceAgentRuntime.workspace_id == normalized_workspace_id,
            WorkspaceAgentRuntime.user_id == normalized_user_id,
        )
    ).scalar_one_or_none()
    if runtime is None:
        runtime = WorkspaceAgentRuntime(
            workspace_id=normalized_workspace_id,
            user_id=normalized_user_id,
            model="",
            reasoning_effort="",
            is_background_default=False,
        )
        db.add(runtime)
        db.flush()
    if model is not None:
        runtime.model = normalize_workspace_runtime_model(provider=provider, value=model)
    if reasoning_effort is not None:
        runtime.reasoning_effort = normalize_workspace_runtime_reasoning(provider=provider, value=reasoning_effort)
    if set_as_background_default is True:
        rows = db.execute(
            select(WorkspaceAgentRuntime).where(WorkspaceAgentRuntime.workspace_id == normalized_workspace_id)
        ).scalars().all()
        for row in rows:
            row.is_background_default = str(row.user_id) == normalized_user_id
    elif set_as_background_default is False and runtime.is_background_default:
        runtime.is_background_default = False
    db.flush()
    targets = list_workspace_runtime_targets(db, normalized_workspace_id)
    target = targets.get(normalized_user_id)
    if target is None:
        raise ValueError("Workspace runtime target could not be resolved after update")
    return target
