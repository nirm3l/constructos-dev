from __future__ import annotations

from sqlalchemy.orm import Session

from .read_models import license_status_read_model


class LicensingApplicationService:
    def __init__(self, db: Session):
        self.db = db

    def get_license_status(self) -> dict:
        return license_status_read_model(self.db)

