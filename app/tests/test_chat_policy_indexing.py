from __future__ import annotations

import os
from importlib import reload
from pathlib import Path

from sqlalchemy import select


def _bootstrap_runtime(tmp_path: Path) -> None:
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()


def test_chat_vector_sync_backfills_and_purges_on_policy_toggle(tmp_path: Path, monkeypatch) -> None:
    _bootstrap_runtime(tmp_path)

    from shared import vector_store
    from shared.models import ChatMessage, ChatSession, Project, SessionLocal, User, VectorChunk

    monkeypatch.setattr(vector_store, "vector_store_enabled", lambda: True)
    monkeypatch.setattr(vector_store, "_ollama_embed_text", lambda _text, _model: [0.11, 0.22, 0.33])

    with SessionLocal() as db:
        project = db.execute(select(Project).where(Project.is_deleted.is_(False))).scalars().first()
        user = db.execute(select(User).where(User.is_active.is_(True))).scalars().first()
        assert project is not None
        assert user is not None

        project.embedding_enabled = True
        project.embedding_model = "nomic-embed-text"
        project.chat_index_mode = "VECTOR_ONLY"
        project.chat_attachment_ingestion_mode = "METADATA_ONLY"

        session = ChatSession(
            id="3c8fbf50-b41c-4b9f-b235-16a1a4811111",
            workspace_id=project.workspace_id,
            project_id=project.id,
            session_key="chat-policy-sync-session",
            title="Session",
            created_by=user.id,
        )
        message = ChatMessage(
            id="8a360f89-4cf5-4868-90d7-a95d4ec22222",
            workspace_id=project.workspace_id,
            project_id=project.id,
            session_id=session.id,
            role="user",
            content="Persist this chat history in vector search.",
            order_index=1,
            attachment_refs="[]",
            usage_json="{}",
            is_deleted=False,
        )
        db.add(session)
        db.add(message)
        db.commit()

        indexed, purged = vector_store.sync_project_chat_vector_chunks(
            db,
            project_id=project.id,
            retention_mode="purge",
        )
        db.commit()

        indexed_rows = db.execute(
            select(VectorChunk).where(
                VectorChunk.project_id == project.id,
                VectorChunk.entity_type == "ChatMessage",
            )
        ).scalars().all()
        indexed_count = len(indexed_rows)
        assert indexed >= 1
        assert purged == 0
        assert indexed_count >= 1

        project.chat_index_mode = "OFF"
        db.commit()
        indexed_after_off, purged_after_off = vector_store.sync_project_chat_vector_chunks(
            db,
            project_id=project.id,
            retention_mode="purge",
        )
        db.commit()

        remaining_rows = db.execute(
            select(VectorChunk).where(
                VectorChunk.project_id == project.id,
                VectorChunk.entity_type == "ChatMessage",
            )
        ).scalars().all()
        assert indexed_after_off == 0
        assert purged_after_off >= indexed_count
        assert remaining_rows == []


def test_chat_vector_sync_respects_keep_retention_mode(tmp_path: Path, monkeypatch) -> None:
    _bootstrap_runtime(tmp_path)

    from shared import vector_store
    from shared.models import ChatMessage, ChatSession, Project, SessionLocal, User, VectorChunk

    monkeypatch.setattr(vector_store, "vector_store_enabled", lambda: True)
    monkeypatch.setattr(vector_store, "_ollama_embed_text", lambda _text, _model: [0.09, 0.19, 0.29])

    with SessionLocal() as db:
        project = db.execute(select(Project).where(Project.is_deleted.is_(False))).scalars().first()
        user = db.execute(select(User).where(User.is_active.is_(True))).scalars().first()
        assert project is not None
        assert user is not None

        project.embedding_enabled = True
        project.embedding_model = "nomic-embed-text"
        project.chat_index_mode = "VECTOR_ONLY"
        project.chat_attachment_ingestion_mode = "METADATA_ONLY"

        session = ChatSession(
            id="f90bc1b6-09a8-43d3-adad-b86373113333",
            workspace_id=project.workspace_id,
            project_id=project.id,
            session_key="chat-policy-keep-retention",
            title="Session",
            created_by=user.id,
        )
        message = ChatMessage(
            id="ce8576d0-c0bb-458d-b5b8-a8f2f4ef4444",
            workspace_id=project.workspace_id,
            project_id=project.id,
            session_id=session.id,
            role="assistant",
            content="This chat vector evidence should remain indexed.",
            order_index=1,
            attachment_refs="[]",
            usage_json="{}",
            is_deleted=False,
        )
        db.add(session)
        db.add(message)
        db.commit()

        vector_store.sync_project_chat_vector_chunks(db, project_id=project.id, retention_mode="purge")
        db.commit()
        before_rows = db.execute(
            select(VectorChunk).where(
                VectorChunk.project_id == project.id,
                VectorChunk.entity_type == "ChatMessage",
            )
        ).scalars().all()
        assert before_rows

        project.chat_index_mode = "OFF"
        db.commit()
        indexed_after_off, purged_after_off = vector_store.sync_project_chat_vector_chunks(
            db,
            project_id=project.id,
            retention_mode="keep",
        )
        db.commit()
        after_rows = db.execute(
            select(VectorChunk).where(
                VectorChunk.project_id == project.id,
                VectorChunk.entity_type == "ChatMessage",
            )
        ).scalars().all()
        assert indexed_after_off == 0
        assert purged_after_off == 0
        assert len(after_rows) == len(before_rows)


