# Project Knowledge Graph (GraphRAG) Implementation Plan

## 1. Cilj
Uvesti project-level `Knowledge Graph` koji se puni iz istog event sourcing toka kao i SQL projekcije, tako da:
- graf bude uvijek blizu real-time stanja iz event store-a,
- graf eksplicitno cuva entitete i relacije izmedju resursa,
- agent moze citati graf kroz MCP alate i koristiti ga za bolji `context pack`.

Kljucna ideja: SQL read-model i graph read-model rade paralelno, svaki sa svojim checkpointom.

## 2. Arhitekturni izbor

### 2.1 Predlozeni model (preporuka)
- Zadrzati postojeci SQL projection worker (`read-model`).
- Dodati novi `knowledge-graph` projection worker koji cita isti EventStore stream (`read_all`) i odrzava Neo4j graf.
- Svaki worker ima svoj checkpoint u `projection_checkpoints` tabeli (vec postoji `name` kolona za vise pipeline-ova).

Zasto je ovo najbolji fit za trenutni kod:
- ne uvodi coupling write putanje sa dostupnoscu Neo4j,
- zadrzava isti event-driven mental model kao postojeca projekcija,
- omogucava replay/catch-up bez uticaja na API write latenciju.

### 2.2 Sta ne raditi u prvoj fazi
- Ne raditi sinhroni upis u Neo4j iz `append_event()` (rizik da Neo4j outage blokira komande).
- Ne uvoditi kompleksan CDC layer dok vec imamo event stream kao source of truth.

## 3. Graph model (MVP schema)

### 3.1 Node tipovi
- `Workspace {id, name}`
- `Project {id, workspace_id, name, description, status, is_deleted}`
- `Task {id, workspace_id, project_id, specification_id, title, status, priority, archived, is_deleted}`
- `Note {id, workspace_id, project_id, task_id, specification_id, title, archived, pinned, is_deleted}`
- `Specification {id, workspace_id, project_id, title, status, archived, is_deleted}`
- `ProjectRule {id, workspace_id, project_id, title, is_deleted}`
- `User {id, username, full_name, user_type}`
- `Tag {value}`

### 3.2 Relacije (MVP)
- `(Project)-[:IN_WORKSPACE]->(Workspace)`
- `(Task)-[:IN_PROJECT]->(Project)`
- `(Task)-[:IN_WORKSPACE]->(Workspace)`
- `(Task)-[:IMPLEMENTS]->(Specification)`
- `(Note)-[:IN_PROJECT]->(Project)`
- `(Note)-[:IN_WORKSPACE]->(Workspace)`
- `(Note)-[:ABOUT_TASK]->(Task)`
- `(Note)-[:ABOUT_SPECIFICATION]->(Specification)`
- `(Specification)-[:IN_PROJECT]->(Project)`
- `(ProjectRule)-[:IN_PROJECT]->(Project)`
- `(Task)-[:TAGGED_WITH]->(Tag)`
- `(Note)-[:TAGGED_WITH]->(Tag)`
- `(Specification)-[:TAGGED_WITH]->(Tag)`
- `(Task)-[:ASSIGNED_TO]->(User)` (kada `assignee_id` postoji)
- `(Task)-[:WATCHED_BY]->(User)` (na `TaskWatchToggled`)
- `(Task)-[:COMMENTED_BY]->(User)` + event metadata (na `TaskCommentAdded`)

Napomena: svi upisi preko `MERGE` + deterministicki kljucevi (`id`) radi idempotentnosti.

## 4. Event -> Graph projection dizajn

### 4.1 Novi modul
Dodati npr.:
- `app/shared/eventing_graph.py`

Sadrzi:
- `project_kurrent_graph_once(limit: int = 500) -> int`
- `start_graph_projection_worker()`
- `stop_graph_projection_worker()`
- `_project_graph_event(...)` mapiranje eventa na Cypher upite
- checkpoint ime: `knowledge-graph`

### 4.2 Integracija u startup
U `app/main.py` lifecycle:
- startup:
  - `project_kurrent_events_once(...)` (postojeci SQL catch-up)
  - `project_kurrent_graph_once(...)` (novi graph catch-up)
  - `start_projection_worker()`
  - `start_graph_projection_worker()`
- shutdown:
  - `stop_graph_projection_worker()`
  - `stop_projection_worker()`

### 4.3 Replay i idempotency pravilo
- worker cita evente po `commit_position`, striktno monotono.
- ako isti event dodje ponovo (retry/replay), Cypher `MERGE` ne pravi duplikate.
- za relacije koje zavise od promjene reference (npr. `task.project_id`), projekcija radi:
  - delete starih edge-ova tog tipa,
  - create/merge novih edge-ova iz trenutnog payloada.

## 5. Neo4j + GraphRAG infrastrukturni sloj

### 5.1 Docker compose prosirenje
Dodati servise:
- `neo4j` (Aura/localhost varijanta, za lokalno: official neo4j image)
- opciono: `neo4j-graphrag-mcp` sidecar (prema Neo4j GraphRAG MCP setup-u)

