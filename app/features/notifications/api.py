import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.core import (
    Notification,
    User,
    ensure_role,
    get_command_id,
    get_current_user,
    get_current_user_detached,
    get_db,
    serialize_notification,
)
from shared.models import SessionLocal
from shared.observability import incr
from shared.realtime import realtime_hub
from features.agents.provider_auth import get_provider_auth_status

from .application import NotificationApplicationService
from .read_models import (
    latest_notification_id_read_model,
    latest_workspace_activity_id_read_model,
    list_notifications_after_cursor_read_model,
    list_notifications_read_model,
    list_workspace_activity_after_id_read_model,
)

router = APIRouter()
_AGENT_AUTH_REALTIME_REASON_PREFIX = "agent-auth:"
_AGENT_AUTH_REALTIME_CHANNEL = "agent-auth"


def _load_user_state_cursor(db: Session, user_id: str) -> str:
    updated_at = db.execute(select(User.updated_at).where(User.id == user_id)).scalar_one_or_none()
    if updated_at is None:
        return ""
    return updated_at.isoformat()


async def _wait_for_signal(subscription, timeout_seconds: float) -> None:
    await asyncio.wait_for(subscription.get(), timeout=timeout_seconds)


def _extract_last_event_id(request: Request) -> str:
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    value = headers.get("last-event-id", "")
    return str(value or "").strip()


def _resolve_notification_cursor(db: Session, user_id: str, explicit_cursor: str | None, last_event_id: str) -> str:
    requested = str(explicit_cursor or "").strip() or str(last_event_id or "").strip()
    if requested:
        row = db.get(Notification, requested)
        if row is not None and row.user_id == user_id:
            return requested
    return latest_notification_id_read_model(db, user_id)


@router.get("/api/notifications")
def list_notifications(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return list_notifications_read_model(db, user.id, limit=100)


@router.post("/api/notifications/read-all")
def mark_all_notifications(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NotificationApplicationService(db, user, command_id=command_id).mark_all_read()


@router.post("/api/notifications/{notification_id}/read")
def mark_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NotificationApplicationService(db, user, command_id=command_id).mark_read(notification_id)


@router.post("/api/notifications/{notification_id}/unread")
def mark_notification_unread(
    notification_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NotificationApplicationService(db, user, command_id=command_id).mark_unread(notification_id)


@router.get("/api/notifications/stream")
async def notifications_stream(
    request: Request,
    last_id: str | None = None,
    workspace_id: str | None = None,
    last_activity_id: int = 0,
    user=Depends(get_current_user_detached),
):
    incr("sse_connections", 1)
    with SessionLocal() as db:
        if workspace_id:
            ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
        last_event_id = _extract_last_event_id(request)
        initial_notification_cursor = _resolve_notification_cursor(db, user.id, last_id, last_event_id)
        initial_activity_cursor = max(last_activity_id, 0)
        if workspace_id and initial_activity_cursor == 0:
            initial_activity_cursor = latest_workspace_activity_id_read_model(db, workspace_id)
        initial_user_state_cursor = _load_user_state_cursor(db, user.id)
    channels = {f"user:{user.id}"}
    if workspace_id:
        channels.add(f"workspace:{workspace_id}")
    channels.add(_AGENT_AUTH_REALTIME_CHANNEL)
    subscription = realtime_hub.subscribe(channels=channels)

    async def event_generator():
        notification_cursor = initial_notification_cursor
        activity_cursor = initial_activity_cursor
        user_state_cursor = initial_user_state_cursor
        flush_now = True
        try:
            while True:
                if await request.is_disconnected():
                    break

                signal_reason = ""
                if not flush_now:
                    try:
                        signal = await subscription.get()
                        signal_reason = str((signal or {}).get("reason") or "").strip().lower()
                        signal_received = True
                        timed_out = False
                    except asyncio.TimeoutError:
                        signal_received = False
                        timed_out = True
                else:
                    signal_received = False
                    timed_out = False
                flush_now = False
                emitted = False
                auth_event_payload: dict[str, object] | None = None
                if signal_received and signal_reason.startswith(_AGENT_AUTH_REALTIME_REASON_PREFIX):
                    provider = signal_reason.removeprefix(_AGENT_AUTH_REALTIME_REASON_PREFIX).strip()
                    payload: dict[str, object] = {"provider": provider} if provider else {}
                    if provider in {"codex", "claude", "opencode"}:
                        try:
                            payload["auth_status"] = get_provider_auth_status(provider)
                        except Exception:
                            pass
                    auth_event_payload = payload

                with SessionLocal() as db:
                    items = list_notifications_after_cursor_read_model(db, user.id, notification_cursor, limit=50)
                    activity_items = (
                        list_workspace_activity_after_id_read_model(
                            db,
                            workspace_id,
                            activity_cursor,
                            limit=100,
                    )
                    if workspace_id
                    else []
                    )
                    refreshed_user_state_cursor = _load_user_state_cursor(db, user.id)

                for n in items:
                    payload = serialize_notification(n)
                    yield f"id: {n.id}\nevent: notification\ndata: {json.dumps(payload)}\n\n"
                    notification_cursor = n.id
                    emitted = True

                for item in activity_items:
                    yield f"event: task_event\ndata: {json.dumps(item)}\n\n"
                    activity_cursor = int(item["id"])
                    emitted = True

                if refreshed_user_state_cursor != user_state_cursor:
                    user_state_cursor = refreshed_user_state_cursor
                    yield "event: task_event\ndata: {}\n\n"
                    emitted = True

                if auth_event_payload is not None:
                    yield f"event: auth_event\ndata: {json.dumps(auth_event_payload)}\n\n"
                    emitted = True

                if not emitted:
                    if signal_received:
                        # Forward a lightweight refresh event even when no new rows are
                        # visible in current notification/activity cursors.
                        yield "event: task_event\ndata: {}\n\n"
                    elif timed_out:
                        # Keep the stream alive while still allowing timeout-based polling
                        # to surface cross-process updates in later iterations.
                        yield "event: ping\ndata: {}\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
