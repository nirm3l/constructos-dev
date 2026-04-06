import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from shared.core import get_current_user, get_db
from shared.settings import APP_BUILD, APP_DEPLOYED_AT_UTC, APP_VERSION
from shared.vector_store import vector_backend_health_summary
from .read_models import bootstrap_payload_read_model

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[2]
INDEX_HTML = BASE_DIR / "static" / "index.html"
FAVICON_ICO = BASE_DIR / "static" / "favicon.ico"


@router.get("/")
def root():
    return FileResponse(
        str(INDEX_HTML),
        headers={
            "Cache-Control": "no-store, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    if FAVICON_ICO.exists():
        return FileResponse(str(FAVICON_ICO), media_type="image/x-icon")
    # Avoid noisy 404 in browsers when favicon is not present.
    return Response(status_code=204)


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vector": vector_backend_health_summary(db),
    }


@router.get("/api/version")
def version():
    backend_version = os.getenv("APP_VERSION", "").strip() or APP_VERSION
    backend_build = os.getenv("APP_BUILD", "").strip() or APP_BUILD
    deployed_at_utc = os.getenv("APP_DEPLOYED_AT_UTC", "").strip() or APP_DEPLOYED_AT_UTC
    return {
        "backend_version": backend_version,
        "backend_build": backend_build or None,
        "deployed_at_utc": deployed_at_utc,
    }


@router.get("/api/bootstrap")
def bootstrap(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return bootstrap_payload_read_model(db, user)
