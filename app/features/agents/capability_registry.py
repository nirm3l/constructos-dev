from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from plugins.registry import list_workflow_plugins
from plugins.descriptors import list_plugin_descriptors
from shared.settings import (
    AGENT_DEFAULT_EXECUTION_PROVIDER,
    agent_default_model_for_provider,
    agent_default_reasoning_effort_for_provider,
    agent_system_full_name_for_provider,
    agent_system_user_id_for_provider,
    agent_system_username_for_provider,
)

_PROVIDER_ORDER = ("codex", "claude", "opencode")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative_to_repo(path: Path) -> str:
    return str(path.relative_to(_repo_root()))


def list_execution_provider_capabilities() -> list[dict[str, Any]]:
    default_provider = str(AGENT_DEFAULT_EXECUTION_PROVIDER or "").strip().lower() or "codex"
    rows: list[dict[str, Any]] = []
    for provider in _PROVIDER_ORDER:
        rows.append(
            {
                "provider": provider,
                "is_default": provider == default_provider,
                "default_model": str(agent_default_model_for_provider(provider) or "").strip() or None,
                "default_reasoning_effort": str(
                    agent_default_reasoning_effort_for_provider(provider) or ""
                ).strip()
                or None,
                "system_user": {
                    "id": agent_system_user_id_for_provider(provider),
                    "username": agent_system_username_for_provider(provider),
                    "full_name": agent_system_full_name_for_provider(provider),
                },
            }
        )
    return rows


def list_workflow_plugin_capabilities() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plugin in list_workflow_plugins():
        key = str(getattr(plugin, "key", "") or "").strip().lower()
        if not key:
            continue
        available_check_ids_fn = getattr(plugin, "available_check_ids", None)
        skill_dependencies_fn = getattr(plugin, "skill_dependencies", None)
        provided_checks = list(plugin.default_required_checks())
        available_check_ids = (
            [str(item).strip() for item in available_check_ids_fn()]
            if callable(available_check_ids_fn)
            else []
        )
        skill_dependencies = skill_dependencies_fn() if callable(skill_dependencies_fn) else {}
        normalized_dependencies: dict[str, list[str]] = {}
        if isinstance(skill_dependencies, dict):
            for dep_key_raw, dep_values in skill_dependencies.items():
                dep_key = str(dep_key_raw or "").strip().lower()
                if not dep_key or not isinstance(dep_values, (list, tuple, set)):
                    continue
                normalized_dependencies[dep_key] = [
                    str(item or "").strip().lower()
                    for item in dep_values
                    if str(item or "").strip()
                ]
        rows.append(
            {
                "key": key,
                "module": type(plugin).__module__,
                "class_name": type(plugin).__name__,
                "check_scope": plugin.check_scope(),
                "default_required_checks": provided_checks,
                "default_required_check_count": len(provided_checks),
                "available_checks": dict(plugin.check_descriptions()),
                "available_check_ids": available_check_ids,
                "skill_dependencies": normalized_dependencies,
            }
        )
    rows.sort(key=lambda item: str(item.get("key") or ""))
    return rows


