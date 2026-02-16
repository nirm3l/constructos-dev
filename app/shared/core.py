from __future__ import annotations

from .bootstrap import bootstrap_data, bootstrap_payload, startup_bootstrap
from .contracts import (
    AgentChatRun,
    BulkAction,
    CommentCreate,
    ConcurrencyConflictError,
    EventEnvelope,
    NoteCreate,
    NoteDTO,
    NotePatch,
    NotificationDTO,
    ProjectCreate,
    ProjectMemberUpsert,
    ProjectPatch,
    ProjectRuleCreate,
    ProjectRulePatch,
    SpecificationCreate,
    SpecificationPatch,
    ReorderPayload,
    SavedViewCreate,
    TaskAutomationRun,
    TaskCommandState,
    TaskCreate,
    TaskDTO,
    TaskPatch,
    ProjectRuleDTO,
    ProjectRuleCommandState,
    SpecificationDTO,
    SpecificationCommandState,
    UserPreferencesPatch,
)
from .deps import ensure_role, get_command_id, get_current_user, get_db, run_command_with_retry
from .eventing import (
    allocate_id,
    append_event,
    current_version,
    emit_system_notifications,
    get_kurrent_client,
    load_events_after,
    project_kurrent_events_once,
    rebuild_state,
    start_projection_worker,
    stop_projection_worker,
)
from .models import (
    ActivityLog,
    AggregateSnapshot,
    Base,
    CommandExecution,
    Note,
    Notification,
    Project,
    ProjectMember,
    ProjectionCheckpoint,
    ProjectTagIndex,
    ProjectRule,
    Specification,
    SavedView,
    SessionLocal,
    StoredEvent,
    Task,
    TaskComment,
    TaskWatcher,
    User,
    Workspace,
    WorkspaceMember,
    engine,
)
from .serializers import (
    export_tasks_response,
    get_user_zoneinfo,
    load_project_view,
    load_project_rule_command_state,
    load_project_rule_view,
    load_specification_command_state,
    load_specification_view,
    load_saved_view,
    load_note_command_state,
    load_note_view,
    load_task_command_state,
    load_task_view,
    normalize_datetime_to_utc,
    serialize_note,
    serialize_notification,
    serialize_project_rule,
    serialize_specification,
    serialize_task,
    to_iso_utc,
)
from .settings import DEFAULT_STATUSES, EVENTSTORE_URI
from .observability import snapshot as metrics_snapshot
from features.notifications.domain import (
    EVENT_CREATED as NOTIFICATION_EVENT_CREATED,
    EVENT_MARKED_READ as NOTIFICATION_EVENT_MARKED_READ,
)
from features.projects.domain import (
    EVENT_CREATED as PROJECT_EVENT_CREATED,
    EVENT_DELETED as PROJECT_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_EVENT_UPDATED,
)
from features.rules.domain import (
    EVENT_CREATED as PROJECT_RULE_EVENT_CREATED,
    EVENT_DELETED as PROJECT_RULE_EVENT_DELETED,
    EVENT_UPDATED as PROJECT_RULE_EVENT_UPDATED,
)
from features.specifications.domain import (
    EVENT_ARCHIVED as SPECIFICATION_EVENT_ARCHIVED,
    EVENT_CREATED as SPECIFICATION_EVENT_CREATED,
    EVENT_DELETED as SPECIFICATION_EVENT_DELETED,
    EVENT_RESTORED as SPECIFICATION_EVENT_RESTORED,
    EVENT_UPDATED as SPECIFICATION_EVENT_UPDATED,
    MUTATION_EVENTS as SPECIFICATION_MUTATION_EVENTS,
)
from features.tasks.domain import (
    EVENT_ARCHIVED as TASK_EVENT_ARCHIVED,
    EVENT_COMMENT_ADDED as TASK_EVENT_COMMENT_ADDED,
    EVENT_COMMENT_DELETED as TASK_EVENT_COMMENT_DELETED,
    EVENT_COMPLETED as TASK_EVENT_COMPLETED,
    EVENT_CREATED as TASK_EVENT_CREATED,
    EVENT_DELETED as TASK_EVENT_DELETED,
    EVENT_MOVED_TO_INBOX as TASK_EVENT_MOVED_TO_INBOX,
    EVENT_REOPENED as TASK_EVENT_REOPENED,
    EVENT_REORDERED as TASK_EVENT_REORDERED,
    EVENT_RESTORED as TASK_EVENT_RESTORED,
    EVENT_UPDATED as TASK_EVENT_UPDATED,
    EVENT_WATCH_TOGGLED as TASK_EVENT_WATCH_TOGGLED,
    MUTATION_EVENTS as TASK_MUTATION_EVENTS,
)
from features.users.domain import EVENT_PREFERENCES_UPDATED as USER_EVENT_PREFERENCES_UPDATED
from features.views.domain import EVENT_CREATED as SAVED_VIEW_EVENT_CREATED
