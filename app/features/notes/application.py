from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import NoteCreate, NotePatch, User

from .command_handlers import (
    ArchiveNoteHandler,
    ArchiveNotesBatchHandler,
    CommandContext,
    CreateNoteHandler,
    DeleteNoteHandler,
    PatchNoteHandler,
    PinNoteHandler,
    RestoreNoteHandler,
    UnpinNoteHandler,
)


class NoteApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_note(self, payload: NoteCreate) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateNoteHandler(self.ctx, payload),
        )

    def patch_note(self, note_id: str, payload: NotePatch) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchNoteHandler(self.ctx, note_id, payload),
        )

    def archive_note(self, note_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveNoteHandler(self.ctx, note_id),
        )

    def archive_notes(self, note_ids: list[str]) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Bulk.Archive",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ArchiveNotesBatchHandler(self.ctx, note_ids),
        )

    def restore_note(self, note_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Restore",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=RestoreNoteHandler(self.ctx, note_id),
        )

    def pin_note(self, note_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Pin",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PinNoteHandler(self.ctx, note_id),
        )

    def unpin_note(self, note_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Unpin",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=UnpinNoteHandler(self.ctx, note_id),
        )

    def delete_note(self, note_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="Note.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteNoteHandler(self.ctx, note_id),
        )
