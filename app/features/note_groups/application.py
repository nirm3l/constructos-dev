from __future__ import annotations

import hashlib

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


def _derive_reorder_command_id(command_id: str | None, group_id: str) -> str | None:
    if not command_id:
        return None
    candidate = f"{command_id}:{group_id}"
    if len(candidate) <= 64:
        return candidate
    # Keep command IDs within DB column limit while preserving deterministic idempotency.
    return f"reorder:{hashlib.sha1(candidate.encode('utf-8')).hexdigest()}"


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
        handler = ReorderNoteGroupsHandler(self.ctx, workspace_id, project_id, payload)
        updated = 0
        for idx, group_id in enumerate(payload.ordered_ids):
            if execute_command(
                self.db,
                command_name="NoteGroup.Reorder",
                user_id=self.user.id,
                command_id=_derive_reorder_command_id(self.command_id, group_id),
                handler=lambda group_id=group_id, idx=idx: handler(group_id, idx + 1),
            ):
                updated += 1
        return {"ok": True, "updated": updated}
