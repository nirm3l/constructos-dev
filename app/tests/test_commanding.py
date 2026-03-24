from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from shared.commanding import execute_command
from shared.models import SessionLocal


def build_client(tmp_path: Path) -> TestClient:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ["AGENT_CODEX_WORKDIR"] = str(tmp_path / "workspace")
    os.environ["AGENT_RUNNER_ENABLED"] = "false"
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert login.status_code == 200
    return client


def test_execute_command_replays_same_command_id_for_same_intent(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    user_id = client.get('/api/bootstrap').json()['current_user']['id']

    with SessionLocal() as db:
        first = execute_command(
            db,
            command_name="Commanding.Test",
            user_id=user_id,
            command_id="test-commanding-replay-001",
            handler=lambda: {"ok": True, "value": 1},
        )
        second = execute_command(
            db,
            command_name="Commanding.Test",
            user_id=user_id,
            command_id="test-commanding-replay-001",
            handler=lambda: {"ok": True, "value": 2},
        )

    assert first == {"ok": True, "value": 1}
    assert second == {"ok": True, "value": 1}


def test_execute_command_rejects_command_id_reuse_for_different_intent_or_user(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    user_id = client.get('/api/bootstrap').json()['current_user']['id']

    with SessionLocal() as db:
        seed = execute_command(
            db,
            command_name="Commanding.Test",
            user_id=user_id,
            command_id="test-commanding-conflict-001",
            handler=lambda: {"ok": True},
        )
        assert seed == {"ok": True}

        try:
            execute_command(
                db,
                command_name="Commanding.Test.Other",
                user_id=user_id,
                command_id="test-commanding-conflict-001",
                handler=lambda: {"ok": False},
            )
            assert False, "Expected HTTPException for command_name conflict"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "command_id already used for different command intent" in str(exc.detail)

        try:
            execute_command(
                db,
                command_name="Commanding.Test",
                user_id="00000000-0000-0000-0000-00000000ffff",
                command_id="test-commanding-conflict-001",
                handler=lambda: {"ok": False},
            )
            assert False, "Expected HTTPException for user_id conflict"
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "command_id already used for different command intent" in str(exc.detail)
