from __future__ import annotations

from sqlalchemy.orm import Session

from shared.commanding import execute_command
from shared.core import NoteGroupCreate, NoteGroupPatch, ReorderPayload, User, ensure_project_access

from .command_handlers import (
    CommandContext,
    CreateNoteGroupHandler,
    DeleteNoteGroupHandler,
    PatchNoteGroupHandler,
    ReorderNoteGroupsHandler,
)


class NoteGroupApplicationService:
    def __init__(self, db: Session, user: User, command_id: str | None = None):
        self.db = db
        self.user = user
        self.command_id = command_id
        self.ctx = CommandContext(db=db, user=user)

    def create_note_group(self, payload: NoteGroupCreate) -> dict:
        return execute_command(
            self.db,
            command_name="NoteGroup.Create",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=CreateNoteGroupHandler(self.ctx, payload),
        )

    def patch_note_group(self, group_id: str, payload: NoteGroupPatch) -> dict:
        return execute_command(
            self.db,
            command_name="NoteGroup.Patch",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=PatchNoteGroupHandler(self.ctx, group_id, payload),
        )

    def delete_note_group(self, group_id: str) -> dict:
        return execute_command(
            self.db,
            command_name="NoteGroup.Delete",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=DeleteNoteGroupHandler(self.ctx, group_id),
        )

    def reorder_note_groups(self, workspace_id: str, project_id: str, payload: ReorderPayload) -> dict:
        ensure_project_access(self.db, workspace_id, project_id, self.user.id, {"Owner", "Admin", "Member"})
        return execute_command(
            self.db,
            command_name="NoteGroup.Reorder",
            user_id=self.user.id,
            command_id=self.command_id,
            handler=ReorderNoteGroupsHandler(self.ctx, workspace_id, project_id, payload),
        )
