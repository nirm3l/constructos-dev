from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import UserPreferencesPatch, get_command_id, get_current_user, get_db
from .application import UserApplicationService

router = APIRouter()


@router.patch("/api/me/preferences")
def patch_me_preferences(
    payload: UserPreferencesPatch,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return UserApplicationService(db, user, command_id=command_id).patch_preferences(payload)
