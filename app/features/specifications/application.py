from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import SpecificationCreate, SpecificationPatch, User

from .command_handlers import (
    ArchiveSpecificationHandler,
    CommandContext,
    CreateSpecificationHandler,
    DeleteSpecificationHandler,
    PatchSpecificationHandler,
    RestoreSpecificationHandler,
)


class SpecificationApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_specification(self, payload: SpecificationCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateSpecificationHandler(self.ctx, payload),
        )

    def patch_specification(self, specification_id: str, payload: SpecificationPatch) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchSpecificationHandler(self.ctx, specification_id, payload),
        )

    def archive_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveSpecificationHandler(self.ctx, specification_id),
        )

    def restore_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Restore",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RestoreSpecificationHandler(self.ctx, specification_id),
        )

    def delete_specification(self, specification_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Specification.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteSpecificationHandler(self.ctx, specification_id),
        )
