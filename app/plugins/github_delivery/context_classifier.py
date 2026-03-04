from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

_PROJECT_CONTEXT_CLASSIFIER_CACHE: dict[str, dict[str, Any]] = {}


def run_structured_codex_prompt(**kwargs):
    from features.agents.codex_mcp_adapter import run_structured_codex_prompt as _run

    return _run(**kwargs)


def classify_project_context_signals(
    *,
    project_description: str,
    project_external_refs: Any,
    project_rules: list[Any],
    parse_json_list: Callable[[Any], list[dict[str, Any]]],
    allow_llm: bool = True,
) -> dict[str, Any]:
    parsed_refs = parse_json_list(project_external_refs)
    normalized_refs = sorted(
        (
            {
                "url": str(ref.get("url") or "").strip(),
                "title": str(ref.get("title") or "").strip(),
            }
            for ref in parsed_refs
            if isinstance(ref, dict)
        ),
        key=lambda item: (item.get("url", "").lower(), item.get("title", "").lower()),
    )
    normalized_rules = sorted(
        (
            {
                "title": str(getattr(rule, "title", "") or "").strip(),
                "body": str(getattr(rule, "body", "") or "").strip(),
            }
            for rule in project_rules
        ),
        key=lambda item: (item.get("title", "").lower(), item.get("body", "").lower()),
    )
    description_blob = str(project_description or "").strip()
    rules_blob = "\n".join(
        f"{item.get('title') or ''}\n{item.get('body') or ''}" for item in normalized_rules
    ).strip()
    refs_blob = "\n".join(
        f"{item.get('url') or ''} {item.get('title') or ''}" for item in normalized_refs
    ).strip()
    combined_blob = f"{description_blob}\n{rules_blob}\n{refs_blob}".strip()
    lower_blob = combined_blob.lower()
    explicit_repo_markers = (
        "://github.com/",
        "://www.github.com/",
        "://gitlab.com/",
        "://bitbucket.org/",
        "file://",
        "/home/app/workspace/",
    )
    explicit_github_markers = (
        "://github.com/",
        "://www.github.com/",
        "github.com/",
        "www.github.com/",
    )
    has_explicit_repo = any(marker in lower_blob for marker in explicit_repo_markers) or (".git" in lower_blob)
    has_explicit_github = any(marker in lower_blob for marker in explicit_github_markers)
    if has_explicit_repo or has_explicit_github:
        return {
            "has_repo_context": bool(has_explicit_repo or has_explicit_github),
            "has_github_context": bool(has_explicit_github),
            "repo_reason": "Explicit repository marker found in project artifacts.",
            "github_reason": "Explicit GitHub marker found in project artifacts."
            if has_explicit_github
            else "Explicit Git marker found without GitHub-specific host.",
        }
    if not any(
        token in lower_blob
        for token in (
            "github",
            "gitlab",
            "bitbucket",
            "repository",
            "repo",
            "branch",
            "commit",
            "workspace",
            "file://",
            "/home/app/workspace/",
            ".git",
        )
    ):
        return {
            "has_repo_context": False,
            "has_github_context": False,
            "repo_reason": "No repository signals found in project artifacts.",
            "github_reason": "No GitHub signals found in project artifacts.",
        }
    if not allow_llm:
        return {
            "has_repo_context": False,
            "has_github_context": False,
            "repo_reason": "Ambiguous repository signals; LLM disabled for this pass.",
            "github_reason": "Ambiguous GitHub signals; LLM disabled for this pass.",
        }

    llm_payload = {
        "project_description": description_blob,
        "project_external_refs": normalized_refs[:40],
        "project_rules": [
            {
                "title": str(rule.get("title") or ""),
                "body": str(rule.get("body") or "")[:8000],
            }
            for rule in normalized_rules[:40]
        ],
        "decision_policy": {
            "repo_context_true_only_when": [
                "explicit repository context exists (local repo path, remote URL, repository identifier, or concrete branch/commit metadata tied to a repository)",
            ],
            "repo_context_false_when": [
                "generic process mentions of git/github/repository without concrete project-owned repository context",
            ],
            "github_context_true_only_when": [
                "explicit GitHub host/domain references are present (github.com/www.github.com)",
                "or explicit GitHub repository/PR/issue URL-like markers are present in project-owned content",
            ],
            "github_context_false_when": [
                "generic mentions of GitHub in process/skill text without explicit project-owned GitHub context",
            ],
        },
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "has_repo_context": {"type": "boolean"},
            "has_github_context": {"type": "boolean"},
            "repo_reason": {"type": "string"},
            "github_reason": {"type": "string"},
        },
        "required": ["has_repo_context", "has_github_context", "repo_reason", "github_reason"],
    }
    payload_hash = hashlib.sha256(
        json.dumps(llm_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    cache_key = f"project-context:{payload_hash}"
    cached = _PROJECT_CONTEXT_CLASSIFIER_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return {
            "has_repo_context": bool(cached.get("has_repo_context")),
            "has_github_context": bool(cached.get("has_github_context")),
            "repo_reason": str(cached.get("repo_reason") or ""),
            "github_reason": str(cached.get("github_reason") or ""),
        }
    prompt = (
        "Classify project repository context and GitHub context.\n"
        "Return JSON matching schema.\n"
        "Set has_repo_context=true only when concrete repository metadata exists in project-owned content.\n"
        "Set has_github_context=true only for explicit project-owned GitHub repository/domain references.\n"
        "Do not treat generic process mentions as context.\n\n"
        f"Input:\n{json.dumps(llm_payload, ensure_ascii=True)}\n"
    )
    try:
        parsed = run_structured_codex_prompt(
            prompt=prompt,
            output_schema=output_schema,
            workspace_id=None,
            session_key=f"project-context-classifier:{payload_hash}",
            mcp_servers=[],
            use_cache=True,
        )
        normalized = {
            "has_repo_context": bool(parsed.get("has_repo_context")),
            "has_github_context": bool(parsed.get("has_github_context")),
            "repo_reason": str(parsed.get("repo_reason") or ""),
            "github_reason": str(parsed.get("github_reason") or ""),
        }
        _PROJECT_CONTEXT_CLASSIFIER_CACHE[cache_key] = normalized
        return normalized
    except Exception:
        return {
            "has_repo_context": False,
            "has_github_context": False,
            "repo_reason": "Project context classification failed.",
            "github_reason": "Project context classification failed.",
        }


def project_has_repo_context(
    *,
    project_description: str,
    project_external_refs: Any,
    project_rules: list[Any],
    parse_json_list: Callable[[Any], list[dict[str, Any]]],
    allow_llm: bool = True,
) -> bool:
    parsed = classify_project_context_signals(
        project_description=project_description,
        project_external_refs=project_external_refs,
        project_rules=project_rules,
        parse_json_list=parse_json_list,
        allow_llm=allow_llm,
    )
    return bool(parsed.get("has_repo_context"))


def project_has_github_context(
    *,
    project_description: str,
    project_external_refs: Any,
    project_rules: list[Any],
    parse_json_list: Callable[[Any], list[dict[str, Any]]],
    allow_llm: bool = True,
) -> bool:
    parsed = classify_project_context_signals(
        project_description=project_description,
        project_external_refs=project_external_refs,
        project_rules=project_rules,
        parse_json_list=parse_json_list,
        allow_llm=allow_llm,
    )
    return bool(parsed.get("has_github_context"))
