import shared.eventing_event_storming as event_storming_module
from shared.eventing_event_storming import _event_storming_ai_prompt, _normalize_ai_extraction


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


def test_event_storming_prompt_applies_text_and_context_caps(monkeypatch):
    monkeypatch.setattr(event_storming_module, "EVENT_STORMING_PROMPT_SOURCE_MAX_CHARS", 30)
    monkeypatch.setattr(event_storming_module, "EVENT_STORMING_PROMPT_FRAME_MAX_CHARS", 20)
    monkeypatch.setattr(event_storming_module, "EVENT_STORMING_PROMPT_ENTITY_CONTEXT_MAX_ITEMS", 2)

    prompt = _event_storming_ai_prompt(
        entity_type="task",
        title="Example task",
        tags=["ddd"],
        text="X" * 120,
        entity_graph_context=[
            {"relation": "LINKED_TO", "neighbor_type": "Task", "neighbor_id": "1", "neighbor_title": "First"},
            {"relation": "LINKED_TO", "neighbor_type": "Task", "neighbor_id": "2", "neighbor_title": "Second"},
            {"relation": "LINKED_TO", "neighbor_type": "Task", "neighbor_id": "3", "neighbor_title": "Third"},
        ],
        project_component_snapshot={
            "components": [
                {"component_type": "aggregate", "component_title": "Orders"},
                {"component_type": "command", "component_title": "CreateOrder"},
            ]
        },
        context_frame_mode="full",
        context_frame_markdown="Y" * 80,
    )

    assert "X" * 31 not in prompt
    assert "Y" * 21 not in prompt
    assert "Third" not in prompt
