# 16 Chat History Persistence + Knowledge Indexing Plan

Date: 2026-02-23  
Status: In Progress

## 1) Goal

Move chat history from browser-only storage to backend persistence using the existing CQRS + event-sourcing architecture, and make chat indexing optional per project for:
- vector search,
- knowledge graph relations,
- or both.

This plan also treats chat attachments as first-class inputs for retrieval.

## 2) Why This Is Worth Doing

Primary product outcomes:
- Cross-device chat continuity for authenticated users.
- Auditable history with replayability and deterministic timelines.
- Better retrieval quality from decisions and rationale that usually stay in chat.
- Stronger project memory by linking chat with tasks, notes, specifications, and rules.

Expected ranking of impact:
1. `VECTOR_ONLY` mode gives the fastest retrieval benefit from chat text.
2. `KG_AND_VECTOR` gives additional graph reasoning value when we need traceable relations and dependency navigation.

## 3) Current State (Repository Baseline)

- Frontend chat sessions are currently persisted in `localStorage` (`app/frontend/src/app/useCodexChatState.ts`).
- Chat API accepts `history` from the client and composes context on request (`app/features/agents/api.py`), but does not persist chat events as domain aggregates.
- Vector indexing exists for `Task`, `Note`, `Specification`, and `ProjectRule` (`app/shared/eventing_vector.py`, `app/shared/vector_store.py`).
- KG projection exists for core entities (`app/shared/eventing_graph.py`), but not for chat sessions/messages/attachments.

## 4) Target Capability Model

Project-level indexing policy (default safe):
- `chat_index_mode`: `OFF | VECTOR_ONLY | KG_AND_VECTOR` (default `OFF`).
- `chat_attachment_ingestion_mode`: `OFF | METADATA_ONLY | FULL_TEXT` (default `METADATA_ONLY`).
- Optional retention:
  - `chat_retention_days` nullable (`null` means keep until explicit delete/archive policy).

Principles:
- Persist all chat history server-side once users are authenticated.
- Keep browser storage only as short-lived cache/offline buffer, never source of truth.
- Run indexing asynchronously from the event stream.

## 5) Domain and Event Model

## 5.1 New aggregate

Add `ChatSessionAggregate` with `aggregate_type = "ChatSession"`.

State fields:
- `workspace_id`, `project_id`, `session_id`, `created_by`, `title`, `status`.
- Session-level metadata: selected MCP servers, Codex session id, last usage snapshot.

## 5.2 Commands

- `ChatSession.Start`
- `ChatSession.Rename`
- `ChatSession.Archive`
- `ChatMessage.AppendUser`
- `ChatMessage.AppendAssistant`
- `ChatMessage.UpdateAssistant` (stream finalization/patch)
- `ChatMessage.Delete` (soft delete)
- `ChatMessage.LinkResource` (task/note/spec/rule links)
- `ChatAttachment.LinkToMessage`
- `ChatAttachment.MarkExtracted`
- `Project.Patch` extension for chat indexing policy fields

## 5.3 Events

- `ChatSessionStarted`
- `ChatSessionRenamed`
- `ChatSessionArchived`
- `ChatMessageAppended`
- `ChatMessageUpdated`
- `ChatMessageDeleted`
- `ChatMessageResourceLinked`
- `ChatAttachmentLinked`
- `ChatAttachmentTextExtracted`
- `ChatAttachmentDeleted`
- `ProjectUpdated` payload extended with chat policy fields

Required metadata on every event:
- `actor_id`, `workspace_id`, `project_id`, `session_id`
- `command_id`, `correlation_id`, `causation_id`
- `message_id` when relevant

## 6) Read Models (Projection Database)

Add projection tables:
- `chat_sessions`
  - session metadata, active/archived flags, latest usage, timestamps.
- `chat_messages`
  - message role, content, token counts, attachment count, soft-delete flag.
- `chat_attachments`
  - attachment metadata + extraction status + checksum.
- `chat_message_resource_links`
  - deterministic links to `Task`, `Note`, `Specification`, `ProjectRule`.

Projection worker:
- Extend current projection flow to build these read models from `ChatSession` events.
- Preserve idempotency via event version checks and projection checkpoints.

## 7) API and Frontend Changes

## 7.1 API

