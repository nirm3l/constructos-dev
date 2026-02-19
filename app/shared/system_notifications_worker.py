from __future__ import annotations

import threading

from sqlalchemy import select

from .eventing import emit_system_notifications
from .models import SessionLocal, User
from .observability import incr
from .settings import SYSTEM_NOTIFICATIONS_INTERVAL_SECONDS, logger

_worker_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _run_tick() -> None:
    with SessionLocal() as db:
        users = db.execute(
            select(User).where(
                User.is_active == True,  # noqa: E712
                User.notifications_enabled == True,  # noqa: E712
            )
        ).scalars().all()
        for user in users:
            try:
                created = emit_system_notifications(db, user)
                if created:
                    incr("notifications_emitted", created)
            except Exception as exc:
                db.rollback()
                logger.warning("System notifications tick failed for user %s: %s", user.id, exc)


def _worker_loop() -> None:
    while not _worker_stop_event.is_set():
        try:
            _run_tick()
        except Exception as exc:
            logger.warning("System notifications worker tick failed: %s", exc)
        _worker_stop_event.wait(max(1.0, float(SYSTEM_NOTIFICATIONS_INTERVAL_SECONDS)))


def start_system_notifications_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="system-notifications-worker",
        daemon=True,
    )
    _worker_thread.start()


def stop_system_notifications_worker() -> None:
    global _worker_thread
    _worker_stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
    _worker_thread = None
