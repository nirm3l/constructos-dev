from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import User, get_current_user, get_db

from .read_models import license_status_read_model

router = APIRouter()


@router.get("/api/license/status")
def get_license_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return {"ok": True, "license": license_status_read_model(db)}

