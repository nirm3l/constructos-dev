# Plan: Knowledge Graph + Vector Store + GraphRAG (Context Pack Re-architecture)

Date: 2026-02-18

Implementation assumption:
- After implementation, databases will be recreated (`Postgres`, `Neo4j`, `KurrentDB/EventStore`).
- Because of that, legacy data migration is not required for initial rollout.

## 1) Goal

Introduce a retrieval layer that combines:
- structure from the Knowledge Graph,
- textual evidence from a vector store,
- an LLM-generated concise answer with citations.

Desired user outcome:
- fewer generic responses,
- more accurate and verifiable responses,
- clear traceability from "answer -> evidence -> source artifact".

## 2) How KG is used today (current state)

### 2.1 Ingestion and projection
- Event -> Neo4j projection runs through `app/shared/eventing_graph.py`.
- Projected relations include: `IN_PROJECT`, `IMPLEMENTS`, `ABOUT_TASK`, `ABOUT_SPECIFICATION`, `ASSIGNED_TO`, `WATCHED_BY`, `COMMENTED_BY`, `TAGGED_WITH`.
- Graph worker runs catch-up + subscribe (`project_kurrent_graph_once`, `start_graph_projection_worker`).

### 2.2 Retrieval/API/MCP
- Core graph query functions are in `app/shared/knowledge_graph.py`:
  - `graph_get_project_overview`
  - `graph_get_neighbors`
  - `graph_find_related_resources`
  - `graph_get_dependency_path`
  - `graph_context_pack`
- REST endpoints:
  - `/api/projects/{project_id}/knowledge-graph/overview`
  - `/api/projects/{project_id}/knowledge-graph/context-pack`
  - `/api/projects/{project_id}/knowledge-graph/subgraph`
- MCP exposure through `app/features/agents/mcp_server.py` (`graph_*` tools).

### 2.3 Usage in agent and UI
- Automation/chat context injects `graph_context_markdown` from `build_graph_context_markdown` (`app/features/agents/executor.py`).
- Codex prompt treats this as `GraphContext.md` (`app/features/agents/codex_mcp_adapter.py`).
- UI panel currently shows:
  - overview,
  - connected resources,
  - subgraph visualization,
  - markdown preview (`app/frontend/src/components/projects/ProjectKnowledgeGraphPanel.tsx`).

## 3) Main gap vs target "KG + Vector + GraphRAG"

1. No vector index: no embedding pipeline or semantic retrieval exists today.
2. `graph_find_related_resources` uses text contains (not semantic retrieval).
3. `graph_context_pack` is mainly a degree/topology snapshot without cited textual evidence.
4. Agent receives one markdown block (`GraphContext.md`) without ranked evidence or confidence signals.
5. UI has no evidence-first view (which paragraph supports which claim).
6. Metrics are operational (requests/failures), not retrieval quality metrics (precision, groundedness).

## 4) Target architecture (New Context Pack)

## 4.1 Three layers

1. Structure layer (KG)
- Neo4j remains the source for relations and dependency paths.
- It answers "what is connected" and "through which relations".

2. Evidence layer (Vector store)
- New vector store for textual chunks from:
  - task title/description,
  - note body,
  - specification body,
  - project rule body,
  - (optional) task comment body.
- Recommendation: `pgvector` in existing Postgres (lower ops overhead).
- Embedding runtime: local `Ollama` service in `docker-compose` by default, no cloud embedding API.
- Embeddings are optional: when `VECTOR_STORE_ENABLED=false`, retrieval runs in graph-only mode with the same API shape.
- Embeddings are configurable per project:
  - `embedding_enabled` (bool),
  - `embedding_model` (string from an allow-list).
- Effective request-time decision:
  - if global `VECTOR_STORE_ENABLED=false` -> graph-only,
  - if global `VECTOR_STORE_ENABLED=true` and `project.embedding_enabled=true` -> graph+vector using `project.embedding_model`,
  - if `project.embedding_enabled=false` -> graph-only.

3. Summary layer (LLM)
- LLM produces a concise answer only from top-ranked evidence.
- Every key claim must reference at least one `evidence_id`.

## 4.2 GraphRAG retrieval flow

1. Seed selection
- If a focus entity exists (Task/Spec/Note), use it as the seed.
- Otherwise use top central entities + recent changes.

2. Graph expansion
- K-hop expansion (for example 1-2) over relation whitelists per use case.

3. Candidate text fetch
- If vector layer is enabled for that project: fetch chunks tied to selected entities from `pgvector`.
- If vector layer is disabled: use graph-only fallback (without semantic score component).

