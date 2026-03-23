# Backend CQRS and Event Sourcing Inventory

## Scope
This document inventories the backend in `app/` (feature modules under `app/features/*` plus shared eventing infrastructure in `app/shared/*`).

It focuses on:
- Aggregate roots
- Commands and command handlers
- Domain events
- Projection/read-model implementation
- Gaps versus the intended CQRS + Event Sourcing style

Note: `license_control_plane/` is a separate service and is not included in this inventory.

## Current CQRS + ES Baseline
The current baseline pattern is:
1. API layer calls application service (`features/*/application.py`).
2. Application service executes commands via `shared.commanding.execute_command(...)` for idempotency by `command_id`.
3. Handler (`features/*/command_handlers.py`) loads aggregate via `AggregateEventRepository.load_with_class(...)`, applies domain method(s), and persists events via `AggregateEventRepository.persist(...)`.
4. `shared.eventing.append_event(...)` stores events and immediately projects read models (`shared.eventing_rebuild.project_event(...)`).

Core infrastructure:
- `app/shared/aggregates.py`
- `app/shared/commanding.py`
- `app/shared/eventing.py`
- `app/shared/eventing_rebuild.py`
- `app/shared/eventing_projections.py`

## Aggregate Inventory

### 1) `Task` Aggregate
- Domain: `app/features/tasks/domain.py`
- Command entry points: `app/features/tasks/application.py`
- Handler implementation: `app/features/tasks/command_handlers.py`
- Commands:
  - `Task.Create`
  - `Task.Patch`
  - `Task.Complete`
  - `Task.ReviewDecision`
  - `Task.Reopen`
  - `Task.Archive`
  - `Task.Restore`
  - `Task.Bulk.*` (fan-out per task)
  - `Task.Reorder`
  - `Task.CommentAdd`
  - `Task.CommentDelete`
  - `Task.ToggleWatch`
  - `Task.Automation.RequestRun`
  - `Task.Automation.RequestInternal` (runner/system-facing lifecycle queueing)
  - `Task.AutomationStream` (special API path, progress-oriented direct event append kept intentionally)
- Events:
  - `TaskCreated`, `TaskUpdated`, `TaskReordered`, `TaskCompleted`, `TaskReopened`
  - `TaskArchived`, `TaskRestored`, `TaskDeleted`, `TaskMovedToInbox`
  - `TaskCommentAdded`, `TaskCommentDeleted`, `TaskWatchToggled`
  - `TaskAutomationRequested`, `TaskAutomationStarted`, `TaskAutomationCompleted`, `TaskAutomationFailed`
  - `TaskScheduleConfigured`, `TaskScheduleQueued`, `TaskScheduleStarted`, `TaskScheduleCompleted`, `TaskScheduleFailed`, `TaskScheduleDisabled`
- Handler style:
  - Mostly aggregate-first command handlers with event persistence through `AggregateEventRepository`.
  - High-throughput progress updates still append directly where needed, while requested/started/failed/completed lifecycle paths are now available through handlers.

### 2) `Project` Aggregate
- Domain: `app/features/projects/domain.py`
- Command entry points: `app/features/projects/application.py`
- Handler implementation: `app/features/projects/command_handlers.py`
- Commands:
  - `Project.Create`
  - `Project.Delete`
  - `Project.Patch`
  - `Project.MemberAdd`
  - `Project.MemberRemove`
- Events:
  - `ProjectCreated`, `ProjectDeleted`, `ProjectUpdated`, `ProjectMemberUpserted`, `ProjectMemberRemoved`
- Handler style:
  - Aggregate-first command handlers.
  - `DeleteProjectHandler` cascades through multiple aggregates (tasks, notes, rules, specs) by emitting delete events for each.

### 3) `Note` Aggregate
- Domain: `app/features/notes/domain.py`
- Command entry points: `app/features/notes/application.py`
- Handler implementation: `app/features/notes/command_handlers.py`
- Commands:
  - `Note.Create`, `Note.Patch`, `Note.Archive`, `Note.Restore`, `Note.Pin`, `Note.Unpin`, `Note.Delete`
- Events:
  - `NoteCreated`, `NoteUpdated`, `NoteArchived`, `NoteRestored`, `NotePinned`, `NoteUnpinned`, `NoteDeleted`
- Handler style:
  - Aggregate-first command handlers.

### 4) `TaskGroup` Aggregate
- Domain: `app/features/task_groups/domain.py`
- Command entry points: `app/features/task_groups/application.py`
- Handler implementation: `app/features/task_groups/command_handlers.py`
- Commands:
  - `TaskGroup.Create`, `TaskGroup.Patch`, `TaskGroup.Delete`, `TaskGroup.Reorder`
