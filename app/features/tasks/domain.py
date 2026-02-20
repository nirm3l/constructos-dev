from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.aggregates import AggregateRoot


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


class TaskAggregate(AggregateRoot):
    aggregate_type = "Task"

    def apply(self, *, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == EVENT_CREATED:
            self.workspace_id = str(payload.get("workspace_id") or "")
            self.project_id = payload.get("project_id")
            self.specification_id = payload.get("specification_id")
            self.title = str(payload.get("title") or "")
            self.description = str(payload.get("description") or "")
            self.status = str(payload.get("status") or "")
            self.priority = str(payload.get("priority") or "Medium")
            self.due_date = payload.get("due_date")
            self.assignee_id = payload.get("assignee_id")
            self.labels = list(payload.get("labels") or [])
            self.subtasks = list(payload.get("subtasks") or [])
            self.attachments = list(payload.get("attachments") or [])
            self.external_refs = list(payload.get("external_refs") or [])
            self.attachment_refs = list(payload.get("attachment_refs") or [])
            self.recurring_rule = payload.get("recurring_rule")
            self.task_type = str(payload.get("task_type") or "manual")
            self.scheduled_instruction = payload.get("scheduled_instruction")
            self.scheduled_at_utc = payload.get("scheduled_at_utc")
            self.schedule_timezone = payload.get("schedule_timezone")
            self.schedule_state = str(payload.get("schedule_state") or "idle")
            self.last_schedule_run_at = payload.get("last_schedule_run_at")
            self.last_schedule_error = payload.get("last_schedule_error")
            self.order_index = int(payload.get("order_index") or 0)
            self.archived = bool(payload.get("archived", False))
            self.is_deleted = bool(payload.get("is_deleted", False))
            self.completed_at = payload.get("completed_at")
            self.automation_state = payload.get("automation_state")
            self.automation_requested_at = payload.get("requested_at")
            self.automation_started_at = payload.get("started_at")
            self.automation_completed_at = payload.get("completed_at")
            self.automation_failed_at = payload.get("failed_at")
            self.last_automation_error = payload.get("error")
            return

        if event_type == EVENT_UPDATED:
            for key, value in dict(payload).items():
                setattr(self, key, value)
            return

        if event_type == EVENT_REORDERED:
            self.order_index = int(payload.get("order_index") or 0)
            status = payload.get("status")
            if status:
                self.status = str(status)
            return

        if event_type == EVENT_COMPLETED:
            self.status = "Done"
            self.completed_at = payload.get("completed_at")
            return

        if event_type == EVENT_REOPENED:
            self.status = str(payload.get("status") or "To do")
            self.completed_at = None
            return

        if event_type == EVENT_ARCHIVED:
            self.archived = True
            return

        if event_type == EVENT_RESTORED:
            self.archived = False
            return

        if event_type == EVENT_DELETED:
            self.is_deleted = True
            return

        if event_type == EVENT_MOVED_TO_INBOX:
            self.project_id = None
            return

        if event_type in {EVENT_COMMENT_ADDED, EVENT_COMMENT_DELETED, EVENT_WATCH_TOGGLED}:
            return

        if event_type == EVENT_AUTOMATION_REQUESTED:
            self.automation_state = "queued"
            self.automation_requested_at = payload.get("requested_at")
            return

        if event_type == EVENT_AUTOMATION_STARTED:
            self.automation_state = "running"
            self.automation_started_at = payload.get("started_at")
            return

        if event_type == EVENT_AUTOMATION_COMPLETED:
            self.automation_state = "completed"
            self.automation_completed_at = payload.get("completed_at")
            self.last_automation_error = None
            return

        if event_type == EVENT_AUTOMATION_FAILED:
            self.automation_state = "failed"
            self.automation_failed_at = payload.get("failed_at")
            self.last_automation_error = payload.get("error")
            return

        if event_type == EVENT_SCHEDULE_CONFIGURED:
            self.scheduled_instruction = payload.get("scheduled_instruction")
            self.scheduled_at_utc = payload.get("scheduled_at_utc")
            self.schedule_timezone = payload.get("schedule_timezone")
            self.schedule_state = str(payload.get("schedule_state") or "idle")
            if "last_schedule_error" in payload:
                self.last_schedule_error = payload.get("last_schedule_error")
            return

        if event_type == EVENT_SCHEDULE_QUEUED:
            self.schedule_state = str(payload.get("schedule_state") or "queued")
            return

        if event_type == EVENT_SCHEDULE_STARTED:
            self.schedule_state = str(payload.get("schedule_state") or "running")
            return

        if event_type == EVENT_SCHEDULE_COMPLETED:
            self.schedule_state = str(payload.get("schedule_state") or "idle")
            self.last_schedule_run_at = payload.get("last_schedule_run_at")
            self.last_schedule_error = None
            return

        if event_type == EVENT_SCHEDULE_FAILED:
            self.schedule_state = str(payload.get("schedule_state") or "error")
            self.last_schedule_error = payload.get("error")
            return

        if event_type == EVENT_SCHEDULE_DISABLED:
            self.task_type = "manual"
            self.schedule_state = str(payload.get("schedule_state") or "idle")
            self.scheduled_instruction = None
            self.scheduled_at_utc = None
            self.schedule_timezone = None
            self.last_schedule_error = None
            return

        raise ValueError(f"Unknown event type: {event_type}")

