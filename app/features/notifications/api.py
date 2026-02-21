import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from shared.core import emit_system_notifications, ensure_role, get_command_id, get_current_user, get_db, serialize_notification
from shared.observability import incr
from shared.realtime import realtime_hub

from .application import NotificationApplicationService
from .read_models import (
    latest_workspace_activity_id_read_model,
    list_notifications_after_cursor_read_model,
    list_notifications_read_model,
    list_workspace_activity_after_id_read_model,
)

router = APIRouter()


@router.get("/api/notifications")
def list_notifications(db: Session = Depends(get_db), user=Depends(get_current_user)):
    created = emit_system_notifications(db, user)
    if created:
        incr("notifications_emitted", created)
    return list_notifications_read_model(db, user.id, limit=100)


@router.post("/api/notifications/{notification_id}/read")
def mark_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return NotificationApplicationService(db, user, command_id=command_id).mark_read(notification_id)


@router.get("/api/notifications/stream")
async def notifications_stream(
    request: Request,
    last_id: str | None = None,
    workspace_id: str | None = None,
    last_activity_id: int = 0,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    incr("sse_connections", 1)
    if workspace_id:
        ensure_role(db, workspace_id, user.id, {"Owner", "Admin", "Member", "Guest"})
    channels = {f"user:{user.id}"}
    if workspace_id:
        channels.add(f"workspace:{workspace_id}")
    subscription = realtime_hub.subscribe(channels=channels)

    async def event_generator():
        notification_cursor = last_id or ""
        activity_cursor = max(last_activity_id, 0)
        if workspace_id and activity_cursor == 0:
            # Tail mode by default: only stream new activity generated after this connection starts.
            activity_cursor = latest_workspace_activity_id_read_model(db, workspace_id)
        created = emit_system_notifications(db, user)
        if created:
            incr("notifications_emitted", created)
        flush_now = True
        try:
            while True:
                if await request.is_disconnected():
                    break

                if not flush_now:
                    try:
                        await asyncio.wait_for(subscription.get(), timeout=30.0)
                        signal_received = True
                    except asyncio.TimeoutError:
                        yield "event: ping\ndata: {}\n\n"
                        continue
                else:
                    signal_received = False
                flush_now = False
                emitted = False

                items = list_notifications_after_cursor_read_model(db, user.id, notification_cursor, limit=50)
                for n in items:
                    payload = serialize_notification(n)
                    yield f"id: {n.id}\nevent: notification\ndata: {json.dumps(payload)}\n\n"
                    notification_cursor = n.id
                    emitted = True

                if workspace_id:
                    activity_items = list_workspace_activity_after_id_read_model(
                        db,
                        workspace_id,
                        activity_cursor,
                        limit=100,
                    )
                    for item in activity_items:
                        yield f"event: task_event\ndata: {json.dumps(item)}\n\n"
                        activity_cursor = int(item["id"])
                        emitted = True

                if signal_received and not emitted:
                    # Forward a lightweight refresh event even when no new rows are
                    # visible in current notification/activity cursors.
                    yield "event: task_event\ndata: {}\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
