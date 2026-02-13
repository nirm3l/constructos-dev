from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.core import SavedViewCreate, get_command_id, get_current_user, get_db
from .application import SavedViewApplicationService

router = APIRouter()


@router.post("/api/saved-views")
def create_saved_view(
    payload: SavedViewCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    command_id: str | None = Depends(get_command_id),
):
    return SavedViewApplicationService(db, user, command_id=command_id).create_saved_view(payload)