4. Hybrid ranking
- `final_score = a*graph_score + b*vector_similarity + c*freshness + d*entity_priority`.

5. Evidence bundle
- Return top N chunks with metadata:
  - entity_id,
  - source_type,
  - snippet,
  - similarity,
  - graph_path.

6. LLM grounded summary
- Generate summary + open questions + recommended actions,
- but only from the evidence bundle.

## 5) Proposed new Context Pack format

```json
{
  "project_id": "...",
  "focus": {"entity_type": "Task", "entity_id": "..."},
  "structure": {
    "overview": {...},
    "focus_neighbors": [...],
    "dependency_paths": [...]
  },
  "evidence": [
    {
      "evidence_id": "ev_001",
      "entity_type": "Specification",
      "entity_id": "...",
      "source_type": "specification.body",
      "snippet": "...",
      "vector_similarity": 0.82,
      "graph_score": 0.66,
      "final_score": 0.75,
      "graph_path": ["Task", "IMPLEMENTS", "Specification"]
    }
  ],
  "summary": {
    "executive": "...",
    "key_points": [
      {"claim": "...", "evidence_ids": ["ev_001"]}
    ],
    "gaps": ["..."]
  },
  "markdown": "..."
}
```

Note:
- `markdown` remains as a helper representation for agents/UI.
- Canonical API shape is `structure + evidence + summary`.

## 6) Implementation phases

## Phase 0: Baseline and feature flags (1 sprint)

Deliverables:
- Add flags in `app/shared/settings.py`:
  - `GRAPH_RAG_ENABLED`
  - `VECTOR_STORE_ENABLED`
  - `CONTEXT_PACK_EVIDENCE_TOP_K`
- Add embedding runtime config:
  - `EMBEDDING_PROVIDER=ollama`
  - `OLLAMA_BASE_URL` (for example `http://ollama:11434`)
  - `DEFAULT_EMBEDDING_MODEL` (fallback when a project has no explicit model)
  - `ALLOWED_EMBEDDING_MODELS` (allow-list for project-level model selection)
  - `OLLAMA_EMBED_GPU_ENABLED` (hint; fallback to CPU if GPU is unavailable)
- Add project-level embedding config (DB + API):
  - extend `Project` model/patches with `embedding_enabled` and `embedding_model`,
  - validate `embedding_model` against `ALLOWED_EMBEDDING_MODELS`,
  - sensible default: `embedding_enabled=false`.
- Add metrics:
  - `graph_rag_requests`,
  - `graph_rag_failures`,
  - `vector_indexed_chunks`,
  - `vector_retrieval_latency_ms`,
  - `context_pack_grounded_claim_ratio`.

## Phase 1: Vector ingestion pipeline (1-2 sprints)

Deliverables:
- New table(s) for chunks + embeddings.
- Chunking + embedding worker reacting to the same events as graph projection.
- Idempotent update/delete on artifact changes and soft-delete.
- `docker-compose` service for `ollama` with persistent model volume.
- App integration to `OLLAMA_BASE_URL` inside compose network.
- Chunk upper bound: max 500 tokens (to avoid context-length errors).
- Chunk overflow strategy: auto-split + retry when runtime returns `input length exceeds context length`.
- Use GPU acceleration where available (for example `/dev/dri` + `OLLAMA_VULKAN=1`), with mandatory CPU fallback.
- Project-level index lifecycle:
  - when `embedding_enabled` changes `false -> true`: run backfill for that project only,
  - when `embedding_model` changes: run re-embed for that project only,
  - when `embedding_enabled` changes `true -> false`: stop new indexing for that project (existing vectors may remain for fast re-enable).
- Initial rollout path with DB recreation:
  - skip legacy backfill,
  - build index from freshly created data/events only.

Proposed new modules:
- `app/shared/vector_store.py`
- `app/shared/eventing_vector.py`

## Phase 2: GraphRAG retriever service (1 sprint)

Deliverables:
- Refactor existing `graph_context_pack` orchestrator to the new shape.
- Implement hybrid ranking (graph + vector + freshness).
- REST and MCP return the new shape with `evidence` field.
- Project-level retrieval branching:
  - graph+vector only for projects with embeddings enabled,
  - graph-only for projects without embeddings (same response schema).

API strategy (hard switch):
- Existing endpoint `/knowledge-graph/context-pack` moves directly to new schema.
- MCP tool `graph_context_pack` moves to the same schema.
- Do not introduce `version` param or parallel `/context-pack-v2` endpoint.

## Phase 3: Grounded summarization (1 sprint)

Deliverables:
- LLM summarize step that accepts only top evidence.
- Output schema with `claim -> evidence_ids` mapping.
- Strict fallback: if summary fails, return `structure+evidence` without summary section.

