import asyncio
import os
from importlib import reload
from pathlib import Path


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
