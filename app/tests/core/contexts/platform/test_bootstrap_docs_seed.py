from __future__ import annotations

import importlib
import os
from pathlib import Path


def _repo_docs_root() -> Path:
    return Path(__file__).resolve().parents[5] / "docs"


def _read_repo_markdown(relative_path: str) -> str:
    return (_repo_docs_root() / relative_path).read_text(encoding="utf-8").strip()


def _bootstrap_runtime(tmp_path: Path, *, internal_seed_enabled: bool) -> object:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    os.environ["SEED_CONSTRUCTOS_INTERNAL_ENABLED"] = "true" if internal_seed_enabled else "false"
    import shared.settings as shared_settings
    import shared.bootstrap as shared_bootstrap

    shared_settings.SEED_CONSTRUCTOS_INTERNAL_ENABLED = bool(internal_seed_enabled)
    shared_bootstrap.SEED_CONSTRUCTOS_INTERNAL_ENABLED = bool(internal_seed_enabled)

    import main

    main = importlib.reload(main)
    main.bootstrap_data()
    return main


def test_constructos_project_seed_uses_markdown_file_content(tmp_path: Path) -> None:
    _bootstrap_runtime(tmp_path, internal_seed_enabled=False)
    from shared import bootstrap as bootstrap_seed
    from shared.models import Note, SessionLocal

    expected_body = _read_repo_markdown("constructos-overview.md")
    with SessionLocal() as db:
        welcome_note = db.get(Note, bootstrap_seed.CONSTRUCTOS_NOTE_WELCOME_ID)
        assert welcome_note is not None
        assert str(welcome_note.body or "") == expected_body


def test_constructos_internal_seed_enabled_by_env(tmp_path: Path) -> None:
    _bootstrap_runtime(tmp_path, internal_seed_enabled=True)
    from shared import bootstrap as bootstrap_seed
    from shared.models import Note, Project, SessionLocal

    expected_body = _read_repo_markdown("internal/00-index.md")
    with SessionLocal() as db:
        internal_project = db.get(Project, bootstrap_seed.CONSTRUCTOS_INTERNAL_PROJECT_ID)
        assert internal_project is not None
        assert str(internal_project.name or "") == bootstrap_seed.CONSTRUCTOS_INTERNAL_PROJECT_NAME

        internal_index_note_id = bootstrap_seed._cos_internal_entity_id("note", "00-index")
        internal_index = db.get(Note, internal_index_note_id)
        assert internal_index is not None
        assert str(internal_index.body or "") == expected_body


def test_constructos_internal_seed_disabled_by_env(tmp_path: Path) -> None:
    _bootstrap_runtime(tmp_path, internal_seed_enabled=False)
    from shared import bootstrap as bootstrap_seed
    from shared.models import Project, SessionLocal

    with SessionLocal() as db:
        internal_project = db.get(Project, bootstrap_seed.CONSTRUCTOS_INTERNAL_PROJECT_ID)
        assert internal_project is None
