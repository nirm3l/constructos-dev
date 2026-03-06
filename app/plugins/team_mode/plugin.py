from __future__ import annotations

from typing import Any

from plugins.base import PolicyEvaluationContext
from .runner import (
    is_team_lead_recurring_oversight_task,
    is_team_mode_agent_project_role,
    is_team_mode_developer_role,
    is_team_mode_kickoff_instruction,
    is_team_mode_lead_role,
    is_team_mode_qa_role,
)
from .executor_policy import (
    is_task_scoped_context_enabled as team_mode_task_scoped_context_enabled,
    should_prepare_task_worktree as team_mode_should_prepare_task_worktree,
)
from .gates import (
    DEFAULT_REQUIRED_TEAM_MODE_CHECKS,
    TEAM_MODE_CHECK_DESCRIPTIONS,
    TEAM_MODE_CHECK_EVALUATORS,
    evaluate_team_mode_gates,
)
from .service_policy import (
    enforce_done_transition as team_mode_enforce_done_transition,
    open_developer_tasks as team_mode_open_developer_tasks,
    project_has_team_mode_enabled as team_mode_project_has_team_mode_enabled,
)
from .api_kickoff import maybe_dispatch_execution_kickoff as maybe_dispatch_team_mode_execution_kickoff


class TeamModePlugin:
    key = "team_mode"

    def check_scope(self) -> str | None:
        return "team_mode"

    def default_required_checks(self) -> list[str]:
        return list(DEFAULT_REQUIRED_TEAM_MODE_CHECKS)

    def check_descriptions(self) -> dict[str, str]:
        return dict(TEAM_MODE_CHECK_DESCRIPTIONS)

    def default_plugin_policy_patch(self) -> dict[str, Any]:
        return {
            "required_checks": {"team_mode": list(DEFAULT_REQUIRED_TEAM_MODE_CHECKS)},
            "available_checks": {"team_mode": dict(TEAM_MODE_CHECK_DESCRIPTIONS)},
            "team_mode": {"lead_recurring_max_minutes": 5},
        }

    def evaluate_checks(self, ctx: PolicyEvaluationContext, **kwargs: Any) -> dict[str, Any]:
        return evaluate_team_mode_gates(
            project_id=ctx.project_id,
            workspace_id=ctx.workspace_id,
            event_storming_enabled=ctx.event_storming_enabled,
            expected_event_storming_enabled=ctx.expected_event_storming_enabled,
            plugin_policy=ctx.plugin_policy,
            plugin_policy_source=ctx.plugin_policy_source,
            tasks=ctx.tasks,
            member_role_by_user_id=ctx.member_role_by_user_id,
            notes_by_task=ctx.notes_by_task,
            comments_by_task=ctx.comments_by_task,
            extract_deploy_ports=kwargs["extract_deploy_ports"],
            has_deploy_stack_marker=kwargs["has_deploy_stack_marker"],
        )

    def available_check_ids(self) -> list[str]:
        return list(TEAM_MODE_CHECK_EVALUATORS.keys())

    def runner_is_agent_project_role(self, *, role: str | None) -> bool:
        return is_team_mode_agent_project_role(role)

    def runner_is_blocker_source_role(self, *, role: str | None) -> bool:
        return is_team_mode_developer_role(role) or is_team_mode_qa_role(role)

    def runner_is_developer_role(self, *, role: str | None) -> bool:
        return is_team_mode_developer_role(role)

    def runner_is_qa_role(self, *, role: str | None) -> bool:
        return is_team_mode_qa_role(role)

    def runner_is_lead_role(self, *, role: str | None) -> bool:
        return is_team_mode_lead_role(role)

    def runner_lead_role_for_project(self, *, db: Any, workspace_id: str, project_id: str | None) -> str | None:
        normalized_project_id = str(project_id or "").strip()
        if not workspace_id or not normalized_project_id:
            return None
        if not team_mode_project_has_team_mode_enabled(
            db=db,
            workspace_id=workspace_id,
            project_id=normalized_project_id,
        ):
            return None
        return "Lead"

    def runner_is_kickoff_instruction(self, *, instruction: str | None) -> bool:
        return is_team_mode_kickoff_instruction(str(instruction or ""))

    def runner_is_recurring_oversight_task(self, *, state: dict | None) -> bool:
        return is_team_lead_recurring_oversight_task(state)

    def runner_normalize_success_outcome(
        self,
        *,
        action: str,
        summary: str,
        comment: str | None,
        instruction: str | None,
        assignee_role: str | None,
        task_state: dict | None,
    ) -> dict[str, object]:
        normalized_action = str(action or "").strip()
        normalized_summary = str(summary or "").strip()
        normalized_comment = None if comment is None else str(comment)
        if (
            normalized_action == "complete"
            and is_team_mode_lead_role(assignee_role)
            and is_team_mode_kickoff_instruction(str(instruction or ""))
        ):
            normalized_action = "comment"
            normalized_summary = "Kickoff dispatch completed; Lead oversight task remains active."
            if not str(normalized_comment or "").strip():
                normalized_comment = (
                    "Kickoff completed in dispatch-only mode. "
                    "Lead oversight task kept active for recurring coordination."
                )
        if (
            normalized_action == "complete"
            and is_team_mode_lead_role(assignee_role)
            and is_team_lead_recurring_oversight_task(task_state)
        ):
            normalized_action = "comment"
            normalized_summary = "Recurring Lead oversight cycle completed; task remains active."
            if not str(normalized_comment or "").strip():
                normalized_comment = (
                    "Recurring Team Lead oversight run completed. "
                    "Task remains active for subsequent oversight cycles."
                )
        return {"action": normalized_action, "summary": normalized_summary, "comment": normalized_comment}

    def runner_blocker_escalation_notification(
        self,
        *,
        blocked_task_id: str,
        blocked_title: str,
        blocked_role: str,
        blocked_status: str,
        blocked_error: str | None,
        queued_lead_tasks: int,
    ) -> dict[str, object]:
        return {
            "message": (
                f"Team Mode blocker detected: {blocked_title or blocked_task_id} "
                f"({blocked_role or 'agent'}, status={blocked_status or 'Blocked'}). "
                "Team Lead escalation run was queued."
            ),
            "dedupe_prefix": "team-mode-blocker",
            "kind": "team_mode_blocker_escalation",
            "source_event": "agents.runner.blocker_escalation",
        }

    def executor_is_task_scoped_context_enabled(
        self,
        *,
        project_plugin_enabled: bool,
        assignee_project_role: str | None,
    ) -> bool:
        return team_mode_task_scoped_context_enabled(
            project_team_mode_enabled=project_plugin_enabled,
            assignee_project_role=assignee_project_role,
        )

    def executor_should_prepare_task_worktree(
        self,
        *,
        plugin_enabled: bool,
        git_delivery_enabled: bool,
        task_status: str,
        actor_project_role: str | None,
        assignee_project_role: str | None,
    ) -> bool:
        return team_mode_should_prepare_task_worktree(
            team_mode_enabled=plugin_enabled,
            git_delivery_enabled=git_delivery_enabled,
            task_status=task_status,
            actor_project_role=actor_project_role,
            assignee_project_role=assignee_project_role,
        )

    def task_should_cleanup_worktree(
        self,
        *,
        plugin_enabled: bool,
        task_status: str,
        assignee_role: str | None,
    ) -> bool:
        if not plugin_enabled:
            return False
        normalized_status = str(task_status or "").strip()
        if normalized_status == "Dev":
            return False
        if normalized_status not in {"QA", "Blocked", "Done", "Lead"}:
            return False
        return is_team_mode_developer_role(assignee_role)

    def service_project_has_enabled(self, *, db: Any, workspace_id: str, project_id: str) -> bool:
        return team_mode_project_has_team_mode_enabled(
            db=db,
            workspace_id=workspace_id,
            project_id=project_id,
        )

    def service_is_delivery_active(self, *, skill_keys: set[str]) -> bool:
        normalized = {str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()}
        return self.key in normalized

    def service_open_developer_tasks(self, *, db: Any, project_id: str) -> list[dict[str, str]]:
        return team_mode_open_developer_tasks(db=db, project_id=project_id)

    def service_enforce_done_transition(
        self,
        *,
        db: Any,
        state: Any,
        assignee_role: str,
        verify_delivery_workflow_fn: Any,
        auth_token: str | None,
    ) -> None:
        team_mode_enforce_done_transition(
            db=db,
            state=state,
            assignee_role=assignee_role,
            verify_delivery_workflow_fn=verify_delivery_workflow_fn,
            auth_token=auth_token,
        )

    def service_verify_workflow(
        self,
        *,
        project_id: str,
        auth_token: str | None,
        workspace_id: str | None,
        expected_event_storming_enabled: bool | None,
        verify_workflow_core: Any,
    ) -> dict | None:
        if not callable(verify_workflow_core):
            return None
        return verify_workflow_core(
            project_id=project_id,
            auth_token=auth_token,
            workspace_id=workspace_id,
            expected_event_storming_enabled=expected_event_storming_enabled,
        )

    def service_ensure_project_contract(
        self,
        *,
        project_id: str | None,
        project_ref: str | None,
        workspace_id: str | None,
        auth_token: str | None,
        expected_event_storming_enabled: bool | None,
        command_id: str | None,
        ensure_project_contract_core: Any,
    ) -> dict | None:
        if not callable(ensure_project_contract_core):
            return None
        return ensure_project_contract_core(
            project_id=project_id,
            project_ref=project_ref,
            workspace_id=workspace_id,
            auth_token=auth_token,
            expected_event_storming_enabled=expected_event_storming_enabled,
            command_id=command_id,
        )

    def api_maybe_dispatch_execution_kickoff(
        self,
        *,
        db: Any,
        user: Any,
        workspace_id: str,
        project_id: str | None,
        intent_flags: dict[str, bool] | None,
        allow_mutations: bool,
        command_id: str | None,
        **context: Any,
    ) -> dict[str, object] | None:
        return maybe_dispatch_team_mode_execution_kickoff(
            db=db,
            user=user,
            workspace_id=workspace_id,
            project_id=project_id,
            intent_flags=intent_flags,
            allow_mutations=allow_mutations,
            command_id=command_id,
            promote_plugin_policy_to_execution_mode_if_needed=context.get(
                "promote_plugin_policy_to_execution_mode_if_needed"
            )
            or context.get("promote_plugin_policy_to_execution_mode_if_needed"),
            build_team_lead_kickoff_instruction=context.get("build_team_lead_kickoff_instruction"),
            command_id_with_suffix=context.get("command_id_with_suffix"),
        )
