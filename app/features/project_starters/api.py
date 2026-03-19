from __future__ import annotations

from fastapi import APIRouter, Depends

from features.agents.gateway import build_ui_gateway
from shared.core import get_current_user


router = APIRouter()


@router.get("/api/project-starters")
def list_project_starters(
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.list_project_starters()


@router.get("/api/project-starters/{starter_key}")
def get_project_starter(
    starter_key: str,
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_starter(starter_key=starter_key)


@router.get("/api/projects/{project_id}/setup-profile")
def get_project_setup_profile(
    project_id: str,
    user=Depends(get_current_user),
):
    gateway = build_ui_gateway(actor_user_id=user.id)
    return gateway.get_project_setup_profile(project_id=project_id)
