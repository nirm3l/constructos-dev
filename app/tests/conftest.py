from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_test_runtime_env(request: pytest.FixtureRequest) -> None:
    # Keep test runs deterministic regardless of host/container runtime env.
    nodeid = str(getattr(request.node, "nodeid", "") or "").lower()
    license_test = "license" in nodeid
    os.environ["LICENSE_ENFORCEMENT_ENABLED"] = "true" if license_test else "false"
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["AGENT_RUNNER_ENABLED"] = "false"
    os.environ["AGENT_CODEX_COMMAND"] = ""
    os.environ["SEED_CONSTRUCTOS_INTERNAL_ENABLED"] = "false"
    if "shared.settings" in sys.modules:
        settings_module = sys.modules["shared.settings"]
        setattr(settings_module, "LICENSE_ENFORCEMENT_ENABLED", bool(license_test))
        setattr(settings_module, "LICENSE_INSTALLATION_ID", str(os.environ.get("LICENSE_INSTALLATION_ID", "")).strip())
        setattr(settings_module, "EVENTSTORE_URI", "")
        setattr(settings_module, "AGENT_RUNNER_ENABLED", False)
        setattr(settings_module, "AGENT_CODEX_COMMAND", "")
        setattr(settings_module, "SEED_CONSTRUCTOS_INTERNAL_ENABLED", False)
    if "shared.licensing" in sys.modules:
        licensing_module = sys.modules["shared.licensing"]
        reset_fn = getattr(licensing_module, "reset_license_installation_id_cache", None)
        if callable(reset_fn):
            reset_fn()
    if "shared.deps" in sys.modules:
        deps_module = sys.modules["shared.deps"]
        setattr(deps_module, "LICENSE_ENFORCEMENT_ENABLED", bool(license_test))
    if "shared.core" in sys.modules:
        core_module = sys.modules["shared.core"]
        setattr(core_module, "EVENTSTORE_URI", "")
    if "shared.eventing_store" in sys.modules:
        eventing_store_module = sys.modules["shared.eventing_store"]
        setattr(eventing_store_module, "EVENTSTORE_URI", "")
        setattr(eventing_store_module, "_kurrent_client", None)
    if "features.licensing.read_models" in sys.modules:
        licensing_read_models = sys.modules["features.licensing.read_models"]
        setattr(licensing_read_models, "LICENSE_ENFORCEMENT_ENABLED", bool(license_test))
    if "features.agents.executor" in sys.modules:
        executor_module = sys.modules["features.agents.executor"]
        setattr(executor_module, "AGENT_CODEX_COMMAND", "")