Evolve agent chat endpoints:
- `POST /api/agents/chat`
- `POST /api/agents/chat/stream`

Behavior changes:
- Persist user message event before execution.
- Persist assistant output event after execution or stream finalization.
- Persist attachment link events for provided `attachment_refs`.
- Return authoritative `session_id`, `message_id`, `codex_session_id`.

Add read/query endpoints:
- `GET /api/chat/sessions?workspace_id=...&project_id=...`
- `GET /api/chat/sessions/{session_id}/messages`
- `POST /api/chat/sessions/{session_id}/archive`
- `POST /api/chat/sessions/import-local` (one-time migration helper)

## 7.2 Frontend

Replace `localStorage` as source of truth in `useCodexChatState`:
- Fetch sessions/messages from new chat read APIs.
- Keep local cache only for optimistic buffering and offline failure fallback.
- Keep existing UX semantics (active session, create/delete session, clear history) with backend commands.

## 8) Vector Search Integration

Extend vector ingestion to include chat entities:
- Add vector indexing support for `ChatMessage` and extracted `ChatAttachment` text.
- Respect project policy:
  - `OFF`: skip indexing.
  - `VECTOR_ONLY`: index chat text and attachments.
  - `KG_AND_VECTOR`: same vector behavior plus KG projection.

Chunking and metadata:
- Reuse existing chunking limits (`<=500 tokens`) and split retry logic.
- Add metadata fields: `session_id`, `message_id`, `role`, `source_type`.

Search behavior:
- Include chat chunks in project knowledge search with source labeling.
- Apply ACL/project filters before returning evidence.

## 9) Knowledge Graph Integration

Extend graph projection with chat nodes and edges:
- Nodes:
  - `ChatSession`
  - `ChatMessage`
  - `ChatAttachment`
- Core edges:
  - `ChatSession -[:IN_PROJECT]-> Project`
  - `ChatSession -[:HAS_MESSAGE]-> ChatMessage`
  - `ChatMessage -[:HAS_ATTACHMENT]-> ChatAttachment`
  - `ChatMessage -[:MENTIONS|CREATED]-> Task/Note/Specification/ProjectRule`
  - `Task/Note/Specification/ProjectRule -[:DISCUSSED_IN]-> ChatSession`

Deterministic linking for "same conversation created task + note":
- When tool execution creates entities, emit `ChatMessageResourceLinked` with explicit IDs.
- Projector creates direct edges from that message to each created entity.
- Optionally create `RELATED_TO` edge between created entities when both are linked to same message.

## 10) Attachment Handling Plan

Keep binary storage in object/file store and persist metadata in events/read models.

Pipeline per attachment:
1. Link attachment to message (`ChatAttachmentLinked`).
2. Run extraction worker (text/PDF/DOCX/OCR by policy).
3. Emit extraction event with checksum + extraction status.
4. Feed extracted text to vector/KG pipelines based on project policy.

Security and governance:
- MIME allowlist + size limits.
- Antivirus scan hook before extraction/indexing.
- PII redaction before vector/KG ingestion.
- Permission-aware retrieval for all attachment-derived evidence.

## 11) Rollout Phases

## Phase 0: Contracts and Schema
- Add chat policy fields to project contracts/domain/serialization.
- Add chat aggregate/domain/contracts.
- Add DB bootstrap/migration support for chat read-model tables.

## Phase 1: Write Path Persistence
- Persist chat events from `/api/agents/chat` and `/api/agents/chat/stream`.
- Keep current request compatibility (`history` accepted), but backend becomes authoritative.

## Phase 2: Read APIs + Frontend Cutover
- Implement chat session/message query endpoints.
- Move frontend state to backend APIs with local cache fallback.
- Add one-time import endpoint from local browser payload.

## Phase 3: Vector Indexing for Chat
- Extend `eventing_vector.py` and `vector_store.py` for chat entities.
- Enforce `chat_index_mode`.
- Add project-scoped backfill job for historical chat events.

## Phase 4: KG Projection for Chat
- Extend `eventing_graph.py` for chat nodes and relations.
- Add deterministic resource link projection.
- Add graph queries that include chat trails in context packs.

## Phase 5: Attachment Extraction and Hardening
- Implement extraction worker + OCR path.
- Add retention/deindex jobs for policy changes (`ON -> OFF`) and deletions.
- Add observability and SLO dashboards.

