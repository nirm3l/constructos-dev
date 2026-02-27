from shared import knowledge_graph as kg


def test_graph_find_related_resources_uses_tokenized_matching_and_project_scope(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(kg, "require_graph_available", lambda: None)

    def fake_run_graph_query(cypher: str, params: dict, write: bool = False):  # noqa: ARG001
        captured["cypher"] = cypher
        captured["params"] = params
        return [
            {
                "entity_type": "Specification",
                "entity_id": "spec-1",
                "title": "MCP Demo Plan Board Specs",
                "score": 191.0,
                "token_hits": 6,
                "title_hits": 5,
                "matched_terms": ["mcp", "demo", "plan", "board", "specs", "kg"],
            }
        ]

    monkeypatch.setattr(kg, "run_graph_query", fake_run_graph_query)

    payload = kg.graph_find_related_resources(
        project_id="project-1",
        query="MCP Demo Plan Board Specs Notes KG",
        limit=12,
    )

    assert payload["project_id"] == "project-1"
    assert payload["query"] == "MCP Demo Plan Board Specs Notes KG"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["entity_type"] == "Specification"

    params = captured["params"]
    assert isinstance(params, dict)
    assert params["project_id"] == "project-1"
    assert params["q"] == "mcp demo plan board specs notes kg"
    assert params["tokens"] == ["mcp", "demo", "plan", "board", "specs", "notes", "kg"]
    assert params["limit"] == 12

    cypher = str(captured["cypher"])
    assert "EXISTS { MATCH (n)-[:IN_PROJECT]->(p) }" in cypher
    assert "matched_tokens" in cypher
    assert "title_hits" in cypher
    assert "phrase_score" in cypher


def test_graph_find_related_resources_returns_empty_for_blank_query(monkeypatch):
    monkeypatch.setattr(kg, "require_graph_available", lambda: None)

    def fail_run_graph_query(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("run_graph_query should not be called for blank query")

    monkeypatch.setattr(kg, "run_graph_query", fail_run_graph_query)

    payload = kg.graph_find_related_resources(project_id="project-1", query="   ")
    assert payload == {"project_id": "project-1", "query": "", "items": []}
