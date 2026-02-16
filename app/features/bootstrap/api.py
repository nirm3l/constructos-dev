from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from shared.core import emit_system_notifications, get_current_user, get_db
from shared.settings import APP_BUILD, APP_DEPLOYED_AT_UTC, APP_VERSION
from .read_models import bootstrap_payload_read_model

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[2]
INDEX_HTML = BASE_DIR / "static" / "index.html"


@router.get("/")
def root():
    return FileResponse(str(INDEX_HTML))


@router.get("/api/health")
def health():
    return {"ok": True, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/api/version")
def version():
    return {
        "backend_version": APP_VERSION,
        "backend_build": APP_BUILD or None,
        "deployed_at_utc": APP_DEPLOYED_AT_UTC,
    }


@router.get("/api/bootstrap")
def bootstrap(db: Session = Depends(get_db), user=Depends(get_current_user)):
    emit_system_notifications(db, user)
    return bootstrap_payload_read_model(db, user)