- Events:
  - `TaskGroupCreated`, `TaskGroupUpdated`, `TaskGroupReordered`, `TaskGroupDeleted`
- Handler style:
  - Aggregate-first command handlers, reorder implemented as fan-out command loop.

### 5) `NoteGroup` Aggregate
- Domain: `app/features/note_groups/domain.py`
- Command entry points: `app/features/note_groups/application.py`
- Handler implementation: `app/features/note_groups/command_handlers.py`
- Commands:
  - `NoteGroup.Create`, `NoteGroup.Patch`, `NoteGroup.Delete`, `NoteGroup.Reorder`
- Events:
  - `NoteGroupCreated`, `NoteGroupUpdated`, `NoteGroupReordered`, `NoteGroupDeleted`
- Handler style:
  - Aggregate-first command handlers, reorder implemented as fan-out command loop.

### 6) `ProjectRule` Aggregate
- Domain: `app/features/rules/domain.py`
- Command entry points: `app/features/rules/application.py`
- Handler implementation: `app/features/rules/command_handlers.py`
- Commands:
  - `ProjectRule.Create`, `ProjectRule.Patch`, `ProjectRule.Delete`
- Events:
  - `ProjectRuleCreated`, `ProjectRuleUpdated`, `ProjectRuleDeleted`
- Handler style:
  - Aggregate-first command handlers.

### 7) `Specification` Aggregate
- Domain: `app/features/specifications/domain.py`
- Command entry points: `app/features/specifications/application.py`
- Handler implementation: `app/features/specifications/command_handlers.py`
- Commands:
  - `Specification.Create`, `Specification.Patch`, `Specification.Archive`, `Specification.Restore`, `Specification.Delete`
  - Orchestration methods in app service that delegate to `TaskApplicationService` and `NoteApplicationService`.
- Events:
  - `SpecificationCreated`, `SpecificationUpdated`, `SpecificationArchived`, `SpecificationRestored`, `SpecificationDeleted`
- Handler style:
  - Aggregate-first command handlers.
  - Cross-aggregate operations are delegated at application service layer.

### 8) `ChatSession` Aggregate
- Domain: `app/features/chat/domain.py`
- Command entry points: `app/features/chat/application.py`
- Handler implementation: `app/features/chat/command_handlers.py`
- Commands:
  - `ChatSession.AppendUserMessage`
  - `ChatSession.AppendAssistantMessage`
  - `ChatSession.UpdateContext`
  - `ChatSession.Archive`
  - `ChatSession.LinkMessageResource`
- Events:
  - `ChatSessionStarted`, `ChatSessionRenamed`, `ChatSessionArchived`, `ChatSessionContextUpdated`
  - `ChatSessionUserMessageAppended`, `ChatSessionAssistantMessageAppended`, `ChatSessionAssistantMessageUpdated`
  - `ChatSessionMessageDeleted`, `ChatSessionAttachmentLinked`, `ChatSessionMessageResourceLinked`
- Handler style:
  - Aggregate-first command handlers with explicit load-or-create logic for session stream.

### 9) `Notification` Aggregate
- Domain: `app/features/notifications/domain.py`
- Command entry points: `app/features/notifications/application.py`
- Handler implementation: `app/features/notifications/command_handlers.py`
- Commands:
  - `Notification.MarkRead`, `Notification.MarkUnread`, `Notification.MarkAllRead`
- Events:
  - `NotificationCreated`, `NotificationMarkedRead`, `NotificationMarkedUnread`
- Handler style:
  - Aggregate-first command handlers.
  - Creation is generally event-driven from other flows, not from notification command handlers.

### 10) `User` Aggregate
- Domain: `app/features/users/domain.py`
- Command entry points: `app/features/users/application.py`
- Handler implementation: `app/features/users/command_handlers.py`
- Commands:
  - `User.PreferencesPatch`
  - `User.PasswordChange`
  - `User.WorkspaceCreate`
  - `User.WorkspaceResetPassword`
  - `User.WorkspaceRoleSet`
  - `User.WorkspaceDeactivate`
- Events:
  - `UserCreated`, `UserPreferencesUpdated`, `UserPasswordChanged`, `UserPasswordReset`, `UserWorkspaceRoleSet`, `UserDeactivated`
- Handler style:
  - Aggregate-first command handlers with admin/member policy checks.

### 11) `SavedView` Aggregate
- Domain: `app/features/views/domain.py`
- Command entry points: `app/features/views/application.py`
- Handler implementation: `app/features/views/command_handlers.py`
- Commands:
  - `SavedView.Create`
- Events:
  - `SavedViewCreated`
