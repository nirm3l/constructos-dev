from __future__ import annotations


def test_parse_model_list_result_keeps_unique_models_and_default():
    from features.agents import model_registry

    models, default_model = model_registry._parse_model_list_result(
        {
            "data": [
                {"model": "gpt-5", "isDefault": True},
                {"model": "o3", "isDefault": False},
                {"id": "gpt-5-mini", "isDefault": False},
                {"model": "GPT-5", "isDefault": False},
            ]
        }
    )

    assert models == ["gpt-5", "o3", "gpt-5-mini"]
    assert default_model == "gpt-5"


def test_list_available_codex_models_uses_cache(monkeypatch):
    from features.agents import model_registry

    calls = {"count": 0}

    def fake_discover() -> tuple[list[str], str]:
        calls["count"] += 1
        return ["gpt-5", "o3"], "gpt-5"

    monkeypatch.setattr(model_registry, "_discover_models_uncached", fake_discover)
    monkeypatch.setattr(model_registry, "_CACHE_MODELS", [])
    monkeypatch.setattr(model_registry, "_CACHE_DEFAULT_MODEL", "")
    monkeypatch.setattr(model_registry, "_CACHE_EXPIRES_AT", 0.0)

    first_models, first_default = model_registry.list_available_codex_models()
    second_models, second_default = model_registry.list_available_codex_models()

    assert first_models == ["gpt-5", "o3"]
    assert second_models == ["gpt-5", "o3"]
    assert first_default == "gpt-5"
    assert second_default == "gpt-5"
    assert calls["count"] == 1


def test_append_agent_chat_models_deduplicates_case_insensitively():
    from features.bootstrap import read_models

    merged = read_models._append_agent_chat_models(
        ["gpt-5"],
        ["o3", "GPT-5", "gpt-5-mini"],
    )

    assert merged == ["gpt-5", "o3", "gpt-5-mini"]
