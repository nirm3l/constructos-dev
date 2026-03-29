from features.agents import task_size_classifier


def test_task_size_pre_gate_returns_safe_unknown_on_classifier_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(task_size_classifier, "run_structured_codex_prompt", _raise)
    task_size_classifier._TASK_SIZE_CLASSIFIER_CACHE.clear()
    payload = task_size_classifier.classify_task_size_pre_gate(
        instruction="Implement tiny copy change in one file.",
        workspace_id="ws-1",
        project_id="project-1",
        session_id=None,
        actor_user_id="user-1",
    )
    assert payload["task_size"] == "unknown"
    assert payload["should_avoid_heavy_orchestration"] is False


def test_task_size_pre_gate_uses_structured_payload(monkeypatch):
    def _classify(*args, **kwargs):
        return {
            "task_size": "small",
            "should_avoid_heavy_orchestration": True,
            "reason": "Single-file, low-risk local change.",
        }

    monkeypatch.setattr(task_size_classifier, "run_structured_codex_prompt", _classify)
    task_size_classifier._TASK_SIZE_CLASSIFIER_CACHE.clear()
    payload = task_size_classifier.classify_task_size_pre_gate(
        instruction="Rename one label in project checks panel.",
        workspace_id="ws-1",
        project_id="project-1",
        session_id=None,
        actor_user_id="user-1",
    )
    assert payload["task_size"] == "small"
    assert payload["should_avoid_heavy_orchestration"] is True
    assert isinstance(payload["reason"], str) and payload["reason"]
