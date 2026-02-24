from __future__ import annotations

from typing import Sequence

from .eventing_store import get_kurrent_client
from .knowledge_graph import graph_enabled
from .settings import (
    PERSISTENT_SUBSCRIPTION_GRAPH_GROUP,
    PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP,
    PERSISTENT_SUBSCRIPTION_VECTOR_GROUP,
    logger,
)
from .vector_store import vector_store_enabled

try:
    from kurrentdbclient.exceptions import AlreadyExistsError as _AlreadyExistsError
except Exception:  # pragma: no cover
    _AlreadyExistsError = None

_DEFAULT_FILTER_EXCLUDE = (
    r"\$.+",
    r"PersistentConfig\d+",
    "Result",
    r"snapshot::.*",
)
_GRAPH_FILTER_INCLUDE = (
    r"Project::.*",
    r"Task::.*",
    r"Note::.*",
    r"Specification::.*",
    r"ProjectRule::.*",
    r"ChatSession::.*",
)
_VECTOR_FILTER_INCLUDE = (
    r"Project::.*",
    r"Task::.*",
    r"Note::.*",
    r"Specification::.*",
    r"ProjectRule::.*",
    r"ChatSession::.*",
)


def ensure_persistent_subscriptions() -> None:
    client = get_kurrent_client()
    if client is None:
        return

    _ensure_subscription_group(
        client=client,
        group_name=PERSISTENT_SUBSCRIPTION_READ_MODEL_GROUP,
    )

    if graph_enabled():
        _ensure_subscription_group(
            client=client,
            group_name=PERSISTENT_SUBSCRIPTION_GRAPH_GROUP,
            filter_include=_GRAPH_FILTER_INCLUDE,
            filter_by_stream_name=True,
        )

    if vector_store_enabled():
        _ensure_subscription_group(
            client=client,
            group_name=PERSISTENT_SUBSCRIPTION_VECTOR_GROUP,
            filter_include=_VECTOR_FILTER_INCLUDE,
            filter_by_stream_name=True,
        )


def _ensure_subscription_group(
    *,
    client,
    group_name: str,
    filter_include: Sequence[str] = (),
    filter_by_stream_name: bool = False,
) -> None:
    if not group_name:
        raise ValueError("Persistent subscription group name must not be empty")

    try:
        client.create_subscription_to_all(
            group_name=group_name,
            from_end=False,
            commit_position=0,
            resolve_links=False,
            filter_exclude=_DEFAULT_FILTER_EXCLUDE,
            filter_include=tuple(filter_include),
            filter_by_stream_name=filter_by_stream_name,
        )
        logger.info("Persistent subscription group created: %s", group_name)
    except Exception as exc:
        if _is_already_exists_error(exc):
            logger.info("Persistent subscription group already exists: %s", group_name)
            return
        raise


def _is_already_exists_error(exc: Exception) -> bool:
    if _AlreadyExistsError is not None and isinstance(exc, _AlreadyExistsError):
        return True
    message = str(exc).lower()
    return "already exists" in message
