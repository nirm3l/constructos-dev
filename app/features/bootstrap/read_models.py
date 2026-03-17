from __future__ import annotations

import json
from typing import Any

from features.agents.execution_provider import encode_execution_model, parse_execution_model
from features.agents.model_registry import list_available_agent_models
from features.agents.provider_auth import resolve_provider_effective_auth_source
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from features.agents.mcp_registry import list_available_mcp_servers
from shared.models import (
    Notification,
    Project,
    ProjectMember,
    ProjectTemplateBinding,
    SavedView,
    User,
    Workspace,
    WorkspaceMember,
)
from shared.serializers import load_created_by_map, serialize_notification, to_iso_utc
from shared.settings import (
    AGENT_CHAT_CONTEXT_LIMIT_TOKENS,
    AGENT_DEFAULT_EXECUTION_PROVIDER,
    ALLOWED_EMBEDDING_MODELS,
    CONTEXT_PACK_EVIDENCE_TOP_K,
    DEFAULT_EMBEDDING_MODEL,
    VECTOR_INDEX_DISTILL_ENABLED,
    agent_default_model_for_provider,
    agent_default_reasoning_effort_for_provider,
)
from shared.vector_store import normalize_embedding_model, project_embedding_index_snapshot, vector_store_enabled


def _normalize_reasoning_effort(raw: object) -> str:
    normalized = str(raw or "").strip().lower()
    if normalized in {"max", "maximum"}:
        return "xhigh"
    if normalized in {"low", "medium", "high", "xhigh"}:
        return normalized
    return "medium"


def _parse_agent_chat_available_models(raw: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw or "").split(","):
        model = str(chunk or "").strip()
        if not model:
            continue
        key = model.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(model)
    return out


def _append_agent_chat_models(target: list[str], extras: list[str]) -> list[str]:
    out = list(target)
    seen = {model.lower() for model in out}
    for raw_model in extras:
        model = str(raw_model or "").strip()
        if not model:
            continue
        key = model.lower()
        if key in seen:
            continue
        out.append(model)
        seen.add(key)
    return out


def _normalize_agent_chat_model(raw: object) -> str:
    model = str(raw or "").strip()
    if not model:
        return ""
    provider, normalized_model = parse_execution_model(model)
    if not normalized_model:
        return ""
    return encode_execution_model(provider=provider, model=normalized_model)


def _resolve_available_default_provider() -> str:
    if resolve_provider_effective_auth_source("codex") != "none":
        return "codex"
    if resolve_provider_effective_auth_source("claude") != "none":
        return "claude"
    return str(AGENT_DEFAULT_EXECUTION_PROVIDER or "").strip().lower() or "codex"


