# Knowledge Graph, RAG, and Vector Search Analysis

## Scope
This document analyzes how the system implements and uses:
- Knowledge Graph (Neo4j projection + graph queries)
- Vector search (pgvector + Ollama embeddings)
- Hybrid GraphRAG (graph topology + vector retrieval + grounded evidence/summary)

The analysis is based on the current backend/frontend implementation in:
- `app/shared/knowledge_graph.py`
- `app/shared/vector_store.py`
- `app/shared/eventing_graph.py`
- `app/shared/eventing_vector.py`
- `app/shared/context_frames.py`
- `app/features/projects/api.py`
- `app/features/agents/service.py`
- `app/features/agents/executor.py`
- `app/shared/models.py`
- `app/shared/settings.py`

## High-Level Architecture
The retrieval stack is split into two synchronized projections driven by event streams:
- Graph projection: writes entity nodes/relations to Neo4j (`eventing_graph.py`)
- Vector projection: writes text chunks + embeddings to `vector_chunks` in Postgres/pgvector (`eventing_vector.py`, `vector_store.py`)

At query time:
- Graph APIs read structural relevance (degree, neighbors, dependency paths)
- Vector APIs read semantic relevance (cosine similarity on embeddings)
- GraphRAG merges both into ranked evidence and optionally grounded summary text

The stack is intentionally mode-driven per project (`chat_index_mode`):
- `OFF`
- `VECTOR_ONLY`
- `KG_AND_VECTOR`

## Data Model and Configuration

### Project-level controls
From `Project` model (`app/shared/models.py`):
- `embedding_enabled`
- `embedding_model`
- `chat_index_mode`
- `chat_attachment_ingestion_mode`
- `vector_index_distill_enabled`
- `context_pack_evidence_top_k`

### Global flags
From `settings.py`:
- Graph: `KNOWLEDGE_GRAPH_ENABLED`, `NEO4J_*`
- GraphRAG rollout: `GRAPH_RAG_ENABLED`, canary project/workspace lists, `GRAPH_RAG_SUMMARY_MODEL`
- Vector: `VECTOR_STORE_ENABLED`, embedding provider/model allowlist, distillation flags

### Storage
- Graph DB: Neo4j (constraints/indexes created in `ensure_graph_schema`)
- Vector table: `vector_chunks` with source chunk metadata, embedding JSON, and pgvector column/index usage on PostgreSQL

## Ingestion and Projection

### Knowledge Graph ingestion
`eventing_graph.py` subscribes to domain events and upserts graph nodes/edges for:
- Project, Task, Note, Specification, ProjectRule
- ChatSession, ChatMessage, ChatAttachment, and chat resource links

Important behavior:
- Chat graph subgraph is policy-aware (`chat_index_mode == KG_AND_VECTOR`)
- If chat graph mode is disabled, chat nodes are purged according to retention mode
- Backfill exists to reconstruct chat graph state for a project

### Vector ingestion
`eventing_vector.py` subscribes to similar streams and indexes text sources via `index_entity_state`:
- Task: title + description
- Note: title + body
- Specification: title + body
- ProjectRule: title + body
- ChatMessage: content
- ChatAttachment: metadata and optionally extracted text (based on ingestion mode)

Key mechanics:
- Text is chunked (`max_tokens=500`, overlap `0.12`)
- Embeddings are generated through Ollama
- If context length fails, chunk is recursively split (`_embed_text_with_split_retry`)
- For PostgreSQL, pgvector HNSW indexes are created per model+dimension
- Reindex is triggered on relevant project setting changes (`embedding_enabled`, `embedding_model`, distillation flags, chat indexing policy)

## Vector Search Behavior
`search_project_chunks`:
- Requires vector runtime enabled for project and PostgreSQL backend
- Embeds query with project-selected model
- Uses cosine distance operator `<=>` and converts to similarity (`1 - distance`)
- Filters by project/model/dimension and optional entity filters
- Returns chunk-level candidates with `vector_similarity`, `snippet`, `source_type`, `source_updated_at`

Operational consequence:
- On non-PostgreSQL DB, vector retrieval is unsupported and raises runtime error (caller paths usually catch and fallback)

## Graph Search and Topology Signals
The graph layer contributes:
- Project overview (entity counts, top tags, top relations)
- Focus neighborhood (`graph_get_neighbors`)
- Dependency paths (`graph_get_dependency_path`)
- Related resources and subgraph extraction

For ranking, graph-based candidate priors are generated mostly from:
- Node degree (normalized)
- Focus-neighborhood distance-derived score
- Optional dependency paths used as explainability (`graph_path`)

## Hybrid Retrieval (GraphRAG)
Two major hybrid entrypoints:
- `search_project_knowledge(...)`
- `graph_context_pack(...)`

