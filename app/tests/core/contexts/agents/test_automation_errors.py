from shared.automation_errors import classify_automation_error


def test_classify_automation_error_detects_worktree_root_mutation() -> None:
    payload = classify_automation_error(
        "Executor modified the repository root outside the task worktree. "
        "Task automation must only edit files inside the assigned task worktree and task branch."
    )
    assert payload.get("code") == "EXECUTOR_WORKTREE_ROOT_MUTATION"
    assert payload.get("recommended_doctor_action_id") == "executor-worktree-guard-diagnostics"
    assert payload.get("worktree_isolation_related") is True


def test_classify_automation_error_uses_explicit_error_prefix() -> None:
    payload = classify_automation_error(
        "[EXECUTOR_WORKTREE_SCOPE_REQUIRED] Executor refused repo-root execution: Team Mode task with Git Delivery requires a task-scoped role and worktree."
    )
    assert payload.get("code") == "EXECUTOR_WORKTREE_SCOPE_REQUIRED"
    assert payload.get("title") == "Task worktree scope is required"
    assert payload.get("recommended_doctor_action_id") == "executor-worktree-guard-diagnostics"

