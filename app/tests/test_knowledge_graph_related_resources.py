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
                {"entity_type": "Task", "entity_id": "task-c", "title": "Task C"},
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
        assignee_id = _Column("task.assignee_id")
        assigned_agent_code = _Column("task.assigned_agent_code")
        labels = _Column("task.labels")
        status = _Column("task.status")
        execution_triggers = _Column("task.execution_triggers")
        task_relationships = _Column("task.task_relationships")
        project_id = _Column("task.project_id")
        is_deleted = _Column("task.is_deleted")

    class _ProjectMemberStub:
        user_id = _Column("project_member.user_id")
        role = _Column("project_member.role")
        project_id = _Column("project_member.project_id")

    class _ProjectPluginConfigStub:
        config_json = _Column("project_plugin_config.config_json")
        project_id = _Column("project_plugin_config.project_id")
        plugin_key = _Column("project_plugin_config.plugin_key")
        enabled = _Column("project_plugin_config.enabled")
        is_deleted = _Column("project_plugin_config.is_deleted")

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

        def first(self):
            return None

        def all(self):
            if self.mode == "task_deps":
                return [
                    (
                        "task-b",
                        "[]",
                        json.dumps(
                            [
                                {
                                    "kind": "depends_on",
                                    "task_ids": ["task-a"],
                                    "match_mode": "all",
                                    "statuses": ["Done"],
                                }
                            ]
                        ),
                    ),
                    (
                        "task-c",
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
                        "[]",
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
    monkeypatch.setattr(models_module, "ProjectMember", _ProjectMemberStub)
    monkeypatch.setattr(models_module, "ProjectPluginConfig", _ProjectPluginConfigStub)

    payload = kg.graph_get_project_subgraph("project-1", limit_nodes=32, limit_edges=160)

    assert payload["project_id"] == "project-1"
    dep_edges = [edge for edge in payload["edges"] if edge["relationship"] == "DEPENDS_ON_TASK_STATUS"]
    assert len(dep_edges) == 2
    assert {"source_entity_id": "task-a", "target_entity_id": "task-b", "relationship": "DEPENDS_ON_TASK_STATUS"} in dep_edges
    assert {"source_entity_id": "task-a", "target_entity_id": "task-c", "relationship": "DEPENDS_ON_TASK_STATUS"} in dep_edges


def test_graph_get_project_subgraph_includes_team_mode_structural_edges_before_kickoff(monkeypatch):
    monkeypatch.setattr(kg, "require_graph_available", lambda: None)

    def fake_run_graph_query(cypher: str, params: dict, write: bool = False):  # noqa: ARG001
        if "RETURN p.id AS project_id" in cypher:
            return [{"project_id": params["project_id"], "project_name": "Project Alpha"}]
        if "RETURN DISTINCT" in cypher and "head(labels(n)) AS entity_type" in cypher:
            return [
                {"entity_type": "Task", "entity_id": "task-dev", "title": "Developer task"},
                {"entity_type": "Task", "entity_id": "task-lead", "title": "Lead task"},
                {"entity_type": "Task", "entity_id": "task-qa", "title": "QA task"},
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
        assignee_id = _Column("task.assignee_id")
        assigned_agent_code = _Column("task.assigned_agent_code")
        labels = _Column("task.labels")
        status = _Column("task.status")
        execution_triggers = _Column("task.execution_triggers")
        task_relationships = _Column("task.task_relationships")
        project_id = _Column("task.project_id")
        is_deleted = _Column("task.is_deleted")

    class _ProjectMemberStub:
        user_id = _Column("project_member.user_id")
        role = _Column("project_member.role")
        project_id = _Column("project_member.project_id")

    class _ProjectPluginConfigStub:
        config_json = _Column("project_plugin_config.config_json")
        project_id = _Column("project_plugin_config.project_id")
        plugin_key = _Column("project_plugin_config.plugin_key")
        enabled = _Column("project_plugin_config.enabled")
        is_deleted = _Column("project_plugin_config.is_deleted")

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
            if self.mode == "task_roles":
                return [
                    ("task-dev", "user-dev", "dev-a", [], "Dev"),
                    ("task-lead", "user-lead", "lead-a", [], "Lead"),
                    ("task-qa", "user-qa", "qa-a", [], "QA"),
                ]
            if self.mode == "project_members":
                return [
                    ("user-dev", "Developer"),
                    ("user-lead", "Lead"),
                    ("user-qa", "QA"),
                ]
            if self.mode == "task_deps":
                return [
                    (
                        "task-dev",
                        "[]",
                        json.dumps(
                            [
                                {
                                    "kind": "delivers_to",
                                    "task_ids": ["task-lead"],
                                    "statuses": ["Lead"],
                                }
                            ]
                        ),
                    ),
                    (
                        "task-lead",
                        "[]",
                        json.dumps(
                            [
                                {
                                    "kind": "depends_on",
                                    "task_ids": ["task-dev", "task-qa"],
                                    "statuses": ["Blocked"],
                                }
                            ]
                        ),
                    ),
                    (
                        "task-qa",
                        "[]",
                        json.dumps(
                            [
                                {
                                    "kind": "hands_off_to",
                                    "task_ids": ["task-lead"],
                                    "statuses": ["QA"],
                                },
                                {
                                    "kind": "escalates_to",
                                    "task_ids": ["task-lead"],
                                    "statuses": ["Blocked"],
                                },
                            ]
                        ),
                    ),
                ]
            return []

        def first(self):
            if self.mode == "team_mode_config":
                return (
                    json.dumps(
                        {
                            "team": {
                                "agents": [
                                    {"id": "dev-a", "name": "Developer A", "authority_role": "Developer"},
                                    {"id": "lead-a", "name": "Lead A", "authority_role": "Lead"},
                                    {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                                ]
                            }
                        }
                    ),
                )
            return None

    class _FakeDB:
        def query(self, *columns):
            names = {getattr(column, "name", "") for column in columns}
            if "task.execution_triggers" in names:
                return _FakeQuery("task_deps")
            if "task.assigned_agent_code" in names:
                return _FakeQuery("task_roles")
            if "project_member.user_id" in names:
                return _FakeQuery("project_members")
            if "project_plugin_config.config_json" in names:
                return _FakeQuery("team_mode_config")
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
    monkeypatch.setattr(models_module, "ProjectMember", _ProjectMemberStub)
    monkeypatch.setattr(models_module, "ProjectPluginConfig", _ProjectPluginConfigStub)

    payload = kg.graph_get_project_subgraph("project-1", limit_nodes=32, limit_edges=160)

    edges = payload["edges"]
    assert any(
        edge["relationship"] == "TEAM_MODE_DELIVERS_TO"
        and edge["source_entity_id"] == "task-dev"
        and edge["target_entity_id"] == "task-lead"
        for edge in edges
    )
    assert any(
        edge["relationship"] == "TEAM_MODE_HANDS_OFF_TO"
        and edge["source_entity_id"] == "task-lead"
        and edge["target_entity_id"] == "task-qa"
        for edge in edges
    )
    assert any(
        edge["relationship"] == "TEAM_MODE_ESCALATES_TO"
        and edge["source_entity_id"] == "task-qa"
        and edge["target_entity_id"] == "task-lead"
        for edge in edges
    )


def test_graph_get_project_subgraph_includes_runtime_automation_request_edges(monkeypatch):
    monkeypatch.setattr(kg, "require_graph_available", lambda: None)

    def fake_run_graph_query(cypher: str, params: dict, write: bool = False):  # noqa: ARG001
        if "RETURN p.id AS project_id" in cypher:
            return [{"project_id": params["project_id"], "project_name": "Project Alpha"}]
        if "RETURN DISTINCT" in cypher and "head(labels(n)) AS entity_type" in cypher:
            return [
                {"entity_type": "Task", "entity_id": "task-lead", "title": "Lead task"},
                {"entity_type": "Task", "entity_id": "task-qa", "title": "QA task"},
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
        assignee_id = _Column("task.assignee_id")
        assigned_agent_code = _Column("task.assigned_agent_code")
        labels = _Column("task.labels")
        status = _Column("task.status")
        execution_triggers = _Column("task.execution_triggers")
        project_id = _Column("task.project_id")
        is_deleted = _Column("task.is_deleted")

    class _ProjectMemberStub:
        user_id = _Column("project_member.user_id")
        role = _Column("project_member.role")
        project_id = _Column("project_member.project_id")

    class _ProjectPluginConfigStub:
        config_json = _Column("project_plugin_config.config_json")
        project_id = _Column("project_plugin_config.project_id")
        plugin_key = _Column("project_plugin_config.plugin_key")
        enabled = _Column("project_plugin_config.enabled")
        is_deleted = _Column("project_plugin_config.is_deleted")

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
            if self.mode == "task_roles":
                return [
                    ("task-lead", "user-lead", "lead-a", [], "Lead"),
                    ("task-qa", "user-qa", "qa-a", [], "QA"),
                ]
            if self.mode == "project_members":
                return [("user-lead", "Lead"), ("user-qa", "QA")]
            if self.mode == "task_deps":
                return []
            return []

        def first(self):
            if self.mode == "team_mode_config":
                return (
                    json.dumps(
                        {
                            "team": {
                                "agents": [
                                    {"id": "lead-a", "name": "Lead A", "authority_role": "Lead"},
                                    {"id": "qa-a", "name": "QA A", "authority_role": "QA"},
                                ]
                            }
                        }
                    ),
                )
            return None

    class _FakeDB:
        def query(self, *columns):
            names = {getattr(column, "name", "") for column in columns}
            if "task.execution_triggers" in names:
                return _FakeQuery("task_deps")
            if "task.assigned_agent_code" in names:
                return _FakeQuery("task_roles")
            if "project_member.user_id" in names:
                return _FakeQuery("project_members")
            if "project_plugin_config.config_json" in names:
                return _FakeQuery("team_mode_config")
            return _FakeQuery("comments")

    class _FakeSessionLocal:
        def __enter__(self):
            return _FakeDB()

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    def fake_rebuild_state(_db, aggregate_type: str, aggregate_id: str):  # noqa: ANN001
        assert aggregate_type == "Task"
        if aggregate_id == "task-qa":
            return (
                {
                    "last_requested_source": "lead_handoff",
                    "last_requested_source_task_id": "task-lead",
                },
                1,
            )
        return ({}, 1)

    import shared.eventing as eventing_module
    import shared.models as models_module

    monkeypatch.setattr(models_module, "SessionLocal", _FakeSessionLocal)
    monkeypatch.setattr(models_module, "Task", _TaskStub)
    monkeypatch.setattr(models_module, "TaskComment", _TaskCommentStub)
    monkeypatch.setattr(models_module, "ProjectMember", _ProjectMemberStub)
    monkeypatch.setattr(models_module, "ProjectPluginConfig", _ProjectPluginConfigStub)
    monkeypatch.setattr(eventing_module, "rebuild_state", fake_rebuild_state)

    payload = kg.graph_get_project_subgraph("project-1", limit_nodes=32, limit_edges=160)

    assert any(
        edge["relationship"] == "TEAM_MODE_RUNTIME_HANDOFF"
        and edge["source_entity_id"] == "task-lead"
        and edge["target_entity_id"] == "task-qa"
        for edge in payload["edges"]
    )
