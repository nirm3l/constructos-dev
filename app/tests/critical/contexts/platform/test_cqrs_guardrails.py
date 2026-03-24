from __future__ import annotations

import ast
from collections import defaultdict
import re
from pathlib import Path


def _has_direct_append_event_call(source: str) -> bool:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "append_event":
            return True
    return False


def test_features_do_not_call_append_event_directly() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    offenders: list[str] = []
    for path in sorted(features_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if "/tests/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        if _has_direct_append_event_call(source):
            offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Direct append_event() calls are forbidden in feature modules. "
        "Use application service -> command handler -> aggregate flow instead. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_shared_append_event_calls_are_limited_to_eventing_and_bootstrap() -> None:
    app_root = Path(__file__).resolve().parents[4]
    shared_root = app_root / "shared"
    assert shared_root.exists()

    allowed = {
        "shared/bootstrap.py",
        "shared/eventing.py",
    }
    offenders: list[str] = []
    for path in sorted(shared_root.rglob("*.py")):
        rel = str(path.relative_to(app_root))
        if rel in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if _has_direct_append_event_call(source):
            offenders.append(rel)

    assert not offenders, (
        "Direct append_event() calls in shared modules are restricted. "
        f"Only {', '.join(sorted(allowed))} may call it directly. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_features_do_not_mutate_aggregate_read_models_via_sqlalchemy_dml() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    forbidden_patterns = (
        r"\bupdate\((Task|Project|Note|TaskGroup|NoteGroup|Specification|ProjectRule)\)",
        r"\bdelete\((Task|Project|Note|TaskGroup|NoteGroup|Specification|ProjectRule)\)",
        r"\bdb\.add\(\s*(Task|Project|Note|TaskGroup|NoteGroup|Specification|ProjectRule)\(",
    )

    offenders: list[str] = []
    for path in sorted(features_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if "/tests/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        if any(re.search(pattern, source) for pattern in forbidden_patterns):
            offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Direct SQLAlchemy DML against aggregate read-model tables is forbidden in feature modules. "
        "Use command handlers + aggregates + events instead. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_command_id_derivation_uses_helpers_in_critical_services() -> None:
    app_root = Path(__file__).resolve().parents[4]
    monitored_files = (
        app_root / "features" / "agents" / "api.py",
        app_root / "features" / "agents" / "service.py",
        app_root / "features" / "agents" / "runner.py",
        app_root / "features" / "doctor" / "service.py",
    )
    direct_fstring_patterns = (
        r'f"\{command_id[^"]*"',
        r"f'\{command_id[^']*'",
        r'f"\{str\(command_id[^"]*"',
        r"f'\{str\(command_id[^']*'",
    )

    offenders: list[str] = []
    for path in monitored_files:
        source = path.read_text(encoding="utf-8")
        if any(re.search(pattern, source) for pattern in direct_fstring_patterns):
            offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Critical services should derive child command ids through helper functions, "
        "not ad-hoc f-string concatenation based on command_id. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_application_services_do_not_reuse_literal_command_names_across_methods() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    offenders: list[str] = []
    for path in sorted(features_root.glob("*/application.py")):
        source = path.read_text(encoding="utf-8")
        try:
            module = ast.parse(source)
        except SyntaxError:
            continue
        command_to_methods: dict[str, set[str]] = defaultdict(set)
        for node in ast.walk(module):
            if not isinstance(node, ast.FunctionDef):
                continue
            method_name = str(node.name or "").strip() or "<unknown>"
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                if not isinstance(call.func, ast.Name) or call.func.id != "execute_command":
                    continue
                for kw in call.keywords:
                    if kw.arg != "command_name":
                        continue
                    if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        command_to_methods[str(kw.value.value)].add(method_name)
        duplicates = {
            command_name: sorted(methods)
            for command_name, methods in command_to_methods.items()
            if len(methods) > 1
        }
        if duplicates:
            rel = str(path.relative_to(app_root))
            for command_name, methods in sorted(duplicates.items()):
                offenders.append(f"{rel} -> {command_name} used by {', '.join(methods)}")

    assert not offenders, (
        "Application services should not reuse the same literal execute_command(command_name=...) "
        "across multiple methods in the same module. "
        f"Offenders: {'; '.join(offenders)}"
    )


def test_feature_modules_do_not_build_child_command_ids_with_parent_fstrings() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    forbidden_patterns = (
        r'f"\{command_id[^"]*"',
        r"f'\{command_id[^']*'",
        r'f"\{str\(command_id[^"]*"',
        r"f'\{str\(command_id[^']*'",
    )
    offenders: list[str] = []
    for path in sorted(features_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if "/tests/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        if any(re.search(pattern, source) for pattern in forbidden_patterns):
            offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Feature modules should derive child command ids through shared helpers, "
        "not parent command_id f-string concatenation. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_feature_modules_do_not_slice_command_ids_directly() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    offenders: list[str] = []
    direct_slice_patterns = (
        r"command_id\s*\[\s*:\s*64\s*\]",
        r"str\(\s*command_id[^)]*\)\s*\[\s*:\s*64\s*\]",
        r"\[\s*:\s*64\s*\]\s*if\s*str\(\s*command_id",
    )
    for path in sorted(features_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if "/tests/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        if any(re.search(pattern, source) for pattern in direct_slice_patterns):
            offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Feature modules should not truncate command ids via direct slicing. "
        "Use shared command-id helpers instead. "
        f"Offenders: {', '.join(offenders)}"
    )


def test_manual_command_execution_lookups_enforce_scope_guard() -> None:
    app_root = Path(__file__).resolve().parents[4]
    features_root = app_root / "features"
    assert features_root.exists()

    offenders: list[str] = []
    for path in sorted(features_root.rglob("*.py")):
        if path.name.startswith("test_"):
            continue
        if "/tests/" in path.as_posix():
            continue
        source = path.read_text(encoding="utf-8")
        if "select(CommandExecution)" not in source:
            continue
        if "CommandExecution.command_id" not in source:
            continue
        if "_assert_command_execution_scope" in source:
            continue
        offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Feature modules doing manual CommandExecution lookup by command_id must enforce "
        "command_name+user_id scope guard (same semantics as execute_command). "
        f"Offenders: {', '.join(offenders)}"
    )
