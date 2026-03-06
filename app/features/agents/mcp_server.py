from __future__ import annotations

import os
from typing import Any

from .gateway import build_mcp_gateway
from shared.settings import AGENT_ENABLED_PLUGINS, MCP_AUTH_TOKEN

MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED = True
MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE = "KG_AND_VECTOR"
MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE = "METADATA_ONLY"

TASK_CREATE_TOOL_DESCRIPTION = (
    "Create a task in a workspace/project. "
    "For Team Mode, route via structured fields: assignee_id (project-member UUID) and assigned_agent_code (team slot). "
    "Do not encode agent slot in labels/tags (tm.agent:* is deprecated). "
    "Use tm.role:<Developer|QA|Lead> labels only for role semantics when needed. "
    "Use agent slots already defined in the project's Team Mode configuration; avoid hardcoded mappings. "
    "Keep titles neutral; do not encode role/agent in title. "
    "Set status to choose an initial task status at creation time. "
    "execution_triggers accepts JSON string, array, or object. "
    "For status watchers use kind='status_change' with scope='self' or scope='external'. "
    "Use selector.task_ids or source_task_ids to listen to specific source tasks. "
    "External without selector.task_ids listens to all source tasks in workspace scope; "
    "add selector.project_id to constrain to one project. "
    "status_change requires at least one to_statuses value. "
    'For recurring schedules set recurring_rule with canonical format every:<number><m|h|d> (for example every:1m), and set task_type="scheduled_instruction" with scheduled_instruction and scheduled_at_utc.'
)

TASK_UPDATE_TOOL_DESCRIPTION = (
    "Patch a task. Accepts the same fields as TaskPatch. "
    "For Team Mode, update routing with assignee_id + assigned_agent_code (+ optional tm.role labels for role semantics), not by renaming titles. "
    "Do not set tm.agent:* labels. "
    "Use agent slots already defined in the project's Team Mode configuration; avoid hardcoded mappings. "
    "execution_triggers accepts JSON string, array, or object. "
    "For status watchers in patch.execution_triggers: "
    "kind='status_change', scope='self'|'external', match_mode='any'|'all', "
    "to_statuses (required), optional selector.task_ids/source_task_ids, and optional selector.project_id. "
    'For recurring schedules set recurring_rule with canonical format every:<number><m|h|d> (for example every:1m), set patch.task_type="scheduled_instruction", and provide patch.scheduled_instruction plus patch.scheduled_at_utc; then verify scheduled_at_utc and recurring_rule by reading the task.'
)

THEME_TOGGLE_TOOL_DESCRIPTION = (
    "Toggle current app-user theme between light and dark. "
    "Use this only when the user explicitly asks to toggle (not set) theme."
)

THEME_SET_TOOL_DESCRIPTION = (
    "Set current app-user theme to light or dark for the current app user profile. "
    "Use this for explicit set requests and report the resulting theme from the tool output."
)

BULK_TASK_ACTION_TOOL_DESCRIPTION = (
    "Apply a bulk action to multiple tasks (for example archive, complete, delete). "
    "Prefer this over per-task loops when the same action applies to many tasks."
)

ARCHIVE_ALL_TASKS_TOOL_DESCRIPTION = (
    "Archive all non-archived tasks in a workspace (optionally filtered by project or query). "
    "Preferred tool for 'archive all tasks/everything' requests."
)

ARCHIVE_ALL_NOTES_TOOL_DESCRIPTION = (
    "Archive all non-archived notes in a workspace (optionally filtered by project or query). "
    "Preferred tool for 'archive all notes/everything' requests."
)

CREATE_NOTE_TOOL_DESCRIPTION = (
    "Create a note in a workspace/project (Markdown body). "
    "Use this for plans/specs/design docs so they are visible in the UI. "
    "When operating in task context, pass task_id to link the note to that task."
)

CREATE_PROJECT_TOOL_DESCRIPTION = (
    "Create a project in a workspace for manual/custom setup (no template). "
    "Use when required fields are known and template seeding is not requested. "
    "Chat default profile: embedding_enabled=true, chat_index_mode=KG_AND_VECTOR, "
    "chat_attachment_ingestion_mode=METADATA_ONLY. "
    "custom_statuses must be an array of strings (for example [\"To do\",\"Dev\",\"QA\",\"Lead\",\"Done\",\"Blocked\"])."
)

UPDATE_PROJECT_TOOL_DESCRIPTION = (
    "Patch a project in a workspace/project scope. "
    "Use this to update project metadata and flags such as event_storming_enabled."
)

