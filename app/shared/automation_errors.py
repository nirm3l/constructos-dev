from __future__ import annotations

import re
from typing import Any

_ERROR_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]\s*(.*)$")


def classify_automation_error(raw_error: Any) -> dict[str, Any]:
    text = str(raw_error or "").strip()
    if not text:
        return {
            "code": None,
            "message": "",
            "title": "Unknown automation failure",
            "recommended_doctor_action_id": None,
            "worktree_isolation_related": False,
        }

    normalized = text.lower()
    code: str | None = None
    message = text
    matched = _ERROR_CODE_RE.match(text)
    if matched:
        code = str(matched.group(1) or "").strip() or None
        message = str(matched.group(2) or "").strip() or text

    if code is None:
        if "repository root outside the task worktree" in normalized:
            code = "EXECUTOR_WORKTREE_ROOT_MUTATION"
        elif "requires a task-scoped role and worktree" in normalized:
            code = "EXECUTOR_WORKTREE_SCOPE_REQUIRED"
        elif "timed out" in normalized and "executor" in normalized:
            code = "EXECUTOR_TIMEOUT"
        elif "output is not valid json" in normalized or "execution_outcome_contract" in normalized:
            code = "EXECUTOR_OUTPUT_CONTRACT"
        else:
            code = "AUTOMATION_RUNTIME_FAILURE"

    title_by_code = {
        "EXECUTOR_WORKTREE_ROOT_MUTATION": "Task worktree isolation violation",
        "EXECUTOR_WORKTREE_SCOPE_REQUIRED": "Task worktree scope is required",
        "EXECUTOR_TIMEOUT": "Executor timed out",
        "EXECUTOR_OUTPUT_CONTRACT": "Executor output contract failure",
        "AUTOMATION_RUNTIME_FAILURE": "Automation runtime failure",
    }
    recommended_action_by_code = {
        "EXECUTOR_WORKTREE_ROOT_MUTATION": "executor-worktree-guard-diagnostics",
        "EXECUTOR_WORKTREE_SCOPE_REQUIRED": "executor-worktree-guard-diagnostics",
    }
    worktree_related = code in {
        "EXECUTOR_WORKTREE_ROOT_MUTATION",
        "EXECUTOR_WORKTREE_SCOPE_REQUIRED",
    }
    return {
        "code": code,
        "message": message,
        "title": title_by_code.get(code, "Automation runtime failure"),
        "recommended_doctor_action_id": recommended_action_by_code.get(code),
        "worktree_isolation_related": worktree_related,
    }

