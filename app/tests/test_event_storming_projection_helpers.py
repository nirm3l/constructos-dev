import shared.eventing_event_storming as event_storming_module
from shared.eventing_event_storming import (
    _build_snapshot_input_hash,
    _default_artifact_scope_classification,
    _event_storming_ai_prompt,
    _normalize_ai_extraction,
    _normalize_artifact_scope_classification,
    _prepare_snapshot_for_analysis,
)


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


def test_normalize_artifact_scope_classification_is_conservative():
    normalized = _normalize_artifact_scope_classification(
        {
            "artifact_scope": "DELIVERY_PROCESS",
            "confidence": 2,
            "reason": "Workflow-heavy artifact.",
            "domain_text": "should be kept",
        }
    )

    assert normalized["artifact_scope"] == "delivery_process"
    assert normalized["confidence"] == 1.0
    assert normalized["reason"] == "Workflow-heavy artifact."
    assert normalized["domain_text"] == "should be kept"

    fallback = _normalize_artifact_scope_classification({"artifact_scope": "nonsense"})
    assert fallback == _default_artifact_scope_classification()


def test_prepare_snapshot_for_analysis_reuses_domain_text(monkeypatch):
    monkeypatch.setattr(
        event_storming_module,
        "_classify_event_storming_artifact_scope",
        lambda **_: {
            "artifact_scope": "mixed",
            "confidence": 0.91,
            "reason": "Contains gameplay and delivery content.",
            "domain_text": "Player tank movement, projectile cooldown, and collision rules.",
        },
    )

    prepared, classification = _prepare_snapshot_for_analysis(
        project_id="project-1",
        entity_type="task",
        entity_id="task-1",
        snapshot={
            "workspace_id": "workspace-1",
            "title": "Implement and deploy feature",
            "text": "Long mixed text.",
            "tags": ["ddd"],
        },
    )

    assert classification["artifact_scope"] == "mixed"
    assert prepared is not None
    assert prepared["artifact_scope"] == "mixed"
    assert prepared["analysis_eligible"] is True
    assert prepared["text"] == "Player tank movement, projectile cooldown, and collision rules."


def test_prepare_snapshot_for_analysis_blocks_delivery_only_artifacts(monkeypatch):
    monkeypatch.setattr(
        event_storming_module,
        "_classify_event_storming_artifact_scope",
        lambda **_: {
            "artifact_scope": "delivery_process",
            "confidence": 0.97,
            "reason": "Only QA handoff and deploy workflow content.",
            "domain_text": "",
        },
    )

    prepared, _classification = _prepare_snapshot_for_analysis(
        project_id="project-1",
        entity_type="task",
        entity_id="task-2",
        snapshot={
            "workspace_id": "workspace-1",
            "title": "Coordinate release handoff",
            "text": "Prepare QA handoff and deployment evidence.",
            "tags": [],
        },
    )

    assert prepared is not None
    assert prepared["artifact_scope"] == "delivery_process"
    assert prepared["analysis_eligible"] is False
    assert prepared["text"] == ""


def test_build_snapshot_input_hash_includes_scope_and_extractor_version():
    base = {
        "title": "Example",
        "text": "Player tank aggregate and movement rules.",
        "tags": ["gameplay"],
        "artifact_scope": "product_domain",
    }
    product_hash = _build_snapshot_input_hash(
        project_id="project-1",
        entity_type="task",
        entity_id="task-1",
        snapshot=base,
    )
    delivery_hash = _build_snapshot_input_hash(
        project_id="project-1",
        entity_type="task",
        entity_id="task-1",
        snapshot={**base, "artifact_scope": "delivery_process", "text": ""},
    )

    assert product_hash != delivery_hash