CREATE_PROJECT_RULE_TOOL_DESCRIPTION = (
    "Create a project rule in a workspace/project. "
    "Body is free-form project guidance text (Markdown or JSON)."
)

UPDATE_PROJECT_RULE_TOOL_DESCRIPTION = (
    "Patch a project rule. Patch accepts only title and/or body. "
    "Body is free-form project guidance text (Markdown or JSON). "
    "If patch.body is sent as an object it will be JSON-serialized."
)

LIST_PROJECT_TEMPLATES_TOOL_DESCRIPTION = (
    "List available project templates for template-based project setup."
)

GET_PROJECT_TEMPLATE_TOOL_DESCRIPTION = (
    "Get one project template definition by key, including expected parameters and seeded entities."
)

PREVIEW_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION = (
    "Preview project creation from a template without writing data. "
    "Use after parameters are known to validate what would be created. "
    "Chat default profile: embedding_enabled=true, chat_index_mode=KG_AND_VECTOR, "
    "chat_attachment_ingestion_mode=METADATA_ONLY. "
    "custom_statuses must be an array of strings when provided."
)

CREATE_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION = (
    "Create a project and seed specifications/tasks/rules from a project template. "
    "Recommended flow: list_project_templates -> get_project_template -> preview_project_from_template -> create_project_from_template. "
    "Chat default profile: embedding_enabled=true, chat_index_mode=KG_AND_VECTOR, "
    "chat_attachment_ingestion_mode=METADATA_ONLY. "
    "custom_statuses must be an array of strings when provided."
)

VERIFY_TEAM_MODE_WORKFLOW_TOOL_DESCRIPTION = (
    "Verify Team Mode workflow wiring for a project (role coverage + required trigger chain). "
    "Use this before final success claims for Team Mode setup."
)
VERIFY_DELIVERY_WORKFLOW_TOOL_DESCRIPTION = (
    "Verify delivery contract wiring for a project (Git evidence + QA artifacts). "
    "Checks include git_contract_ok, dev_tasks_have_commit_evidence, and qa_has_verifiable_artifacts."
)

ENSURE_TEAM_MODE_PROJECT_TOOL_DESCRIPTION = (
    "[Legacy fallback] Ensure Team Mode is fully ready on a project in one idempotent step: "
    "enable `team_mode` and `git_delivery` project plugins, "
    "conditionally attach/apply `github_delivery` when GitHub context exists, and return verification status. "
    "Accepts project id or exact project name via project_ref. "
    "Prefer setup_project_orchestration for new setup flows."
)

SETUP_PROJECT_ORCHESTRATION_TOOL_DESCRIPTION = (
    "Run staged project setup in one call with strict backend enforcement: "
    "project create/resolve, plugin toggles, plugin config apply, optional Team Mode task seeding, and workflow verification. "
    "Set kickoff_after_setup=true to dispatch Team Mode kickoff as part of the same call (Lead-first kickoff dispatch). "
    "Supports Team Mode, Git Delivery, and Docker Compose setup while returning a stable per-step result contract. "
    "For incomplete new-project inputs, this tool returns HTTP 422 with structured `missing_inputs` and `next_question`."
)

SEND_IN_APP_NOTIFICATION_TOOL_DESCRIPTION = (
    "Create an in-app notification for a target user. "
    "Use this when the user asks to send a direct in-app notification message. "
    "The `message` field is Markdown content (CommonMark/GFM style) and can include links, emphasis, and lists. "
    "Provide optional scope references (workspace/project/task/note/specification) to deep-link context."
)

GET_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION = (
    "Get project plugin configuration for a plugin key (`team_mode`, `git_delivery`, `docker_compose`)."
)

VALIDATE_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION = (
    "Validate draft project plugin config with strict schema and cross-field checks. "
    "Returns blocking errors/warnings and compiled policy preview. "
    "This tool does not accept command_id."
)

APPLY_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION = (
    "Apply validated project plugin config with optimistic version check (`expected_version`). "
    "Rejects invalid config. "
    "This tool does not accept command_id."
)

SET_PROJECT_PLUGIN_ENABLED_TOOL_DESCRIPTION = (
    "Enable or disable a project plugin (`team_mode`, `git_delivery`, `docker_compose`). "
    "This tool does not accept command_id."
)

DIFF_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION = (
    "Diff current vs draft project plugin config and compiled policy. "
    "Returns structured JSON pointer changes plus blocking validation errors/warnings. "
    "This tool does not accept command_id."
)

GET_PROJECT_CAPABILITIES_TOOL_DESCRIPTION = (
    "Get derived project capabilities and plugin enablement snapshot for context/tool gating."
)


