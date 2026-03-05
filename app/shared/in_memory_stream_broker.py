from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from typing import Any


class InMemoryStreamBroker:
    def __init__(self, *, max_events: int = 1500) -> None:
        self._max_events = max(1, int(max_events))
        self._lock = threading.Lock()
        self._brokers: dict[str, dict[str, Any]] = {}

    def create_run(self, *, key: str, preferred_run_id: str | None = None) -> str:
        normalized_preferred = str(preferred_run_id or "").strip()
        run_id = normalized_preferred or f"run-{uuid.uuid4()}"
        with self._lock:
            self._brokers[key] = {
                "run_id": run_id,
                "next_seq": 1,
                "done": False,
                "events": deque(maxlen=self._max_events),
                "subscribers": [],
                "updated_at": time.time(),
            }
        return run_id

    def publish_event(self, *, key: str, event: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            broker = self._brokers.get(key)
            if not isinstance(broker, dict):
                return None
            seq = int(broker.get("next_seq") or 1)
            broker["next_seq"] = seq + 1
            broker_event = {
                "seq": seq,
                "run_id": str(broker.get("run_id") or ""),
                **event,
            }
            events: deque = broker["events"]
            events.append(broker_event)
            broker["updated_at"] = time.time()
            subscribers = list(broker.get("subscribers") or [])
        for subscriber_queue in subscribers:
            try:
                subscriber_queue.put_nowait(broker_event)
            except Exception:
                continue
        return broker_event

    def finish_run(self, *, key: str) -> None:
        with self._lock:
            broker = self._brokers.get(key)
            if not isinstance(broker, dict):
                return
            broker["done"] = True
            broker["updated_at"] = time.time()

    def subscribe_run(
        self,
        *,
        key: str,
        run_id: str,
        since_seq: int,
    ) -> tuple[queue.Queue[dict[str, Any]], list[dict[str, Any]], bool]:
        normalized_run_id = str(run_id or "").strip()
        subscriber_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            broker = self._brokers.get(key)
            if not isinstance(broker, dict):
                return subscriber_queue, [], True
            if str(broker.get("run_id") or "").strip() != normalized_run_id:
                return subscriber_queue, [], True
            events = [
                item
                for item in list(broker.get("events") or [])
                if int(item.get("seq") or 0) > int(since_seq)
            ]
            done = bool(broker.get("done"))
            if not done:
                subscribers = list(broker.get("subscribers") or [])
                subscribers.append(subscriber_queue)
                broker["subscribers"] = subscribers
        return subscriber_queue, events, done

    def unsubscribe_run(self, *, key: str, subscriber_queue: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            broker = self._brokers.get(key)
            if not isinstance(broker, dict):
                return
            subscribers = [item for item in list(broker.get("subscribers") or []) if item is not subscriber_queue]
            broker["subscribers"] = subscribers

    def current_state(self, *, key: str) -> dict[str, Any] | None:
        with self._lock:
            broker = self._brokers.get(key)
            if not isinstance(broker, dict):
                return None
            return dict(broker)
