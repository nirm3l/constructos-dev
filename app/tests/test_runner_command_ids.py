from __future__ import annotations

from features.agents.runner import _derive_runner_command_id


def test_derive_runner_command_id_is_overflow_safe_and_deterministic() -> None:
    base = "runner-completion-project-refs"
    long_suffix = "project-12345678:0123456789abcdef0123456789abcdef01234567"

    first = _derive_runner_command_id(base, long_suffix)
    second = _derive_runner_command_id(base, long_suffix)
    different = _derive_runner_command_id(base, f"{long_suffix}:different")

    assert isinstance(first, str) and first
    assert len(first) <= 64
    assert first == second
    assert first != different


def test_derive_runner_command_id_handles_empty_parts() -> None:
    value = _derive_runner_command_id("tm-orch", "", None, "task-1")
    assert isinstance(value, str) and value
    assert len(value) <= 64
    assert "task-1" in value or ":" in value