def test_maybe_reindex_project_purges_chunks_when_runtime_is_disabled(tmp_path: Path, monkeypatch) -> None:
    _bootstrap_runtime(tmp_path)

    from shared import vector_store
    from shared.models import Project, SessionLocal, VectorChunk

    monkeypatch.setattr(vector_store, "vector_store_enabled", lambda: True)

    with SessionLocal() as db:
        project = db.execute(select(Project).where(Project.is_deleted.is_(False))).scalars().first()
        assert project is not None

        project.embedding_enabled = False
        project.embedding_model = "nomic-embed-text"
        db.add(
            VectorChunk(
                workspace_id=project.workspace_id,
                project_id=project.id,
                entity_type="Task",
                entity_id="task-retention-test",
                source_type="task.title",
                chunk_index=0,
                text_chunk="Legacy chunk",
                token_count=2,
                embedding_json="[0.1,0.2]",
                embedding_model="nomic-embed-text",
                content_hash="retention-hash-1",
                is_deleted=False,
            )
        )
        db.commit()

        indexed = vector_store.maybe_reindex_project(
            db,
            project_id=project.id,
            embedding_enabled=False,
            embedding_model="nomic-embed-text",
        )
        db.commit()

        remaining = db.execute(select(VectorChunk).where(VectorChunk.project_id == project.id)).scalars().all()
        assert indexed == 0
        assert remaining == []


def test_project_vector_event_routes_chat_policy_changes_to_chat_sync(monkeypatch) -> None:
    from features.projects.domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED
    from shared import eventing_vector
    from shared.contracts import EventEnvelope

    calls = {"reindex": 0, "sync": 0}

    def fake_reindex(*_args, **_kwargs):
        calls["reindex"] += 1
        return 0

    def fake_sync(*_args, **_kwargs):
        calls["sync"] += 1
        return 0, 0

    monkeypatch.setattr(eventing_vector, "maybe_reindex_project", fake_reindex)
    monkeypatch.setattr(eventing_vector, "sync_project_chat_vector_chunks", fake_sync)

    ev = EventEnvelope(
        aggregate_type="Project",
        aggregate_id="project-chat-policy",
        version=3,
        event_type=PROJECT_EVENT_UPDATED,
        payload={"chat_index_mode": "VECTOR_ONLY"},
        metadata={},
    )
    eventing_vector._project_vector_event(None, ev)

    assert calls["sync"] == 1
    assert calls["reindex"] == 0


def test_project_vector_event_passes_chat_policy_overrides_to_reindex(monkeypatch) -> None:
    from features.projects.domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED
    from shared import eventing_vector
    from shared.contracts import EventEnvelope

    captured: dict[str, object] = {}

    def fake_reindex(*_args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(eventing_vector, "maybe_reindex_project", fake_reindex)
    monkeypatch.setattr(eventing_vector, "project_embedding_index_status", lambda *_args, **_kwargs: "indexing")
    monkeypatch.setattr(eventing_vector, "_project_workspace_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eventing_vector, "_emit_project_index_activity", lambda *_args, **_kwargs: None)

    ev = EventEnvelope(
        aggregate_type="Project",
        aggregate_id="project-chat-policy",
        version=5,
        event_type=PROJECT_EVENT_UPDATED,
        payload={
            "embedding_enabled": True,
            "embedding_model": "nomic-embed-text",
            "chat_index_mode": "VECTOR_ONLY",
            "chat_attachment_ingestion_mode": "METADATA_ONLY",
        },
        metadata={},
    )
    eventing_vector._project_vector_event(None, ev)

    assert captured.get("project_id") == "project-chat-policy"
    assert captured.get("chat_index_mode") == "VECTOR_ONLY"
    assert captured.get("chat_attachment_ingestion_mode") == "METADATA_ONLY"


def test_project_graph_event_routes_policy_changes_to_chat_sync(monkeypatch) -> None:
    from features.projects.domain import EVENT_UPDATED as PROJECT_EVENT_UPDATED
    from shared import eventing_graph
    from shared.contracts import EventEnvelope

    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(eventing_graph, "_project_project_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        eventing_graph,
        "sync_project_chat_graph_for_policy",
        lambda project_id, force_purge=False: calls.append((project_id, bool(force_purge)))
        or {"deleted_nodes": 0, "synced_nodes": 0},
    )

    ev = EventEnvelope(
        aggregate_type="Project",
        aggregate_id="project-chat-policy",
        version=6,
        event_type=PROJECT_EVENT_UPDATED,
        payload={"chat_index_mode": "KG_AND_VECTOR"},
        metadata={},
    )
    eventing_graph._project_graph_event(ev, commit_position=99)

    assert calls == [("project-chat-policy", False)]


def test_project_graph_event_for_delete_forces_chat_purge(monkeypatch) -> None:
    from features.projects.domain import EVENT_DELETED as PROJECT_EVENT_DELETED
    from shared import eventing_graph
    from shared.contracts import EventEnvelope

    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(eventing_graph, "_project_project_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        eventing_graph,
        "sync_project_chat_graph_for_policy",
        lambda project_id, force_purge=False: calls.append((project_id, bool(force_purge)))
        or {"deleted_nodes": 0, "synced_nodes": 0},
    )

    ev = EventEnvelope(
        aggregate_type="Project",
        aggregate_id="project-chat-policy",
        version=7,
        event_type=PROJECT_EVENT_DELETED,
        payload={},
        metadata={},
    )
    eventing_graph._project_graph_event(ev, commit_position=100)

    assert calls == [("project-chat-policy", True)]
