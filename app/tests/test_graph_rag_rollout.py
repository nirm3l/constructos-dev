from __future__ import annotations


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