Novi env (task-app i mcp-tools gdje treba):
- `KNOWLEDGE_GRAPH_ENABLED=true|false`
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`
- `GRAPH_PROJECTION_BATCH_SIZE`
- `GRAPH_PROJECTION_POLL_INTERVAL_SECONDS`
- `GRAPH_CONTEXT_MAX_HOPS`
- `GRAPH_CONTEXT_MAX_TOKENS`

### 5.2 Indexi/constraints u Neo4j
Na bootstrapu osigurati:
- unique constraints na `id` za glavne node tipove,
- indexe za ceste filtere (`workspace_id`, `project_id`, `status`, `archived`, `is_deleted`).

## 6. MCP plan

## 6.1 Novi MCP toolovi (read-only)
U postojecom `app/features/agents/mcp_server.py` dodati read alate koji citaju iz grafa (preko internog servisa ili Neo4j GraphRAG MCP proxy-ja):
- `graph_get_project_overview(project_id, workspace_id)`
- `graph_get_neighbors(entity_type, entity_id, rel_types?, depth=1, limit=50)`
- `graph_find_related_resources(project_id, query, limit=20)`
- `graph_get_dependency_path(from_entity, to_entity, max_depth=4)`
- `graph_context_pack(project_id, focus_entity_type?, focus_entity_id?, limit=30)`

Svi alati moraju postovati isti auth/allowlist model kao postojeci MCP alati (`MCP_AUTH_TOKEN`, workspace/project allowlist).

### 6.2 Integracija sa external Neo4j GraphRAG MCP
Dvije opcije:
- A) `task-management-mcp` toolovi direktno koriste Neo4j driver (manje moving parts).
- B) `task-management-mcp` toolovi delegiraju prema zasebnom Neo4j GraphRAG MCP serveru (cistiji separation).

Preporuka za rollout:
- Faza 1: A (brze i jednostavnije),
- Faza 2: B ako zelite centralizovan GraphRAG servis za vise sistema.

## 7. Context pack integracija

### 7.1 Prosirenje executor contexta
U `app/features/agents/executor.py`:
- pored `project_description` i `project_rules`, ucitati i `graph_context` (sa summarizovanim cvorovima/vezama).

### 7.2 Prompt prosirenje
U `app/features/agents/codex_mcp_adapter.py` dodati novu sekciju:
- `File: GraphContext.md (source: knowledge_graph)`

Sadrzaj:
- Top relacije za projekat,
- focus podaci za trenutni task/spec/note,
- eksplicitni `related resources` i `dependency hints`.

Fallback pravilo:
- ako graph nije dostupan, nastaviti sa Soul.md + ProjectRules.md (bez failanja agenta).

## 8. Observability i operacije

Dodati metrike:
- `graph_projection_events_processed_total`
- `graph_projection_lag_commits`
- `graph_projection_failures_total`
- `graph_projection_last_success_at`
- `graph_context_requests_total`
- `graph_context_failures_total`

Health endpoint dopuniti info poljima:
- neo4j connectivity status,
- graph checkpoint position i zaostatak.

## 9. Test plan

### 9.1 Unit tests
- event->graph mapper za svaki glavni event tip (`Task*`, `Note*`, `Specification*`, `Project*`, `ProjectRule*`).
- idempotent projection (isti event 2x ne duplira node/edge).

### 9.2 Integration tests
- spin-up test Neo4j (docker test service),
- append event -> graph projection -> MCP graph tool read validates expected relacije.

### 9.3 Regression tests za context pack
Prosiriti `app/tests/test_agents_context_pack.py`:
- provjeriti da `GraphContext.md` ulazi u prompt,
- provjeriti graceful fallback kad je graph nedostupan.

## 10. Rollout faze

1. **Faza 0 - Design freeze**
- potvrditi MVP node/edge schema i tool API shape.

2. **Faza 1 - Infra + projection skeleton**
- Neo4j service + env + constraints,
- novi graph worker sa checkpointom i osnovnim event mapiranjem.

3. **Faza 2 - MCP read alati**
- implementirati `graph_*` toolove,
- auth/allowlist i osnovni query limiting.

4. **Faza 3 - Context pack**
- executor + prompt prosirenje (`GraphContext.md`),
- fallback i timeout policy.

5. **Faza 4 - Hardening**
- metrike, retries/backoff, replay skripta,
- load test i tuning batch size/queries.

## 11. Konkretni fajlovi za izmjene
- `app/shared/settings.py`
- `app/shared/eventing_graph.py` (novi)
- `app/main.py`
- `app/features/agents/service.py` (graph read servis)
- `app/features/agents/mcp_server.py` (novi graph toolovi)
- `app/features/agents/executor.py` (graph context load)
- `app/features/agents/codex_mcp_adapter.py` (GraphContext.md u prompt)
- `app/tests/test_agents_context_pack.py`
- `app/tests/test_api.py` (projection/MCP regresije)
- `docker-compose.yml`
- `README.md`

## 12. Otvorene odluke koje treba zakljucati prije implementacije
- Da li graph query ide direktno iz app-a ili preko zasebnog Neo4j GraphRAG MCP servera.
- Da li u MVP uvodimo embedding retrieval odmah ili prvo samo strukturni graf + traversal.
- Koliki je prihvatljiv max lag (npr. <= 5s) izmedju event append i graph dostupnosti.

## 13. Definition of Done
- Knowledge graph se puni automatski iz event store-a sa zasebnim checkpointom.
- Graf korektno predstavlja kljucne resurse i njihove relacije.
- Novi MCP graph alati vracaju upotrebljiv output za agenta.
- Agent context pack ukljucuje `GraphContext.md` kada je dostupno.
- U slucaju Neo4j problema, core API i postojeci SQL projekcije ostaju funkcionalni.