## Phase 4: UX improvements (1 sprint)

Deliverables in `ProjectKnowledgeGraphPanel`:
- New "Evidence" panel sorted by score.
- Click on evidence highlights node/path in graph.
- Labels: `Source`, `Updated`, `Score`, `Why selected`.
- "Summary with citations" section.
- In project settings:
  - `Embedding enabled` toggle,
  - `Embedding model` dropdown (from allow-list),
  - indexing status: `not indexed / indexing / ready / stale`.

Deliverables in agent prompt:
- In addition to `GraphContext.md`, include:
  - `GraphEvidence.json`
  - `GraphSummary.md`
- Rule: treat claims without evidence id as low confidence.

## Phase 5: Rollout and evaluation (continuous)

Strategy:
- Canary by project/workspace.
- No A/B by context-pack version (no v1/v2 dual mode).
- Fallback within same shape: if summarizer fails, return `structure + evidence + gaps`.
- If vector/embedding layer fails: automatically fallback to graph-only retrieval (embeddings remain optional).

## 7) UX improvements focused on experience

1. Auditable context pack
- Every recommendation in summary must have clickable evidence.

2. Entity focus mode
- Selecting a graph node automatically refreshes `focus_entity_type/id` + evidence.

3. "What is missing" block
- LLM and retrieval return missing context (for example "no note exists for incident runbook").

4. Freshness indicator
- Show source age and warn when evidence is stale.

5. Actionability
- Offer direct actions from summary section:
  - create note,
  - create task,
  - link task/spec.

## 8) Testing and quality

Required testing layers:
- Unit: chunking, deduplication, ranking formula.
- Integration: event -> vector index, graph + vector retrieval, API schema.
- E2E: agent/chat response with citations and valid evidence ids.

New acceptance criteria:
- >=90% of summary claims have at least 1 evidence id.
- P95 context-pack latency under agreed SLO (for example 1200ms without LLM, 2500ms with LLM).
- In demo script scenarios, groundedness score improves vs baseline measured before cutover.
- P95 embedding ingestion latency per chunk is within agreed SLO.
- Context-length embedding errors <= 0.1% (with max 500 token chunk cap + auto-split).
- Project-level config works without regressions:
  - changing `embedding_enabled` impacts only that project,
  - changing `embedding_model` retriggers re-embed only for that project.

## 9) Risks and mitigations

1. Higher complexity and latency
- Mitigation: async precompute, cache by `(project_id, focus_entity, query)`.

2. Drift between graph and vector layers
- Mitigation: same event source, same commit checkpoint model, lag metrics.

3. Hallucination in summary layer
- Mitigation: citation-required schema + fallback without summary when citations are invalid.

4. Operational overhead
- Mitigation: start with `pgvector` in existing Postgres, no extra DB service initially.

## 10) Concrete backlog (proposal)

1. Add feature flags and metrics (settings + observability).
2. Confirm DB recreation cutover plan (reset + bootstrap) and drop legacy migration scope.
3. Add project-level embedding fields (`embedding_enabled`, `embedding_model`) + allow-list validation.
4. Design vector schema + migrations.
5. Implement event-driven indexing worker.
6. Add backfill/re-embed logic per project when embedding config changes.
7. Refactor `graph_context_pack` orchestrator to new shape.
8. Update existing REST/MCP context-pack endpoint/tool (breaking change).
9. Add `ollama` service in `docker-compose` + model volume.
10. Connect app to `OLLAMA_BASE_URL` and implement embedding client.
11. Extend Codex prompt with evidence + summary inputs.
12. Extend frontend panel with Evidence and Summary sections + project embedding settings.
13. Add QA scenarios for groundedness, latency, context-length edge case, and project-level toggling.
14. Canary rollout and SLO/quality measurement.

## 11) Recommended technical choices

- Vector store: `pgvector` (first step), with a possible future migration to a dedicated vector DB at scale.
- Embedding runtime: local `Ollama` in `docker-compose` (default), with future provider flexibility.
- Embedding model: configurable per project from a central allow-list, with versioning (`embedding_model_version`).
- Chunking: 300-500 tokens (hard cap 500), overlap 10-15%, plus entity-scope metadata.
- Hardware policy: use GPU acceleration when available; otherwise deterministic CPU fallback.
- Ranking tuning: start with fixed weights, then tune on offline eval set.

## 12) Definition of success

The new Context Pack is successful when the system consistently delivers:
- Structure: relevant relations and dependencies,
- Evidence: textual citations tied to artifacts,
- Summary: concise, actionable response grounded in evidence.
