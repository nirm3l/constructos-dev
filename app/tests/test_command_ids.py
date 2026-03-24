from __future__ import annotations

from shared.command_ids import derive_child_command_id, derive_scoped_command_id


def test_derive_child_command_id_is_deterministic_and_overflow_safe() -> None:
    base = "x" * 64
    suffix = "very-long-child-suffix-for-overflow-checks"

    first = derive_child_command_id(base, suffix)
    second = derive_child_command_id(base, suffix)
    different = derive_child_command_id(base, f"{suffix}-changed")

    assert isinstance(first, str) and first
    assert len(first) <= 64
    assert first == second
    assert first != different


def test_derive_scoped_command_id_is_deterministic_and_overflow_safe() -> None:
    first = derive_scoped_command_id("runner", "project", "task", "x" * 80)
    second = derive_scoped_command_id("runner", "project", "task", "x" * 80)
    different = derive_scoped_command_id("runner", "project", "task", "y" * 80)

    assert isinstance(first, str) and first
    assert len(first) <= 64
    assert first == second
    assert first != different
