# 03 Domain Model and Workflows

## 1. Glavni Entiteti i Relacije
```mermaid
erDiagram
  WORKSPACE ||--o{ WORKSPACE_MEMBER : has
  WORKSPACE ||--o{ PROJECT : contains
  PROJECT ||--o{ PROJECT_MEMBER : has
  PROJECT ||--o{ PROJECT_RULE : governs
  PROJECT ||--o{ SPECIFICATION : defines
  PROJECT ||--o{ TASK : contains
  PROJECT ||--o{ NOTE : contains

  SPECIFICATION ||--o{ TASK : implemented_by
  SPECIFICATION ||--o{ NOTE : documented_by
  TASK ||--o{ TASK_COMMENT : has
  TASK ||--o{ TASK_WATCHER : watched_by
  USER ||--o{ TASK : assigned_to
  USER ||--o{ NOTE : authored
```

## 2. Task Lifecycle
```mermaid
stateDiagram-v2
  [*] --> ToDo: TaskCreated
  ToDo --> InProgress: TaskUpdated(status)
  InProgress --> Done: TaskCompleted
  Done --> ToDo: TaskReopened

  ToDo --> Archived: TaskArchived
  InProgress --> Archived: TaskArchived
  Done --> Archived: TaskArchived
  Archived --> ToDo: TaskRestored

  ToDo --> Deleted: TaskDeleted
  InProgress --> Deleted: TaskDeleted
  Done --> Deleted: TaskDeleted
  Archived --> Deleted: TaskDeleted
```

## 3. Scheduled Task i Automation Substates
```mermaid
stateDiagram-v2
  [*] --> idle
  idle --> queued: TaskScheduleQueued / TaskAutomationRequested
  queued --> running: TaskScheduleStarted / TaskAutomationStarted
  running --> done: TaskScheduleCompleted / TaskAutomationCompleted
  running --> failed: TaskScheduleFailed / TaskAutomationFailed
  failed --> queued: retry / next recurrence
  done --> idle: next recurring window
```

## 4. Specification Lifecycle
```mermaid
stateDiagram-v2
  [*] --> Draft: SpecificationCreated
  Draft --> Ready: status update
  Ready --> InProgress: status update
  InProgress --> Implemented: status update
  Implemented --> Archived: SpecificationArchived
  Archived --> Ready: SpecificationRestored
  Draft --> Deleted: SpecificationDeleted
  Ready --> Deleted: SpecificationDeleted
  InProgress --> Deleted: SpecificationDeleted
  Implemented --> Deleted: SpecificationDeleted
  Archived --> Deleted: SpecificationDeleted
```

## 5. Kljucna Domenska Pravila
- Task, Note i Specification create su case-insensitive idempotent po title/name unutar projekt scope-a.
- Cross-project linking nije dozvoljen (`task/spec/note` moraju deliti workspace + project).
- Ako je task ili note vezan za specification, project change je ogranicen dok se link ne razresi.
- Scheduled instruction task zahteva:
  - `task_type=scheduled_instruction`,
  - `scheduled_instruction`,
  - `scheduled_at_utc`.
- `Project.Delete` kaskadno soft-delete-uje taskove, notes, rules i specifications.

## 6. End-to-End Workflow: Specification -> Execution
```mermaid
sequenceDiagram
  participant U as User
  participant S as Specification API
  participant T as Task API
  participant N as Note API
  participant E as Event Store

  U->>S: create specification
  S->>E: SpecificationCreated
  U->>S: create task(s) from specification
  S->>T: delegate TaskCreate(specification_id)
  T->>E: TaskCreated
  U->>S: create note from specification
  S->>N: delegate NoteCreate(specification_id)
  N->>E: NoteCreated
  U->>T: complete / reopen / archive
  T->>E: Task lifecycle events
```

## 7. Project Deletion Cascade
```mermaid
flowchart TD
  A[Project.Delete command] --> B[TaskDeleted events]
  A --> C[NoteDeleted events]
  A --> D[ProjectRuleDeleted events]
  A --> E[SpecificationDeleted events]
  A --> F[ProjectDeleted event]
  B --> G[SQL + Graph projections]
  C --> G
  D --> G
  E --> G
  F --> G
```

## 8. Domen + Graph Perspektiva
Neo4j projekcija pravi relacije tipa:
- `IN_WORKSPACE`, `IN_PROJECT`
- `IMPLEMENTS` (Task -> Specification)
- `ABOUT_TASK`, `ABOUT_SPECIFICATION` (Note links)
- `ASSIGNED_TO`, `WATCHED_BY`, `COMMENTED_BY`
- `TAGGED_WITH`

Ovo omogucava context pack i dependency-aware pretragu bez menjanja write modela.
