# GraphRAG Rollout and Evaluation Runbook

Date: 2026-02-19

## 1) Canary controls

Use environment flags to limit GraphRAG to selected scopes:

- `GRAPH_RAG_ENABLED=true`
- `GRAPH_RAG_CANARY_WORKSPACE_IDS=ws-1,ws-2`
- `GRAPH_RAG_CANARY_PROJECT_IDS=pr-1,pr-2`

Rules:

1. If both canary lists are empty, GraphRAG is enabled globally.
2. If at least one list is non-empty, GraphRAG is enabled only for matching project/workspace.
3. Non-canary projects automatically use graph-only mode, with the same context-pack schema.

## 2) Optional grounded summary with local LLM

Summary mode:

- Set `GRAPH_RAG_SUMMARY_MODEL` to enable Ollama summary generation.
- Leave `GRAPH_RAG_SUMMARY_MODEL` empty to use deterministic heuristic summary.

When LLM summary fails:

- API returns `structure + evidence + markdown` with no `summary` section.
- Response may include `gaps` describing fallback reason.

## 3) SLO configuration

- `GRAPH_RAG_SLO_CONTEXT_NO_SUMMARY_MS` (default `1200`)
- `GRAPH_RAG_SLO_CONTEXT_WITH_SUMMARY_MS` (default `2500`)
- `GRAPH_RAG_SLO_EMBED_INGEST_P95_MS` (default `800`)
- `GRAPH_RAG_SLO_EMBED_CONTEXT_ERROR_RATE_PCT` (default `0.1`)

## 4) Operational endpoints

- Raw runtime metrics: `GET /api/metrics`
- GraphRAG SLO view: `GET /api/metrics/graph-rag`

`/api/metrics/graph-rag` includes:

- request/failure counts and failure rate
- grounded claim ratio
- context latency (`last`, `p95`)
- vector retrieval latency (`last`, `p95`)
- embedding ingest latency (`last`, `p95`)
- embedding context-length error rate
- active canary lists
- computed `slo_breaches`

## 5) QA scenarios

Run:

```bash
docker compose exec -T task-app python scripts/qa_graph_rag.py
```

The script verifies:

1. Context-pack schema and evidence IDs.
2. Summary citations map to known evidence IDs (when summary is present).
3. Project-level `embedding_enabled` toggle round-trip.
4. GraphRAG metrics endpoint availability and key fields.

## 6) Suggested rollout sequence

1. Deploy with `GRAPH_RAG_ENABLED=true` and canary lists set to one internal project.
2. Monitor `/api/metrics/graph-rag` for 24h:
   - `failure_rate_pct`
   - `context_latency_ms.p95`
   - `embedding_context_length_error_rate_pct`
3. Expand canary to more projects/workspaces.
4. Remove canary lists for full rollout when SLO remains stable.
