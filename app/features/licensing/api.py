from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.core import User, get_current_user, get_db

from .read_models import license_status_read_model
from .sync import LicenseActivationError, activate_with_code_once

router = APIRouter()


class LicenseActivationRequest(BaseModel):
    activation_code: str = Field(min_length=8, max_length=128)


@router.get("/api/license/status")
def get_license_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return {"ok": True, "license": license_status_read_model(db)}


@router.post("/api/license/activate")
def activate_license(
    payload: LicenseActivationRequest,
    _user: User = Depends(get_current_user),
):
    try:
        result = activate_with_code_once(payload.activation_code)
    except LicenseActivationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"ok": True, **result}
