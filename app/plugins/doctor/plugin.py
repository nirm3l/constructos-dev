from __future__ import annotations

from typing import Any

from plugins.base import PolicyEvaluationContext


class DoctorPlugin:
    key = "doctor"
    scope = "workspace"

    def check_scope(self) -> str | None:
        return None

    def default_required_checks(self) -> list[str]:
        return []

    def check_descriptions(self) -> dict[str, str]:
        return {}

    def default_plugin_policy_patch(self) -> dict[str, Any]:
        return {}

    def evaluate_checks(self, ctx: PolicyEvaluationContext, **kwargs: Any) -> dict[str, Any]:
        _ = (ctx, kwargs)
        return {"ok": True, "checks": {}}
