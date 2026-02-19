from __future__ import annotations

from shared.knowledge_graph import (
    _template_alignment_score,
    _template_query_terms,
)


def test_template_alignment_prefers_ddd_domain_entities():
    aggregate_score = _template_alignment_score(
        template_key="ddd_product_build",
        entity_type="Aggregate",
        source_type="specification.body",
        graph_path=["Project", "CONTAINS_AGGREGATE", "Aggregate"],
    )
    note_score = _template_alignment_score(
        template_key="ddd_product_build",
        entity_type="Note",
        source_type="note.body",
        graph_path=["Project", "ABOUT", "Note"],
    )
    assert aggregate_score > note_score
    assert aggregate_score >= 0.9


def test_template_alignment_prefers_mobile_game_domain_entities():
    deploy_score = _template_alignment_score(
        template_key="mobile_browser_game_development",
        entity_type="DeploymentTarget",
        source_type="specification.body",
        graph_path=["ReleasePipeline", "DEPLOYS_TO", "DeploymentTarget"],
    )
    note_score = _template_alignment_score(
        template_key="mobile_browser_game_development",
        entity_type="Note",
        source_type="note.body",
        graph_path=["Project", "ABOUT", "Note"],
    )
    assert deploy_score > note_score
    assert deploy_score >= 0.9


def test_template_alignment_still_prioritizes_project_rule_for_ddd():
    rule_score = _template_alignment_score(
        template_key="ddd_product_build",
        entity_type="ProjectRule",
        source_type="project_rule.body",
        graph_path=["ProjectRule"],
    )
    note_score = _template_alignment_score(
        template_key="ddd_product_build",
        entity_type="Note",
        source_type="note.body",
        graph_path=["Project", "ABOUT", "Note"],
    )
    assert rule_score > note_score


def test_template_alignment_has_neutral_fallback_for_unknown_template():
    score = _template_alignment_score(
        template_key="unknown-template",
        entity_type="Task",
        source_type="task.description",
        graph_path=["Task"],
    )
    assert score == 0.5


def test_template_query_terms_available_for_supported_templates():
    ddd_terms = _template_query_terms("ddd")
    mobile_terms = _template_query_terms("mobile-game")
    assert "aggregate" in ddd_terms
    assert "docker compose" in mobile_terms
