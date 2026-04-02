from features.agents.executor import AutomationOutcome, build_automation_usage_metadata


def test_build_automation_usage_metadata_includes_provider_model_and_skill_trace():
    outcome = AutomationOutcome(
        action="comment",
        summary="Done",
        comment=None,
        execution_outcome_contract={},
        usage={
            "input_tokens": 120,
            "cached_input_tokens": 40,
            "output_tokens": 30,
            "execution_provider": "codex",
            "execution_model": "gpt-5",
            "reasoning_effort": "high",
            "cost_usd": 0.0123,
            "project_skill_trace": [
                {
                    "skill_key": "skill.codegen.react",
                    "name": "React Codegen",
                    "mode": "advisory",
                    "trust_level": "reviewed",
                    "reason": "Frontend changes requested",
                    "source_locator": "workspace://skills/react",
                }
            ],
        },
        codex_session_id=None,
        resume_attempted=False,
        resume_succeeded=False,
        resume_fallback_used=False,
    )
    payload = build_automation_usage_metadata(outcome)
    usage = payload.get("last_agent_usage")
    assert isinstance(usage, dict)
    assert usage.get("execution_provider") == "codex"
    assert usage.get("execution_model") == "gpt-5"
    assert usage.get("reasoning_effort") == "high"
    assert float(usage.get("cost_usd") or 0.0) == 0.0123
    assert usage.get("project_skill_trace_count") == 1
    skill_trace = usage.get("project_skill_trace")
    assert isinstance(skill_trace, list)
    assert len(skill_trace) == 1
    assert isinstance(skill_trace[0], dict)
    assert skill_trace[0].get("skill_key") == "skill.codegen.react"


def test_build_automation_usage_metadata_estimates_cost_from_rate_card(monkeypatch):
    monkeypatch.setenv(
        "AGENT_USAGE_COST_RATE_CARD_JSON",
        '{"codex":{"*":{"input_per_1k":0.01,"cached_input_per_1k":0.0025,"output_per_1k":0.03}}}',
    )
    from features.agents import executor as executor_module

    executor_module._load_usage_cost_rate_card.cache_clear()

    outcome = AutomationOutcome(
        action="comment",
        summary="Done",
        comment=None,
        execution_outcome_contract={},
        usage={
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "output_tokens": 500,
            "execution_provider": "codex",
            "execution_model": "gpt-5",
        },
        codex_session_id=None,
        resume_attempted=False,
        resume_succeeded=False,
        resume_fallback_used=False,
    )
    payload = build_automation_usage_metadata(outcome)
    usage = payload.get("last_agent_usage")
    assert isinstance(usage, dict)
    # (800/1000*0.01) + (200/1000*0.0025) + (500/1000*0.03) = 0.0235
    assert float(usage.get("cost_usd") or 0.0) == 0.0235
    assert usage.get("cost_estimated_from_rate_card") is True
