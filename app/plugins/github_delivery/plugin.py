from __future__ import annotations

from typing import Any

from .context_classifier import classify_project_context_signals as classify_github_delivery_context_signals


class GithubDeliveryPlugin:
    key = "github_delivery"

    def check_scope(self) -> str | None:
        return None

    def default_required_checks(self) -> list[str]:
        return []

    def check_descriptions(self) -> dict[str, str]:
        return {}

    def default_plugin_policy_patch(self) -> dict[str, Any]:
        return {}

    def evaluate_checks(self, _ctx, **_kwargs: Any) -> dict[str, Any]:
        return {"scope": "github_delivery", "checks": [], "required_failed": []}

    def service_is_delivery_active(self, *, skill_keys: set[str]) -> bool:
        normalized = {str(item or "").strip().lower() for item in (skill_keys or set()) if str(item or "").strip()}
        return self.key in normalized

    def skill_dependencies(self) -> dict[str, tuple[str, ...]]:
        return {}

    def classify_project_context_signals(
        self,
        *,
        project_description: str,
        project_external_refs: Any,
        project_rules: list[Any],
        parse_json_list: Any,
        allow_llm: bool = True,
    ) -> dict[str, Any]:
        return classify_github_delivery_context_signals(
            project_description=project_description,
            project_external_refs=project_external_refs,
            project_rules=project_rules,
            parse_json_list=parse_json_list,
            allow_llm=allow_llm,
        )
