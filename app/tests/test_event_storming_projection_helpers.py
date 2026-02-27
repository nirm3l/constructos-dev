from shared.eventing_event_storming import _normalize_ai_extraction


def test_normalize_ai_extraction_builds_components_and_relations():
    project_id = "proj-1"
    payload = {
        "components": [
            {"component_type": "bounded_context", "name": "Planning", "confidence": 0.9, "evidence": "bounded context"},
            {"component_type": "aggregate", "name": "Task", "confidence": 0.85, "evidence": "aggregate task"},
            {"component_type": "command", "name": "CreateTask", "confidence": 0.8, "evidence": "create task"},
        ],
        "relations": [
            {
                "source_component_type": "bounded_context",
                "source_name": "Planning",
                "relation": "CONTAINS_AGGREGATE",
                "target_component_type": "aggregate",
                "target_name": "Task",
                "confidence": 0.8,
                "evidence": "planning contains task",
            },
            {
                "source_component_type": "aggregate",
                "source_name": "Task",
                "relation": "HANDLES_COMMAND",
                "target_component_type": "command",
                "target_name": "CreateTask",
                "confidence": 0.75,
                "evidence": "task handles create",
            },
        ],
    }
    components, relations = _normalize_ai_extraction(project_id, payload)
    assert len(components) == 3
    assert len(relations) == 2
    assert any(item["relation"] == "CONTAINS_AGGREGATE" for item in relations)
    assert any(item["relation"] == "HANDLES_COMMAND" for item in relations)


def test_normalize_ai_extraction_dedupes_components_by_type_and_name():
    project_id = "proj-2"
    payload = {
        "components": [
            {"component_type": "policy", "name": "AuthPolicy", "confidence": 0.61, "evidence": "policy one"},
            {"component_type": "policy", "name": "authpolicy", "confidence": 0.88, "evidence": "policy two"},
        ],
        "relations": [],
    }
    components, relations = _normalize_ai_extraction(project_id, payload)
    assert len(components) == 1
    assert components[0]["component_type"] == "policy"
    assert components[0]["confidence"] == 0.88
    assert relations == []
