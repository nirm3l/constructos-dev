from __future__ import annotations

from types import SimpleNamespace


def test_embed_text_with_split_retry_handles_context_length(monkeypatch):
    from shared import vector_store

    def fake_embed(text: str, _model: str) -> list[float]:
        if vector_store.estimate_tokens(text) > 60:
            raise vector_store.EmbeddingContextLengthError("input length exceeds context length")
        return [0.01, 0.02, 0.03]

    monkeypatch.setattr(vector_store, "_ollama_embed_text", fake_embed)

    long_text = " ".join([f"token-{i}" for i in range(140)])
    embedded = vector_store._embed_text_with_split_retry(long_text, "nomic-embed-text")

    assert len(embedded) >= 2
    assert all(vector_store.estimate_tokens(chunk) <= 60 for chunk, _ in embedded)
    assert all(len(vector) == 3 for _, vector in embedded)


def test_graph_rag_canary_scope_controls_rollout(monkeypatch):
    from shared import knowledge_graph

    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_ENABLED", True)
    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_CANARY_PROJECT_IDS", {"project-canary"})
    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_CANARY_WORKSPACE_IDS", {"workspace-canary"})

    assert knowledge_graph.graph_rag_enabled_for_scope(project_id="project-canary", workspace_id="workspace-x") is True
    assert knowledge_graph.graph_rag_enabled_for_scope(project_id="project-x", workspace_id="workspace-canary") is True
    assert knowledge_graph.graph_rag_enabled_for_scope(project_id="project-x", workspace_id="workspace-x") is False


def test_graph_rag_scope_is_enabled_without_canary_lists(monkeypatch):
    from shared import knowledge_graph

    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_ENABLED", True)
    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_CANARY_PROJECT_IDS", set())
    monkeypatch.setattr(knowledge_graph, "GRAPH_RAG_CANARY_WORKSPACE_IDS", set())

    assert knowledge_graph.graph_rag_enabled_for_scope(project_id="any-project", workspace_id="any-workspace") is True


def test_chat_attachment_sources_follow_ingestion_mode():
    from shared import vector_store

    base_state = {
        "path": "workspace/w1/project/p1/file.txt",
        "name": "file.txt",
        "mime_type": "text/plain",
        "size_bytes": 128,
        "extracted_text": "Attachment extracted content.",
    }

    off_sources = vector_store._entity_state_sources(
        "ChatAttachment",
        {**base_state, "chat_attachment_ingestion_mode": "OFF"},
    )
    assert off_sources == []

    metadata_sources = vector_store._entity_state_sources(
        "ChatAttachment",
        {**base_state, "chat_attachment_ingestion_mode": "METADATA_ONLY"},
    )
    assert any(source_type == "chat_attachment.metadata" for source_type, _ in metadata_sources)
    assert not any(source_type == "chat_attachment.text" for source_type, _ in metadata_sources)

    full_text_sources = vector_store._entity_state_sources(
        "ChatAttachment",
        {**base_state, "chat_attachment_ingestion_mode": "FULL_TEXT"},
    )
    assert any(source_type == "chat_attachment.metadata" for source_type, _ in full_text_sources)
    assert any(source_type == "chat_attachment.text" for source_type, _ in full_text_sources)


def test_chunk_text_prefers_paragraph_boundaries_before_word_level_splitting():
    from shared import vector_store

    first_paragraph = " ".join([f"alpha-{index}" for index in range(18)])
    second_paragraph = " ".join([f"beta-{index}" for index in range(18)])

    chunks = vector_store.chunk_text(
        f"{first_paragraph}\n\n{second_paragraph}",
        max_tokens=32,
        overlap_ratio=0.12,
    )

    assert len(chunks) == 2
    assert chunks[0] == first_paragraph
    assert chunks[1] == second_paragraph


