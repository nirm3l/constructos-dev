from __future__ import annotations

import json

from shared.eventing_graph import _clean_props


def test_clean_props_keeps_scalar_and_scalar_lists():
    props = _clean_props(
        {
            "id": "ignore-me",
            "title": "Spec",
            "status": "Draft",
            "tags": ["frontend", "ux"],
            "custom_statuses": ["To do", "Done"],
            "archived": False,
            "order_index": 3,
        }
    )
    assert "id" not in props
    assert props["title"] == "Spec"
    assert props["status"] == "Draft"
    assert props["tags"] == ["frontend", "ux"]
    assert props["custom_statuses"] == ["To do", "Done"]
    assert props["archived"] is False
    assert props["order_index"] == 3


def test_clean_props_serializes_nested_values_for_neo4j():
    refs = [{"url": "https://example.com", "title": "Doc"}]
    attachments = [{"path": "/tmp/file.txt", "name": "file.txt"}]
    props = _clean_props(
        {
            "external_refs": refs,
            "attachment_refs": attachments,
            "metadata": {"source": "agent", "kind": "spec"},
            "mixed": ["ok", {"nested": True}],
        }
    )
    assert json.loads(props["external_refs"]) == refs
    assert json.loads(props["attachment_refs"]) == attachments
    assert json.loads(props["metadata"]) == {"source": "agent", "kind": "spec"}
    assert json.loads(props["mixed"]) == ["ok", {"nested": True}]
