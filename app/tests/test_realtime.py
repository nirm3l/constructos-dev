import asyncio
import os
from importlib import reload
from pathlib import Path
from sqlalchemy import select


def _bootstrap_runtime(tmp_path: Path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["ATTACHMENTS_DIR"] = str(tmp_path / "uploads")
    os.environ.pop("DB_PATH", None)
    os.environ["EVENTSTORE_URI"] = ""
    import main

    main = reload(main)
    main.bootstrap_data()
    return main


def test_realtime_publishes_on_commit_and_skips_rollback(tmp_path: Path):
    _bootstrap_runtime(tmp_path)

    from shared.models import SessionLocal
    from shared.realtime import enqueue_realtime_channel, realtime_hub, register_realtime_session_hooks

    register_realtime_session_hooks(SessionLocal)

    async def scenario() -> None:
        subscription = realtime_hub.subscribe(channels={"workspace:test"})
        try:
            with SessionLocal() as db:
                enqueue_realtime_channel(db, "workspace:test")
                db.commit()

            signal = await asyncio.wait_for(subscription.get(), timeout=1.0)
            assert signal["reason"] == "db-commit"

            with SessionLocal() as db:
                enqueue_realtime_channel(db, "workspace:test")
                db.rollback()

            with_timeout = asyncio.wait_for(subscription.get(), timeout=0.2)
            try:
                await with_timeout
                assert False, "rollback should not publish realtime signals"
            except asyncio.TimeoutError:
                pass
        finally:
            subscription.close()

    asyncio.run(scenario())


def test_vector_index_activity_publishes_workspace_signal(tmp_path: Path):
    _bootstrap_runtime(tmp_path)

    from shared.eventing_vector import _emit_project_index_activity
    from shared.models import Project, SessionLocal
    from shared.realtime import realtime_hub, register_realtime_session_hooks

    register_realtime_session_hooks(SessionLocal)

    with SessionLocal() as db:
        project = db.execute(select(Project).limit(1)).scalar_one()

    async def scenario() -> None:
        subscription = realtime_hub.subscribe(channels={f"workspace:{project.workspace_id}"})
        try:
            with SessionLocal() as db:
                _emit_project_index_activity(
                    db,
                    project_id=project.id,
                    workspace_id=project.workspace_id,
                    event_key="test-project-index-ready",
                    status="ready",
                    indexed_chunks=42,
                    embedding_model="nomic-embed-text",
                )
                db.commit()

            signal = await asyncio.wait_for(subscription.get(), timeout=1.0)
            assert signal["reason"] == "db-commit"
        finally:
            subscription.close()

    asyncio.run(scenario())
