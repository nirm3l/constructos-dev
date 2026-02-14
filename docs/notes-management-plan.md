# Plan: Notes Management + Codex Tools + Markdown Viewer

Ovaj dokument definise kako da postojecu aplikaciju (task management) prosirimo tako da postane i **notes management** aplikacija, uz:

- CRUD i management notes kroz UI
- dobar Markdown viewer sa syntax highlighting-om (code u bojama)
- izlaganje MCP tool-ova tako da Codex moze kreirati/azurirati notes (npr. kad ga pitas da napravi plan, plan zavrsi kao note koji se vidi u UI)

## 1. Cilj i scope (MVP)

### MVP funkcionalnosti
- Kreiranje note-a u workspace-u (opciono vezano za project i/ili task).
- Uredjivanje: title + Markdown body.
- Listanje i pretraga (basic) po title/body.
- Statusi: `pinned`, `archived`, `is_deleted` (soft delete).
- UI: Notes tab sa listom + editor/preview (split view).
- Markdown render: GFM (tabele, checkboxes) + code syntax highlighting.
- MCP tools: `create_note`, `update_note`, `get_note`, `list_notes`, `search_notes`, (opciono) `link_note_to_task`.

### Non-goals (za MVP)
- Real-time kolaboracija i conflict resolution u UI.
- Attachments i file upload.
- Full-text search (FTS5) i napredni tagging sistem (moze kasnije).

## 2. Data model (SQL read model + ES events)

Postojeci sistem vec koristi **CQRS + Event Sourcing** sa SQL read modelima. Notes treba uklopiti istim stilom kao `Task` i `Project`.

### 2.1 SQLAlchemy modeli (read model)
Dodati u `app/shared/models.py`:

- `Note`
  - `id: str (uuid)`
  - `workspace_id: str`
  - `project_id: str | None` (opciono)
  - `task_id: str | None` (opciono, za “plan note” vezan za task)
  - `title: str`
  - `body: str` (Markdown)
  - `tags: str` (JSON lista stringova, default `"[]"`)
  - `pinned: bool` (default `False`)
  - `archived: bool` (default `False`)
  - `is_deleted: bool` (default `False`)
  - `created_by: str` (user_id)
  - `updated_by: str` (user_id)
  - `created_at/updated_at` (TimeMixin)

Opcija (kasnije): `NoteLink` tabela (note_id <-> task_id) ako hocemo N:M umjesto 1 note -> 1 task.

### 2.2 ES events (domain)
Dodati novi slice `app/features/notes/` sa `NoteAggregate` (kao `TaskAggregate`):

- `NoteCreated`
- `NoteUpdated`
- `NoteArchived`
- `NoteRestored`
- `NotePinned`
- `NoteUnpinned`
- `NoteDeleted`
- (opciono) `NoteLinkedToTask` / `NoteUnlinkedFromTask`

U `app/shared/eventing_rebuild.py`:
- Dodati `apply_note_event()` za rebuild state.
- Prosiriti `rebuild_state()` da razumije `aggregate_type == "Note"`.
- Prosiriti `project_event()` da projektuje note evente u `notes` tabelu (isti pattern kao taskovi).

## 3. Backend: Vertical slice (features/notes)

Struktura (kopirati pattern iz `features/tasks`):
- `app/features/notes/domain.py`
- `app/features/notes/command_handlers.py`
- `app/features/notes/application.py`
- `app/features/notes/read_models.py`
- `app/features/notes/api.py`

### 3.1 API endpointi (MVP)
Dodati router u `app/main.py` (kao ostali):

- `GET /api/notes`
  - query: `workspace_id` (required)
  - optional: `project_id`, `task_id`, `q`, `archived`, `pinned`, `limit`, `offset`
- `POST /api/notes`
  - payload: `workspace_id`, optional `project_id`, optional `task_id`, `title`, `body`, optional `tags`
- `GET /api/notes/{note_id}`
- `PATCH /api/notes/{note_id}`
  - patch: `title?`, `body?`, `tags?`, `pinned?`, `archived?`, `project_id?`, `task_id?`
- `POST /api/notes/{note_id}/archive`
- `POST /api/notes/{note_id}/restore`
- `POST /api/notes/{note_id}/pin`
- `POST /api/notes/{note_id}/unpin`
- `POST /api/notes/{note_id}/delete` (soft delete)

Auth/ACL:
- koristiti `ensure_role(db, workspace_id, user.id, {Owner, Admin, Member, Guest})` za read
- za write zabraniti `Guest` (kao sto vec radite za neke akcije): `{Owner, Admin, Member}`

### 3.2 Contracts (Pydantic)
U `app/shared/contracts.py` dodati:
- `NoteCreate`, `NotePatch`, `NoteDTO` (analogno Task)

### 3.3 Activity log (opciono, ali preporuceno)
Ako hocemo “note activity” u UI:
- prosiriti `ActivityLog` sa `note_id: str | None`
- dodati lightweight SQLite migraciju u `app/shared/bootstrap.py` (kao `ensure_task_table_columns`)
- u `project_event()` kad projektujemo note event, postaviti `note_id` u `ActivityLog`
- dodati `GET /api/notes/{note_id}/activity` (isti pattern kao task)

Ako hocemo minimalno, MVP moze bez note activity.

## 4. Codex MCP tools: Notes toolset

Postojeci MCP server je `app/features/agents/mcp_server.py`. Prosiriti ga:

### 4.1 Read tools
- `list_notes(workspace_id, project_id?, task_id?, q?, archived?, pinned?, limit?, offset?)`
- `get_note(note_id)`

### 4.2 Mutating tools (samo kad `read_only=False`)
- `create_note(title, workspace_id?, project_id?, task_id?, body, tags?, pinned?, command_id?)`
- `update_note(note_id, patch, command_id?)`
- `archive_note(note_id, command_id?)`
- `restore_note(note_id, command_id?)`
- `pin_note(note_id, command_id?)`
- `unpin_note(note_id, command_id?)`
- `delete_note(note_id, command_id?)`

Opcija (ako uvedemo N:M linkove):
- `link_note_to_task(note_id, task_id, command_id?)`
- `unlink_note_from_task(note_id, task_id, command_id?)`

### 4.3 Agent behavior: “Plan ide u Note”
Update u `app/features/agents/codex_mcp_adapter.py` prompt-u:
- Ako user trazi “napravi plan” ili “spec”, agent treba:
  1) kreirati note (npr. title: `Plan: <kratko ime>`, body: markdown sa koracima)
  2) opcionalno pin-ovati note
  3) ako je chat u kontekstu task-a: setovati `task_id` na note ili linkovati note na task
  4) vratiti summary koji sadrzi `note_id` i gdje se nalazi u UI

Isto vazi i za `/api/agents/chat` put (general chat, nevezan za task): plan zavrsi kao note u workspace.

## 5. Frontend (React): Notes tab + editor + preview

Frontend je trenutno monolitni `app/frontend/src/main.tsx` sa tabovima.

### 5.1 UI integracija
- Dodati `Tab = 'notes'` i ubaciti u `TAB_ORDER` (npr. izmedju `projects` i `search`).
- Dodati novi “Notes” card layout:
  - lijevo: lista note-ova (search input + filter: pinned/archived)
  - desno: editor i preview (split view)

Minimum UX:
- “New note” button (default title: `Untitled`, body prazan)
- Autosave (PATCH nakon debounce 400-800ms) ili “Save” dugme (MVP moze Save).
- Keyboard shortcuts (kasnije): `Ctrl+S` save, `Ctrl+K` search.

### 5.2 Markdown viewer: biblioteke i izbor
Preporucena kombinacija (balans kvaliteta i jednostavnosti):
- `react-markdown`
- `remark-gfm` (checkboxes, tables)
- `rehype-highlight` + `highlight.js` (syntax highlighting)

Security:
- ne renderovati raw HTML iz note-a (bez `rehype-raw`) u MVP-u.

Implementacija:
- napraviti komponentu `MarkdownView` (npr. `app/frontend/src/markdown/MarkdownView.tsx`)
- custom `code` renderer:
  - inline code: koristi `code` stil
  - fenced code: `pre > code` sa `hljs` klasama
  - dodati “copy” button (opciono)

CSS:
- u `app/frontend/src/styles.css` dodati markdown styles:
  - headings, lists, blockquote, table
  - code block background prilagodjen temi
  - highlight.js token boje mapirati na CSS varijable (da radi i light/dark)

### 5.3 API client i types
U `app/frontend/src/types.ts` dodati `Note` tip.
U `app/frontend/src/api.ts` dodati:
- `getNotes`, `createNote`, `patchNote`, `getNote` (i sl. po potrebi)

React Query:
- query keys npr. `['notes', userId, workspaceId, filters...]`
- invalidacija nakon mutacija

## 6. Bootstrap/migracije (SQLite)

Postojece migracije su “lightweight” preko `PRAGMA table_info` + `ALTER TABLE`.

Za notes:
- nova tabela `notes` ce se kreirati kroz `Base.metadata.create_all(bind=engine)` ako ne postoji.
- ako prosirujemo postojece tabele (npr. `activity_logs.note_id`) dodati `ensure_activity_log_columns()` u `app/shared/bootstrap.py`.

## 7. Test plan

Backend:
- Unit: Note command handlers (create/patch/archive/pin/delete) + permission checks.
- Integration: API endpoints (happy path + 403/404).
- Eventing: `eventing_rebuild.apply_note_event` i projekcija u `Note` tabelu.

MCP:
- tool pozivi vracaju note DTO
- read_only mode: mutating tools nisu dostupni

Frontend (minimalno):
- smoke test manuelno: create note -> edit -> refresh -> content persists
- markdown rendering: fenced code block, tabela, checkbox

## 8. Preporuceni redoslijed implementacije

1. Model + contracts:
   - `Note` SQLAlchemy model
   - `NoteCreate/NotePatch/NoteDTO`
2. Notes slice backend:
   - domain/events + command handlers + read models + API
   - projekcija u `eventing_rebuild.py`
3. MCP toolovi:
   - expose notes CRUD + (opciono) link-to-task
   - update Codex prompt da “plan ide u note”
4. Frontend:
   - Notes tab, lista + editor
   - Markdown viewer + highlight
5. Poliranje:
   - pinned/archived filteri, search
   - note activity (ako hocemo)
   - UI ergonomija (autosave, copy code)

## 9. Minimalna “Definition of Done” (MVP)

- Notes tab postoji i radi (create/edit/list/search).
- Markdown preview prikazuje code u bojama (syntax highlighting) i GFM.
- Codex moze preko MCP alata kreirati note (npr. plan) i note se odmah vidi u UI.
- ACL: guest ne moze mutate, member/admin/owner mogu.
- API i MCP rade idempotentno preko `X-Command-Id` / `command_id` gdje je primjenjivo.