### `search_project_knowledge` (search API)
Flow:
1. Build graph candidate scores (if graph enabled)
2. Expand query using starter/facet retrieval hints
3. Run vector search with entity filters from graph candidates
4. Score each item with weighted blend
5. Fallback to graph-only evidence if vector path unavailable

Primary blended score (vector path):
- `0.42 * vector_similarity`
- `0.14 * graph_score`
- `0.12 * freshness`
- `0.07 * entity_priority`
- `0.05 * source_priority`
- `0.04 * starter_alignment`
- `0.16 * lexical_overlap`

Fallback score (graph-only path):
- `0.62 * graph_score`
- `0.16 * freshness`
- `0.08 * entity_priority`
- `0.06 * source_priority`
- `0.08 * starter_alignment`

Output includes:
- `mode`: `graph+vector`, `graph-only`, `vector-only`, or `empty`
- Ranked `items` with `why_selected`, `graph_path`, and per-signal scores
- `gaps` list describing disabled/failed subsystems

### `graph_context_pack` (context assembly for agents/UI)
Flow:
1. Build structure (`overview`, `focus_neighbors`, `dependency_paths`)
2. Collect evidence candidates with graph priors
3. If GraphRAG enabled for scope, attempt vector retrieval
4. Rank evidence with graph+vector or graph-only formula
5. Assign stable evidence IDs (`ev_001`, ...)
6. Optionally generate grounded summary (heuristic or model-backed)
7. Return markdown + machine-readable evidence + summary + gaps

Ranking in this path uses slightly different weights than search API:
- Vector path: `0.44/0.22/0.14/0.08/0.07/0.05` over `vector_similarity/graph/freshness/entity/source/starter`
- Graph-only path: `0.60/0.18/0.08/0.06/0.08` over `graph/freshness/entity/source/starter`

## Agent Runtime Usage
Agent executions consume graph context through `build_project_context_frame`:
- Full frame: includes full graph context/evidence/summary
- Delta frame: if hard context revision unchanged, sends only incremental project deltas

This is injected into automation/chat context as:
- `graph_context_markdown`
- `graph_evidence_json`
- `graph_summary_markdown`
- `graph_context_frame_mode`
- `graph_context_frame_revision`

Result:
- Retrieval context is first-class input to agent prompts
- Cost control exists via full/delta framing

## API Surface
Project endpoints expose graph and hybrid retrieval:
- `GET /api/projects/{id}/knowledge-graph/overview`
- `GET /api/projects/{id}/knowledge-graph/context-pack`
- `GET /api/projects/{id}/knowledge-graph/subgraph`
- `GET /api/projects/{id}/knowledge/search`

Agent/MCP service also exposes:
- `graph_get_project_overview`
- `graph_get_neighbors`
- `graph_find_related_resources`
- `graph_get_dependency_path`
- `graph_context_pack`
- `search_project_knowledge`

## Observability and Reliability
Metrics include:
- Graph projection events/failures/lag
- Graph context request/failure counters
- GraphRAG request/failure counters
- Vector indexed chunk count
- Vector retrieval latency
- Graph context latency with/without summary
- Embedding ingest latency and context-length error counters

Reliability patterns:
- Degradation to graph-only on vector failure
- Degradation to heuristic summary when model summary unavailable
- Explicit `gaps` emitted in responses for transparency

## Notable Design Characteristics

### Strengths
- Clear hybrid design: graph topology + semantic retrieval + grounded evidence IDs
- Per-project retrieval controls enable fine-grained rollout and cost/risk management
- Good fallback behavior and explicit degradation reporting
- Event-driven projection keeps graph/vector indexes aligned with domain events
- Agent runtime integration is mature (context frames, evidence/summaries, refresh policy)

### Risks / inconsistencies
- Defaults are not fully uniform across surfaces:
  - Core project contract default is `chat_index_mode="OFF"`
  - MCP create-project default is `chat_index_mode="KG_AND_VECTOR"`
- Dual ranking formulas exist (`search_project_knowledge` vs `graph_context_pack`), which can produce different ordering for similar queries
- Retrieval quality depends on source text density and extraction quality for chat attachments
- Vector retrieval hard-requires PostgreSQL+pgvector; other DB setups lose semantic retrieval

## Practical Summary
The system is not using a naive RAG pipeline. It uses a structured GraphRAG architecture with:
- Event-projected knowledge graph for topology-aware relevance
- pgvector chunk search for semantic similarity
- Starter/facet-aware query expansion and ranking
- Evidence-first output with explainability fields (`why_selected`, `graph_path`, score components)
- Context framing integration directly in agent execution inputs

In practice, this is a production-oriented hybrid retrieval design with explicit mode controls and fallback semantics rather than a single monolithic retriever.
