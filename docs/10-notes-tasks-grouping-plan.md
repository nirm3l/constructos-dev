# Plan: Logical Grouping for Tasks and Notes (Separated)

Date: 2026-02-20

## 1) Goal

Add persistent, logical grouping for tasks and notes to improve overview and organization, with strict separation:

- Task grouping is managed independently from note grouping.
- Note grouping is managed independently from task grouping.

## 2) Scope and Non-Goals

In scope:

- New group entities for tasks and notes.
- Assigning each task/note to one optional group.
- CRUD + reorder for groups.
- Filtering and grouped rendering in UI.
- MCP coverage for group management.

Out of scope (phase 1):

- Shared groups across tasks and notes.
- Nested groups (group inside group).
- Complex permission model beyond existing project/workspace role checks.

## 3) Current-State Summary

Current model has no first-class grouping entity for tasks or notes:

- Tasks: grouped visually by status in board mode, no logical group domain field.
- Notes: sorted by `pinned` + `updated_at`, no logical group domain field.

This means grouping is not durable, not queryable, and not managed as a domain object.

## 4) Target Domain Design

### 4.1 New Entities

Introduce two separate aggregate roots and tables:

1. `TaskGroup`
- `id`, `workspace_id`, `project_id`
- `name` (unique within project for task groups)
- `description` (optional)
- `color` (optional UI hint)
- `order_index`
- `is_deleted`

2. `NoteGroup`
- `id`, `workspace_id`, `project_id`
- `name` (unique within project for note groups)
- `description` (optional)
- `color` (optional UI hint)
- `order_index`
- `is_deleted`

### 4.2 Entity Extensions

Add optional foreign keys:

- `tasks.task_group_id -> task_groups.id` (nullable)
- `notes.note_group_id -> note_groups.id` (nullable)

`NULL` means “Ungrouped”.

### 4.3 Domain Rules

- A task can reference only a `TaskGroup` in the same workspace/project.
- A note can reference only a `NoteGroup` in the same workspace/project.
- Task cannot reference `NoteGroup`, and note cannot reference `TaskGroup`.
- Deleting a group does not delete tasks/notes; members become ungrouped (`group_id = null`).
- Group rename/reorder must be idempotent under command id.

## 5) API and Contract Changes

### 5.1 New REST Endpoints

Task groups:

- `GET /api/task-groups?workspace_id=&project_id=`
- `POST /api/task-groups`
- `PATCH /api/task-groups/{group_id}`
- `POST /api/task-groups/{group_id}/delete`
- `POST /api/task-groups/reorder`

Note groups:

- `GET /api/note-groups?workspace_id=&project_id=`
- `POST /api/note-groups`
- `PATCH /api/note-groups/{group_id}`
- `POST /api/note-groups/{group_id}/delete`
- `POST /api/note-groups/reorder`

### 5.2 Existing Endpoint Extensions

- `TaskCreate` / `TaskPatch`: add `task_group_id`.
- `NoteCreate` / `NotePatch`: add `note_group_id`.
- `GET /api/tasks`: add optional filter `task_group_id`.
- `GET /api/notes`: add optional filter `note_group_id`.
- DTOs/serializers return group ids for both entities.

### 5.3 MCP Tool Extensions

Add dedicated tools:

- `list_task_groups`, `create_task_group`, `update_task_group`, `delete_task_group`, `reorder_task_groups`
- `list_note_groups`, `create_note_group`, `update_note_group`, `delete_note_group`, `reorder_note_groups`

Extend existing tools:

- `create_task` / `update_task` support `task_group_id`
- `create_note` / `update_note` support `note_group_id`
- `list_tasks` accepts `task_group_id`
- `list_notes` accepts `note_group_id`

## 6) Event-Sourcing and Projection Plan

### 6.1 New Event Families

Task group events:

- `TaskGroupCreated`, `TaskGroupUpdated`, `TaskGroupReordered`, `TaskGroupDeleted`

Note group events:

- `NoteGroupCreated`, `NoteGroupUpdated`, `NoteGroupReordered`, `NoteGroupDeleted`

### 6.2 Existing Event Payload Extensions

- `TaskCreated` / `TaskUpdated` include `task_group_id` when set/changed.
- `NoteCreated` / `NoteUpdated` include `note_group_id` when set/changed.

### 6.3 Projection/Rebuild Updates

Update:

- `app/shared/eventing_rebuild.py` (`apply_*_event`, `project_event`)
- `app/shared/serializers.py`
- `app/shared/models.py`
- `app/shared/contracts.py`

Add group projection handling and idempotent delete-to-ungroup behavior.

## 7) Backend Implementation Breakdown

1. Data layer:
- Add `TaskGroup` and `NoteGroup` models.
- Add `task_group_id` and `note_group_id` columns + indexes.
- Add bootstrap schema upgraders in `app/shared/bootstrap.py`.

2. Feature slices:
- New slices: `app/features/task_groups/*`, `app/features/note_groups/*`.
- Add routers in `app/main.py`.

3. Existing slices:
- Update tasks and notes command handlers to validate group ownership/scope.
- Update read models for group filters and optional grouped payload support.

4. Cross-cutting:
- Update `shared/core.py` exports.
- Update API map docs and MCP server/service wiring.

## 8) Frontend Plan

1. Types + API client:
- Extend `Task`, `Note`, payloads, and query params with group ids.
- Add client calls for task-group and note-group endpoints.

2. Task UX:
- Add group selector in task editor/drawer.
- Add list mode grouping sections by task group (collapse/expand).
- Keep board mode status-based in phase 1 (no forced redesign).

3. Note UX:
- Add group selector in note editor.
- Render notes grouped by note group (collapse/expand).

4. Group management UX:
- Add lightweight CRUD/reorder UI in each panel header.
- Keep task-group and note-group controls separated to match domain split.

## 9) Migration and Rollout Strategy

Because this app already uses runtime schema-upgrade helpers:

- Add non-breaking nullable columns first.
- Existing tasks/notes remain usable as ungrouped.
- Introduce groups with feature-complete API after schema is available.
- No destructive migration is needed.

Rollout order:

1. Backend schema + domain/events/projections.
2. REST + MCP interfaces.
3. Frontend assignment + grouped views.
4. Tests, docs, and operational validation.

## 10) Testing Plan

Backend tests:

- Group CRUD (task groups and note groups).
- Assignment validation (cross-project and wrong-group-type rejection).
- Group deletion unassigns members.
- List filtering by group id.
- Event rebuild parity for group fields.

Frontend tests/manual QA:

- Create/rename/delete/reorder groups.
- Assign/unassign in editors.
- Grouped rendering stability with archived/pinned/filter states.

MCP tests:

- New group tools return expected payloads.
- Existing task/note tools accept and persist group ids.

## 11) Acceptance Criteria

- Users can create, edit, delete, and reorder task groups and note groups independently.
- Users can assign/unassign task group per task and note group per note.
- Task and note lists can be filtered by their respective group ids.
- UI shows grouped sections for tasks and notes without mixing domains.
- MCP tools support full group lifecycle and group assignment.
- Existing tasks/notes continue to work as ungrouped without regression.