def bootstrap_payload_read_model(db: Session, user: User) -> dict[str, Any]:
    memberships = db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).scalars().all()
    workspace_ids = [m.workspace_id for m in memberships]
    role_by_workspace = {m.workspace_id: m.role for m in memberships}
    workspaces = db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids), Workspace.is_deleted == False)).scalars().all()
    projects_all = db.execute(select(Project).where(Project.workspace_id.in_(workspace_ids), Project.is_deleted == False)).scalars().all()
    assigned_project_ids = set(
        db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.workspace_id.in_(workspace_ids),
                ProjectMember.user_id == user.id,
            )
        ).scalars().all()
    )
    projects = [
        project
        for project in projects_all
        if role_by_workspace.get(project.workspace_id) in {"Owner", "Admin"} or project.id in assigned_project_ids
    ]
    users = db.execute(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id.in_(workspace_ids))
        .distinct()
    ).scalars().all()
    notifications = db.execute(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(20)).scalars().all()
    project_ids = [p.id for p in projects]
    project_members = db.execute(
        select(ProjectMember).where(
            ProjectMember.workspace_id.in_(workspace_ids),
            ProjectMember.project_id.in_(project_ids),
        )
    ).scalars().all()
    project_template_bindings = db.execute(
        select(ProjectTemplateBinding).where(
            ProjectTemplateBinding.workspace_id.in_(workspace_ids),
            ProjectTemplateBinding.project_id.in_(project_ids),
        )
    ).scalars().all()
    saved = db.execute(
        select(SavedView).where(
            SavedView.workspace_id.in_(workspace_ids),
            SavedView.project_id.in_(project_ids),
            or_(SavedView.user_id == user.id, SavedView.shared == True),
        )
    ).scalars().all()
    project_creator_map = load_created_by_map(db, "Project", project_ids)
    project_template_binding_map = {
        binding.project_id: {
            "template_key": binding.template_key,
            "template_version": binding.template_version,
            "applied_by": binding.applied_by,
            "applied_at": to_iso_utc(binding.created_at),
        }
        for binding in project_template_bindings
    }
    projects_payload = []
    for p in projects:
        index_snapshot = project_embedding_index_snapshot(
            db,
            project_id=p.id,
            embedding_enabled=bool(p.embedding_enabled),
            embedding_model=p.embedding_model,
            chat_index_mode=getattr(p, "chat_index_mode", None),
            chat_attachment_ingestion_mode=getattr(p, "chat_attachment_ingestion_mode", None),
        )
        projects_payload.append(
            {
                "id": p.id,
                "workspace_id": p.workspace_id,
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "custom_statuses": json.loads(p.custom_statuses),
                "external_refs": json.loads(p.external_refs or "[]"),
                "attachment_refs": json.loads(p.attachment_refs or "[]"),
                "embedding_enabled": bool(p.embedding_enabled),
                "embedding_model": p.embedding_model,
                "context_pack_evidence_top_k": p.context_pack_evidence_top_k,
                "automation_max_parallel_tasks": int(getattr(p, "automation_max_parallel_tasks", 4) or 4),
                "chat_index_mode": str(p.chat_index_mode or "OFF"),
                "chat_attachment_ingestion_mode": str(
                    p.chat_attachment_ingestion_mode or "METADATA_ONLY"
                ),
                "vector_index_distill_enabled": bool(
                    getattr(p, "vector_index_distill_enabled", VECTOR_INDEX_DISTILL_ENABLED)
                ),
                "event_storming_enabled": bool(getattr(p, "event_storming_enabled", True)),
                "embedding_index_status": str(index_snapshot.get("status") or "not_indexed"),
                "embedding_index_progress_pct": index_snapshot.get("progress_pct"),
                "embedding_indexed_entities": int(index_snapshot.get("indexed_entities") or 0),
                "embedding_index_expected_entities": int(index_snapshot.get("expected_entities") or 0),
                "embedding_indexed_chunks": int(index_snapshot.get("indexed_chunks") or 0),
                "created_by": project_creator_map.get(p.id, ""),
                "created_at": to_iso_utc(p.created_at),
                "updated_at": to_iso_utc(p.updated_at),
                "template_binding": project_template_binding_map.get(p.id),
            }
        )
    vector_enabled = bool(vector_store_enabled())
    discovered_agent_chat_models, discovered_default_agent_chat_model = list_available_agent_models()
    preferred_default_provider = _resolve_available_default_provider()
    default_agent_chat_model = _normalize_agent_chat_model(
        agent_default_model_for_provider(preferred_default_provider)
    )
    if not default_agent_chat_model:
        alternate_provider = "claude" if preferred_default_provider == "codex" else "codex"
        default_agent_chat_model = _normalize_agent_chat_model(agent_default_model_for_provider(alternate_provider))
    if not default_agent_chat_model:
        default_agent_chat_model = _normalize_agent_chat_model(discovered_default_agent_chat_model)
    if not default_agent_chat_model:
        default_agent_chat_model = "claude:sonnet" if preferred_default_provider == "claude" else "codex:gpt-5"
    agent_chat_available_models = list(discovered_agent_chat_models)
    if not agent_chat_available_models:
        agent_chat_available_models = ["codex:gpt-5", "claude:sonnet", "claude:opus"]
    available_model_keys = {model.lower() for model in agent_chat_available_models}
    if default_agent_chat_model and default_agent_chat_model.lower() not in available_model_keys:
        agent_chat_available_models.insert(0, default_agent_chat_model)
        available_model_keys.add(default_agent_chat_model.lower())
    default_agent_chat_provider, _ = parse_execution_model(default_agent_chat_model)
    default_agent_chat_reasoning_effort = _normalize_reasoning_effort(
        agent_default_reasoning_effort_for_provider(default_agent_chat_provider or "codex")
    )
    current_agent_chat_model = _normalize_agent_chat_model(getattr(user, "agent_chat_model", ""))
    if current_agent_chat_model and current_agent_chat_model.lower() not in available_model_keys:
        agent_chat_available_models.insert(0, current_agent_chat_model)
        available_model_keys.add(current_agent_chat_model.lower())
    current_agent_chat_reasoning_effort = _normalize_reasoning_effort(getattr(user, "agent_chat_reasoning_effort", ""))
    if not str(getattr(user, "agent_chat_reasoning_effort", "") or "").strip():
        current_agent_chat_reasoning_effort = default_agent_chat_reasoning_effort
    embedding_models = list(ALLOWED_EMBEDDING_MODELS)
    default_embedding_model = normalize_embedding_model(DEFAULT_EMBEDDING_MODEL)
    if embedding_models and default_embedding_model not in embedding_models:
        default_embedding_model = embedding_models[0]
    if not embedding_models and default_embedding_model:
        embedding_models = [default_embedding_model]
    agent_chat_available_mcp_servers = list_available_mcp_servers()
    return {
        "current_user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "user_type": user.user_type,
            "theme": user.theme,
            "timezone": user.timezone,
            "agent_chat_model": current_agent_chat_model,
            "agent_chat_reasoning_effort": current_agent_chat_reasoning_effort,
            "onboarding_quick_tour_completed": bool(getattr(user, "onboarding_quick_tour_completed", False)),
            "onboarding_advanced_tour_completed": bool(getattr(user, "onboarding_advanced_tour_completed", False)),
        },
        "workspaces": [{"id": w.id, "name": w.name, "type": w.type} for w in workspaces],
        "memberships": [{"workspace_id": m.workspace_id, "role": m.role} for m in memberships],
        "projects": projects_payload,
        "embedding_allowed_models": embedding_models,
        "embedding_default_model": default_embedding_model,
        "vector_store_enabled": vector_enabled,
        "context_pack_evidence_top_k_default": int(CONTEXT_PACK_EVIDENCE_TOP_K or 10),
        "agent_chat_context_limit_tokens_default": int(AGENT_CHAT_CONTEXT_LIMIT_TOKENS or 0),
        "agent_chat_default_model": default_agent_chat_model,
        "agent_chat_default_reasoning_effort": default_agent_chat_reasoning_effort,
        "agent_chat_available_models": agent_chat_available_models,
        "agent_chat_available_mcp_servers": agent_chat_available_mcp_servers,
        # Backward-compatible mirror for older UI bundles reading bootstrap.config.*
        "config": {
            "embedding_allowed_models": embedding_models,
            "embedding_default_model": default_embedding_model,
            "vector_store_enabled": vector_enabled,
            "context_pack_evidence_top_k_default": int(CONTEXT_PACK_EVIDENCE_TOP_K or 10),
            "agent_chat_context_limit_tokens_default": int(AGENT_CHAT_CONTEXT_LIMIT_TOKENS or 0),
            "agent_chat_default_model": default_agent_chat_model,
            "agent_chat_default_reasoning_effort": default_agent_chat_reasoning_effort,
            "agent_chat_available_models": agent_chat_available_models,
            "agent_chat_available_mcp_servers": agent_chat_available_mcp_servers,
        },
        "users": [{"id": u.id, "username": u.username, "full_name": u.full_name, "user_type": u.user_type} for u in users],
        "project_members": [
            {
                "project_id": pm.project_id,
                "user_id": pm.user_id,
                "role": pm.role,
            }
            for pm in project_members
        ],
        "notifications": [serialize_notification(n) for n in notifications],
        "saved_views": [
            {
                "id": s.id,
                "workspace_id": s.workspace_id,
                "project_id": s.project_id,
                "user_id": s.user_id,
                "name": s.name,
                "shared": s.shared,
                "filters": json.loads(s.filters),
            }
            for s in saved
        ],
    }
