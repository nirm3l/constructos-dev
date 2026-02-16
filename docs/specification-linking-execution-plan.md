# Specification -> Tasks/Notes Linking Plan

## 1. Scope
This plan covers how to make `Specification` the central place for implementation work:
- create one task from spec
- create multiple tasks from spec
- link existing tasks to spec
- create note from spec
- link existing notes to spec
- unlink tasks/notes from spec

No data migrations are included (fresh reset flow is already expected).

## 2. Current State (already implemented)
- `Task` and `Note` already support `specification_id`.
- API already supports:
  - create/patch task with `specification_id`
  - create/patch note with `specification_id`
  - list tasks/notes filtered by `specification_id`
- Backend already validates specification scope for task/note linking.

## 3. Target UX

### 3.1 In Specification view
Each opened specification gets two new sections:
- `Implementation tasks`
- `Notes`

Each section has actions:
- `+ New`
- `Link existing`
- per-item `Unlink`

For tasks section only:
- `Create multiple` (textarea/list input, one task per line)

### 3.2 Expected behavior
- New task/note created from spec is auto-linked (`specification_id = current spec id`).
- Link existing action only shows items from the same project/workspace.
- Unlink keeps task/note alive, only clears `specification_id`.

## 4. API Strategy

## 4.1 Keep base model canonical
Continue using canonical endpoints:
- `POST /api/tasks`
- `PATCH /api/tasks/{id}`
- `POST /api/notes`
- `PATCH /api/notes/{id}`

All linking/unlinking logic writes through `specification_id`.

## 4.2 Add convenience endpoints for spec-driven UX
Add thin wrappers (optional but recommended for clean frontend):
- `POST /api/specifications/{id}/tasks`
- `POST /api/specifications/{id}/tasks/bulk`
- `POST /api/specifications/{id}/notes`
- `POST /api/specifications/{id}/tasks/{task_id}/link`
- `POST /api/specifications/{id}/notes/{note_id}/link`
- `POST /api/specifications/{id}/tasks/{task_id}/unlink`
- `POST /api/specifications/{id}/notes/{note_id}/unlink`

Internally these call existing task/note application services.

## 4.3 Validation rules
- same workspace and project required
- cannot link archived/deleted specification
- cannot change project while linked (already enforced for task patch)
- idempotent commands via `X-Command-Id`

## 4.4 MCP tool exposure plan
Current MCP coverage already available:
- `list_specifications`, `get_specification`, `create_specification`, `update_specification`, `archive_specification`, `restore_specification`, `delete_specification`
- task/note tools already accept/filter `specification_id` (`create_task`, `update_task`, `list_tasks`, `create_note`, `update_note`, `list_notes`)

New MCP tools to expose for spec-driven flow:
- `create_tasks_from_spec` (bulk task create bound to one spec)
- `link_task_to_spec`
- `unlink_task_from_spec`
- `link_note_to_spec`
- `unlink_note_from_spec`
- `list_spec_tasks` (wrapper around tasks filter)
- `list_spec_notes` (wrapper around notes filter)

Implementation note:
- keep these as thin wrappers over existing task/note/specification services to avoid duplicated business rules.
- mutation tools are available on the MCP server by default.

## 5. Frontend Plan

## 5.1 Data hooks
In `specifications` tab, fetch:
- tasks query with `specification_id`
- notes query with `specification_id`

Use dedicated query keys to avoid cache collisions.

## 5.2 SpecificationsPanel extensions
Add under opened spec accordion:
- task list (compact rows)
- note list (compact rows)
- quick actions:
  - create task
  - bulk create tasks
  - create note
  - link existing task
  - link existing note

Reuse existing UI patterns from notes/tasks drawers where possible.

## 5.3 Link existing modal
Simple searchable modal per entity:
- input search
- list from same project
- hide already linked items
- link on click

## 5.4 Bulk task creation UX
Input format:
- one line = one task title
- empty lines ignored
- optional prefix parser later (`[High]`, `@assignee`) as phase 2

On submit:
- create in sequence or bounded concurrency
- show per-item result summary (created/failed)

## 6. Backend Implementation Steps
1. Add convenience spec endpoints (wrappers).
2. Add service methods for bulk create and link/unlink wrappers.
3. Reuse existing validators for scope and archived checks.
4. Add tests for all wrapper endpoints and idempotency.
5. Expose dedicated MCP tools for spec linking/bulk flows.

## 7. Frontend Implementation Steps
1. Add API client methods for new spec wrapper endpoints.
2. Add queries for linked tasks/notes in spec tab.
3. Add sections and action buttons in `SpecificationsPanel`.
4. Add link modal component (shared for task/note via props).
5. Add bulk create tasks dialog and result reporting.
6. Wire optimistic updates/invalidation (`tasks`, `notes`, `specifications`).

## 8. Test Plan

### 8.1 Backend
- create task from spec endpoint links correctly
- bulk create creates N tasks, all linked
- link existing rejects cross-project/cross-workspace
- unlink clears only `specification_id`
- idempotency with repeated command id

### 8.2 Frontend smoke
- open spec -> create task -> appears in linked tasks
- bulk create 3 tasks -> all visible, no duplicates
- create note -> visible in linked notes
- link existing task/note -> appears once
- unlink -> disappears from spec section but remains in global lists

## 9. Rollout
Phase A (fast):
- implement UI using existing create/patch endpoints only

Phase B (clean API):
- add wrapper endpoints and switch UI to wrappers

Phase C (quality):
- improve bulk parser, add progress UI, add telemetry

## 10. Definition of Done
- User can manage implementation tasks and notes directly from a specification.
- Multiple tasks can be created from one spec in one flow.
- Existing tasks/notes can be linked/unlinked safely.
- No duplicate writes from click races.
- Backend + frontend tests for spec-driven linking pass.
