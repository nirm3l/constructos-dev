# Specification-Driven Development Plan

## 1. Cilj
Uvesti novi koncept `Specification` tako da:
- `Specification` pripada jednom `Project`.
- Jedna specifikacija moze imati vise `Task` i `Note`.
- Taskovi implementiraju specifikaciju (jedan ili vise taskova po specifikaciji).
- Specifikacija ima svoj statusni tok.
- Specifikacija moze imati `external_refs` i `attachment_refs`.

## 2. Domenski model (MVP)
Predlozena pravila:
- `Specification` pripada tacno jednom `workspace_id` i `project_id`.
- `Task` ima opciono `specification_id`.
- `Note` ima opciono `specification_id`.
- Jedan task/note moze biti vezan za najvise jednu specifikaciju.
- Zabraniti cross-project vezu (task/note i specification moraju biti u istom projektu).

Predlozeni statusi specifikacije:
- `Draft`
- `Ready`
- `In progress`
- `Implemented`
- `Archived`

## 3. Data model i migracije

### 3.1 Nova tabela `specifications` (`app/shared/models.py`)
Kolone:
- `id` (uuid)
- `workspace_id` (FK -> workspaces.id)
- `project_id` (FK -> projects.id, indexed)
- `title` (string, required)
- `body` (text, markdown)
- `status` (string, default `Draft`)
- `external_refs` (text/json, default `[]`)
- `attachment_refs` (text/json, default `[]`)
- `created_by` (FK -> users.id)
- `updated_by` (FK -> users.id)
- `archived` (bool, default `False`)
- `is_deleted` (bool, default `False`)
- `created_at`, `updated_at` (TimeMixin)

### 3.2 Prosiriti postojece tabele
- `tasks`: dodati `specification_id` (nullable FK -> specifications.id, indexed).
- `notes`: dodati `specification_id` (nullable FK -> specifications.id, indexed).

### 3.3 Bootstrap migracije (`app/shared/bootstrap.py`)
Dodati:
- `ensure_specification_table_columns()`
- prosirenje `ensure_task_table_columns()` za `specification_id`
- prosirenje `ensure_note_table_columns()` za `specification_id`

## 4. Event sourcing i projekcije

### 4.1 Novi specification eventi (`app/features/specifications/domain.py`)
- `SpecificationCreated`
- `SpecificationUpdated`
- `SpecificationArchived`
- `SpecificationRestored`
- `SpecificationDeleted`

### 4.2 Rebuild i projekcija (`app/shared/eventing_rebuild.py`)
- Dodati `apply_specification_event()`.
- Ukljuciti `aggregate_type == "Specification"` u `rebuild_state()`.
- U `project_event()` dodati upis specification eventa u SQL read model.
- Prosiriti projekciju `TaskUpdated` i `NoteUpdated` da podrzi `specification_id`.

### 4.3 Upcaster kompatibilnost (`app/shared/event_upcasters.py`)
- Za starije task/note evente postaviti implicitno `specification_id = None`.

## 5. Backend vertical slice: `features/specifications`
Dodati novu strukturu:
- `app/features/specifications/domain.py`
- `app/features/specifications/command_handlers.py`
- `app/features/specifications/application.py`
- `app/features/specifications/read_models.py`
- `app/features/specifications/api.py`

## 6. Contracts i serializeri

### 6.1 Contracts (`app/shared/contracts.py`)
Dodati:
- `SpecificationCreate`
- `SpecificationPatch`
- `SpecificationDTO`
- `SpecificationCommandState`

Prosiriti:
- `TaskCreate`, `TaskPatch`, `TaskDTO` sa `specification_id`
- `NoteCreate`, `NotePatch`, `NoteDTO` sa `specification_id`

### 6.2 Serializeri (`app/shared/serializers.py`)
Dodati:
- `serialize_specification()`
- `load_specification_view()`
- `load_specification_command_state()`

Prosiriti task/note serializaciju za `specification_id`.

## 7. API dizajn

### 7.1 Specification endpointi
- `GET /api/specifications` (workspace_id, project_id, q, status, archived, limit, offset)
- `POST /api/specifications`
- `GET /api/specifications/{specification_id}`
- `PATCH /api/specifications/{specification_id}`
- `POST /api/specifications/{specification_id}/archive`
- `POST /api/specifications/{specification_id}/restore`
- `POST /api/specifications/{specification_id}/delete`

### 7.2 Task/Note endpointi
Prosiriti:
- `POST /api/tasks`, `PATCH /api/tasks/{id}` sa `specification_id`
- `POST /api/notes`, `PATCH /api/notes/{id}` sa `specification_id`
- `GET /api/tasks` filter `specification_id`
- `GET /api/notes` filter `specification_id`

### 7.3 Router wiring
U `app/main.py` registrovati `specifications` router.

## 8. Validacije i poslovna pravila
- `specification_id` mora postojati i ne smije biti obrisan.
- `specification.workspace_id == task/note.workspace_id`.
- `specification.project_id == task/note.project_id`.
- Ako task/note ima `specification_id`, zabraniti patch `project_id` bez unlink-a.
- Ako je specification `Archived`, po dogovoru:
  - ili blokirati nove linkove task/note,
  - ili dozvoliti samo read i status promjene (odluku fiksirati prije implementacije).

## 9. Project delete ponasanje
Kod brisanja projekta (`DeleteProjectHandler`) dodati:
- soft delete svih aktivnih specifikacija projekta (SpecificationDeleted event)
- ciscenje referenci ako je potrebno

## 10. Frontend plan

### 10.1 Tipovi i API (`app/frontend/src/types.ts`, `app/frontend/src/api.ts`)
- Dodati `Specification` tip.
- Dodati specification CRUD API funkcije.
- Dodati `specification_id` u task/note payload tipove.

### 10.2 UI
- Novi tab/panel: `SpecificationsPanel`.
- Lista specifikacija po projektu + status filter.
- Editor za `title`, `body`, `status`, refs.
- U task/note editoru dodati selector specifikacije.
- U task/note listi opcioni filter po specifikaciji.

## 11. MCP/Agent integracija
Prosiriti:
- `app/features/agents/mcp_server.py`
- `app/features/agents/service.py`

Novi alati:
- `list_specifications`
- `get_specification`
- `create_specification`
- `update_specification`
- `archive_specification`
- `restore_specification`
- `delete_specification`

I prosiriti task/note alate da prihvataju `specification_id`.

## 12. Test plan

### 12.1 Novi test fajl
- `app/tests/test_specifications_api.py`

### 12.2 Prosirenja postojecih testova
- `app/tests/test_api.py`: task flow sa `specification_id`, filteri, project delete.
- `app/tests/test_notes_api.py`: note flow sa `specification_id`.
- validacija cross-project i cross-workspace gresaka.
- idempotency provjera sa `X-Command-Id`.

## 13. Predlozeni redoslijed implementacije
1. Model + bootstrap migracije.
2. Contracts + serializer + eventing rebuild.
3. `features/specifications` backend + API.
4. Task/Note integracija (`specification_id` + validacije + filteri).
5. Testovi backend.
6. Frontend tipovi/API i `SpecificationsPanel`.
7. MCP alati.
8. Dokumentacija i release smoke test.

## 14. Definition of Done (MVP)
- Postoji full CRUD za `Specification` sa statusom i refs.
- Task i note mogu biti povezani na specifikaciju uz ispravne validacije.
- Listanje taskova/nota po `specification_id` radi.
- Brisanje projekta pravilno uklanja i specifikacije.
- Testovi za specification flow i regresije prolaze.