def test_distillation_candidates_only_include_large_supported_sources(monkeypatch):
    from shared import vector_store

    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_ENABLED", True)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MIN_TOKENS", 10)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MAX_SOURCE_TOKENS", 20)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MAX_SOURCES_PER_REQUEST", 8)

    candidates = vector_store._distillation_candidates(
        [
            ("task.title", "short title should not be distilled"),
            ("task.description", " ".join([f"desc-{index}" for index in range(14)])),
            ("note.body", " ".join([f"note-{index}" for index in range(16)])),
            ("chat_message.user", " ".join([f"msg-{index}" for index in range(18)])),
        ]
    )

    assert [item["source_type"] for item in candidates] == ["task.description", "note.body"]
    assert all(vector_store.estimate_tokens(item["text"]) <= 20 for item in candidates)


def test_distill_index_sources_batches_multiple_sources_in_one_request(monkeypatch):
    from shared import vector_store

    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_ENABLED", True)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MIN_TOKENS", 5)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MAX_SOURCE_TOKENS", 40)
    monkeypatch.setattr(vector_store, "VECTOR_INDEX_DISTILL_MAX_SOURCES_PER_REQUEST", 8)
    vector_store._VECTOR_DISTILLATION_CACHE.clear()

    calls = {"count": 0}

    def _fake_run_structured_agent_prompt(**kwargs):
        calls["count"] += 1
        payload = kwargs
        assert "vector-index-distillation" in str(payload.get("session_key") or "")
        return {
            "sources": [
                {
                    "source_type": "task.description",
                    "distilled_text": "Implement API contract and validation flow.",
                },
                {
                    "source_type": "chat_attachment.text",
                    "distilled_text": "Attachment describes deployment requirements and runtime health checks.",
                },
            ]
        }

    monkeypatch.setattr("features.agents.agent_mcp_adapter.run_structured_agent_prompt", _fake_run_structured_agent_prompt)

    distilled = vector_store._distill_index_sources(
        enabled=True,
        workspace_id="ws-1",
        project_id="project-1",
        entity_type="Task",
        entity_id="task-1",
        sources=[
            ("task.description", " ".join([f"desc-{index}" for index in range(12)])),
            ("chat_attachment.text", " ".join([f"attach-{index}" for index in range(12)])),
        ],
    )

    assert calls["count"] == 1
    assert distilled == [
        ("task.description.distilled", "Implement API contract and validation flow."),
        (
            "chat_attachment.text.distilled",
            "Attachment describes deployment requirements and runtime health checks.",
        ),
    ]


def test_search_project_knowledge_boosts_snippets_with_query_overlap(monkeypatch):
    from shared import knowledge_graph
    from shared import models as shared_models

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(knowledge_graph, "graph_enabled", lambda: False)
    monkeypatch.setattr(shared_models, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        knowledge_graph,
        "resolve_project_embedding_runtime",
        lambda db, project_id: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(knowledge_graph, "_load_project_template_binding", lambda project_id: None)
    monkeypatch.setattr(
        knowledge_graph,
        "search_project_chunks",
        lambda *args, **kwargs: [
            {
                "entity_type": "Note",
                "entity_id": "note-1",
                "source_type": "note.body",
                "snippet": "The secret number is 99.",
                "vector_similarity": 0.52,
                "source_updated_at": None,
            },
            {
                "entity_type": "Task",
                "entity_id": "task-1",
                "source_type": "task.description",
                "snippet": "Create Docker Compose service wiring and release checks.",
                "vector_similarity": 0.51,
                "source_updated_at": None,
            },
        ],
    )

    payload = knowledge_graph.search_project_knowledge(
        project_id="project-1",
        query="secret number",
        limit=5,
    )

    assert payload["items"]
    assert payload["items"][0]["entity_type"] == "Note"
    assert payload["items"][0]["entity_id"] == "note-1"
    assert payload["items"][0]["lexical_overlap"] > payload["items"][1]["lexical_overlap"]
