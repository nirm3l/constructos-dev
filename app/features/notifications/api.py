import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from shared.core import emit_system_notifications, get_command_id, get_current_user, get_db, serialize_notification
from shared.observability import incr

from .application import NotificationApplicationService
from .read_models import list_notifications_after_cursor_read_model, list_notifications_read_model

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
async def notifications_stream(request: Request, last_id: str | None = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    incr("sse_connections", 1)

    async def event_generator():
        cursor = last_id or ""
        while True:
            if await request.is_disconnected():
                break

            created = emit_system_notifications(db, user)
            if created:
                incr("notifications_emitted", created)
            items = list_notifications_after_cursor_read_model(db, user.id, cursor, limit=50)

            for n in items:
                payload = serialize_notification(n)
                yield f"id: {n.id}\nevent: notification\ndata: {json.dumps(payload)}\n\n"
                cursor = n.id

            yield "event: ping\ndata: {}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