## 12) Policy Transition Rules

- `OFF -> VECTOR_ONLY` or `OFF -> KG_AND_VECTOR`:
  - start async backfill from `ChatSession` event streams for that project.
- `VECTOR_ONLY -> KG_AND_VECTOR`:
  - keep vector index, add KG projection backfill.
- `KG_AND_VECTOR -> VECTOR_ONLY`:
  - stop KG updates for chat, optionally keep historical graph edges or soft-delete by policy.
- `ANY -> OFF`:
  - stop new indexing and run deindex job (soft or hard delete depending on retention policy).

## 13) Observability and Quality Gates

Add metrics:
- `chat_events_persisted_total`
- `chat_projection_lag_commits`
- `chat_vector_chunks_indexed_total`
- `chat_kg_links_created_total`
- `chat_attachment_extract_failures_total`
- `chat_policy_backfill_jobs_total`

Acceptance criteria:
- Chat survives reload/logout/device change.
- Chat event replay rebuilds the same session/message state.
- Policy toggle only affects selected project.
- Search includes chat evidence only when policy allows.
- KG shows chat-to-resource links for tool-created entities from the same conversation.

## 14) Risks and Mitigations

- Increased storage and token cost:
  - Mitigation: retention windows, chunk caps, indexing policy defaults to `OFF`.
- Privacy leakage through indexing:
  - Mitigation: opt-in policy, redaction, ACL filters, explicit attachment mode.
- Projection drift:
  - Mitigation: single event source, checkpoint-based catch-up, replay tests.

## 15) Concrete File-Level Backlog

Write side:
- `app/features/agents/api.py`
- `app/shared/contracts.py`
- New module: `app/features/chat/` (`domain.py`, `command_handlers.py`, `application.py`, `api.py`)

Read side and bootstrap:

## 16) Implementation Progress (2026-02-23)

- Done:
  - Chat persistence write path implemented for `/api/agents/chat` and `/api/agents/chat/stream`.
  - Chat read models and query endpoints implemented (`chat_sessions`, `chat_messages`, `chat_attachments`, `chat_message_resource_links`).
  - Project policy fields implemented (`chat_index_mode`, `chat_attachment_ingestion_mode`).
  - Vector indexing now supports `ChatMessage` and `ChatAttachment` with project policy gating.
  - Knowledge graph projection now supports `ChatSession`, `ChatMessage`, `ChatAttachment`, and message-to-resource links.
  - Automatic chat-to-created-resource linking implemented via activity-log window detection after each chat run.
  - Chat attachment extraction snippets are persisted in chat attachment events for downstream retrieval use.
  - Policy transition sync implemented:
    - project chat policy updates now run chat-only vector sync/backfill/deindex,
    - project chat policy updates now run chat graph backfill or purge.
  - Retention/deindex strategy implemented via env switches:
    - `CHAT_VECTOR_RETENTION_MODE=purge|keep`,
    - `CHAT_GRAPH_RETENTION_MODE=purge|keep`.

- Remaining:
  - `import-local` endpoint for one-time browser localStorage migration (explicitly optional).
- `app/shared/models.py`
- `app/shared/serializers.py`
- `app/shared/bootstrap.py`
- `app/shared/eventing_rebuild.py`

Knowledge indexing:
- `app/shared/eventing_vector.py`
- `app/shared/vector_store.py`
- `app/shared/eventing_graph.py`
- `app/shared/knowledge_graph.py`

Project settings:
- `app/features/projects/domain.py`
- `app/features/projects/command_handlers.py`
- `app/features/projects/api.py`
- `app/shared/contracts.py` (`ProjectCreate`, `ProjectPatch`)

Frontend:
- `app/frontend/src/app/useCodexChatState.ts`
- `app/frontend/src/components/chat/CodexChatDrawer.tsx`
- `app/frontend/src/api.ts`

## 16) Recommended Delivery Order

1. Persist chat events + read models without changing retrieval behavior.
2. Switch frontend to server-backed history.
3. Enable `VECTOR_ONLY` as first indexing rollout.
4. Add KG chat links for projects that opt into `KG_AND_VECTOR`.
5. Harden attachment extraction, retention, and deindex workflows.
