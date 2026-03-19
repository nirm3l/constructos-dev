from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


STARTER_VERSION = "1"

_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
_STARTERS_DIR = _CATALOG_DIR / "starters"
_FACETS_PATH = _CATALOG_DIR / "facets.json"
_ALIASES_PATH = _CATALOG_DIR / "aliases.json"


@dataclass(frozen=True, slots=True)
class StarterArtifactSpecification:
    title: str
    body: str = ""
    status: str = "Ready"


@dataclass(frozen=True, slots=True)
class StarterArtifactTask:
    title: str
    description: str = ""
    priority: str = "Med"
    labels: tuple[str, ...] = ()
    specification_title: str | None = None


@dataclass(frozen=True, slots=True)
class StarterArtifactRule:
    title: str
    body: str = ""


@dataclass(frozen=True, slots=True)
class ProjectStarterDefinition:
    key: str
    label: str
    description: str
    positioning_text: str
    recommended_use_cases: tuple[str, ...]
    default_custom_statuses: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    question_set: tuple[str, ...]
    specifications: tuple[StarterArtifactSpecification, ...] = ()
    tasks: tuple[StarterArtifactTask, ...] = ()
    rules: tuple[StarterArtifactRule, ...] = ()
    setup_tags: tuple[str, ...] = ()
    facet_defaults: tuple[str, ...] = ()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_string_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("Expected a JSON array of strings")
    return tuple(str(item).strip() for item in raw if str(item).strip())


def _load_specifications(raw_items: object) -> tuple[StarterArtifactSpecification, ...]:
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise ValueError("Expected specifications to be an array")
    return tuple(
        StarterArtifactSpecification(
            title=str(item.get("title") or "").strip(),
            body=str(item.get("body") or ""),
            status=str(item.get("status") or "Ready").strip() or "Ready",
        )
        for item in raw_items
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    )


def _load_tasks(raw_items: object) -> tuple[StarterArtifactTask, ...]:
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise ValueError("Expected tasks to be an array")
    return tuple(
        StarterArtifactTask(
            title=str(item.get("title") or "").strip(),
            description=str(item.get("description") or ""),
            priority=str(item.get("priority") or "Med").strip() or "Med",
            labels=_as_string_tuple(item.get("labels")),
            specification_title=(
                str(item.get("specification_title") or "").strip() or None
            ),
        )
        for item in raw_items
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    )


def _load_rules(raw_items: object) -> tuple[StarterArtifactRule, ...]:
    if raw_items is None:
        return ()
    if not isinstance(raw_items, list):
        raise ValueError("Expected rules to be an array")
    return tuple(
        StarterArtifactRule(
            title=str(item.get("title") or "").strip(),
            body=str(item.get("body") or ""),
        )
        for item in raw_items
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    )


def _load_starter_definition(path: Path) -> ProjectStarterDefinition:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Starter file must contain a JSON object: {path}")
    key = str(payload.get("key") or "").strip()
    label = str(payload.get("label") or "").strip()
    description = str(payload.get("description") or "").strip()
    positioning_text = str(payload.get("positioning_text") or "").strip()
    if not key or not label or not description or not positioning_text:
        raise ValueError(f"Starter file is missing required fields: {path}")
    return ProjectStarterDefinition(
        key=key,
        label=label,
        description=description,
        positioning_text=positioning_text,
        recommended_use_cases=_as_string_tuple(payload.get("recommended_use_cases")),
        default_custom_statuses=_as_string_tuple(payload.get("default_custom_statuses")),
        retrieval_hints=_as_string_tuple(payload.get("retrieval_hints")),
        question_set=_as_string_tuple(payload.get("question_set")),
        specifications=_load_specifications(payload.get("specifications")),
        tasks=_load_tasks(payload.get("tasks")),
        rules=_load_rules(payload.get("rules")),
        setup_tags=_as_string_tuple(payload.get("setup_tags")),
        facet_defaults=_as_string_tuple(payload.get("facet_defaults")),
    )


def _load_starters() -> dict[str, ProjectStarterDefinition]:
    starters: dict[str, ProjectStarterDefinition] = {}
    for path in sorted(_STARTERS_DIR.glob("*.json")):
        definition = _load_starter_definition(path)
        normalized_key = normalize_starter_key(definition.key)
        if normalized_key in starters:
            raise ValueError(f"Duplicate starter key in catalog: {definition.key}")
        starters[normalized_key] = definition
    if not starters:
        raise ValueError(f"No starter definitions found in {_STARTERS_DIR}")
    return starters


def _load_facets() -> tuple[str, ...]:
    payload = _read_json(_FACETS_PATH)
    if not isinstance(payload, list):
        raise ValueError("Facet catalog must be a JSON array")
    return tuple(str(item).strip() for item in payload if str(item).strip())


def _load_alias_map() -> dict[str, str]:
    payload = _read_json(_ALIASES_PATH)
    if not isinstance(payload, dict):
        raise ValueError("Starter aliases must be a JSON object")
    aliases: dict[str, str] = {}
    for raw_alias, raw_target in payload.items():
        alias = str(raw_alias or "").strip()
        target = str(raw_target or "").strip()
        if not alias or not target:
            continue
        aliases[normalize_starter_key(alias)] = normalize_starter_key(target)
    return aliases


def normalize_starter_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


_STARTER_ALIASES = _load_alias_map()
_STARTERS = _load_starters()
_FACET_KEYS = _load_facets()


def list_project_starters() -> list[ProjectStarterDefinition]:
    return sorted(_STARTERS.values(), key=lambda item: item.label.casefold())


def get_project_starter(starter_key: str | None) -> ProjectStarterDefinition | None:
    normalized = normalize_starter_key(starter_key)
    canonical = _STARTER_ALIASES.get(normalized, normalized)
    return _STARTERS.get(canonical)


def list_project_facets() -> list[str]:
    return list(_FACET_KEYS)
