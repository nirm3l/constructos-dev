from __future__ import annotations

import os
from importlib import reload
from pathlib import Path
from typing import Mapping

from fastapi.testclient import TestClient


def bootstrap_app_runtime(
    tmp_path: Path,
    *,
    attachments_dir: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> object:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    if attachments_dir:
        os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    if extra_env:
        for key, value in extra_env.items():
            os.environ[str(key)] = str(value)

    import main

    main = reload(main)
    main.bootstrap_data()
    return main


def build_client(
    tmp_path: Path,
    *,
    login: bool = True,
    attachments_dir: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> TestClient:
    main = bootstrap_app_runtime(
        tmp_path,
        attachments_dir=attachments_dir,
        extra_env=extra_env,
    )
    client = TestClient(main.app)
    if login:
        login_response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert login_response.status_code == 200
    return client