def _evaluate_string_expr(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _evaluate_string_expr(node.left, constants)
        right = _evaluate_string_expr(node.right, constants)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            return None
        return "".join(parts)
    return None


def _load_module_string_constants(module_path: Path) -> dict[str, str]:
    tree = ast.parse(_safe_read_text(module_path), filename=str(module_path))
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _evaluate_string_expr(node.value, constants)
            if value is not None:
                constants[node.targets[0].id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            value = _evaluate_string_expr(node.value, constants)
            if value is not None:
                constants[node.target.id] = value
    return constants


def _extract_plugin_gate_keys(test: ast.AST) -> list[str]:
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "plugin_enabled":
        if len(test.args) != 1:
            return []
        if isinstance(test.args[0], ast.Constant) and isinstance(test.args[0].value, str):
            normalized = str(test.args[0].value or "").strip().lower()
            return [normalized] if normalized else []
        return []
    if isinstance(test, ast.BoolOp):
        out: list[str] = []
        for value in test.values:
            for key in _extract_plugin_gate_keys(value):
                if key not in out:
                    out.append(key)
        return out
    return []


def _decorator_description(
    decorators: list[ast.expr],
    *,
    constants: dict[str, str],
) -> str | None:
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        if decorator.func.attr != "tool":
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "mcp":
            continue
        for keyword in decorator.keywords:
            if keyword.arg != "description":
                continue
            value = _evaluate_string_expr(keyword.value, constants)
            if value is not None:
                return value.strip()
            return None
    return None


def _build_parameter_inventory(args: ast.arguments) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    positional = list(args.posonlyargs) + list(args.args)
    positional_defaults = list(args.defaults)
    default_start_index = len(positional) - len(positional_defaults)
    for index, arg in enumerate(positional):
        required = index < default_start_index
        out.append(
            {
                "name": arg.arg,
                "required": required,
                "kind": "positional_or_keyword",
            }
        )
    for index, arg in enumerate(args.kwonlyargs):
        required = args.kw_defaults[index] is None
        out.append(
            {
                "name": arg.arg,
                "required": required,
                "kind": "keyword_only",
            }
        )
    if args.vararg is not None:
        out.append({"name": args.vararg.arg, "required": False, "kind": "vararg"})
    if args.kwarg is not None:
        out.append({"name": args.kwarg.arg, "required": False, "kind": "kwarg"})
    return out


def _collect_mcp_tool_nodes(
    statements: list[ast.stmt],
    *,
    constants: dict[str, str],
    active_plugin_gates: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_gates = list(active_plugin_gates or [])
    for statement in statements:
        if isinstance(statement, ast.If):
            gated_keys = _extract_plugin_gate_keys(statement.test)
            next_gates = current_gates
            if gated_keys:
                next_gates = sorted({*current_gates, *gated_keys})
            rows.extend(
                _collect_mcp_tool_nodes(
                    statement.body,
                    constants=constants,
                    active_plugin_gates=next_gates,
                )
            )
            rows.extend(
                _collect_mcp_tool_nodes(
                    statement.orelse,
                    constants=constants,
                    active_plugin_gates=current_gates,
                )
            )
            continue
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        description = _decorator_description(statement.decorator_list, constants=constants)
        if description is None:
            continue
        parameters = _build_parameter_inventory(statement.args)
        rows.append(
            {
                "name": statement.name,
                "description": description,
                "plugin_gates": list(current_gates),
                "parameter_names": [str(item["name"]) for item in parameters],
                "required_parameters": [str(item["name"]) for item in parameters if bool(item.get("required"))],
                "parameter_count": len(parameters),
            }
        )
    return rows


def list_constructos_mcp_tool_capabilities() -> list[dict[str, Any]]:
    module_path = _app_root() / "features" / "agents" / "mcp_server.py"
    tree = ast.parse(_safe_read_text(module_path), filename=str(module_path))
    constants = _load_module_string_constants(module_path)
    create_mcp_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_mcp"
        ),
        None,
    )
    if create_mcp_node is None:
        return []
    rows = _collect_mcp_tool_nodes(create_mcp_node.body, constants=constants)
    rows.sort(key=lambda item: str(item.get("name") or ""))
    return rows


def list_prompt_template_capabilities() -> list[dict[str, Any]]:
    repo_root = _repo_root()
    roots = [
        repo_root / "app" / "shared" / "prompt_templates",
        repo_root / "app" / "plugins",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.name == "plugins":
            files.extend(sorted(root.glob("*/prompt_templates/*.md")))
            continue
        files.extend(sorted(root.rglob("*.md")))
    rows: list[dict[str, Any]] = []
    for path in sorted(set(files)):
        content = _safe_read_text(path)
        placeholders = sorted({match.group(1) for match in _PLACEHOLDER_RE.finditer(content)})
        rows.append(
            {
                "path": _relative_to_repo(path),
                "placeholder_names": placeholders,
                "placeholder_count": len(placeholders),
                "line_count": len(content.splitlines()),
            }
        )
    return rows


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _collect_lifespan_calls(
    statements: list[ast.stmt],
    *,
    condition: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for statement in statements:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            name = _call_name(statement.value)
            if name:
                payload = {"name": name}
                if condition:
                    payload["condition"] = condition
                rows.append(payload)
            continue
        if isinstance(statement, ast.Try):
            rows.extend(_collect_lifespan_calls(statement.body, condition=condition))
            continue
        if isinstance(statement, ast.If):
            conditional = ast.unparse(statement.test).strip() if hasattr(ast, "unparse") else None
            rows.extend(_collect_lifespan_calls(statement.body, condition=conditional or condition))
            rows.extend(_collect_lifespan_calls(statement.orelse, condition=condition))
            continue
    return rows


def build_bootstrap_phase_capabilities() -> dict[str, Any]:
    module_path = _repo_root() / "app" / "main.py"
    tree = ast.parse(_safe_read_text(module_path), filename=str(module_path))
    lifespan_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        ),
        None,
    )
    if lifespan_node is None:
        return {"startup": [], "shutdown": []}
    startup_statements: list[ast.stmt] = []
    shutdown_statements: list[ast.stmt] = []
    current_target = startup_statements
    for statement in lifespan_node.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Yield):
            current_target = shutdown_statements
            continue
        current_target.append(statement)
    startup = _collect_lifespan_calls(startup_statements)
    shutdown = _collect_lifespan_calls(shutdown_statements)
    return {
        "startup": startup,
        "shutdown": shutdown,
        "startup_phase_count": len(startup),
        "shutdown_phase_count": len(shutdown),
    }


def build_capability_registry() -> dict[str, Any]:
    workflow_plugins = list_workflow_plugin_capabilities()
    plugin_descriptors = list_plugin_descriptors()
    execution_providers = list_execution_provider_capabilities()
    mcp_tools = list_constructos_mcp_tool_capabilities()
    prompt_templates = list_prompt_template_capabilities()
    bootstrap = build_bootstrap_phase_capabilities()
    return {
        "workflow_plugins": workflow_plugins,
        "plugin_descriptors": plugin_descriptors,
        "execution_providers": execution_providers,
        "constructos_mcp_tools": mcp_tools,
        "prompt_templates": prompt_templates,
        "bootstrap": bootstrap,
        "counts": {
            "workflow_plugins": len(workflow_plugins),
            "plugin_descriptors": len(plugin_descriptors),
            "execution_providers": len(execution_providers),
            "constructos_mcp_tools": len(mcp_tools),
            "prompt_templates": len(prompt_templates),
            "bootstrap_startup_phases": int(bootstrap.get("startup_phase_count") or 0),
            "bootstrap_shutdown_phases": int(bootstrap.get("shutdown_phase_count") or 0),
        },
    }
