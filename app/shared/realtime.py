from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

_PENDING_CHANNELS_KEY = "_pending_realtime_channels"
_SESSION_HOOKS_FLAG = "_realtime_session_hooks_registered"


@dataclass(slots=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, str]]
    channels: set[str]


class RealtimeSubscription:
    def __init__(self, hub: "RealtimeHub", subscriber_id: int, queue: asyncio.Queue[dict[str, str]]) -> None:
        self._hub = hub
        self._subscriber_id = subscriber_id
        self._queue = queue
        self._closed = False

    async def get(self) -> dict[str, str]:
        return await self._queue.get()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._hub.unsubscribe(self._subscriber_id)


class RealtimeHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_subscriber_id = 1
        self._subscribers: dict[int, _Subscriber] = {}
        self._channel_index: dict[str, set[int]] = {}

    def subscribe(self, *, channels: set[str], queue_size: int = 256) -> RealtimeSubscription:
        if not channels:
            raise ValueError("channels must not be empty")
        normalized = {str(channel).strip() for channel in channels if str(channel).strip()}
        if not normalized:
            raise ValueError("channels must not be empty")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=max(1, int(queue_size)))
        with self._lock:
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            subscriber = _Subscriber(
                loop=loop,
                queue=queue,
                channels=normalized,
            )
            self._subscribers[subscriber_id] = subscriber
            for channel in normalized:
                self._channel_index.setdefault(channel, set()).add(subscriber_id)
        return RealtimeSubscription(self, subscriber_id, queue)

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            subscriber = self._subscribers.pop(subscriber_id, None)
            if subscriber is None:
                return
            for channel in subscriber.channels:
                members = self._channel_index.get(channel)
                if not members:
                    continue
                members.discard(subscriber_id)
                if not members:
                    self._channel_index.pop(channel, None)

    def publish(self, channel: str, *, reason: str = "update") -> None:
        self.publish_many({channel}, reason=reason)

    def publish_many(self, channels: set[str], *, reason: str = "update") -> None:
        normalized = {str(channel).strip() for channel in channels if str(channel).strip()}
        if not normalized:
            return
        with self._lock:
            subscriber_ids: set[int] = set()
            for channel in normalized:
                subscriber_ids.update(self._channel_index.get(channel, set()))
            subscribers: list[tuple[int, _Subscriber]] = [
                (subscriber_id, self._subscribers[subscriber_id])
                for subscriber_id in subscriber_ids
                if subscriber_id in self._subscribers
            ]

        if not subscribers:
            return

        signal = {"reason": reason}

        for subscriber_id, subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(self._enqueue_signal, subscriber.queue, signal)
            except RuntimeError:
                self.unsubscribe(subscriber_id)

    @staticmethod
    def _enqueue_signal(queue: asyncio.Queue[dict[str, str]], signal: dict[str, str]) -> None:
        try:
            queue.put_nowait(signal)
            return
        except asyncio.QueueFull:
            pass

        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        try:
            queue.put_nowait(signal)
        except asyncio.QueueFull:
            pass


realtime_hub = RealtimeHub()
_hook_registration_lock = threading.Lock()


def enqueue_realtime_channel(db: Session, channel: str) -> None:
    value = str(channel or "").strip()
    if not value:
        return
    pending = db.info.setdefault(_PENDING_CHANNELS_KEY, set())
    pending.add(value)


def enqueue_realtime_channels(db: Session, channels: set[str]) -> None:
    for channel in channels:
        enqueue_realtime_channel(db, channel)


def register_realtime_session_hooks(session_factory: sessionmaker) -> None:
    target = session_factory.class_
    with _hook_registration_lock:
        if getattr(target, _SESSION_HOOKS_FLAG, False):
            return
        event.listen(target, "after_commit", _after_commit)
        event.listen(target, "after_rollback", _after_rollback)
        setattr(target, _SESSION_HOOKS_FLAG, True)


def _after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_CHANNELS_KEY, None)
    if not pending:
        return
    realtime_hub.publish_many(set(pending), reason="db-commit")


def _after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_CHANNELS_KEY, None)