- Handler style:
  - Aggregate-first command handler for create only.

## Projection Coverage
`project_event(...)` in `app/shared/eventing_rebuild.py` projects event streams into SQL read models for:
- Task, Project, Note, TaskGroup, NoteGroup, ProjectRule, Specification, ChatSession
- Notification, SavedView, User
- ActivityLog side effects

`rebuild_state(...)` currently has aggregate-specific state rebuild branches for:
- Task, Project, Note, TaskGroup, NoteGroup, ProjectRule, Specification, ChatSession
- Notification, SavedView, User

## Handler Implementation Patterns

### Pattern A: Full CQRS + ES command path
Used by most business aggregates.
- API -> Application service -> `execute_command` idempotency -> command handler -> aggregate method -> `repo.persist` -> projection.

### Pattern B: ES append outside aggregate handler
Used where streaming/async progress is required and strict aggregate command overhead is intentionally avoided.
- Direct `append_event(...)` in API/runtime code, especially task automation streams and agent runner internals.
- Example hotspots:
  - `app/features/tasks/api.py`
  - `app/features/agents/service.py`

### Pattern C: Read model / service-oriented modules without aggregate roots
Modules centered on orchestration, integrations, retrieval, or admin flows, not aggregate command models.
- `features/project_skills`
- `features/project_starters`
- `features/licensing` (constants + read/sync style)
- `features/support`
- `features/attachments`
- `features/doctor`
- `features/debug`

## Gaps Against Target Style
1. Rebuild support mismatch.
- Resolved: `rebuild_state(...)` now supports `User`, `Notification`, and `SavedView`.

2. Parallel command path for Task automation stream.
- `Task.AutomationStream` still appends high-frequency progress updates directly for throughput.
- Lifecycle state transitions now have dedicated handlers and are increasingly routed through command handlers.

3. Event emission spread across runtime modules.
- `agents/service.py` and selected progress/runtime paths still emit direct Task events.
- `agents/runner.py` now routes automation request/started/failure/completion lifecycle transitions through handlers.
- `AutomationStarted` claim keeps optimistic concurrency semantics through handler support for `expected_version`.

4. Mixed consistency model.
- Core CRUD flows are aggregate-driven.
- Operational/runtime flows are event-driven but not always aggregate-centric.

## Recommended Refactor Direction
1. Continue shrinking direct runtime event emission by migrating remaining runner/service mutation paths to dedicated handlers.
2. Keep `AutomationStarted` claim semantics concurrency-safe (`expected_version`) through the aggregate-backed handler path.
3. Keep `execute_command` idempotency at all public mutation entry points.
4. Preserve high-throughput append-only progress paths only where strictly needed, but route state transitions through domain command facades.

## Mermaid Event Storming Diagram
```mermaid
flowchart LR
  U[User] -->|HTTP/API| GW[FastAPI Routers]
  AG[Agent Runtime] -->|Tool/API calls| GW

  GW --> APP[Application Services]
  APP --> CMD[Command Handlers]
  CMD --> AGG[Aggregates]
  AGG --> EVT[(Stored Events)]
  EVT --> PROJ[Projectors]
  PROJ --> RM[(SQL Read Models)]
  RM --> QRY[Read Models / Query APIs]
  QRY --> U
  QRY --> AG

  subgraph Bounded Contexts
    TSK[Task]
    PRJ[Project]
    NOTE[Note]
    TG[TaskGroup]
    NG[NoteGroup]
    RULE[ProjectRule]
    SPEC[Specification]
    CHAT[ChatSession]
    NOTIF[Notification]
    USR[User]
    VIEW[SavedView]
  end

  CMD --> TSK
  CMD --> PRJ
  CMD --> NOTE
  CMD --> TG
  CMD --> NG
  CMD --> RULE
  CMD --> SPEC
  CMD --> CHAT
  CMD --> NOTIF
  CMD --> USR
  CMD --> VIEW

  subgraph Runtime Event Producers
    TAS[Task automation stream endpoint]
    RUN[agents/runner.py]
    SVC[agents/service.py]
  end

  TAS -->|append_event| EVT
  RUN -->|append_event| EVT
  SVC -->|append_event| EVT

  EVT --> ACT[ActivityLog + Notifications + Automation Triggers]
  ACT --> RM
```

## Quick Mapping Summary
- Strong CQRS/ES coverage: `tasks`, `projects`, `notes`, `task_groups`, `note_groups`, `rules`, `specifications`, `chat`, `users`, `notifications`, `views`.
- Hybrid areas needing cleanup: runtime/task automation paths that emit events directly.
- Service-style (non-aggregate) contexts: integrations, starters, skills, support, and utility/admin modules.
