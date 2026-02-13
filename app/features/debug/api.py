from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import get_current_user, get_db, load_events_after, metrics_snapshot

router = APIRouter()


@router.get("/api/events/{aggregate_type}/{aggregate_id}")
def stream_events(aggregate_type: str, aggregate_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    events = load_events_after(db, aggregate_type, aggregate_id, 0)
    return [
        {
            "version": e.version,
            "event_type": e.event_type,
            "payload": e.payload,
            "metadata": e.metadata,
        }
        for e in events
    ]


@router.get("/api/metrics")
def runtime_metrics(_user=Depends(get_current_user)):
    return metrics_snapshot()
