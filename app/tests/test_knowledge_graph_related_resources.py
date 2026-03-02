import json

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


def test_graph_get_project_subgraph_includes_task_status_dependencies(monkeypatch):
    monkeypatch.setattr(kg, "require_graph_available", lambda: None)

    def fake_run_graph_query(cypher: str, params: dict, write: bool = False):  # noqa: ARG001
        if "RETURN p.id AS project_id" in cypher:
            return [{"project_id": params["project_id"], "project_name": "Project Alpha"}]
        if "RETURN DISTINCT" in cypher and "head(labels(n)) AS entity_type" in cypher:
            return [
                {"entity_type": "Task", "entity_id": "task-a", "title": "Task A"},
                {"entity_type": "Task", "entity_id": "task-b", "title": "Task B"},
                {"entity_type": "Note", "entity_id": "note-1", "title": "Note 1"},
            ]
        if "MATCH (t:Task)-[r:COMMENTED_BY]->(u:User)" in cypher:
            return []
        if "MATCH (a)-[r]-(b)" in cypher:
            return []
        raise AssertionError(f"Unexpected graph query: {cypher}")

    monkeypatch.setattr(kg, "run_graph_query", fake_run_graph_query)

    class _Column:
        def __init__(self, name: str):
            self.name = name

        def in_(self, _values):  # noqa: ANN001
            return ("in", self.name)

        def is_(self, _value):  # noqa: ANN001
            return ("is", self.name)

        def __eq__(self, _other):  # noqa: ANN001
            return ("eq", self.name)

        def desc(self):
            return ("desc", self.name)

    class _TaskStub:
        id = _Column("task.id")
        execution_triggers = _Column("task.execution_triggers")
        project_id = _Column("task.project_id")
        is_deleted = _Column("task.is_deleted")

    class _TaskCommentStub:
        task_id = _Column("task_comment.task_id")
        user_id = _Column("task_comment.user_id")
        body = _Column("task_comment.body")
        created_at = _Column("task_comment.created_at")
        id = _Column("task_comment.id")

    class _FakeQuery:
        def __init__(self, mode: str):
            self.mode = mode

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            if self.mode == "task_deps":
                return [
                    (
                        "task-b",
                        json.dumps(
                            [
                                {
                                    "kind": "status_change",
                                    "enabled": True,
                                    "scope": "external",
                                    "to_statuses": ["Done"],
                                    "selector": {"task_ids": ["task-a"]},
                                }
                            ]
                        ),
                    )
                ]
            return []

    class _FakeDB:
        def query(self, *columns):
            names = {getattr(column, "name", "") for column in columns}
            if "task.execution_triggers" in names:
                return _FakeQuery("task_deps")
            return _FakeQuery("comments")

    class _FakeSessionLocal:
        def __enter__(self):
            return _FakeDB()

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    import shared.models as models_module

    monkeypatch.setattr(models_module, "SessionLocal", _FakeSessionLocal)
    monkeypatch.setattr(models_module, "Task", _TaskStub)
    monkeypatch.setattr(models_module, "TaskComment", _TaskCommentStub)

    payload = kg.graph_get_project_subgraph("project-1", limit_nodes=32, limit_edges=160)

    assert payload["project_id"] == "project-1"
    dep_edges = [edge for edge in payload["edges"] if edge["relationship"] == "DEPENDS_ON_TASK_STATUS"]
    assert len(dep_edges) == 1
    assert dep_edges[0]["source_entity_id"] == "task-a"
    assert dep_edges[0]["target_entity_id"] == "task-b"
