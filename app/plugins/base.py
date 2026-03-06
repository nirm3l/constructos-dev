from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PolicyEvaluationContext:
    project_id: str
    workspace_id: str
    event_storming_enabled: bool
    expected_event_storming_enabled: bool | None
    plugin_policy: dict[str, Any]
    plugin_policy_source: str
    tasks: list[dict[str, Any]]
    member_role_by_user_id: dict[str, str]
    notes_by_task: dict[str, list[Any]]
    comments_by_task: dict[str, list[Any]]

class WorkflowPlugin(Protocol):
    key: str

    def check_scope(self) -> str | None: ...

    def default_required_checks(self) -> list[str]: ...

    def check_descriptions(self) -> dict[str, str]: ...

    def default_plugin_policy_patch(self) -> dict[str, Any]: ...

    def evaluate_checks(self, ctx: PolicyEvaluationContext, **kwargs: Any) -> dict[str, Any]: ...
