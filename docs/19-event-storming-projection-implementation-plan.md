# Event Storming Projection Implementation Plan

## 1. Objective

Add Event Storming support as a derived capability on top of existing project artifacts (`Task`, `Note`, `Specification`) so the system can:

- infer Event Storming components (bounded contexts, aggregates, commands, domain events, policies, read models),
- maintain links between artifacts and inferred components,
- support bidirectional traversal:
  - from artifact to Event Storming components,
  - from Event Storming component to related artifacts,
- render a dedicated Event Storming diagram view without changing existing source-of-truth rules.

Source of truth remains unchanged:

- write-side domain events in event storage,
- read-side models in SQL,
- graph projection in Neo4j.

## 2. Current System Analysis

The current application already has the key architecture needed for this feature:

- Event-sourced domain flow with projection workers.
- Independent projection workers and checkpoints:
  - read-model projection,
  - knowledge graph projection,
  - vector projection.
- Startup wiring already supports multiple long-running workers.
- Knowledge graph layer already supports several DDD/Event Storming labels:
  - `BoundedContext`, `Aggregate`, `Command`, `DomainEvent`, `Policy`, `ReadModel`.
- Project template graph scaffolding already seeds DDD-style nodes and relations.

Conclusion: this feature should be implemented as an additional projection pipeline, not as a new source-of-truth subsystem.

## 3. Architecture Decision

Use a two-stage projection approach:

1. `event_storming_projection` worker listens to relevant domain changes and enqueues analysis jobs.
2. `event_storming_analysis` worker executes AI-assisted extraction and updates graph relationships.

This avoids calling AI in subscription ack path and keeps event processing reliable under load.

## 4. Data and Graph Model

### 4.1 SQL Tables

Add a queue/outbox style table:

- `event_storming_analysis_jobs`
  - `id`
  - `project_id`
  - `entity_type` (`task`, `note`, `specification`)
  - `entity_id`
  - `reason` (`initial`, `updated`, `deleted`, `reindex`)
  - `status` (`queued`, `running`, `done`, `failed`)
  - `attempt_count`
  - `next_attempt_at`
  - `last_error`
  - `dedupe_key`
  - timestamps

Optional audit table:

- `event_storming_analysis_runs`
  - model/extractor metadata
  - elapsed time
  - output summary
  - confidence aggregate
  - timestamps

### 4.2 Neo4j Nodes

Use (or continue using) these labels:

- `BoundedContext`
- `Aggregate`
- `Command`
- `DomainEvent`
- `Policy`
- `ReadModel`

### 4.3 Neo4j Relations

Component relations:

- `CONTAINS_AGGREGATE`
- `HANDLES_COMMAND`
- `EMITS_EVENT`
- `UPDATES_READ_MODEL`
- `TRIGGERS_POLICY`

Artifact-to-component relation:

- `RELATES_TO_ES`

Properties on `RELATES_TO_ES`:

- `confidence` (0..1)
- `inference_method` (`rule`, `ai_initial`, `ai_incremental`, `manual`)
- `review_status` (`candidate`, `approved`, `rejected`)
- `updated_at`
- `source_entity_type`
- `source_entity_id`
- optional evidence metadata (snippet hash/reference)

Note: one directed relationship is sufficient; Neo4j traversal supports both directions.

## 5. Event Processing Flow

### 5.1 Trigger Events

Process these events:

- Task create/update/archive/restore/delete family
- Note create/update/archive/restore/delete family
- Specification create/update/archive/restore/delete family

### 5.2 Projection Stage

For each relevant event:

1. Resolve `project_id`, `entity_type`, `entity_id`.
2. Upsert analysis job with dedupe semantics.
3. Acknowledge event quickly.

### 5.3 Analysis Stage

Worker loop:

1. Claim queued job.
2. Load latest entity state.
3. Run extraction (rules + optional AI).
4. Upsert Event Storming nodes.
5. Upsert `RELATES_TO_ES` links.
6. Remove stale links for that artifact.
7. Mark job done or failed with retry backoff.

## 6. Extraction Strategy

### 6.1 Deterministic Layer

Use explicit heuristics first:

- naming patterns (`CreateX`, `XCreated`, `WhenX`, `Policy`, etc.),
- explicit domain phrases in specifications/notes/tasks,
- status/label hints from artifacts.

### 6.2 AI Layer

Run strict JSON extraction with schema constraints:

- components
- relations
- confidence
- evidence references

### 6.3 Confidence and Review

Recommended thresholds:

- `< 0.55`: candidate only
- `0.55 - 0.80`: linked as candidate/review-required
- `> 0.80`: auto-approved (optional by flag)

## 7. API and UI Plan

Add Event Storming endpoints under project scope:

- `GET /api/projects/{project_id}/event-storming/overview`
- `GET /api/projects/{project_id}/event-storming/subgraph`
- `GET /api/projects/{project_id}/event-storming/entity-links`
- `GET /api/projects/{project_id}/event-storming/component-links`

UI additions:

- new Event Storming view/tab in Knowledge Graph page,
- diagram rendering (React Flow),
- click-through:
  - artifact -> linked Event Storming components,
  - component -> linked tasks/specifications/notes.

## 8. Reliability and Operations

Add metrics:

- `event_storming_jobs_created`
- `event_storming_jobs_processed`
- `event_storming_jobs_failed`
- `event_storming_inference_latency_ms`
- `event_storming_links_total`

Add feature flags:

- `EVENT_STORMING_ENABLED`
- `EVENT_STORMING_AI_ENABLED`
- canary lists by workspace/project

Use retry backoff and max attempts for analysis jobs to avoid infinite hot-loop failures.

## 9. Rollout Phases

### Phase 1: Foundation

- migrations for analysis job table(s),
- projection worker skeleton,
- settings/flags/metrics,
- no AI yet.

### Phase 2: Deterministic Linking

- rules-based extraction,
- graph link lifecycle (create/update/remove stale),
- basic API read endpoints.

### Phase 3: AI Incremental Enrichment

- strict JSON AI extractor,
- confidence + review status,
- retries and failure instrumentation.

### Phase 4: UI Event Storming Diagram

- dedicated Event Storming view,
- bidirectional drill-down and relation inspection.

### Phase 5: Hardening

- performance tuning,
- canary rollout,
- threshold calibration,
- review workflow improvements.

## 10. Risks and Mitigations

### Risk: AI latency or outages

Mitigation:

- asynchronous analysis worker,
- retries/backoff,
- fallback deterministic extraction.

### Risk: low-quality inferred links

Mitigation:

- confidence thresholds,
- review status,
- provenance metadata on links.

### Risk: projection drift over time

Mitigation:

- periodic reconciliation per project,
- stale-link cleanup by artifact scope,
- deterministic IDs for inferred components.

## 11. Final Recommendation

Proceed with a new Event Storming projection pipeline, using existing event-driven architecture and Neo4j graph model.

This approach:

- preserves current source-of-truth boundaries,
- adds high-value semantic navigation,
- supports incremental refresh on real artifact changes,
- enables a dedicated Event Storming diagram view with bidirectional traceability.