def create_mcp():
    try:
        from fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("fastmcp is required to run MCP server. Install dependency: fastmcp>=2.0.0") from exc

    mcp = FastMCP(name="task-management-mcp")
    service = build_mcp_gateway()
    default_tool_token = str(MCP_AUTH_TOKEN or "").strip() or None
    enabled_plugins = {str(item or "").strip().lower() for item in (AGENT_ENABLED_PLUGINS or []) if str(item or "").strip()}
    if not enabled_plugins:
        enabled_plugins = {"team_mode", "git_delivery", "docker_compose"}

    def plugin_enabled(key: str) -> bool:
        return str(key or "").strip().lower() in enabled_plugins

    @mcp.tool(description="List tasks in a workspace with optional filters.")
    def list_tasks(
        workspace_id: str,
        auth_token: str | None = None,
        view: str | None = None,
        q: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
        task_group_id: str | None = None,
        specification_id: str | None = None,
        label: str | None = None,
        assignee_id: str | None = None,
        priority: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_tasks(
            workspace_id=workspace_id,
            auth_token=auth_token,
            view=view,
            q=q,
            status=status,
            project_id=project_id,
            task_group_id=task_group_id,
            specification_id=specification_id,
            label=label,
            assignee_id=assignee_id,
            priority=priority,
            archived=archived,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="Get one task by id.")
    def get_task(task_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_task(task_id=task_id, auth_token=auth_token)

    @mcp.tool(description="List notes in a workspace with optional filters.")
    def list_notes(
        workspace_id: str,
        auth_token: str | None = None,
        project_id: str | None = None,
        note_group_id: str | None = None,
        task_id: str | None = None,
        specification_id: str | None = None,
        q: str | None = None,
        archived: bool = False,
        pinned: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_notes(
            workspace_id=workspace_id,
            auth_token=auth_token,
            project_id=project_id,
            note_group_id=note_group_id,
            task_id=task_id,
            specification_id=specification_id,
            q=q,
            archived=archived,
            pinned=pinned,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="Get one note by id.")
    def get_note(note_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_note(note_id=note_id, auth_token=auth_token)

    @mcp.tool(description=THEME_TOGGLE_TOOL_DESCRIPTION)
    def toggle_my_theme(
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.toggle_my_theme(auth_token=auth_token, command_id=command_id)

    @mcp.tool(description=THEME_SET_TOOL_DESCRIPTION)
    def set_user_theme(
        theme: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.set_my_theme(theme=theme, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="List task groups in a workspace/project.")
    def list_task_groups(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_task_groups(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="Create a task group in a project.")
    def create_task_group(
        name: str,
        project_id: str,
        workspace_id: str | None = None,
        description: str = "",
        color: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_task_group(
            name=name,
            project_id=project_id,
            workspace_id=workspace_id,
            description=description,
            color=color,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Patch a task group.")
    def update_task_group(
        group_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_task_group(
            group_id=group_id,
            patch=patch,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Delete a task group.")
    def delete_task_group(group_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_task_group(group_id=group_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Reorder task groups in a project.")
    def reorder_task_groups(
        ordered_ids: list[str],
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.reorder_task_groups(
            ordered_ids=ordered_ids,
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="List note groups in a workspace/project.")
    def list_note_groups(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_note_groups(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="Create a note group in a project.")
    def create_note_group(
        name: str,
        project_id: str,
        workspace_id: str | None = None,
        description: str = "",
        color: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_note_group(
            name=name,
            project_id=project_id,
            workspace_id=workspace_id,
            description=description,
            color=color,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Patch a note group.")
    def update_note_group(
        group_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_note_group(
            group_id=group_id,
            patch=patch,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Delete a note group.")
    def delete_note_group(group_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_note_group(group_id=group_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Reorder note groups in a project.")
    def reorder_note_groups(
        ordered_ids: list[str],
        project_id: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.reorder_note_groups(
            ordered_ids=ordered_ids,
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="List project rules in a workspace/project.")
    def list_project_rules(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_project_rules(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List project members in a workspace/project, including UUID user ids used for assignee_id.")
    def list_project_members(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        role: str | None = None,
        user_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_project_members(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            role=role,
            user_type=user_type,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List project skills in a workspace/project.")
    def list_project_skills(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_project_skills(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List workspace skill catalog entries for a workspace.")
    def list_workspace_skills(
        workspace_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_workspace_skills(
            workspace_id=workspace_id,
            auth_token=auth_token,
            q=q,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List specifications in a workspace/project.")
    def list_specifications(
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        q: str | None = None,
        status: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_specifications(
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            q=q,
            status=status,
            archived=archived,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List tasks linked to one specification.")
    def list_spec_tasks(
        specification_id: str,
        auth_token: str | None = None,
        archived: bool = False,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_spec_tasks(
            specification_id=specification_id,
            auth_token=auth_token,
            archived=archived,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="List notes linked to one specification.")
    def list_spec_notes(
        specification_id: str,
        auth_token: str | None = None,
        archived: bool = False,
        pinned: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_spec_notes(
            specification_id=specification_id,
            auth_token=auth_token,
            archived=archived,
            pinned=pinned,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(description="Get one project rule by id.")
    def get_project_rule(rule_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_rule(rule_id=rule_id, auth_token=auth_token)

    @mcp.tool(description="Get one project skill by id.")
    def get_project_skill(skill_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_skill(skill_id=skill_id, auth_token=auth_token)

    @mcp.tool(description=GET_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION)
    def get_project_plugin_config(
        project_id: str,
        plugin_key: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_plugin_config(
            project_id=project_id,
            plugin_key=plugin_key,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )

    @mcp.tool(description=VALIDATE_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION)
    def validate_project_plugin_config(
        project_id: str,
        plugin_key: str,
        draft_config: dict[str, Any] | str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.validate_project_plugin_config(
            project_id=project_id,
            plugin_key=plugin_key,
            draft_config=draft_config,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )

    @mcp.tool(description=APPLY_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION)
    def apply_project_plugin_config(
        project_id: str,
        plugin_key: str,
        config: dict[str, Any] | str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        expected_version: int | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.apply_project_plugin_config(
            project_id=project_id,
            plugin_key=plugin_key,
            config=config,
            workspace_id=workspace_id,
            expected_version=expected_version,
            enabled=enabled,
            auth_token=auth_token,
        )

    @mcp.tool(description=SET_PROJECT_PLUGIN_ENABLED_TOOL_DESCRIPTION)
    def set_project_plugin_enabled(
        project_id: str,
        plugin_key: str,
        enabled: bool,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.set_project_plugin_enabled(
            project_id=project_id,
            plugin_key=plugin_key,
            enabled=enabled,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )

    @mcp.tool(description=DIFF_PROJECT_PLUGIN_CONFIG_TOOL_DESCRIPTION)
    def diff_project_plugin_config(
        project_id: str,
        plugin_key: str,
        draft_config: dict[str, Any] | str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.diff_project_plugin_config(
            project_id=project_id,
            plugin_key=plugin_key,
            draft_config=draft_config,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )

    @mcp.tool(description=GET_PROJECT_CAPABILITIES_TOOL_DESCRIPTION)
    def get_project_capabilities(
        project_id: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_capabilities(
            project_id=project_id,
            workspace_id=workspace_id,
            auth_token=auth_token,
        )

    @mcp.tool(description="Get one specification by id.")
    def get_specification(specification_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_specification(specification_id=specification_id, auth_token=auth_token)

    @mcp.tool(description="Read project-level knowledge graph overview (counts, tags, top relations).")
    def graph_get_project_overview(
        project_id: str,
        auth_token: str | None = None,
        top_limit: int = 8,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.graph_get_project_overview(
            project_id=project_id,
            auth_token=auth_token,
            top_limit=top_limit,
        )

    @mcp.tool(description="List graph neighbors of one entity within a project scope.")
    def graph_get_neighbors(
        project_id: str,
        entity_type: str,
        entity_id: str,
        auth_token: str | None = None,
        rel_types: list[str] | None = None,
        depth: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.graph_get_neighbors(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            auth_token=auth_token,
            rel_types=rel_types,
            depth=depth,
            limit=limit,
        )

    @mcp.tool(description="Find related resources in project knowledge graph by text query.")
    def graph_find_related_resources(
        project_id: str,
        query: str,
        auth_token: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.graph_find_related_resources(
            project_id=project_id,
            query=query,
            auth_token=auth_token,
            limit=limit,
        )

    @mcp.tool(description="Find dependency path between two entities in project knowledge graph.")
    def graph_get_dependency_path(
        project_id: str,
        from_entity_type: str,
        from_entity_id: str,
        to_entity_type: str,
        to_entity_id: str,
        auth_token: str | None = None,
        max_depth: int = 4,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.graph_get_dependency_path(
            project_id=project_id,
            from_entity_type=from_entity_type,
            from_entity_id=from_entity_id,
            to_entity_type=to_entity_type,
            to_entity_id=to_entity_id,
            auth_token=auth_token,
            max_depth=max_depth,
        )

    @mcp.tool(description="Build markdown context pack from project knowledge graph.")
    def graph_context_pack(
        project_id: str,
        auth_token: str | None = None,
        focus_entity_type: str | None = None,
        focus_entity_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.graph_context_pack(
            project_id=project_id,
            auth_token=auth_token,
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            limit=limit,
        )

    @mcp.tool(
        description=(
            "Fetch full project chat context (Soul, project rules, project skills, and graph context) "
            "by project ID or exact project name. Use this before project implementation work, and "
            "call it again if context becomes stale or incomplete."
        )
    )
    def get_project_chat_context(
        project_ref: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        graph_limit: int = 20,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_chat_context(
            project_ref=project_ref,
            workspace_id=workspace_id,
            graph_limit=graph_limit,
            auth_token=auth_token,
        )

    @mcp.tool(description="Search project knowledge using vector retrieval and graph relevance signals.")
    def search_project_knowledge(
        project_id: str,
        query: str,
        auth_token: str | None = None,
        focus_entity_type: str | None = None,
        focus_entity_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.search_project_knowledge(
            project_id=project_id,
            query=query,
            auth_token=auth_token,
            focus_entity_type=focus_entity_type,
            focus_entity_id=focus_entity_id,
            limit=limit,
        )

    @mcp.tool(description=BULK_TASK_ACTION_TOOL_DESCRIPTION)
    def bulk_task_action(
        task_ids: list[str],
        action: str,
        payload: dict[str, Any] | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.bulk_task_action(task_ids=task_ids, action=action, payload=payload or {}, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description=ARCHIVE_ALL_TASKS_TOOL_DESCRIPTION)
    def archive_all_tasks(
        workspace_id: str,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.archive_all_tasks(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            limit=limit,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description=ARCHIVE_ALL_NOTES_TOOL_DESCRIPTION)
    def archive_all_notes(
        workspace_id: str,
        project_id: str | None = None,
        q: str | None = None,
        limit: int = 200,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.archive_all_notes(
            workspace_id=workspace_id,
            project_id=project_id,
            q=q,
            limit=limit,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description=TASK_CREATE_TOOL_DESCRIPTION)
    def create_task(
        title: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        description: str = "",
        status: str | None = None,
        priority: str = "Med",
        due_date: str | None = None,
        instruction: str | None = None,
        execution_triggers: str | list[dict[str, Any]] | dict[str, Any] | None = None,
        recurring_rule: str | None = None,
        specification_id: str | None = None,
        task_group_id: str | None = None,
        task_type: str | None = None,
        scheduled_instruction: str | None = None,
        scheduled_at_utc: str | None = None,
        schedule_timezone: str | None = None,
        assignee_id: str | None = None,
        assigned_agent_code: str | None = None,
        labels: str | list[str] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        normalized_task_type = str(task_type or "").strip().lower()
        if normalized_task_type == "scheduled_instruction":
            if not str(scheduled_instruction or "").strip() and str(instruction or "").strip():
                scheduled_instruction = instruction
        return service.create_task(
            workspace_id=workspace_id,
            title=title,
            auth_token=auth_token,
            project_id=project_id,
            description=description,
            status=status,
            priority=priority,
            due_date=due_date,
            instruction=instruction,
            execution_triggers=execution_triggers,
            recurring_rule=recurring_rule,
            specification_id=specification_id,
            task_group_id=task_group_id,
            task_type=task_type,
            scheduled_instruction=scheduled_instruction,
            scheduled_at_utc=scheduled_at_utc,
            schedule_timezone=schedule_timezone,
            assignee_id=assignee_id,
            assigned_agent_code=assigned_agent_code,
            labels=labels,
            command_id=command_id,
        )

    @mcp.tool(description=CREATE_NOTE_TOOL_DESCRIPTION)
    def create_note(
        title: str,
        body: str = "",
        workspace_id: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        note_group_id: str | None = None,
        task_id: str | None = None,
        specification_id: str | None = None,
        tags: str | list[str] | None = None,
        pinned: bool = False,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_note(
            title=title,
            body=body,
            workspace_id=workspace_id,
            auth_token=auth_token,
            project_id=project_id,
            note_group_id=note_group_id,
            task_id=task_id,
            specification_id=specification_id,
            tags=tags,
            pinned=pinned,
            command_id=command_id,
        )

    @mcp.tool(description="Patch a note. Accepts the same fields as NotePatch.")
    def update_note(
        note_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_note(note_id=note_id, patch=patch, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Archive a note.")
    def archive_note(note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.archive_note(note_id=note_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Restore an archived note.")
    def restore_note(note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.restore_note(note_id=note_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Pin a note.")
    def pin_note(note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.pin_note(note_id=note_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Unpin a note.")
    def unpin_note(note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.unpin_note(note_id=note_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Soft-delete a note.")
    def delete_note(note_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_note(note_id=note_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description=CREATE_PROJECT_TOOL_DESCRIPTION)
    def create_project(
        name: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        description: str = "",
        custom_statuses: list[str] | str | None = None,
        embedding_enabled: bool = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE,
        chat_attachment_ingestion_mode: str = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE,
        event_storming_enabled: bool = True,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_project(
            name=name,
            workspace_id=workspace_id,
            auth_token=auth_token,
            description=description,
            custom_statuses=custom_statuses,
            embedding_enabled=embedding_enabled,
            embedding_model=embedding_model,
            context_pack_evidence_top_k=context_pack_evidence_top_k,
            chat_index_mode=chat_index_mode,
            chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
            event_storming_enabled=event_storming_enabled,
            command_id=command_id,
        )

    if plugin_enabled("team_mode") or plugin_enabled("git_delivery") or plugin_enabled("docker_compose"):
        @mcp.tool(description=SETUP_PROJECT_ORCHESTRATION_TOOL_DESCRIPTION)
        def setup_project_orchestration(
            name: str | None = None,
            short_description: str = "",
            project_id: str | None = None,
            workspace_id: str | None = None,
            auth_token: str | None = None,
            enable_team_mode: bool | None = None,
            enable_git_delivery: bool | None = None,
            enable_docker_compose: bool | None = None,
            docker_port: int | None = None,
            team_mode_config: dict[str, Any] | str | None = None,
            git_delivery_config: dict[str, Any] | str | None = None,
            docker_compose_config: dict[str, Any] | str | None = None,
            expected_event_storming_enabled: bool | None = None,
            seed_team_tasks: bool = True,
            kickoff_after_setup: bool = False,
            command_id: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.setup_project_orchestration(
                name=name,
                short_description=short_description,
                project_id=project_id,
                workspace_id=workspace_id,
                auth_token=auth_token,
                enable_team_mode=enable_team_mode,
                enable_git_delivery=enable_git_delivery,
                enable_docker_compose=enable_docker_compose,
                docker_port=docker_port,
                team_mode_config=team_mode_config,
                git_delivery_config=git_delivery_config,
                docker_compose_config=docker_compose_config,
                expected_event_storming_enabled=expected_event_storming_enabled,
                seed_team_tasks=seed_team_tasks,
                kickoff_after_setup=kickoff_after_setup,
                command_id=command_id,
            )

    @mcp.tool(description=UPDATE_PROJECT_TOOL_DESCRIPTION)
    def update_project(
        project_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_project(
            project_id=project_id,
            patch=patch,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description=LIST_PROJECT_TEMPLATES_TOOL_DESCRIPTION)
    def list_project_templates(
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.list_project_templates(auth_token=auth_token)

    @mcp.tool(description=GET_PROJECT_TEMPLATE_TOOL_DESCRIPTION)
    def get_project_template(
        template_key: str,
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_template(
            template_key=template_key,
            auth_token=auth_token,
        )

    @mcp.tool(description=PREVIEW_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION)
    def preview_project_from_template(
        template_key: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        name: str = "",
        description: str = "",
        custom_statuses: list[str] | str | None = None,
        member_user_ids: list[str] | None = None,
        embedding_enabled: bool | None = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE,
        chat_attachment_ingestion_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.preview_project_from_template(
            template_key=template_key,
            workspace_id=workspace_id,
            auth_token=auth_token,
            name=name,
            description=description,
            custom_statuses=custom_statuses,
            member_user_ids=member_user_ids,
            embedding_enabled=embedding_enabled,
            embedding_model=embedding_model,
            context_pack_evidence_top_k=context_pack_evidence_top_k,
            chat_index_mode=chat_index_mode,
            chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
            parameters=parameters,
        )

    @mcp.tool(description=CREATE_PROJECT_FROM_TEMPLATE_TOOL_DESCRIPTION)
    def create_project_from_template(
        template_key: str,
        name: str,
        workspace_id: str | None = None,
        auth_token: str | None = None,
        description: str = "",
        custom_statuses: list[str] | str | None = None,
        member_user_ids: list[str] | None = None,
        embedding_enabled: bool | None = MCP_DEFAULT_PROJECT_EMBEDDING_ENABLED,
        embedding_model: str | None = None,
        context_pack_evidence_top_k: int | None = None,
        chat_index_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_INDEX_MODE,
        chat_attachment_ingestion_mode: str | None = MCP_DEFAULT_PROJECT_CHAT_ATTACHMENT_INGESTION_MODE,
        parameters: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_project_from_template(
            template_key=template_key,
            name=name,
            workspace_id=workspace_id,
            auth_token=auth_token,
            description=description,
            custom_statuses=custom_statuses,
            member_user_ids=member_user_ids,
            embedding_enabled=embedding_enabled,
            embedding_model=embedding_model,
            context_pack_evidence_top_k=context_pack_evidence_top_k,
            chat_index_mode=chat_index_mode,
            chat_attachment_ingestion_mode=chat_attachment_ingestion_mode,
            parameters=parameters,
            command_id=command_id,
        )

    if plugin_enabled("team_mode"):
        @mcp.tool(description=VERIFY_TEAM_MODE_WORKFLOW_TOOL_DESCRIPTION)
        def verify_team_mode_workflow(
            project_id: str,
            workspace_id: str | None = None,
            auth_token: str | None = None,
            expected_event_storming_enabled: bool | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.verify_team_mode_workflow(
                project_id=project_id,
                workspace_id=workspace_id,
                auth_token=auth_token,
                expected_event_storming_enabled=expected_event_storming_enabled,
            )

    if plugin_enabled("git_delivery"):
        @mcp.tool(description=VERIFY_DELIVERY_WORKFLOW_TOOL_DESCRIPTION)
        def verify_delivery_workflow(
            project_id: str,
            workspace_id: str | None = None,
            auth_token: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.verify_delivery_workflow(
                project_id=project_id,
                workspace_id=workspace_id,
                auth_token=auth_token,
            )

    if plugin_enabled("team_mode"):
        @mcp.tool(description=ENSURE_TEAM_MODE_PROJECT_TOOL_DESCRIPTION)
        def ensure_team_mode_project(
            project_id: str | None = None,
            project_ref: str | None = None,
            workspace_id: str | None = None,
            auth_token: str | None = None,
            expected_event_storming_enabled: bool | None = None,
            command_id: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.ensure_team_mode_project(
                project_id=project_id,
                project_ref=project_ref,
                workspace_id=workspace_id,
                auth_token=auth_token,
                expected_event_storming_enabled=expected_event_storming_enabled,
                command_id=command_id,
            )

    @mcp.tool(description=CREATE_PROJECT_RULE_TOOL_DESCRIPTION)
    def create_project_rule(
        title: str,
        project_id: str,
        workspace_id: str | None = None,
        body: str = "",
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_project_rule(
            title=title,
            project_id=project_id,
            workspace_id=workspace_id,
            body=body,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Import an external skill URL into a project.")
    def import_project_skill(
        workspace_id: str,
        project_id: str,
        source_url: str,
        auth_token: str | None = None,
        name: str = "",
        skill_key: str = "",
        mode: str = "advisory",
        trust_level: str = "reviewed",
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.import_project_skill(
            workspace_id=workspace_id,
            project_id=project_id,
            source_url=source_url,
            auth_token=auth_token,
            name=name,
            skill_key=skill_key,
            mode=mode,
            trust_level=trust_level,
            command_id=command_id,
        )

    @mcp.tool(description="Apply a project skill to context by creating/updating its linked project rule.")
    def apply_project_skill(
        skill_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.apply_project_skill(
            skill_id=skill_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Attach a workspace catalog skill to a project.")
    def attach_workspace_skill_to_project(
        workspace_skill_id: str,
        workspace_id: str,
        project_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.attach_workspace_skill_to_project(
            workspace_skill_id=workspace_skill_id,
            workspace_id=workspace_id,
            project_id=project_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Create a specification in a workspace/project.")
    def create_specification(
        title: str,
        project_id: str,
        workspace_id: str | None = None,
        body: str = "",
        status: str = "Draft",
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_specification(
            title=title,
            project_id=project_id,
            workspace_id=workspace_id,
            body=body,
            status=status,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Create multiple tasks linked to one specification.")
    def create_tasks_from_spec(
        specification_id: str,
        titles: list[str],
        auth_token: str | None = None,
        description: str = "",
        priority: str = "Med",
        due_date: str | None = None,
        assignee_id: str | None = None,
        labels: list[str] | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.create_tasks_from_spec(
            specification_id=specification_id,
            titles=titles,
            auth_token=auth_token,
            description=description,
            priority=priority,
            due_date=due_date,
            assignee_id=assignee_id,
            labels=labels,
            command_id=command_id,
        )

    @mcp.tool(description="Link an existing task to a specification.")
    def link_task_to_spec(
        specification_id: str,
        task_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.link_task_to_spec(
            specification_id=specification_id,
            task_id=task_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Unlink a task from a specification.")
    def unlink_task_from_spec(
        specification_id: str,
        task_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.unlink_task_from_spec(
            specification_id=specification_id,
            task_id=task_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Link an existing note to a specification.")
    def link_note_to_spec(
        specification_id: str,
        note_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.link_note_to_spec(
            specification_id=specification_id,
            note_id=note_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Unlink a note from a specification.")
    def unlink_note_from_spec(
        specification_id: str,
        note_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.unlink_note_from_spec(
            specification_id=specification_id,
            note_id=note_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Patch a specification. Accepts the same fields as SpecificationPatch.")
    def update_specification(
        specification_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_specification(
            specification_id=specification_id,
            patch=patch,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Archive a specification.")
    def archive_specification(
        specification_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.archive_specification(
            specification_id=specification_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Restore an archived specification.")
    def restore_specification(
        specification_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.restore_specification(
            specification_id=specification_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Soft-delete a specification.")
    def delete_specification(
        specification_id: str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_specification(
            specification_id=specification_id,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description=UPDATE_PROJECT_RULE_TOOL_DESCRIPTION)
    def update_project_rule(
        rule_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_project_rule(rule_id=rule_id, patch=patch, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Soft-delete a project rule.")
    def delete_project_rule(rule_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_project_rule(rule_id=rule_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Patch a project skill.")
    def update_project_skill(
        skill_id: str,
        patch: dict[str, Any],
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_project_skill(
            skill_id=skill_id,
            patch=patch,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Soft-delete a project skill.")
    def delete_project_skill(
        skill_id: str,
        auth_token: str | None = None,
        delete_linked_rule: bool = True,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.delete_project_skill(
            skill_id=skill_id,
            delete_linked_rule=delete_linked_rule,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description=TASK_UPDATE_TOOL_DESCRIPTION)
    def update_task(
        task_id: str,
        patch: dict[str, Any] | str,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.update_task(task_id=task_id, patch=patch, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Mark a task as complete.")
    def complete_task(task_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.complete_task(task_id=task_id, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description="Add a comment to a task.")
    def add_task_comment(
        task_id: str,
        body: str,
        auth_token: str | None = None,
        command_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        # `workspace_id` is accepted for compatibility with model-generated tool calls.
        _ = workspace_id
        auth_token = auth_token or default_tool_token
        return service.add_task_comment(task_id=task_id, body=body, auth_token=auth_token, command_id=command_id)

    @mcp.tool(description=SEND_IN_APP_NOTIFICATION_TOOL_DESCRIPTION)
    def send_in_app_notification(
        user_id: str,
        message: str,
        auth_token: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        note_id: str | None = None,
        specification_id: str | None = None,
        notification_type: str | None = "ManualMessage",
        severity: str | None = "info",
        dedupe_key: str | None = None,
        payload: dict[str, Any] | str | None = None,
        source_event: str | None = "mcp.manual_notification",
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.send_in_app_notification(
            user_id=user_id,
            message=message,
            auth_token=auth_token,
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            note_id=note_id,
            specification_id=specification_id,
            notification_type=notification_type,
            severity=severity,
            dedupe_key=dedupe_key,
            payload=payload,
            source_event=source_event,
            command_id=command_id,
        )

    @mcp.tool(description="Queue Codex automation run for a task.")
    def run_task_with_codex(
        task_id: str,
        instruction: str | None = None,
        auth_token: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.request_task_automation_run(
            task_id=task_id,
            instruction=instruction,
            auth_token=auth_token,
            command_id=command_id,
        )

    @mcp.tool(description="Get Codex automation status for a task.")
    def get_task_automation_status(task_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_task_automation_status(task_id=task_id, auth_token=auth_token)

    return mcp


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":  # pragma: no cover
    transport = os.getenv("MCP_SERVER_TRANSPORT", "streamable-http").strip() or "streamable-http"
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.getenv("MCP_SERVER_PORT", "8091"))
    path = os.getenv("MCP_SERVER_PATH", "/mcp").strip() or "/mcp"
    stateless_http = _env_bool("MCP_SERVER_STATELESS_HTTP", True)
    create_mcp().run(
        transport=transport,
        host=host,
        port=port,
        path=path,
        stateless_http=stateless_http,
    )
