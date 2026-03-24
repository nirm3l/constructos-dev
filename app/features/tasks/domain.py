from __future__ import annotations

from typing import Any

from eventsourcing.domain import Aggregate, event


class TaskAggregate(Aggregate):
    aggregate_type = "Task"

    @event("Created")
    def __init__(
        self,
        id: Any,
        workspace_id: str,
        project_id: str | None,
        task_group_id: str | None,
        specification_id: str | None,
        title: str,
        description: str,
        status: str,
        priority: str,
        due_date: str | None,
        assignee_id: str | None,
        assigned_agent_code: str | None,
        labels: list[str],
        subtasks: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        external_refs: list[dict[str, Any]],
        attachment_refs: list[dict[str, Any]],
        recurring_rule: str | None,
        order_index: int,
        instruction: str | None = None,
        execution_triggers: list[dict[str, Any]] | None = None,
        task_relationships: list[dict[str, Any]] | None = None,
        delivery_mode: str | None = None,
        task_type: str = "manual",
        scheduled_instruction: str | None = None,
        scheduled_at_utc: str | None = None,
        schedule_timezone: str | None = None,
        schedule_state: str = "idle",
    ) -> None:
        _ = id
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.task_group_id = task_group_id
        self.specification_id = specification_id
        self.title = title
        self.description = description
        self.status = status
        self.priority = priority
        self.due_date = due_date
        self.assignee_id = assignee_id
        self.assigned_agent_code = assigned_agent_code
        self.labels = labels
        self.subtasks = subtasks
        self.attachments = attachments
        self.external_refs = external_refs
        self.attachment_refs = attachment_refs
        self.instruction = instruction
        self.execution_triggers = execution_triggers or []
        self.task_relationships = task_relationships or []
        self.delivery_mode = delivery_mode
        self.recurring_rule = recurring_rule
        self.task_type = task_type
        self.scheduled_instruction = scheduled_instruction
        self.scheduled_at_utc = scheduled_at_utc
        self.schedule_timezone = schedule_timezone
        self.schedule_state = schedule_state
        self.last_schedule_run_at = None
        self.last_schedule_error = None
        self.order_index = order_index
        self.archived = False
        self.is_deleted = False
        self.completed_at = None
        self.automation_state = None
        self.automation_requested_at = None
        self.automation_started_at = None
        self.automation_completed_at = None
        self.automation_failed_at = None
        self.last_automation_error = None
        self.last_requested_instruction = None
        self.last_requested_source = None
        self.last_requested_chat_session_id = None
        self.last_requested_trigger_task_id = None
        self.last_requested_from_status = None
        self.last_requested_to_status = None
        self.last_requested_triggered_at = None
        self.last_requested_execution_intent = None
        self.last_requested_execution_kickoff_intent = None
        self.last_requested_project_creation_intent = None
        self.last_requested_workflow_scope = None
        self.last_requested_execution_mode = None
        self.last_requested_task_completion_requested = None
        self.last_requested_classifier_reason = None

    @event("Updated")
    def update(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            setattr(self, key, value)

    @event("Reordered")
    def reorder(self, order_index: int, status: str | None) -> None:
        self.order_index = order_index
        if status:
            self.status = status

    @event("Completed")
    def complete(self, completed_at: str, status: str = "Completed") -> None:
        self.status = status
        self.completed_at = completed_at

    @event("Reopened")
    def reopen(self, status: str = "To Do") -> None:
        self.status = status
        self.completed_at = None

    @event("Archived")
    def archive(self) -> None:
        self.archived = True

    @event("Restored")
    def restore(self) -> None:
        self.archived = False

    @event("Deleted")
    def delete(self) -> None:
        self.is_deleted = True

    @event("MovedToInbox")
    def move_to_inbox(self, from_project_id: str | None = None) -> None:
        _ = from_project_id
        self.project_id = None

    @event("CommentAdded")
    def add_comment(self, task_id: str, user_id: str, body: str) -> None:
        _ = (task_id, user_id, body)

    @event("CommentDeleted")
    def delete_comment(self, task_id: str, comment_id: int) -> None:
        _ = (task_id, comment_id)

    @event("WatchToggled")
    def toggle_watch(self, task_id: str, user_id: str, watched: bool | None = None) -> None:
        _ = (task_id, user_id, watched)

    @event("AutomationRequested")
    def request_automation(
        self,
        requested_at: str,
        instruction: str | None = None,
        source: str | None = None,
        source_task_id: str | None = None,
        chat_session_id: str | None = None,
        reason: str | None = None,
        trigger_link: str | None = None,
        correlation_id: str | None = None,
        trigger_task_id: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        triggered_at: str | None = None,
        lead_handoff_token: str | None = None,
        lead_handoff_at: str | None = None,
        lead_handoff_refs: list[dict[str, Any]] | None = None,
        lead_handoff_deploy_execution: dict[str, Any] | None = None,
        execution_intent: bool | None = None,
        execution_kickoff_intent: bool | None = None,
        project_creation_intent: bool | None = None,
        workflow_scope: str | None = None,
        execution_mode: str | None = None,
        task_completion_requested: bool | None = None,
        classifier_reason: str | None = None,
    ) -> None:
        self.automation_state = "queued"
        self.automation_requested_at = requested_at
        self.last_requested_instruction = instruction
        self.last_requested_source = source
        self.last_requested_source_task_id = source_task_id
        self.last_requested_chat_session_id = chat_session_id
        self.last_requested_reason = reason
        self.last_requested_trigger_link = trigger_link
        self.last_requested_correlation_id = correlation_id
        self.last_requested_trigger_task_id = trigger_task_id
        self.last_requested_from_status = from_status
        self.last_requested_to_status = to_status
        self.last_requested_triggered_at = triggered_at
        if lead_handoff_token is not None:
            self.last_lead_handoff_token = lead_handoff_token
        if lead_handoff_at is not None:
            self.last_lead_handoff_at = lead_handoff_at
        if lead_handoff_refs is not None:
            self.last_lead_handoff_refs_json = lead_handoff_refs
        if lead_handoff_deploy_execution is not None:
            self.last_lead_handoff_deploy_execution = lead_handoff_deploy_execution
        self.last_requested_execution_intent = execution_intent
        self.last_requested_execution_kickoff_intent = execution_kickoff_intent
        self.last_requested_project_creation_intent = project_creation_intent
        self.last_requested_workflow_scope = workflow_scope
        self.last_requested_execution_mode = execution_mode
        self.last_requested_task_completion_requested = task_completion_requested
        self.last_requested_classifier_reason = classifier_reason

    @event("AutomationStarted")
    def mark_automation_started(self, started_at: str) -> None:
        self.automation_state = "running"
        self.automation_started_at = started_at

    @event("AutomationCompleted")
    def mark_automation_completed(
        self,
        completed_at: str,
        summary: str | None = None,
        comment: str | None = None,
        usage: dict[str, Any] | None = None,
        prompt_mode: str | None = None,
        prompt_segment_chars: dict[str, Any] | None = None,
        codex_session_id: str | None = None,
        resume_attempted: bool | None = None,
        resume_succeeded: bool | None = None,
        resume_fallback_used: bool | None = None,
    ) -> None:
        self.automation_state = "completed"
        self.automation_completed_at = completed_at
        self.last_automation_error = None
        if summary is not None:
            self.last_agent_comment = summary
        if comment is not None:
            self.last_agent_comment = comment
        if usage is not None:
            self.last_agent_usage = usage
        if prompt_mode is not None:
            self.last_agent_prompt_mode = prompt_mode
        if prompt_segment_chars is not None:
            self.last_agent_prompt_segment_chars = prompt_segment_chars
        if codex_session_id is not None:
            self.last_agent_codex_session_id = codex_session_id
        if resume_attempted is not None:
            self.last_agent_codex_resume_attempted = bool(resume_attempted)
        if resume_succeeded is not None:
            self.last_agent_codex_resume_succeeded = bool(resume_succeeded)
        if resume_fallback_used is not None:
            self.last_agent_codex_resume_fallback_used = bool(resume_fallback_used)

    @event("AutomationFailed")
    def mark_automation_failed(self, failed_at: str, error: str, summary: str | None = None) -> None:
        self.automation_state = "failed"
        self.automation_failed_at = failed_at
        self.last_automation_error = error
        if summary is not None:
            self.last_agent_comment = summary

    @event("ScheduleConfigured")
    def configure_schedule(
        self,
        scheduled_instruction: str | None,
        scheduled_at_utc: str | None,
        schedule_timezone: str | None,
        schedule_state: str = "idle",
        last_schedule_error: str | None = None,
    ) -> None:
        self.scheduled_instruction = scheduled_instruction
        self.scheduled_at_utc = scheduled_at_utc
        self.schedule_timezone = schedule_timezone
        self.schedule_state = schedule_state
        self.last_schedule_error = last_schedule_error

    @event("ScheduleQueued")
    def mark_schedule_queued(self, schedule_state: str = "queued", queued_at: str | None = None) -> None:
        _ = queued_at
        self.schedule_state = schedule_state

    @event("ScheduleStarted")
    def mark_schedule_started(self, schedule_state: str = "running", started_at: str | None = None) -> None:
        self.schedule_state = schedule_state
        if started_at is not None:
            self.last_schedule_run_at = started_at

    @event("ScheduleCompleted")
    def mark_schedule_completed(
        self,
        schedule_state: str = "idle",
        completed_at: str | None = None,
        last_schedule_run_at: str | None = None,
    ) -> None:
        self.schedule_state = schedule_state
        self.last_schedule_run_at = completed_at if completed_at is not None else last_schedule_run_at
        self.last_schedule_error = None

    @event("ScheduleFailed")
    def mark_schedule_failed(
        self,
        schedule_state: str = "error",
        error: str | None = None,
        failed_at: str | None = None,
    ) -> None:
        self.schedule_state = schedule_state
        self.last_schedule_error = error
        if failed_at is not None:
            self.last_schedule_run_at = failed_at

    @event("ScheduleDisabled")
    def disable_schedule(self, schedule_state: str = "idle") -> None:
        self.task_type = "manual"
        self.schedule_state = schedule_state
        self.scheduled_instruction = None
        self.scheduled_at_utc = None
        self.schedule_timezone = None
        self.last_schedule_error = None


EVENT_CREATED = "TaskCreated"
EVENT_UPDATED = "TaskUpdated"
EVENT_REORDERED = "TaskReordered"
EVENT_COMPLETED = "TaskCompleted"
EVENT_REOPENED = "TaskReopened"
EVENT_ARCHIVED = "TaskArchived"
EVENT_RESTORED = "TaskRestored"
EVENT_DELETED = "TaskDeleted"
EVENT_MOVED_TO_INBOX = "TaskMovedToInbox"
EVENT_COMMENT_ADDED = "TaskCommentAdded"
EVENT_COMMENT_DELETED = "TaskCommentDeleted"
EVENT_WATCH_TOGGLED = "TaskWatchToggled"
EVENT_AUTOMATION_REQUESTED = "TaskAutomationRequested"
EVENT_AUTOMATION_STARTED = "TaskAutomationStarted"
EVENT_AUTOMATION_COMPLETED = "TaskAutomationCompleted"
EVENT_AUTOMATION_FAILED = "TaskAutomationFailed"
EVENT_SCHEDULE_CONFIGURED = "TaskScheduleConfigured"
EVENT_SCHEDULE_QUEUED = "TaskScheduleQueued"
EVENT_SCHEDULE_STARTED = "TaskScheduleStarted"
EVENT_SCHEDULE_COMPLETED = "TaskScheduleCompleted"
EVENT_SCHEDULE_FAILED = "TaskScheduleFailed"
EVENT_SCHEDULE_DISABLED = "TaskScheduleDisabled"

MUTATION_EVENTS = {
    EVENT_UPDATED,
    EVENT_REORDERED,
    EVENT_COMPLETED,
    EVENT_REOPENED,
    EVENT_ARCHIVED,
    EVENT_RESTORED,
    EVENT_DELETED,
    EVENT_MOVED_TO_INBOX,
    EVENT_SCHEDULE_CONFIGURED,
    EVENT_SCHEDULE_QUEUED,
    EVENT_SCHEDULE_STARTED,
    EVENT_SCHEDULE_COMPLETED,
    EVENT_SCHEDULE_FAILED,
    EVENT_SCHEDULE_DISABLED,
}
