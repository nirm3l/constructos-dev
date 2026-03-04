from __future__ import annotations

from typing import Any, Callable

from plugins.registry import list_workflow_plugins


def classify_project_delivery_context(
    *,
    project_description: str,
    project_external_refs: Any,
    project_rules: list[Any],
    parse_json_list: Callable[[Any], list[dict[str, Any]]],
    allow_llm: bool = True,
) -> dict[str, Any]:
    for plugin in list_workflow_plugins():
        fn = getattr(plugin, "classify_project_context_signals", None)
        if not callable(fn):
            continue
        raw = fn(
            project_description=project_description,
            project_external_refs=project_external_refs,
            project_rules=project_rules,
            parse_json_list=parse_json_list,
            allow_llm=allow_llm,
        )
        if not isinstance(raw, dict):
            continue
        if any(key in raw for key in ("has_repo_context", "has_github_context", "repo_reason", "github_reason")):
            return {
                "has_repo_context": bool(raw.get("has_repo_context")),
                "has_github_context": bool(raw.get("has_github_context")),
                "repo_reason": str(raw.get("repo_reason") or ""),
                "github_reason": str(raw.get("github_reason") or ""),
            }
    return {
        "has_repo_context": False,
        "has_github_context": False,
        "repo_reason": "No delivery context classifier available.",
        "github_reason": "No delivery context classifier available.",
    }

