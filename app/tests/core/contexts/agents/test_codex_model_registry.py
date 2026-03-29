from __future__ import annotations


def test_parse_execution_model_detects_opencode_style_provider_path():
    from features.agents.execution_provider import parse_execution_model

    provider, model = parse_execution_model("openai/gpt-5-nano")

    assert provider == "opencode"
    assert model == "openai/gpt-5-nano"


def test_parse_execution_model_keeps_opencode_prefixed_model_path():
    from features.agents.execution_provider import parse_execution_model

    provider, model = parse_execution_model("opencode/nemotron-3-super-free")

    assert provider == "opencode"
    assert model == "opencode/nemotron-3-super-free"


def test_parse_execution_model_supports_ui_display_format():
    from features.agents.execution_provider import parse_execution_model

    provider, model = parse_execution_model("OpenCode · opencode/gpt-5-nano")

    assert provider == "opencode"
    assert model == "opencode/gpt-5-nano"


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

    monkeypatch.setattr(model_registry, "_discover_codex_models_uncached", fake_discover)
    monkeypatch.setattr(model_registry, "_CACHE_CODEX_MODELS", [])
    monkeypatch.setattr(model_registry, "_CACHE_CODEX_DEFAULT_MODEL", "")
    monkeypatch.setattr(model_registry, "_CACHE_EXPIRES_AT", 0.0)

    first_models, first_default = model_registry.list_available_codex_models()
    second_models, second_default = model_registry.list_available_codex_models()

    assert first_models == ["gpt-5", "o3"]
    assert second_models == ["gpt-5", "o3"]
    assert first_default == "gpt-5"
    assert second_default == "gpt-5"
    assert calls["count"] == 1


def test_list_available_agent_models_combines_providers(monkeypatch):
    from features.agents import model_registry

    monkeypatch.setattr(model_registry, "list_available_codex_models", lambda force_refresh=False: (["gpt-5"], "gpt-5"))
    monkeypatch.setattr(model_registry, "list_available_claude_models", lambda: (["sonnet"], "sonnet"))
    monkeypatch.setattr(
        model_registry,
        "list_available_opencode_models",
        lambda force_refresh=False: (["opencode/gpt-5-nano"], "opencode/gpt-5-nano"),
    )

    models, default_model = model_registry.list_available_agent_models(force_refresh=True)

    assert models == ["codex:gpt-5", "claude:sonnet", "opencode:opencode/gpt-5-nano"]
    assert default_model == "codex:gpt-5"


def test_list_available_claude_models_uses_built_in_fallbacks(monkeypatch):
    from features.agents import model_registry

    monkeypatch.delenv("AGENT_CLAUDE_AVAILABLE_MODELS", raising=False)
    monkeypatch.setattr(model_registry, "agent_default_model_for_provider", lambda provider: "sonnet" if provider == "claude" else "")

    models, default_model = model_registry.list_available_claude_models()

    assert models == ["sonnet", "opus"]
    assert default_model == "sonnet"


def test_list_available_opencode_models_uses_env_fallback(monkeypatch):
    from features.agents import model_registry

    monkeypatch.setattr(model_registry, "_read_model_list_from_opencode", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setenv("AGENT_OPENCODE_AVAILABLE_MODELS", "opencode/gpt-5-nano,openai/gpt-5-mini,opencode/mimo-v2-pro-free")
    monkeypatch.setattr(model_registry, "agent_default_model_for_provider", lambda provider: "opencode/gpt-5-nano")
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_MODELS", [])
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_DEFAULT_MODEL", "")
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_EXPIRES_AT", 0.0)

    models, default_model = model_registry.list_available_opencode_models()

    assert models == ["opencode/gpt-5-nano", "opencode/mimo-v2-pro-free"]
    assert default_model == "opencode/gpt-5-nano"


def test_list_available_opencode_models_uses_cache(monkeypatch):
    from features.agents import model_registry

    calls = {"count": 0}

    def fake_discover() -> tuple[list[str], str]:
        calls["count"] += 1
        return ["opencode/gpt-5-nano"], "opencode/gpt-5-nano"

    monkeypatch.setattr(model_registry, "_discover_opencode_models_uncached", fake_discover)
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_MODELS", [])
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_DEFAULT_MODEL", "")
    monkeypatch.setattr(model_registry, "_CACHE_OPENCODE_EXPIRES_AT", 0.0)

    first_models, first_default = model_registry.list_available_opencode_models()
    second_models, second_default = model_registry.list_available_opencode_models()

    assert first_models == ["opencode/gpt-5-nano"]
    assert second_models == ["opencode/gpt-5-nano"]
    assert first_default == "opencode/gpt-5-nano"
    assert second_default == "opencode/gpt-5-nano"
    assert calls["count"] == 1


def test_append_agent_chat_models_deduplicates_case_insensitively():
    from features.bootstrap import read_models

    merged = read_models._append_agent_chat_models(
        ["gpt-5"],
        ["o3", "GPT-5", "gpt-5-mini"],
    )

    assert merged == ["gpt-5", "o3", "gpt-5-mini"]
