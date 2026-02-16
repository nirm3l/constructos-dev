from __future__ import annotations

import hmac
import os
from typing import Any

from shared.settings import MCP_AUTH_TOKEN

from .service import AgentTaskService


def _require_token(auth_token: str | None):
    """Mirror AgentTaskService token enforcement for tools that bypass the app service layer."""
    if not MCP_AUTH_TOKEN:
        return
    if not auth_token or not hmac.compare_digest(auth_token, MCP_AUTH_TOKEN):
        raise RuntimeError("Invalid MCP token")


def create_mcp(*, read_only: bool = False):
    try:
        from fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("fastmcp is required to run MCP server. Install dependency: fastmcp>=2.0.0") from exc

    mcp = FastMCP(name="task-management-mcp")
    service = AgentTaskService()
    default_tool_token = os.getenv("MCP_TOOL_AUTH_TOKEN", "").strip() or None

    @mcp.tool(description="List tasks in a workspace with optional filters.")
    def list_tasks(
        workspace_id: str,
        auth_token: str | None = None,
        view: str | None = None,
        q: str | None = None,
        status: str | None = None,
        project_id: str | None = None,
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
        task_id: str | None = None,
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
            task_id=task_id,
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

    @mcp.tool(description="Get one project rule by id.")
    def get_project_rule(rule_id: str, auth_token: str | None = None) -> dict[str, Any]:
        auth_token = auth_token or default_tool_token
        return service.get_project_rule(rule_id=rule_id, auth_token=auth_token)

    if not read_only:
        @mcp.tool(description="Apply a bulk action to multiple tasks (e.g. archive, complete, delete).")
        def bulk_task_action(
            task_ids: list[str],
            action: str,
            payload: dict[str, Any] | None = None,
            auth_token: str | None = None,
            command_id: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.bulk_task_action(task_ids=task_ids, action=action, payload=payload or {}, auth_token=auth_token, command_id=command_id)

        @mcp.tool(description="Archive all non-archived tasks in a workspace (optionally filtered by project or query).")
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

        @mcp.tool(description="Archive all non-archived notes in a workspace (optionally filtered by project or query).")
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

        @mcp.tool(description="Create a task in a workspace/project.")
        def create_task(
            title: str,
            workspace_id: str | None = None,
            auth_token: str | None = None,
            project_id: str | None = None,
            description: str = "",
            priority: str = "Med",
            due_date: str | None = None,
            recurring_rule: str | None = None,
            task_type: str = "manual",
            scheduled_instruction: str | None = None,
            scheduled_at_utc: str | None = None,
            schedule_timezone: str | None = None,
            assignee_id: str | None = None,
            labels: list[str] | None = None,
            command_id: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.create_task(
                workspace_id=workspace_id,
                title=title,
                auth_token=auth_token,
                project_id=project_id,
                description=description,
                priority=priority,
                due_date=due_date,
                recurring_rule=recurring_rule,
                task_type=task_type,
                scheduled_instruction=scheduled_instruction,
                scheduled_at_utc=scheduled_at_utc,
                schedule_timezone=schedule_timezone,
                assignee_id=assignee_id,
                labels=labels,
                command_id=command_id,
            )

        @mcp.tool(description="Create a note in a workspace/project (Markdown body).")
        def create_note(
            title: str,
            body: str = "",
            workspace_id: str | None = None,
            auth_token: str | None = None,
            project_id: str | None = None,
            task_id: str | None = None,
            tags: list[str] | None = None,
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
                task_id=task_id,
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

        @mcp.tool(description="Send an email via SMTP (requires MCP email env configuration).")
        def send_email(
            to: list[str],
            subject: str,
            body: str,
            auth_token: str | None = None,
            cc: list[str] | None = None,
            bcc: list[str] | None = None,
            html: bool = False,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            from .email import send_email_smtp

            auth_token = auth_token or default_tool_token
            _require_token(auth_token)
            return send_email_smtp(
                to=to,
                subject=subject,
                body=body,
                cc=cc or [],
                bcc=bcc or [],
                html=html,
                dry_run=dry_run,
            )

        @mcp.tool(description="Create a project in a workspace.")
        def create_project(
            name: str,
            workspace_id: str | None = None,
            auth_token: str | None = None,
            description: str = "",
            custom_statuses: list[str] | None = None,
            command_id: str | None = None,
        ) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.create_project(
                name=name,
                workspace_id=workspace_id,
                auth_token=auth_token,
                description=description,
                custom_statuses=custom_statuses,
                command_id=command_id,
            )

        @mcp.tool(description="Create a project rule in a workspace/project.")
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

        @mcp.tool(description="Patch a project rule. Accepts the same fields as ProjectRulePatch.")
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

        @mcp.tool(description="Patch a task. Accepts the same fields as TaskPatch.")
        def update_task(task_id: str, patch: dict[str, Any], auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.update_task(task_id=task_id, patch=patch, auth_token=auth_token, command_id=command_id)

        @mcp.tool(description="Mark a task as complete.")
        def complete_task(task_id: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.complete_task(task_id=task_id, auth_token=auth_token, command_id=command_id)

        @mcp.tool(description="Add a comment to a task.")
        def add_task_comment(task_id: str, body: str, auth_token: str | None = None, command_id: str | None = None) -> dict[str, Any]:
            auth_token = auth_token or default_tool_token
            return service.add_task_comment(task_id=task_id, body=body, auth_token=auth_token, command_id=command_id)

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
    port = int(os.getenv("MCP_SERVER_PORT", "8090"))
    path = os.getenv("MCP_SERVER_PATH", "/mcp").strip() or "/mcp"
    stateless_http = _env_bool("MCP_SERVER_STATELESS_HTTP", True)
    read_only = _env_bool("MCP_SERVER_READ_ONLY", False)
    create_mcp(read_only=read_only).run(
        transport=transport,
        host=host,
        port=port,
        path=path,
        stateless_http=stateless_http,
    )
