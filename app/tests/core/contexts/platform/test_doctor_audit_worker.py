from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.core.support.runtime import build_client as build_runtime_client


def build_client(tmp_path: Path) -> TestClient:
    return build_runtime_client(
        tmp_path,
        extra_env={
            "AGENT_CODEX_WORKDIR": str(tmp_path / "workspace"),
            "AGENT_RUNNER_ENABLED": "false",
            "DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_ENABLED": "false",
        },
    )


def test_doctor_runtime_contract_audit_auto_tick_records_quick_action(tmp_path: Path, monkeypatch):
    client = build_client(tmp_path)
    bootstrap = client.get('/api/bootstrap').json()
    workspace_id = bootstrap['workspaces'][0]['id']

    seeded = client.post(f'/api/workspaces/{workspace_id}/doctor/seed')
    assert seeded.status_code == 200

    import features.doctor.audit_worker as audit_worker

    monkeypatch.setattr(audit_worker, "DOCTOR_RUNTIME_CONTRACT_AUDIT_AUTO_ENABLED", True)
    completed = audit_worker.run_doctor_runtime_contract_audit_auto_tick(
        explicit_workspace_ids=[workspace_id]
    )
    assert completed == 1

    status = client.get(f'/api/workspaces/{workspace_id}/doctor')
    assert status.status_code == 200
    payload = status.json()
    recent_actions = payload.get("recent_actions") or []
    action_ids = [
        str((item or {}).get("id") or "").strip()
        for item in recent_actions
        if isinstance(item, dict)
    ]
    assert "runtime-contract-audit" in action_ids

    contracts_domain = (((payload.get("runtime_health") or {}).get("domains") or {}).get("contracts") or {})
    contracts_metrics = contracts_domain.get("metrics") or {}
    assert contracts_metrics.get("runtime_contract_audit_stale") is False
