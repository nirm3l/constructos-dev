from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_test_runtime_env(request: pytest.FixtureRequest) -> None:
    # Keep test runs deterministic regardless of host/container runtime env.
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["AGENT_RUNNER_ENABLED"] = "false"
    os.environ["AGENT_CODEX_COMMAND"] = ""
    os.environ["SEED_CONSTRUCTOS_INTERNAL_ENABLED"] = "false"
    if "shared.settings" in sys.modules:
        settings_module = sys.modules["shared.settings"]
        setattr(settings_module, "EVENTSTORE_URI", "")
        setattr(settings_module, "AGENT_RUNNER_ENABLED", False)
        setattr(settings_module, "AGENT_CODEX_COMMAND", "")
        setattr(settings_module, "SEED_CONSTRUCTOS_INTERNAL_ENABLED", False)
    if "shared.core" in sys.modules:
        core_module = sys.modules["shared.core"]
        setattr(core_module, "EVENTSTORE_URI", "")
    if "shared.eventing_store" in sys.modules:
        eventing_store_module = sys.modules["shared.eventing_store"]
        setattr(eventing_store_module, "EVENTSTORE_URI", "")
        setattr(eventing_store_module, "_kurrent_client", None)
    if "features.agents.executor" in sys.modules:
        executor_module = sys.modules["features.agents.executor"]
        setattr(executor_module, "AGENT_CODEX_COMMAND", "")
