from __future__ import annotations

from types import SimpleNamespace

from plugins.github_delivery import context_classifier as context_classifier_module
from features.agents.service import AgentTaskService


def test_project_context_classifier_reuses_single_llm_call_for_repo_and_github(monkeypatch):
    context_classifier_module._PROJECT_CONTEXT_CLASSIFIER_CACHE.clear()
    calls = {"count": 0}

    def _fake_run_structured_codex_prompt(**kwargs):
        calls["count"] += 1
        return {
            "has_repo_context": True,
            "has_github_context": True,
            "repo_reason": "explicit repo url present",
            "github_reason": "explicit github host present",
        }

    monkeypatch.setattr(context_classifier_module, "run_structured_codex_prompt", _fake_run_structured_codex_prompt)

    rules = [
        SimpleNamespace(
            title="Repository Context",
            body='{"repository":"acme/demo-99","default_branch":"main","provider":"github"}',
        )
    ]

    has_repo = AgentTaskService._project_has_repo_context(
        project_description="Delivery project",
        project_external_refs='[{"url":"","title":"github repo acme/demo-99"}]',
        project_rules=rules,
    )
    has_github = AgentTaskService._project_has_github_context(
        project_description="Delivery project",
        project_external_refs='[{"url":"","title":"github repo acme/demo-99"}]',
        project_rules=rules,
    )

    assert has_repo is True
    assert has_github is True
    assert calls["count"] == 1


def test_project_context_classifier_skips_llm_when_no_signals(monkeypatch):
    context_classifier_module._PROJECT_CONTEXT_CLASSIFIER_CACHE.clear()

    def _should_not_call_llm(**kwargs):
        raise AssertionError("LLM should not be called without repository/github signals")

    monkeypatch.setattr(context_classifier_module, "run_structured_codex_prompt", _should_not_call_llm)

    rules = [SimpleNamespace(title="General Rule", body="No deployment details here.")]

    has_repo = AgentTaskService._project_has_repo_context(
        project_description="Simple planning project",
        project_external_refs="[]",
        project_rules=rules,
    )
    has_github = AgentTaskService._project_has_github_context(
        project_description="Simple planning project",
        project_external_refs="[]",
        project_rules=rules,
    )

    assert has_repo is False
    assert has_github is False


def test_project_context_classifier_can_skip_llm_for_ambiguous_signals(monkeypatch):
    context_classifier_module._PROJECT_CONTEXT_CLASSIFIER_CACHE.clear()

    def _should_not_call_llm(**kwargs):
        raise AssertionError("LLM should be skipped when allow_llm=False")

    monkeypatch.setattr(context_classifier_module, "run_structured_codex_prompt", _should_not_call_llm)

    rules = [SimpleNamespace(title="Repo hint", body="Repository and branch process should be followed.")]

    has_repo = AgentTaskService._project_has_repo_context(
        project_description="Project follows git repository workflow with branches and commits.",
        project_external_refs="[]",
        project_rules=rules,
        allow_llm=False,
    )
    has_github = AgentTaskService._project_has_github_context(
        project_description="Project follows GitHub workflow process.",
        project_external_refs="[]",
        project_rules=rules,
        allow_llm=False,
    )

    assert has_repo is False
    assert has_github is False
