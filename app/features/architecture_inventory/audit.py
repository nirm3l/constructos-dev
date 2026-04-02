from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .build import build_architecture_inventory

_OPTIONAL_INTERNAL_DOCS = {
    # Historical/planning documents can remain outside the core index reading path.
    "07-omc-adoption-backlog-v2.md",
    "08-constructos-omc-implementation-plan.md",
    "09-omc-adoption-implementation-report.md",
}


@dataclass(frozen=True)
class ArchitectureInventoryAuditResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def audit_architecture_inventory(inventory: dict[str, Any] | None = None) -> ArchitectureInventoryAuditResult:
    source = dict(inventory or build_architecture_inventory())
    errors: list[str] = []
    warnings: list[str] = []

    capabilities = dict(source.get("capabilities") or {})
    providers = list(capabilities.get("execution_providers") or [])
    provider_names = [str(item.get("provider") or "").strip().lower() for item in providers if str(item.get("provider") or "").strip()]
    provider_duplicates = _duplicate_values(provider_names)
    if provider_duplicates:
        errors.append(f"duplicate execution providers: {', '.join(provider_duplicates)}")
    if not provider_names:
        errors.append("execution provider inventory is empty")

    plugins = list(capabilities.get("workflow_plugins") or [])
    plugin_keys = [str(item.get("key") or "").strip().lower() for item in plugins if str(item.get("key") or "").strip()]
    plugin_duplicates = _duplicate_values(plugin_keys)
    if plugin_duplicates:
        errors.append(f"duplicate workflow plugin keys: {', '.join(plugin_duplicates)}")
    if not plugin_keys:
        errors.append("workflow plugin inventory is empty")

    mcp_tools = list(capabilities.get("constructos_mcp_tools") or [])
    mcp_tool_names = [str(item.get("name") or "").strip() for item in mcp_tools if str(item.get("name") or "").strip()]
    mcp_duplicates = _duplicate_values(mcp_tool_names)
    if mcp_duplicates:
        errors.append(f"duplicate MCP tool names: {', '.join(mcp_duplicates)}")
    if not mcp_tool_names:
        errors.append("ConstructOS MCP tool inventory is empty")
    missing_tool_descriptions = [
        str(item.get("name") or "").strip()
        for item in mcp_tools
        if not str(item.get("description") or "").strip()
    ]
    if missing_tool_descriptions:
        errors.append(
            "MCP tools missing descriptions: " + ", ".join(sorted(missing_tool_descriptions))
        )

    prompt_templates = list(capabilities.get("prompt_templates") or [])
    prompt_paths = [str(item.get("path") or "").strip() for item in prompt_templates if str(item.get("path") or "").strip()]
    prompt_duplicates = _duplicate_values(prompt_paths)
    if prompt_duplicates:
        errors.append(f"duplicate prompt template paths: {', '.join(prompt_duplicates)}")
    if not prompt_paths:
        errors.append("prompt template inventory is empty")

    bootstrap = dict(capabilities.get("bootstrap") or {})
    startup = list(bootstrap.get("startup") or [])
    shutdown = list(bootstrap.get("shutdown") or [])
    if not startup:
        errors.append("bootstrap startup phase inventory is empty")
    if not shutdown:
        errors.append("bootstrap shutdown phase inventory is empty")

    internal_docs = dict(source.get("internal_docs") or {})
    reading_order = list(internal_docs.get("reading_order") or [])
    missing_docs = [str(item).strip() for item in (internal_docs.get("missing_from_reading_order") or []) if str(item).strip()]
    if not reading_order:
        errors.append("internal docs reading order is empty")
    if missing_docs:
        errors.append("internal docs index references missing files: " + ", ".join(missing_docs))
    if "11-claw-code-parity-analysis.md" not in reading_order:
        warnings.append("internal docs reading order does not include 11-claw-code-parity-analysis.md")
    unreferenced_docs = [
        str(item).strip()
        for item in (internal_docs.get("unreferenced_docs") or [])
        if str(item).strip()
    ]
    unexpected_unreferenced_docs = [
        doc for doc in unreferenced_docs if doc not in _OPTIONAL_INTERNAL_DOCS
    ]
    if unexpected_unreferenced_docs:
        warnings.append(
            "internal docs not referenced by 00-index.md: "
            + ", ".join(sorted(unexpected_unreferenced_docs))
        )

    return ArchitectureInventoryAuditResult(errors=errors, warnings=warnings)
