from __future__ import annotations

from shared.knowledge_graph import (
    _starter_alignment_score,
    _starter_query_terms,
)


def test_starter_alignment_prefers_ddd_domain_entities():
    aggregate_score = _starter_alignment_score(
        starter_key="ddd_system",
        entity_type="Aggregate",
        source_type="specification.body",
        graph_path=["Project", "CONTAINS_AGGREGATE", "Aggregate"],
    )
    note_score = _starter_alignment_score(
        starter_key="ddd_system",
        entity_type="Note",
        source_type="note.body",
        graph_path=["Project", "ABOUT", "Note"],
    )
    assert aggregate_score > note_score
    assert aggregate_score >= 0.9


def test_starter_alignment_prefers_web_game_entities():
    deploy_score = _starter_alignment_score(
        starter_key="web_game",
        facet_keys=["mobile_first"],
        entity_type="DeploymentTarget",
        source_type="specification.body",
        graph_path=["ReleasePipeline", "DEPLOYS_TO", "DeploymentTarget"],
    )
    note_score = _starter_alignment_score(
        starter_key="web_game",
        facet_keys=["mobile_first"],
        entity_type="Note",
        source_type="note.body",
        graph_path=["Project", "ABOUT", "Note"],
    )
    assert deploy_score > note_score
    assert deploy_score >= 0.9


def test_starter_alignment_has_neutral_fallback_for_unknown_starter():
    score = _starter_alignment_score(
        starter_key="unknown-starter",
        entity_type="Task",
        source_type="task.description",
        graph_path=["Task"],
    )
    assert score == 0.5


def test_starter_query_terms_include_primary_and_facet_hints():
    terms = _starter_query_terms("web_game", facet_keys=["ddd_system"])
    assert "docker compose" in terms
    assert "aggregate" in terms
