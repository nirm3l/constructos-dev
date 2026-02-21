from __future__ import annotations

from .service import AgentTaskService


def build_mcp_gateway() -> AgentTaskService:
    return AgentTaskService()


def build_ui_gateway(*, actor_user_id: str) -> AgentTaskService:
    return AgentTaskService(
        require_token=False,
        actor_user_id=actor_user_id,
        allowed_workspace_ids=set(),
        allowed_project_ids=set(),
        default_workspace_id="",
    )

