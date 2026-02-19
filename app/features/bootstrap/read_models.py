from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.models import Notification, Project, ProjectMember, SavedView, User, Workspace, WorkspaceMember
from shared.serializers import load_created_by_map, serialize_notification, to_iso_utc
from shared.settings import ALLOWED_EMBEDDING_MODELS, CONTEXT_PACK_EVIDENCE_TOP_K, DEFAULT_EMBEDDING_MODEL
from shared.vector_store import normalize_embedding_model, project_embedding_index_status, vector_store_enabled


def bootstrap_payload_read_model(db: Session, user: User) -> dict[str, Any]:
    memberships = db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).scalars().all()
    workspace_ids = [m.workspace_id for m in memberships]
    workspaces = db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids), Workspace.is_deleted == False)).scalars().all()
    projects = db.execute(select(Project).where(Project.workspace_id.in_(workspace_ids), Project.is_deleted == False)).scalars().all()
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
    saved = db.execute(
        select(SavedView).where(
            SavedView.workspace_id.in_(workspace_ids),
            SavedView.project_id.in_(project_ids),
            or_(SavedView.user_id == user.id, SavedView.shared == True),
        )
    ).scalars().all()
    project_creator_map = load_created_by_map(db, "Project", project_ids)
    projects_payload = []
    for p in projects:
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
                "embedding_index_status": project_embedding_index_status(
                    db,
                    project_id=p.id,
                    embedding_enabled=bool(p.embedding_enabled),
                    embedding_model=p.embedding_model,
                ),
                "created_by": project_creator_map.get(p.id, ""),
                "created_at": to_iso_utc(p.created_at),
                "updated_at": to_iso_utc(p.updated_at),
            }
        )
    vector_enabled = bool(vector_store_enabled())
    embedding_models = list(ALLOWED_EMBEDDING_MODELS)
    default_embedding_model = normalize_embedding_model(DEFAULT_EMBEDDING_MODEL)
    if embedding_models and default_embedding_model not in embedding_models:
        default_embedding_model = embedding_models[0]
    if not embedding_models and default_embedding_model:
        embedding_models = [default_embedding_model]
    return {
        "current_user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "user_type": user.user_type,
            "theme": user.theme,
            "timezone": user.timezone,
        },
        "workspaces": [{"id": w.id, "name": w.name, "type": w.type} for w in workspaces],
        "memberships": [{"workspace_id": m.workspace_id, "role": m.role} for m in memberships],
        "projects": projects_payload,
        "embedding_allowed_models": embedding_models,
        "embedding_default_model": default_embedding_model,
        "vector_store_enabled": vector_enabled,
        "context_pack_evidence_top_k_default": int(CONTEXT_PACK_EVIDENCE_TOP_K or 10),
        # Backward-compatible mirror for older UI bundles reading bootstrap.config.*
        "config": {
            "embedding_allowed_models": embedding_models,
            "embedding_default_model": default_embedding_model,
            "vector_store_enabled": vector_enabled,
            "context_pack_evidence_top_k_default": int(CONTEXT_PACK_EVIDENCE_TOP_K or 10),
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
