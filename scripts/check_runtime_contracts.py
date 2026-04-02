#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_sys_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_root = repo_root / "app"
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))


def main(argv: list[str] | None = None) -> int:
    _bootstrap_sys_path()

    from features.architecture_inventory import audit_architecture_inventory, build_architecture_inventory

    parser = argparse.ArgumentParser(
        description="Validate generated runtime contracts and optionally print the current architecture inventory."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the generated architecture inventory and audit result as JSON.",
    )
    args = parser.parse_args(argv)

    inventory = build_architecture_inventory()
    audit_result = audit_architecture_inventory(inventory)

    if args.json:
        print(
            json.dumps(
                {
                    "audit": audit_result.as_dict(),
                    "inventory": inventory,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("Runtime Contract Audit")
        print(f"OK: {audit_result.ok}")
        print(f"Providers: {inventory['counts'].get('execution_providers', 0)}")
        print(f"Workflow plugins: {inventory['counts'].get('workflow_plugins', 0)}")
        print(f"Plugin descriptors: {inventory['counts'].get('plugin_descriptors', 0)}")
        print(f"MCP tools: {inventory['counts'].get('constructos_mcp_tools', 0)}")
        print(f"Prompt templates: {inventory['counts'].get('prompt_templates', 0)}")
        print(f"Bootstrap startup phases: {inventory['counts'].get('bootstrap_startup_phases', 0)}")
        print(f"Bootstrap shutdown phases: {inventory['counts'].get('bootstrap_shutdown_phases', 0)}")
        if audit_result.errors:
            print("")
            print("Errors:")
            for error in audit_result.errors:
                print(f"- {error}")
        if audit_result.warnings:
            print("")
            print("Warnings:")
            for warning in audit_result.warnings:
                print(f"- {warning}")

    return 0 if audit_result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
