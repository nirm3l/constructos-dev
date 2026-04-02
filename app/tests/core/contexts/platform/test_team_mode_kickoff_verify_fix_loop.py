from __future__ import annotations

from plugins.team_mode.api_kickoff import _run_kickoff_verify_fix_loop


def test_kickoff_verify_fix_loop_confirms_dispatch_when_developer_active() -> None:
    pump_calls: list[int] = []

    def _pump(limit: int) -> None:
        pump_calls.append(int(limit))

    def _collect() -> dict[str, object]:
        return {
            "developer_task_ids": ["dev-1"],
            "developer_active_task_ids": ["dev-1"],
            "developer_idle_task_ids": [],
            "developer_dispatch_confirmed": True,
            "usage_summary": {
                "provider": "codex",
                "model": "gpt-5",
                "reasoning_effort": "high",
            },
        }

    result = _run_kickoff_verify_fix_loop(
        max_attempts=3,
        queue_depth=2,
        pump_runner=_pump,
        collect_state=_collect,
    )

    assert result["ok"] is True
    assert result["developer_dispatch_confirmed"] is True
    assert result["blocked_reason"] is None
    usage_summary = result.get("usage_summary") or {}
    assert usage_summary.get("provider") == "codex"
    assert usage_summary.get("model") == "gpt-5"
    assert usage_summary.get("reasoning_effort") == "high"
    assert len(result["attempts"]) == 1
    assert pump_calls == [2]


def test_kickoff_verify_fix_loop_fails_with_explicit_reason_when_dispatch_not_confirmed() -> None:
    pump_calls: list[int] = []

    def _pump(limit: int) -> None:
        pump_calls.append(int(limit))

    def _collect() -> dict[str, object]:
        return {
            "developer_task_ids": ["dev-1"],
            "developer_active_task_ids": [],
            "developer_idle_task_ids": ["dev-1"],
            "developer_dispatch_confirmed": False,
            "usage_summary": {},
        }

    result = _run_kickoff_verify_fix_loop(
        max_attempts=3,
        queue_depth=1,
        pump_runner=_pump,
        collect_state=_collect,
    )

    assert result["ok"] is False
    assert result["developer_dispatch_confirmed"] is False
    assert result["blocked_reason_code"] == "developer_dispatch_not_confirmed"
    assert isinstance(result["blocked_reason"], str) and result["blocked_reason"]
    assert len(result["attempts"]) == 3
    assert pump_calls == [1, 1, 1]


def test_kickoff_verify_fix_loop_accepts_no_developer_targets() -> None:
    pump_calls: list[int] = []

    def _pump(limit: int) -> None:
        pump_calls.append(int(limit))

    def _collect() -> dict[str, object]:
        return {
            "developer_task_ids": [],
            "developer_active_task_ids": [],
            "developer_idle_task_ids": [],
            "developer_dispatch_confirmed": False,
            "usage_summary": {},
        }

    result = _run_kickoff_verify_fix_loop(
        max_attempts=2,
        queue_depth=0,
        pump_runner=_pump,
        collect_state=_collect,
    )

    assert result["ok"] is True
    assert result["developer_dispatch_confirmed"] is True
    assert result["attempts"][0]["runner_status"] == "skipped"
    assert pump_calls == []
