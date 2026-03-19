from __future__ import annotations

from typing import Any


EXECUTION_GATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "repo_context": {
        "label": "Repository context",
        "blocking": True,
        "description": "Project repository context is required before Developer execution.",
    },
    "dev_commit_evidence": {
        "label": "Commit evidence",
        "blocking": True,
        "description": "Developer work must persist commit evidence before handoff.",
    },
    "dev_task_branch_evidence": {
        "label": "Task branch evidence",
        "blocking": True,
        "description": "Developer work must run on a task branch tied to the current task.",
    },
    "developer_handoff_not_committed": {
        "label": "Committed Developer handoff",
        "blocking": True,
        "description": "Developer work must end with a clean task branch commit ahead of main before handoff.",
    },
    "developer_main_reconciliation_required": {
        "label": "Main reconciliation",
        "blocking": True,
        "description": "The task branch must be reconciled with the latest main branch before merge handoff can continue.",
    },
    "developer_deploy_lock_waiting": {
        "label": "Deployment in progress",
        "blocking": True,
        "description": "Developer merge-to-main is waiting for the current project deploy cycle to finish.",
    },
    "dev_tests_required": {
        "label": "Developer tests",
        "blocking": True,
        "description": "Required deterministic tests must pass before Developer handoff.",
    },
    "lead_merge_to_main": {
        "label": "Merge to main",
        "blocking": True,
        "description": "Lead deploy work requires merge-to-main evidence for the current task.",
    },
    "compose_manifest": {
        "label": "Compose manifest",
        "blocking": True,
        "description": "Docker Compose deploy requires a compose manifest in the project repository.",
    },
    "runtime_deploy_health": {
        "label": "Runtime deploy health",
        "blocking": True,
        "description": "Lead deploy must produce a healthy runtime on the configured stack and health path.",
    },
    "lead_deploy_scaffolding": {
        "label": "Deployment scaffolding",
        "blocking": True,
        "description": "Lead is waiting for a deployment-scaffolding follow-up task to add missing deploy/runtime assets.",
    },
    "lead_waiting_committed_developer_handoff": {
        "label": "Developer handoff",
        "blocking": True,
        "description": "Lead cannot continue until the current task has real committed Developer handoff evidence.",
    },
    "lead_waiting_merge_ready_developer": {
        "label": "Merge-ready Developer output",
        "blocking": True,
        "description": "Lead is waiting for a Developer task to become merge-ready for the next cycle.",
    },
    "lead_runtime_health_failed": {
        "label": "Runtime health failure",
        "blocking": True,
        "description": "Lead deploy completed without a healthy runtime on the configured deploy target.",
    },
    "lead_deploy_topology_reconciliation_required": {
        "label": "Deploy topology reconciliation",
        "blocking": True,
        "description": "Lead found a deploy topology or service-identity mismatch that must be reconciled by Developer before deploy can continue.",
    },
    "qa_handoff_ready": {
        "label": "Lead handoff",
        "blocking": True,
        "description": "QA can only execute after a valid Lead handoff for the current deploy cycle.",
    },
    "qa_waiting_current_deploy_cycle": {
        "label": "Current deploy cycle",
        "blocking": True,
        "description": "QA is waiting for Lead handoff evidence that matches the latest successful deploy cycle.",
    },
    "qa_verifiable_artifacts": {
        "label": "QA artifacts",
        "blocking": False,
        "description": "QA should record verifiable artifacts for the validation result.",
    },
}


def execution_gate_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": gate_id,
            "label": str(definition.get("label") or gate_id),
            "blocking": bool(definition.get("blocking", False)),
            "description": str(definition.get("description") or "").strip() or None,
        }
        for gate_id, definition in EXECUTION_GATE_DEFINITIONS.items()
    ]


def build_execution_gate(
    gate_id: str,
    *,
    status: str,
    message: str | None = None,
    blocking: bool | None = None,
) -> dict[str, Any]:
    definition = EXECUTION_GATE_DEFINITIONS.get(str(gate_id or "").strip(), {})
    normalized_status = str(status or "").strip().lower() or "waiting"
    return {
        "id": str(gate_id or "").strip(),
        "label": str(definition.get("label") or gate_id or "").strip(),
        "status": normalized_status,
        "blocking": bool(definition.get("blocking", False)) if blocking is None else bool(blocking),
        "message": str(message or "").strip() or None,
        "description": str(definition.get("description") or "").strip() or None,
    }
